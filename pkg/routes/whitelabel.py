import re
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Tenant
from ..utils.helpers import get_active_context, is_enterprise_context
from ..services.cloudflare_service import (
    create_custom_hostname,
    get_custom_hostname_status,
    delete_custom_hostname
)

whitelabel_bp = Blueprint('whitelabel', __name__)

def _clean_domain(domain_str):
    if not domain_str:
        return ""
    # Strip protocol, paths, and trailing slashes
    domain = domain_str.strip().lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = domain.split('/')[0].split(':')[0].strip()
    return domain

@whitelabel_bp.route('/config', methods=['GET'])
def get_whitelabel_config():
    """
    Public Endpoint: Resolves tenant branding by hostname.
    Used by frontend on application boot.
    """
    domain = _clean_domain(request.args.get('domain', ''))
    
    # Exclude root domains and local dev
    standard_domains = [
        'proofdeck.app', 'www.proofdeck.app', 'localhost', '127.0.0.1',
        'proofdeck-frontend.vercel.app', 'domains.proofdeck.app'
    ]

    if not domain or domain in standard_domains:
        return jsonify({"is_whitelabel": False}), 200

    # Query tenant with active custom domain
    tenant = Tenant.query.filter_by(custom_domain=domain, domain_status='active').first()
    if not tenant:
        # Check if tenant exists but is pending
        pending_tenant = Tenant.query.filter_by(custom_domain=domain).first()
        if pending_tenant:
            return jsonify({
                "is_whitelabel": True,
                "is_pending": True,
                "company_name": pending_tenant.name,
                "msg": "Domain DNS is pending verification."
            }), 200
        return jsonify({"is_whitelabel": False, "msg": "Domain not registered"}), 404

    return jsonify({
        "is_whitelabel": True,
        "is_pending": False,
        "company_id": tenant.id,
        "company_name": tenant.name,
        "logo_url": tenant.brand_logo_url,
        "favicon_url": tenant.brand_favicon_url,
        "primary_color": tenant.brand_primary_color or "#2563EB",
        "accent_color": tenant.brand_accent_color or "#1E40AF",
        "font_family": tenant.brand_font_family or "Inter",
        "hide_badge": bool(tenant.hide_proofdeck_badge),
        "support_email": tenant.custom_support_email,
        "website_url": tenant.custom_website_url,
        "linkedin_org_id": tenant.linkedin_org_id
    }), 200


@whitelabel_bp.route('/settings', methods=['GET'])
@jwt_required()
def get_tenant_whitelabel_settings():
    """
    Tenant Admin Endpoint: Fetch current white-label configuration.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    is_comp, tenant_id, _, active_role = get_active_context(user)

    if not is_comp or not tenant_id:
        return jsonify({"msg": "White-label settings require a company workspace."}), 400

    tenant = Tenant.query.get_or_404(tenant_id)
    fallback_origin = current_app.config.get('CLOUDFLARE_FALLBACK_ORIGIN', 'domains.proofdeck.app')

    return jsonify({
        "is_enterprise": is_enterprise_context(user),
        "company_id": tenant.id,
        "company_name": tenant.name,
        "custom_domain": tenant.custom_domain,
        "domain_status": tenant.domain_status,
        "cloudflare_hostname_id": tenant.cloudflare_hostname_id,
        "fallback_origin": fallback_origin,
        "branding": {
            "logo_url": tenant.brand_logo_url,
            "favicon_url": tenant.brand_favicon_url,
            "primary_color": tenant.brand_primary_color or "#2563EB",
            "accent_color": tenant.brand_accent_color or "#1E40AF",
            "font_family": tenant.brand_font_family or "Inter",
            "hide_badge": bool(tenant.hide_proofdeck_badge),
            "custom_support_email": tenant.custom_support_email,
            "custom_website_url": tenant.custom_website_url,
            "custom_sender_name": tenant.custom_sender_name
        }
    }), 200


@whitelabel_bp.route('/domain', methods=['POST'])
@jwt_required()
def setup_custom_domain():
    """
    Tenant Admin Endpoint: Connect custom domain via Cloudflare for SaaS.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    is_comp, tenant_id, _, active_role = get_active_context(user)

    if not is_comp or not tenant_id:
        return jsonify({"msg": "Company workspace required."}), 400
    if active_role not in ('owner', 'admin'):
        return jsonify({"msg": "Only company owners and admins can configure custom domains."}), 403
    if not is_enterprise_context(user):
        return jsonify({"msg": "Custom domain and white-labeling is exclusively available on the Enterprise plan. Please upgrade to Enterprise."}), 403

    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json() or {}
    domain = _clean_domain(data.get('domain', ''))

    if not domain:
        return jsonify({"msg": "Valid domain is required."}), 400

    if domain in ['proofdeck.app', 'www.proofdeck.app', 'api.proofdeck.app']:
        return jsonify({"msg": "Cannot use root ProofDeck domain."}), 400

    # Check uniqueness
    existing = Tenant.query.filter(Tenant.custom_domain == domain, Tenant.id != tenant.id).first()
    if existing:
        return jsonify({"msg": "This domain is already registered by another organization."}), 400

    # Delete previous Cloudflare hostname if changing domain
    if tenant.cloudflare_hostname_id:
        try:
            delete_custom_hostname(tenant.cloudflare_hostname_id)
        except Exception as e:
            current_app.logger.warning(f"Failed to remove old hostname {tenant.cloudflare_hostname_id}: {e}")

    # Register in Cloudflare
    cf_res = create_custom_hostname(domain)
    if not cf_res.get("success"):
        return jsonify({"msg": f"Failed to register domain with Cloudflare: {cf_res.get('error')}"}), 400

    cf_data = cf_res.get("result", {})
    tenant.custom_domain = domain
    tenant.cloudflare_hostname_id = cf_data.get("id")
    tenant.domain_status = "pending_dns"
    
    db.session.commit()

    fallback_origin = current_app.config.get('CLOUDFLARE_FALLBACK_ORIGIN', 'domains.proofdeck.app')

    return jsonify({
        "msg": "Domain registered successfully. Please add the CNAME record in your DNS provider.",
        "domain": domain,
        "status": "pending_dns",
        "dns_instructions": {
            "type": "CNAME",
            "name": domain,
            "target": fallback_origin
        }
    }), 201


@whitelabel_bp.route('/verify-domain', methods=['POST'])
@jwt_required()
def verify_domain_status():
    """
    Tenant Admin Endpoint: Check if the CNAME and SSL are active in Cloudflare.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)

    if not is_comp or not tenant_id:
        return jsonify({"msg": "Company workspace required."}), 400
    if not is_enterprise_context(user):
        return jsonify({"msg": "Custom domain verification is exclusively available on the Enterprise plan."}), 403

    tenant = Tenant.query.get_or_404(tenant_id)
    if not tenant.custom_domain or not tenant.cloudflare_hostname_id:
        return jsonify({"msg": "No custom domain configured."}), 400

    status_res = get_custom_hostname_status(tenant.cloudflare_hostname_id)
    if not status_res.get("success"):
        return jsonify({"msg": f"Cloudflare status check failed: {status_res.get('error')}"}), 400

    if status_res.get("is_active"):
        tenant.domain_status = "active"
        db.session.commit()

    return jsonify({
        "domain": tenant.custom_domain,
        "domain_status": tenant.domain_status,
        "is_active": status_res.get("is_active", False),
        "hostname_status": status_res.get("hostname_status"),
        "ssl_status": status_res.get("ssl_status"),
        "ssl_validation_errors": status_res.get("ssl_validation_errors", []),
        "ownership_verification": status_res.get("ownership_verification")
    }), 200


@whitelabel_bp.route('/branding', methods=['PUT'])
@jwt_required()
def update_branding():
    """
    Tenant Admin Endpoint: Update logo, colors, support email, and badge settings.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    is_comp, tenant_id, _, active_role = get_active_context(user)

    if not is_comp or not tenant_id:
        return jsonify({"msg": "Company workspace required."}), 400
    if active_role not in ('owner', 'admin'):
        return jsonify({"msg": "Only company owners and admins can update branding."}), 403
    if not is_enterprise_context(user):
        return jsonify({"msg": "Branding customization is exclusively available on the Enterprise plan. Please upgrade to Enterprise."}), 403

    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json() or {}

    if "brand_logo_url" in data:
        tenant.brand_logo_url = data["brand_logo_url"]
    if "brand_favicon_url" in data:
        tenant.brand_favicon_url = data["brand_favicon_url"]
    if "brand_primary_color" in data:
        color = data["brand_primary_color"]
        if color and re.match(r'^#[0-9a-fA-F]{6}$', color):
            tenant.brand_primary_color = color
    if "brand_accent_color" in data:
        color = data["brand_accent_color"]
        if color and re.match(r'^#[0-9a-fA-F]{6}$', color):
            tenant.brand_accent_color = color
    if "brand_font_family" in data:
        tenant.brand_font_family = data["brand_font_family"]
    if "hide_proofdeck_badge" in data:
        tenant.hide_proofdeck_badge = bool(data["hide_proofdeck_badge"])
    if "custom_support_email" in data:
        tenant.custom_support_email = data["custom_support_email"]
    if "custom_website_url" in data:
        tenant.custom_website_url = data["custom_website_url"]
    if "custom_sender_name" in data:
        tenant.custom_sender_name = data["custom_sender_name"]

    db.session.commit()
    return jsonify({"msg": "Branding updated successfully."}), 200


@whitelabel_bp.route('/domain', methods=['DELETE'])
@jwt_required()
def remove_custom_domain():
    """
    Tenant Admin Endpoint: Disconnect custom domain.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    is_comp, tenant_id, _, active_role = get_active_context(user)

    if not is_comp or not tenant_id:
        return jsonify({"msg": "Company workspace required."}), 400
    if active_role not in ('owner', 'admin'):
        return jsonify({"msg": "Only company owners and admins can remove custom domains."}), 403
    if not is_enterprise_context(user):
        return jsonify({"msg": "Custom domain management is exclusively available on the Enterprise plan."}), 403

    tenant = Tenant.query.get_or_404(tenant_id)
    if tenant.cloudflare_hostname_id:
        try:
            delete_custom_hostname(tenant.cloudflare_hostname_id)
        except Exception as e:
            current_app.logger.warning(f"Error deleting Cloudflare hostname: {e}")

    tenant.custom_domain = None
    tenant.cloudflare_hostname_id = None
    tenant.domain_status = "unconfigured"
    db.session.commit()

    return jsonify({"msg": "Custom domain disconnected successfully."}), 200
