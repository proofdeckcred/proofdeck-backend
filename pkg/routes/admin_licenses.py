import os
import re
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from ..models import db, Admin, EnterpriseLicense, LicenseActivation, AdminActionLog

admin_licenses_bp = Blueprint('admin_licenses', __name__)

def _generate_license_key(institution_name):
    # Generates a formatted key like PD-ENT-NILE-9F8A-7B2C-1E4D
    clean = re.sub(r'[^A-Za-z0-9]', '', institution_name.upper())[:4] or "UNIV"
    part1 = secrets.token_hex(2).upper()
    part2 = secrets.token_hex(2).upper()
    part3 = secrets.token_hex(2).upper()
    return f"PD-ENT-{clean}-{part1}-{part2}-{part3}"

@admin_licenses_bp.route('/licenses', methods=['GET'])
@jwt_required()
def list_licenses():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 15, type=int)
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = EnterpriseLicense.query

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            db.or_(
                EnterpriseLicense.institution_name.ilike(search_term),
                EnterpriseLicense.license_key.ilike(search_term),
                EnterpriseLicense.contact_person.ilike(search_term),
                EnterpriseLicense.contact_email.ilike(search_term)
            )
        )

    if status_filter:
        query = query.filter(EnterpriseLicense.status == status_filter)

    query = query.order_by(EnterpriseLicense.created_at.desc())
    pagination = query.paginate(page=page, per_page=limit, error_out=False)

    return jsonify({
        "licenses": [lic.to_dict() for lic in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": pagination.page
    }), 200

@admin_licenses_bp.route('/licenses', methods=['POST'])
@jwt_required()
def create_license():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    data = request.get_json() or {}
    institution_name = (data.get('institution_name') or '').strip()
    if not institution_name:
        return jsonify({"msg": "Institution name is required"}), 400

    duration_days = int(data.get('duration_days') or 365)
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    license_key = data.get('license_key') or _generate_license_key(institution_name)

    lic = EnterpriseLicense(
        license_key=license_key,
        institution_name=institution_name,
        contact_person=(data.get('contact_person') or '').strip(),
        contact_email=(data.get('contact_email') or '').strip(),
        contact_phone=(data.get('contact_phone') or '').strip(),
        plan_tier=data.get('plan_tier', 'enterprise_academic'),
        max_workstations=int(data.get('max_workstations') or 5),
        enable_sis_connector=bool(data.get('enable_sis_connector', True)),
        enable_custom_qr=bool(data.get('enable_custom_qr', True)),
        enable_bulk_documents=bool(data.get('enable_bulk_documents', True)),
        status='active',
        issued_at=datetime.utcnow(),
        expires_at=expires_at,
        notes=(data.get('notes') or '').strip()
    )

    db.session.add(lic)
    log = AdminActionLog(
        admin_id=current_user.id,
        action=f"Created enterprise license {lic.license_key} for {lic.institution_name}",
        target_type="enterprise_license",
        target_id=lic.id
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        "msg": "Enterprise license issued successfully.",
        "license": lic.to_dict()
    }), 201

@admin_licenses_bp.route('/licenses/<int:license_id>', methods=['GET'])
@jwt_required()
def get_license_details(license_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    lic = EnterpriseLicense.query.get_or_404(license_id)
    activations = [act.to_dict() for act in lic.activations]

    data = lic.to_dict()
    data['activations'] = activations
    return jsonify({"license": data}), 200

@admin_licenses_bp.route('/licenses/<int:license_id>/status', methods=['PATCH'])
@jwt_required()
def update_license_status(license_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    lic = EnterpriseLicense.query.get_or_404(license_id)
    data = request.get_json() or {}
    new_status = data.get('status')

    if new_status not in ['active', 'suspended', 'expired', 'revoked']:
        return jsonify({"msg": "Invalid status"}), 400

    lic.status = new_status
    log = AdminActionLog(
        admin_id=current_user.id,
        action=f"Changed status of license {lic.license_key} to {new_status}",
        target_type="enterprise_license",
        target_id=lic.id
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"msg": f"License is now {new_status}.", "license": lic.to_dict()}), 200

@admin_licenses_bp.route('/licenses/<int:license_id>/extend', methods=['POST'])
@jwt_required()
def extend_license(license_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    lic = EnterpriseLicense.query.get_or_404(license_id)
    data = request.get_json() or {}
    days = int(data.get('days') or 365)

    base_time = lic.expires_at if lic.expires_at and lic.expires_at > datetime.utcnow() else datetime.utcnow()
    lic.expires_at = base_time + timedelta(days=days)
    if lic.status in ['expired', 'suspended']:
        lic.status = 'active'

    log = AdminActionLog(
        admin_id=current_user.id,
        action=f"Extended license {lic.license_key} by {days} days until {lic.expires_at.strftime('%Y-%m-%d')}",
        target_type="enterprise_license",
        target_id=lic.id
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"msg": f"License extended until {lic.expires_at.strftime('%Y-%m-%d')}.", "license": lic.to_dict()}), 200

@admin_licenses_bp.route('/licenses/<int:license_id>', methods=['PUT'])
@jwt_required()
def update_license(license_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    lic = EnterpriseLicense.query.get_or_404(license_id)
    data = request.get_json() or {}

    if 'institution_name' in data and data['institution_name'].strip():
        lic.institution_name = data['institution_name'].strip()
    if 'contact_person' in data:
        lic.contact_person = (data['contact_person'] or '').strip()
    if 'contact_email' in data:
        lic.contact_email = (data['contact_email'] or '').strip()
    if 'contact_phone' in data:
        lic.contact_phone = (data['contact_phone'] or '').strip()
    if 'max_workstations' in data:
        try:
            lic.max_workstations = max(1, int(data['max_workstations']))
        except (ValueError, TypeError):
            pass
    if 'plan_tier' in data:
        lic.plan_tier = data['plan_tier']
    if 'enable_sis_connector' in data:
        lic.enable_sis_connector = bool(data['enable_sis_connector'])
    if 'enable_custom_qr' in data:
        lic.enable_custom_qr = bool(data['enable_custom_qr'])
    if 'enable_bulk_documents' in data:
        lic.enable_bulk_documents = bool(data['enable_bulk_documents'])
    if 'notes' in data:
        lic.notes = (data['notes'] or '').strip()

    log = AdminActionLog(
        admin_id=current_user.id,
        action=f"Updated enterprise license {lic.license_key} details (seats: {lic.max_workstations})",
        target_type="enterprise_license",
        target_id=lic.id
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        "msg": "Enterprise license updated successfully.",
        "license": lic.to_dict()
    }), 200
