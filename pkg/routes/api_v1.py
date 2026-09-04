from flask import Blueprint, request, jsonify, g, current_app
from functools import wraps
from datetime import datetime
from ..models import db, User, Template, Certificate
import uuid

# --- CHANGED IMPORTS ---
from ..services.pdf_service import generate_certificate_pdf
from ..services.email_service import create_certificate_email
from ..utils.helpers import parse_smart_date
from ..extensions import mail

# Create a new blueprint for the versioned API
api_v1_bp = Blueprint('api_v1', __name__)

def api_key_required(f):
    """Custom decorator to protect routes with an API key."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"msg": "Authentication failed: API key is missing."}), 401
        
        # Find the user associated with the provided API key
        user = User.query.filter_by(api_key=api_key).first()
        if not user:
            return jsonify({"msg": "Authentication failed: Invalid API key."}), 401

        # Attach the user object to the request context (g) for use in the route
        g.user = user
        return f(*args, **kwargs)
    return decorated_function

@api_v1_bp.route('/certificates', methods=['POST'])
@api_key_required
def create_certificate_via_api():
    """
    API endpoint for creating a single certificate.
    Authenticates via X-API-Key header.
    """
    # The user object is available from the decorator via g.user
    user = g.user
    data = request.get_json()

    required_fields = ['template_id', 'recipient_name', 'recipient_email', 'course_title', 'issue_date']
    if not all(field in data for field in required_fields):
        missing = [field for field in required_fields if field not in data]
        return jsonify({"msg": f"Missing required fields: {', '.join(missing)}"}), 400

    # Check user's certificate quota
    if user.cert_quota <= 0:
        return jsonify({"msg": "Insufficient certificate quota remaining"}), 403

    # Validate the template
    template = Template.query.get(data['template_id'])
    if not template or (not template.is_public and template.user_id != user.id):
        return jsonify({"msg": "Template not found or permission denied"}), 404

    try:
        issue_date = parse_smart_date(data['issue_date'])
        
        certificate = Certificate(
            user_id=user.id,
            template_id=template.id,
            recipient_name=data['recipient_name'],
            recipient_email=data['recipient_email'],
            course_title=data['course_title'],
            issuer_name=data.get('issuer_name', user.name),
            issue_date=issue_date,
            extra_fields=data.get('extra_fields', {}),
            verification_id=str(uuid.uuid4())
        )
        
        # Decrement quota and create certificate
        user.cert_quota -= 1
        db.session.add(certificate)
        db.session.commit()

        # Generate PDF and send email
        try:
            pdf_buffer = generate_certificate_pdf(certificate, template, user)
            
            certificate.template = template
            
            msg = create_certificate_email(certificate, pdf_buffer)
            mail.send(msg)
            
            certificate.sent_at = datetime.utcnow()
            db.session.commit()
            current_app.logger.info(f"API: Certificate {certificate.id} for user {user.id} created and emailed to {certificate.recipient_email}")
        except Exception as e:
            current_app.logger.error(f"API: Email sending error for cert {certificate.id}: {e}")
            # The certificate is still created, which is important. The external service might have its own retry logic for delivery.
            # We don't roll back the creation.

        frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')
        verification_url = f"{frontend_url}/verify/{certificate.verification_id}"

        return jsonify({
            "msg": "Certificate created and dispatched successfully.",
            "certificate_id": certificate.id,
            "verification_id": certificate.verification_id,
            "verification_url": verification_url
        }), 201

    except ValueError as e:
        return jsonify({"msg": f"Invalid data format: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API Error creating certificate for user {user.id}: {e}")
        return jsonify({"msg": "An internal error occurred."}), 500


@api_v1_bp.route('/account', methods=['GET'])
@api_key_required
def get_account_info_api():
    """Returns the authenticated account details and remaining credit quota."""
    user = g.user
    from ..utils.helpers import get_active_context
    is_comp, tenant_id, quota_holder, active_role = get_active_context(user)
    
    return jsonify({
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "plan_role": user.role,
        "available_quota": quota_holder.cert_quota if is_comp else user.cert_quota,
        "personal_quota": user.cert_quota,
        "operating_context": "team" if is_comp else "personal"
    }), 200


@api_v1_bp.route('/templates', methods=['GET'])
@api_key_required
def get_templates_api():
    """Lists templates accessible by the authenticated user."""
    user = g.user
    templates = Template.query.filter(
        (Template.user_id == user.id) | (Template.is_public == True)
    ).order_by(Template.created_at.desc()).all()

    templates_data = []
    for t in templates:
        templates_data.append({
            "id": t.id,
            "title": t.title,
            "layout_style": t.layout_style,
            "is_public": t.is_public,
            "created_at": t.created_at.isoformat() if t.created_at else None
        })

    return jsonify({"templates": templates_data}), 200


@api_v1_bp.route('/certificates/<string:verification_id>', methods=['GET'])
@api_key_required
def get_certificate_details_api(verification_id):
    """Retrieves single certificate details by verification_id."""
    user = g.user
    cert = Certificate.query.filter_by(verification_id=verification_id).first()
    if not cert:
        return jsonify({"msg": "Certificate not found."}), 404

    # Ensure certificate belongs to the user or their workspace
    if cert.user_id != user.id and cert.tenant_id != (user.owned_tenant.id if hasattr(user, 'owned_tenant') and user.owned_tenant else None):
        return jsonify({"msg": "Permission denied."}), 403

    frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')

    return jsonify({
        "certificate_id": cert.id,
        "verification_id": cert.verification_id,
        "recipient_name": cert.recipient_name,
        "recipient_email": cert.recipient_email,
        "course_title": cert.course_title,
        "issuer_name": cert.issuer_name,
        "issue_date": cert.issue_date.isoformat() if cert.issue_date else None,
        "status": cert.status,
        "verification_url": f"{frontend_url}/verify/{cert.verification_id}",
        "extra_fields": cert.extra_fields or {}
    }), 200


@api_v1_bp.route('/certificates/<string:verification_id>/revoke', methods=['POST'])
@api_key_required
def revoke_certificate_api(verification_id):
    """Revokes an issued certificate."""
    user = g.user
    cert = Certificate.query.filter_by(verification_id=verification_id).first()
    if not cert:
        return jsonify({"msg": "Certificate not found."}), 404

    if cert.user_id != user.id and cert.tenant_id != (user.owned_tenant.id if hasattr(user, 'owned_tenant') and user.owned_tenant else None):
        return jsonify({"msg": "Permission denied."}), 403

    cert.status = 'revoked'
    db.session.commit()

    return jsonify({
        "msg": f"Certificate {verification_id} has been revoked successfully.",
        "status": cert.status
    }), 200