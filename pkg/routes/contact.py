from flask import Blueprint, request, jsonify, current_app
from flask_mail import Message
from ..extensions import mail
from ..models import db, SupportWidgetMessage
from ..utils.email_utils import get_sender
import bleach
import traceback

contact_bp = Blueprint('contact', __name__)

@contact_bp.route('/', methods=['POST'])
def handle_contact_form():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    message = (data.get('message') or '').strip()
    company = (data.get('company') or '').strip()
    volume = (data.get('volume') or '').strip()

    if not all([name, email, message]):
        return jsonify({"msg": "Name, email, and message are required."}), 400

    # Sanitize inputs to prevent HTML injection
    clean_name = bleach.clean(name)
    clean_message = bleach.clean(message)
    clean_company = bleach.clean(company) if company else "Not specified"
    clean_volume = bleach.clean(volume) if volume else "Not specified"
    admin_email = current_app.config.get('ADMIN_EMAIL') or 'support@proofdeck.app'

    subject = f"New Inquiry from {clean_name}"
    if company:
        subject += f" ({clean_company})"

    html_body = f"""
    <p>You have received a new message from the ProofDeck website:</p>
    <ul>
        <li><strong>Name:</strong> {clean_name}</li>
        <li><strong>Email:</strong> {email}</li>
        <li><strong>Organization:</strong> {clean_company}</li>
        <li><strong>Estimated Volume:</strong> {clean_volume}</li>
    </ul>
    <hr>
    <p><strong>Message:</strong></p>
    <p>{clean_message}</p>
    """

    # Persist in SupportWidgetMessage so it appears in Admin Dashboard
    saved_to_db = False
    try:
        inquiry_text = f"[Pricing / Custom Plan Inquiry]\nOrganization: {clean_company}\nVolume: {clean_volume}\n\nMessage:\n{clean_message}"
        widget_msg = SupportWidgetMessage(
            email=email,
            message=inquiry_text,
            status='new',
            sender_type='user'
        )
        db.session.add(widget_msg)
        db.session.commit()
        saved_to_db = True
    except Exception as e:
        current_app.logger.warning(f"Could not persist contact message to DB: {e}")
        db.session.rollback()

    msg = Message(
        subject=subject,
        sender=get_sender('ProofDeck Inquiries'),
        recipients=[admin_email],
        reply_to=email,
        html=html_body
    )

    try:
        mail.send(msg)
        return jsonify({"msg": "Thank you for reaching out! Our team will get back to you shortly."}), 200
    except Exception as e:
        current_app.logger.error(f"Failed to send contact email: {e}\n{traceback.format_exc()}")
        if saved_to_db:
            return jsonify({"msg": "Thank you for reaching out! We have received your inquiry."}), 200
        return jsonify({"msg": "Could not send message. Please try again later."}), 500