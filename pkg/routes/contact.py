from flask import Blueprint, request, jsonify, current_app
from flask_mail import Message
from ..extensions import mail
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

    if not all([name, email, message]):
        return jsonify({"msg": "All fields are required."}), 400

    # Sanitize inputs to prevent HTML injection
    clean_name = bleach.clean(name)
    clean_message = bleach.clean(message)
    admin_email = current_app.config.get('ADMIN_EMAIL') or 'support@proofdeck.app'

    subject = f"New Contact Form Submission from {clean_name}"

    html_body = f"""
    <p>You have received a new message from the ProofDeck contact form:</p>
    <ul>
        <li><strong>Name:</strong> {clean_name}</li>
        <li><strong>Email:</strong> {email}</li>
    </ul>
    <hr>
    <p><strong>Message:</strong></p>
    <p>{clean_message}</p>
    """

    # Use get_sender to properly resolve a valid from-address (e.g. notifications@proofdeck.app)
    # instead of raw MAIL_USERNAME (which is 'resend' when using Resend SMTP)
    msg = Message(
        subject=subject,
        sender=get_sender('ProofDeck Contact Form'),
        recipients=[admin_email],
        reply_to=email, # Allows you to reply directly to the user
        html=html_body
    )

    try:
        mail.send(msg)
        return jsonify({"msg": "Thank you for your message! We'll get back to you shortly."}), 200
    except Exception as e:
        current_app.logger.error(f"Failed to send contact email: {e}\n{traceback.format_exc()}")
        return jsonify({"msg": "Could not send message. Please try again later."}), 500