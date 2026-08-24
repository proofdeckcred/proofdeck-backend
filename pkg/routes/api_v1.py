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

        return jsonify({
            "msg": "Certificate created and dispatched successfully.",
            "certificate_id": certificate.id,
            "verification_id": certificate.verification_id
        }), 201

    except ValueError as e:
        return jsonify({"msg": f"Invalid data format: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API Error creating certificate for user {user.id}: {e}")
        return jsonify({"msg": "An internal error occurred."}), 500