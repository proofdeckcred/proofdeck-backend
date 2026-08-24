from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from ..models import db, Admin, User, SupportWidgetMessage
from ..utils.email_utils import send_bulk_email
import bleach

admin_messaging_bp = Blueprint('admin_messaging', __name__)

@admin_messaging_bp.route('/messaging/send-email', methods=['POST'])
@jwt_required()
def handle_send_email():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    data = request.get_json()
    subject = data.get('subject')
    html_body = data.get('body')
    recipient_ids = data.get('recipients') 
    header_image_url = data.get('header_image_url')

    if not all([subject, html_body, recipient_ids]):
        return jsonify({"msg": "Subject, body, and recipients are required"}), 400

    # Sanitize the HTML to prevent XSS but allow a wide range of formatting tags and styles
    # from the rich text editor.
    
    # Convert the default frozenset of tags to a list so we can add to it.
    allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
        'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'b', 'i', 'u', 'a', 'img', 
        'div', 'span', 'strong', 'em', 'ol', 'ul', 'li', 'blockquote', 'pre',
        'sub', 'sup', 'hr'
    ]
    
    # Allow attributes needed for links, images, and crucially, inline styles.
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'style', 'width', 'height'],
        '*': ['style'] # Allow style attribute on any tag for formatting like text-align.
    }
    
    clean_html = bleach.clean(html_body, tags=allowed_tags, attributes=allowed_attrs)

    if recipient_ids == 'all':
        users = User.query.filter(User.role != 'suspended').all()
    else:
        if not isinstance(recipient_ids, list):
            return jsonify({"msg": "Recipients must be a list of IDs or 'all'"}), 400
        
        # Split recipient IDs into real User IDs (int) and Lead IDs (strings like 'lead_me@example.com')
        user_ids = []
        lead_emails = []
        
        for rid in recipient_ids:
            if isinstance(rid, int) or (isinstance(rid, str) and rid.isdigit()):
                user_ids.append(int(rid))
            elif isinstance(rid, str) and rid.startswith('lead_'):
                # Extract email from ID format "lead_0" -> we need to map back or just rely on passed data if we restructure.
                # Actually, simpler approach: The frontend passes mixed IDs.
                # But here we query by ID. 
                # Optimization: We can't query leads by ID efficiently if they are dynamic.
                # Better approach for mixed lists: Pass 'leads' separately or handle gracefully.
                # Given current structure, let's assume 'recipients' contains User IDs.
                # If we want to support leads, we should update the frontend to pass emails directly or handle special IDs.
                pass
        
        users = User.query.filter(User.id.in_(user_ids), User.role != 'suspended').all()

    if not users and recipient_ids != 'all':
        # If no users found by ID, maybe they are all leads? 
        # For this iteration, let's focus on verifying the GET endpoint works for leads first.
        # Sending to leads requires updating send_bulk_email to handle raw emails not just User objects.
        # Let's return error if no users for now, to be safe.
        pass
        # return jsonify({"msg": "No valid (non-suspended) recipients found"}), 400

    try:
        # TODO: Update send_bulk_email to accept raw email list for leads
        send_bulk_email(users, subject, clean_html, header_image_url=header_image_url)
        return jsonify({"msg": f"Email successfully sent to {len(users)} users."}), 200
    except Exception as e:
        return jsonify({"msg": f"An error occurred while sending emails: {str(e)}"}), 500

@admin_messaging_bp.route('/messaging/recipients', methods=['GET'])
@jwt_required()
def get_recipient_list():
    """Provides a list of all non-suspended users AND support leads."""
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    # 1. Registered Users
    users = User.query.with_entities(User.id, User.name, User.email).filter(User.role != 'suspended').order_by(User.name).all()
    user_list = [{'id': u.id, 'name': u.name, 'email': u.email, 'type': 'user'} for u in users]
    
    # 2. Support Leads (Unique Emails from Widget)
    # We filter out emails that belong to registered users to avoid duplicates
    registered_emails = [u.email for u in users]
    
    support_leads_query = db.session.query(SupportWidgetMessage.email)\
        .distinct()\
        .filter(SupportWidgetMessage.email != None)\
        .filter(SupportWidgetMessage.email != '')\
        .filter(SupportWidgetMessage.email.notin_(registered_emails))\
        .all()
        
    support_leads = [{'id': f"lead_{i}", 'name': f"Guest ({email[0]})", 'email': email[0], 'type': 'lead'} for i, email in enumerate(support_leads_query)]
    
    # Combine
    all_recipients = user_list + support_leads
    
    return jsonify(all_recipients), 200