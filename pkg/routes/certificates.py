from flask import Blueprint, request, jsonify, Response, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from sqlalchemy import func, case
import csv
from io import StringIO, BytesIO
import threading
import uuid
import uuid
import pandas as pd
from flask_mail import Message

# Database & Models
from ..models import db, Certificate, Template, User, Company
from ..extensions import mail

# Modular Services & Utils
from ..services.pdf_service import generate_certificate_pdf
from ..services.email_service import create_certificate_email
from ..services.bulk_service import process_bulk_upload
from ..utils.helpers import parse_smart_date, normalize_email

certificate_bp = Blueprint('certificates', __name__)

# --- Notification Helpers (Local to this route group) ---

def _send_issuer_notification_email(issuer, subject, summary_html):
    try:
        msg = Message(
            subject=subject,
            sender=('ProofDeck', current_app.config.get('MAIL_USERNAME')),
            recipients=[issuer.email],
            html=summary_html
        )
        mail.send(msg)
    except Exception as e:
        current_app.logger.error(f"Failed to send issuer notification: {e}")

def _create_issuer_summary_email(issuer_name, count, cert_list, action_type="created"):
    rows_html = "".join([
        f"<tr><td>{i+1}</td><td>{c['recipient_name']}</td><td>{c['course_title']}</td><td>{c['verification_id']}</td></tr>"
        for i, c in enumerate(cert_list[:20]) # Limit to first 20 in email to prevent bloat
    ])
    
    if len(cert_list) > 20:
        rows_html += f"<tr><td colspan='4' style='text-align:center;'>...and {len(cert_list) - 20} more...</td></tr>"

    dashboard_url = f"{current_app.config['FRONTEND_URL']}/dashboard"

    html = f"""
    <html>
    <body style="font-family:Arial, sans-serif; background:#f8f9fa; padding:20px;">
        <div style="max-width:600px;margin:auto;background:white;padding:30px;border-radius:8px;">
            <h2 style="color:#2563EB;">ProofDeck — Documents {action_type.title()}</h2>
            <p>Dear <b>{issuer_name}</b>,</p>
            <p>This is to confirm that <b>{count}</b> document{'s' if count > 1 else ''} have been successfully {action_type}.</p>

            <table width="100%" border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse; margin-top:20px;">
                <thead style="background:#2563EB;color:white;">
                    <tr>
                        <th>#</th><th>Recipient</th><th>Title</th><th>ID</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>

            <p style="margin-top:20px;">View details on your dashboard.</p>
            <a href="{dashboard_url}" style="display:inline-block;background:#2563EB;color:white;padding:12px 20px;border-radius:5px;text-decoration:none;margin-top:10px;">Go to Dashboard</a>
        </div>
    </body>
    </html>
    """
    return html


# --- Routes ---

@certificate_bp.route('/<int:cert_id>/pdf', methods=['GET'])
@jwt_required()
def get_certificate_pdf(cert_id):
    """
    Generates and downloads the PDF for a specific certificate.
    """
    user_id = int(get_jwt_identity())
    certificate = Certificate.query.get_or_404(cert_id)
    
    # Ownership check
    if certificate.user_id != user_id:
        return jsonify({"msg": "Permission denied"}), 403

    template = Template.query.get(certificate.template_id)
    issuer = User.query.get(certificate.user_id)

    try:
        # Use centralized service
        pdf_buffer = generate_certificate_pdf(certificate, template, issuer)
        return Response(
            pdf_buffer, 
            mimetype='application/pdf', 
            headers={'Content-Disposition': f'attachment; filename=doc_{certificate.verification_id}.pdf'}
        )
    except Exception as e:
        current_app.logger.error(f"PDF Gen Error: {e}")
        return jsonify({"msg": "Failed to generate PDF"}), 500


@certificate_bp.route('/', methods=['POST'])
@jwt_required()
def create_certificate():
    """
    Creates a single certificate or receipt.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    data = request.get_json()

    required_fields = ['template_id', 'recipient_name', 'course_title', 'issue_date']
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"msg": "Missing required fields"}), 400

    template = Template.query.get(data['template_id'])
    if not template or (not template.is_public and template.user_id != user_id):
        return jsonify({"msg": "Template not found or permission denied"}), 404

    if user.cert_quota <= 0:
        return jsonify({"msg": "Insufficient quota remaining"}), 403

    try:
        # Use Utils for parsing
        issue_date = parse_smart_date(data['issue_date'])
        recipient_email = normalize_email(data.get('recipient_email'))
        
        extra_fields = data.get('extra_fields', {})
        
        # Fallback signature logic
        sig = data.get('signature')
        if not sig and user.signature_image_url:
            sig = user.name
            
        # Fallback issuer name logic
        issuer_name = data.get('issuer_name')
        if not issuer_name:
            issuer_name = user.company.name if user.company else user.name

        certificate = Certificate(
            user_id=user_id,
            company_id=user.company_id,
            template_id=template.id,
            group_id=data.get('group_id'),
            recipient_name=data['recipient_name'],
            recipient_email=recipient_email, 
            course_title=data['course_title'],
            issuer_name=issuer_name,
            issue_date=issue_date,
            signature=sig,
            extra_fields=extra_fields,
            verification_id=str(uuid.uuid4())
        )
        
        user.cert_quota -= 1
        db.session.add(certificate)
        db.session.commit()

        email_sent = False

        # Email Sending Logic
        if certificate.recipient_email:
            try:
                # Generate PDF using Service
                pdf_buffer = generate_certificate_pdf(certificate, template, user)
                
                # Attach template to object for email service logic (checks if receipt)
                certificate.template = template 
                
                # Create & Send
                msg = create_certificate_email(certificate, pdf_buffer)
                mail.send(msg)
                
                certificate.sent_at = datetime.utcnow()
                db.session.commit()
                email_sent = True
                
                # Notify Issuer
                issuer_summary = [{"recipient_name": certificate.recipient_name, "course_title": certificate.course_title, "verification_id": certificate.verification_id}]
                summary_html = _create_issuer_summary_email(user.name, 1, issuer_summary, action_type="created and sent")
                _send_issuer_notification_email(user, "Document Issued — ProofDeck", summary_html)

            except Exception as e:
                current_app.logger.error(f"Email sending error for cert {certificate.id}: {e}")
                # We do NOT rollback transaction here; the cert is created even if email fails
        
        response_msg = "Document created" + (" and emailed successfully" if email_sent else " successfully")
        return jsonify({
            "msg": response_msg, 
            "certificate_id": certificate.id, 
            "verification_id": certificate.verification_id
        }), 201

    except Exception as e:
        current_app.logger.error(f"Error creating certificate: {e}")
        db.session.rollback()
        return jsonify({"msg": "Failed to create document"}), 500


@certificate_bp.route('/', methods=['GET'])
@jwt_required()
def get_certificates():
    """
    Lists all certificates for the current user.
    """
    user_id = int(get_jwt_identity())
    certs = Certificate.query.filter_by(user_id=user_id).order_by(Certificate.created_at.desc()).all()

    return jsonify([{
        'id': cert.id, 
        'recipient_name': cert.recipient_name,
        'recipient_email': cert.recipient_email, 
        'course_title': cert.course_title,
        'issue_date': cert.issue_date.isoformat(), 
        'status': cert.status,
        'verification_id': cert.verification_id, 
        'sent_at': cert.sent_at.isoformat() if cert.sent_at else None,
        'template_id': cert.template_id, 
        'group_id': cert.group_id,
        'extra_fields': cert.extra_fields
    } for cert in certs]), 200


@certificate_bp.route('/<int:cert_id>', methods=['GET'])
@jwt_required()
def get_certificate(cert_id):
    """
    Gets details of a single certificate.
    """
    user_id = int(get_jwt_identity())
    certificate = Certificate.query.get_or_404(cert_id)
    if certificate.user_id != user_id:
        return jsonify({"msg": "Permission denied"}), 403

    template = Template.query.get_or_404(certificate.template_id)
    
    cert_data = {
        'id': certificate.id, 
        'recipient_name': certificate.recipient_name,
        'recipient_email': certificate.recipient_email, 
        'course_title': certificate.course_title,
        'issue_date': certificate.issue_date.isoformat(), 
        'issuer_name': certificate.issuer_name,
        'signature': certificate.signature, 
        'verification_id': certificate.verification_id,
        'status': certificate.status, 
        'extra_fields': certificate.extra_fields
    }
    
    template_data = {
        'id': template.id, 
        'title': template.title, 
        'logo_url': template.logo_url,
        'background_url': template.background_url, 
        'primary_color': template.primary_color,
        'secondary_color': template.secondary_color, 
        'body_font_color': template.body_font_color,
        'font_family': template.font_family, 
        'layout_style': template.layout_style,
        'layout_data': template.layout_data,
        'is_public': template.is_public, 
        'custom_text': template.custom_text
    }
    return jsonify({ "certificate": cert_data, "template": template_data }), 200


@certificate_bp.route('/<int:cert_id>', methods=['PUT'])
@jwt_required()
def update_certificate(cert_id):
    """
    Updates certificate details.
    """
    user_id = int(get_jwt_identity())
    cert = Certificate.query.get_or_404(cert_id)
    
    if cert.user_id != user_id:
        return jsonify({"msg": "Unauthorized"}), 403
        
    data = request.get_json()
    
    if 'recipient_name' in data: cert.recipient_name = data['recipient_name']
    if 'recipient_email' in data: cert.recipient_email = normalize_email(data['recipient_email'])
    if 'course_title' in data: cert.course_title = data['course_title']
    if 'issuer_name' in data: cert.issuer_name = data['issuer_name']
    if 'issue_date' in data: cert.issue_date = parse_smart_date(data['issue_date'])
    if 'signature' in data: cert.signature = data['signature']
    if 'extra_fields' in data: cert.extra_fields = data['extra_fields']
    if 'template_id' in data: cert.template_id = data['template_id']
    
    db.session.commit()
    return jsonify({"msg": "Updated successfully"}), 200


@certificate_bp.route('/bulk', methods=['POST'])
@jwt_required()
def bulk_create_certificates():
    """
    Handles bulk certificate creation via CSV/Excel upload using the Bulk Service.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    
    if 'file' not in request.files: 
        return jsonify({"msg": "No file part"}), 400

    file = request.files['file']
    if not file:
        return jsonify({"msg": "No file selected."}), 400
        
    template_id = request.form.get('template_id')
    group_id = request.form.get('group_id')
    if not template_id or not group_id:
        return jsonify({"msg": "Template ID and Group ID are required"}), 400

    template = Template.query.get(template_id)
    if not template or (not template.is_public and template.user_id != user_id):
        return jsonify({"msg": "Template not found or permission denied"}), 404

    # Call the Bulk Service to handle parsing and processing in a BACKGROUND THREAD
    # We read the file stream into memory first to avoid file handle closure issues
    try:
        file_content = file.read()
        filename = file.filename
        
        # We need to pass the app object for the thread to create an app_context
        app = current_app._get_current_object()
        
        thread = threading.Thread(target=process_bulk_upload, args=(app, file_content, filename, template.id, group_id, user.id))
        thread.start()
        
        return jsonify({"msg": "Processing started. You will be notified via email upon completion."}), 202
        
    except Exception as e:
        current_app.logger.error(f"Failed to start background process: {e}")
        return jsonify({"msg": "Failed to start processing"}), 500


@certificate_bp.route('/bulk-template', methods=['GET'])
@jwt_required()
def download_bulk_template():
    """
    Returns a CSV template for bulk uploads.
    """
    output = StringIO()
    writer = csv.writer(output)
    # Added 'amount' for receipt support
    headers = ['recipient_name', 'recipient_email', 'course_title', 'issuer_name', 'issue_date', 'signature', 'amount']
    writer.writerow(headers)
    writer.writerow(['Jane Doe', 'jane@example.com', 'Web Development', 'Tech Institute', '2024-10-22', 'Dr. Smith', '500.00'])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=proofdeck_bulk_template.csv"})


@certificate_bp.route('/<int:cert_id>/send', methods=['POST'])
@jwt_required()
def send_certificate_email_route(cert_id):
    """
    Resends an email for a specific certificate.
    """
    user_id = int(get_jwt_identity())
    certificate = Certificate.query.get_or_404(cert_id)
    
    if certificate.user_id != user_id: 
        return jsonify({"msg": "Permission denied"}), 403
    if not certificate.recipient_email: 
        return jsonify({"msg": "No email address found for this recipient."}), 400
    
    try:
        template = Template.query.get(certificate.template_id)
        issuer = User.query.get(user_id)
        
        # Generate PDF
        pdf_buffer = generate_certificate_pdf(certificate, template, issuer)
        
        # Attach template for email logic checks (is_receipt?)
        certificate.template = template
        
        # Create and Send
        msg = create_certificate_email(certificate, pdf_buffer)
        mail.send(msg)
        
        certificate.sent_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"msg": "Emailed successfully"}), 200
    except Exception as e:
        current_app.logger.error(f"Email error: {e}")
        return jsonify({"msg": "Failed to send email"}), 500


@certificate_bp.route('/bulk-send', methods=['POST'])
@jwt_required()
def send_bulk_emails():
    """
    Sends emails for a list of certificate IDs.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    certificate_ids = data.get('certificate_ids', [])
    
    if not certificate_ids: 
        return jsonify({"msg": "No IDs provided"}), 400

    sent, errors = 0, []
    certs_to_send = Certificate.query.filter(Certificate.id.in_(certificate_ids), Certificate.user_id == user_id).all()
    
    for cert in certs_to_send:
        if not cert.recipient_email:
            errors.append({"id": cert.id, "msg": "No email address"})
            continue
        try:
            template = Template.query.get(cert.template_id)
            pdf_buffer = generate_certificate_pdf(cert, template, user)
            
            cert.template = template
            msg = create_certificate_email(cert, pdf_buffer)
            mail.send(msg)
            
            cert.sent_at = datetime.utcnow()
            sent += 1
        except Exception as e: 
            errors.append({"id": cert.id, "msg": str(e)})
            
    db.session.commit()
    
    # Notify Issuer about bulk send completion
    if sent > 0:
        cert_list = [{"recipient_name": c.recipient_name, "course_title": c.course_title, "verification_id": c.verification_id} for c in certs_to_send if c.sent_at]
        summary_html = _create_issuer_summary_email(user.name, sent, cert_list, action_type="sent")
        _send_issuer_notification_email(user, "Bulk Emails Sent — ProofDeck", summary_html)

    if errors: 
        return jsonify({"msg": f"Sent {sent} emails with {len(errors)} errors", "sent": sent, "errors": errors}), 207
    
    return jsonify({"msg": f"Successfully sent {sent} emails"}), 200


@certificate_bp.route('/verify/<string:verification_id>', methods=['GET'])
def verify_certificate(verification_id):
    """
    Public Verification Endpoint.
    """
    certificate = Certificate.query.filter_by(verification_id=verification_id).first()
    if not certificate:
        return jsonify({"msg": "Certificate not found"}), 404

    template = Template.query.get_or_404(certificate.template_id)

    company_data = None
    if certificate.company_id:
        company = Company.query.get(certificate.company_id)
        if company:
            company_data = { "id": company.id, "name": company.name }

    certificate_data = {
        "id": certificate.id,
        "recipient_name": certificate.recipient_name,
        "recipient_email": certificate.recipient_email,
        "course_title": certificate.course_title,
        "issue_date": certificate.issue_date.isoformat(),
        "issuer_name": certificate.issuer_name,
        "status": certificate.status,
        "verification_id": certificate.verification_id,
        "signature": certificate.signature,
        "extra_fields": certificate.extra_fields
    }

    template_data = {
        "id": template.id,
        "title": template.title,
        "layout_style": template.layout_style,
        "layout_data": template.layout_data,
        "logo_url": template.logo_url,
        "background_url": template.background_url,
        "primary_color": template.primary_color,
        "secondary_color": template.secondary_color,
        "body_font_color": template.body_font_color,
        "font_family": template.font_family,
        "custom_text": template.custom_text
    }

    return jsonify({
        "certificate": certificate_data,
        "template": template_data,
        "company": company_data
    }), 200


@certificate_bp.route('/<int:cert_id>/status', methods=['PUT'])
@jwt_required()
def update_certificate_status(cert_id):
    """
    Revoke or Re-validate a certificate.
    """
    user_id = int(get_jwt_identity())
    certificate = Certificate.query.get_or_404(cert_id)
    if certificate.user_id != user_id:
        return jsonify({"msg": "Permission denied"}), 403

    data = request.get_json()
    status = data.get('status')
    if status not in ['valid', 'revoked']:
        return jsonify({"msg": "Invalid status"}), 400

    certificate.status = status
    db.session.commit()
    return jsonify({"msg": f"Status updated to {status}"}), 200

@certificate_bp.route('/advanced-search', methods=['GET'])
def advanced_search_certificates():
    """
    Public Ledger Search.
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 9
        recipient_name = request.args.get('recipient', '').strip()
        issuer_name_filter = request.args.get('issuer', '').strip()
        course_title = request.args.get('course', '').strip()
        start_date_str = request.args.get('start_date', '').strip()
        end_date_str = request.args.get('end_date', '').strip()
        sort_by = request.args.get('sort_by', 'issue_date')
        sort_order = request.args.get('sort_order', 'desc')

        # Advanced Query Building
        issuer_name_column = func.coalesce(Company.name, User.name).label('issuer_name')
        issuer_type_column = case((Company.id != None, 'company'), else_='individual').label('issuer_type')

        base_query = db.session.query(
            Certificate.recipient_name,
            Certificate.course_title,
            Certificate.issue_date,
            Certificate.verification_id,
            issuer_name_column,
            issuer_type_column
        ).join(User, Certificate.user_id == User.id) \
         .join(Company, Certificate.company_id == Company.id, isouter=True)

        if len(recipient_name) >= 3:
            base_query = base_query.filter(func.lower(Certificate.recipient_name).like(f"%{recipient_name.lower()}%"))
        if len(issuer_name_filter) >= 2:
            base_query = base_query.filter(func.lower(issuer_name_column).like(f"%{issuer_name_filter.lower()}%"))
        if len(course_title) >= 3:
            base_query = base_query.filter(func.lower(Certificate.course_title).like(f"%{course_title.lower()}%"))

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                base_query = base_query.filter(Certificate.issue_date.between(start_date, end_date))
            except ValueError:
                pass

        sort_column = Certificate.issue_date
        if sort_by == 'recipient_name': sort_column = func.lower(Certificate.recipient_name)
        
        base_query = base_query.order_by(sort_column.asc() if sort_order == 'asc' else sort_column.desc())

        paginated_results = base_query.paginate(page=page, per_page=per_page, error_out=False)

        results = [{
            "recipient_name": cert.recipient_name,
            "course_title": cert.course_title,
            "issue_date": cert.issue_date.isoformat(),
            "verification_id": cert.verification_id,
            "issuer_name": cert.issuer_name,
            "issuer_type": cert.issuer_type
        } for cert in paginated_results.items]

        return jsonify({
            "results": results,
            "pagination": {
                "total": paginated_results.total,
                "pages": paginated_results.pages,
                "page": paginated_results.page,
                "has_next": paginated_results.has_next,
                "has_prev": paginated_results.has_prev,
                "per_page": per_page
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"Search error: {e}")
        return jsonify({"msg": "Search error"}), 500

@certificate_bp.route('/<int:cert_id>', methods=['DELETE'])
@jwt_required()
def delete_certificate(cert_id):
    """
    Deletes a certificate.
    """
    user_id = int(get_jwt_identity())
    certificate = Certificate.query.get_or_404(cert_id)
    if certificate.user_id != user_id:
        return jsonify({"msg": "Permission denied"}), 403

    try:
        db.session.delete(certificate)
        db.session.commit()
        return jsonify({"msg": "Certificate deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(f"Error deleting certificate {cert_id}: {e}")
        db.session.rollback()
        return jsonify({"msg": "Failed to delete certificate"}), 500