from flask import Blueprint, request, jsonify, current_app, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Group, Certificate, Template
from ..extensions import mail
from datetime import datetime
from io import BytesIO
import zipfile
import re

# --- CHANGED IMPORTS ---
from ..services.pdf_service import generate_certificate_pdf
from ..services.email_service import create_certificate_email

groups_bp = Blueprint('groups', __name__)

@groups_bp.route('/', methods=['POST'])
@jwt_required()
def create_group():
    user_id = int(get_jwt_identity())
    data = request.get_json()
    name = data.get('name')
    if not name: return jsonify({"msg": "Group name is required"}), 400
    new_group = Group(user_id=user_id, name=name)
    db.session.add(new_group)
    db.session.commit()
    return jsonify({"msg": "Group created successfully", "group": { "id": new_group.id, "name": new_group.name, "certificate_count": 0 }}), 201

@groups_bp.route('/', methods=['GET'])
@jwt_required()
def get_groups():
    user_id = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    pagination = Group.query.filter_by(user_id=user_id).order_by(Group.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    groups_data = [{"id": group.id, "name": group.name, "certificate_count": len(group.certificates), "created_at": group.created_at.isoformat()} for group in pagination.items]
    return jsonify({"groups": groups_data, "total": pagination.total, "pages": pagination.pages, "current_page": pagination.page}), 200

@groups_bp.route('/<int:group_id>', methods=['GET'])
@jwt_required()
def get_group_details(group_id):
    user_id = int(get_jwt_identity())
    group = Group.query.filter_by(id=group_id, user_id=user_id).first_or_404()
    certificates_data = [{'id': c.id, 'recipient_name': c.recipient_name, 'recipient_email': c.recipient_email, 'course_title': c.course_title, 'issue_date': c.issue_date.isoformat(), 'sent_at': c.sent_at.isoformat() if c.sent_at else None} for c in group.certificates]
    return jsonify({"id": group.id, "name": group.name, "certificates": certificates_data}), 200

@groups_bp.route('/<int:group_id>', methods=['DELETE'])
@jwt_required()
def delete_group(group_id):
    user_id = int(get_jwt_identity())
    group = Group.query.filter_by(id=group_id, user_id=user_id).first_or_404()
    Certificate.query.filter_by(group_id=group.id, user_id=user_id).delete()
    db.session.delete(group)
    db.session.commit()
    return jsonify({"msg": "Group and all associated certificates deleted successfully"}), 200

@groups_bp.route('/<int:group_id>/send-bulk-email', methods=['POST'])
@jwt_required()
def send_bulk_email_for_group(group_id):
    user_id = int(get_jwt_identity())
    group = Group.query.filter_by(id=group_id, user_id=user_id).first_or_404()

    certificates_to_send = [cert for cert in group.certificates if not cert.sent_at]
    if not certificates_to_send:
        return jsonify({"msg": "All certificates in this group have already been sent."}), 400

    sent_certs, errors = [], []
    
    # Iterate and send
    for certificate in certificates_to_send:
        try:
            # Re-fetch template to be safe
            template = Template.query.get(certificate.template_id)
            
            # Generate PDF
            pdf_buffer = generate_certificate_pdf(certificate, template, group.user)
            
            # Attach template for email logic
            certificate.template = template
            
            # Create Email
            msg = create_certificate_email(certificate, pdf_buffer)
            mail.send(msg)
            
            certificate.sent_at = datetime.utcnow()
            sent_certs.append(certificate.id)
            
        except Exception as e:
            current_app.logger.error(f"Failed to send email for cert {certificate.id}: {e}")
            errors.append({"certificate_id": certificate.id, "msg": str(e)})

    db.session.commit()
    
    if errors:
        return jsonify({"msg": f"Processed with errors. Sent: {len(sent_certs)}", "sent": sent_certs, "errors": errors}), 207
    return jsonify({"msg": f"Successfully sent {len(sent_certs)} emails"}), 200

@groups_bp.route('/<int:group_id>/download-bulk-pdf', methods=['GET'])
@jwt_required()
def download_bulk_pdf_for_group(group_id):
    user_id = int(get_jwt_identity())
    group = Group.query.filter_by(id=group_id, user_id=user_id).first_or_404()

    if not group.certificates:
        return jsonify({"msg": "This group contains no certificates to download."}), 404

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for certificate in group.certificates:
            try:
                template = Template.query.get(certificate.template_id)
                pdf_buffer = generate_certificate_pdf(certificate, template, group.user)
                
                # Sanitize recipient name for the filename
                sane_name = re.sub(r'[\W_]+', '_', certificate.recipient_name)
                filename = f"certificate_{sane_name}_{certificate.verification_id[:8]}.pdf"
                zip_file.writestr(filename, pdf_buffer.getvalue())
            except Exception as e:
                current_app.logger.error(f"Skipping PDF for cert {certificate.id} due to error: {e}")
                zip_file.writestr(f"ERROR_cert_{certificate.id}.txt", f"Could not generate PDF. Error: {e}")

    zip_buffer.seek(0)
    
    # Sanitize group name for the zip filename
    sane_group_name = re.sub(r'[\W_]+', '_', group.name)
    zip_filename = f"{sane_group_name}_certificates.zip"

    return Response(
        zip_buffer,
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename={zip_filename}'}
    )