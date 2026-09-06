from flask import Blueprint, request, jsonify, current_app
from ..models import SupportWidgetMessage, User
from ..extensions import db, mail
from ..utils.email_utils import get_sender
from flask_mail import Message as MailMessage
import os
import traceback
import bleach

support_bp = Blueprint('support', __name__)


def _notify_admin_of_widget_message(sender_email, message_text):
    """Send an email notification to the admin when a visitor sends a widget message."""
    admin_email = current_app.config.get('ADMIN_EMAIL') or 'support@proofdeck.app'
    frontend_url = current_app.config.get('FRONTEND_URL', 'https://proofdeck.app')

    clean_message = bleach.clean(message_text)
    clean_email = bleach.clean(sender_email or 'Anonymous visitor')

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #4F46E5, #4338CA); padding: 24px 28px; border-radius: 12px 12px 0 0;">
            <h2 style="color: #ffffff; margin: 0; font-size: 18px;">💬 New Widget Message</h2>
            <p style="color: rgba(255,255,255,0.8); margin: 6px 0 0; font-size: 13px;">Someone reached out via the support chat on proofdeck.app</p>
        </div>
        <div style="background: #ffffff; padding: 24px 28px; border: 1px solid #E5E7EB; border-top: none;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px 0; color: #6B7280; font-size: 13px; width: 80px; vertical-align: top;">From:</td>
                    <td style="padding: 8px 0; font-size: 14px; font-weight: 600; color: #0B0B12;">{clean_email}</td>
                </tr>
            </table>
            <hr style="border: none; border-top: 1px solid #F3F4F6; margin: 16px 0;">
            <div style="background: #F9FAFB; border-radius: 8px; padding: 16px; border: 1px solid #F3F4F6;">
                <p style="color: #374151; font-size: 14px; line-height: 1.6; margin: 0; white-space: pre-wrap;">{clean_message}</p>
            </div>
            <div style="margin-top: 20px; text-align: center;">
                <a href="{frontend_url}/admin/support"
                   style="display: inline-block; background: #4F46E5; color: #ffffff; text-decoration: none; padding: 10px 24px; border-radius: 8px; font-size: 13px; font-weight: 600;">
                    View in Admin Panel →
                </a>
            </div>
        </div>
        <div style="text-align: center; padding: 16px; color: #9CA3AF; font-size: 11px;">
            ProofDeck Support Notifications
        </div>
    </div>
    """

    msg = MailMessage(
        subject=f"💬 New widget message from {clean_email}",
        sender=get_sender('ProofDeck Support'),
        recipients=[admin_email],
        reply_to=sender_email if sender_email else None,
        html=html_body
    )

    try:
        mail.send(msg)
        current_app.logger.info(f"Widget notification email sent to {admin_email}")
    except Exception as e:
        # Log but don't fail the request — the message is already saved
        current_app.logger.error(f"Failed to send widget notification email: {e}\n{traceback.format_exc()}")


@support_bp.route('/message', methods=['POST'])
def send_support_message():
    data = request.get_json()
    email = data.get('email') # Optional if already in session/logged in
    message = data.get('message')
    user_id = data.get('user_id') # Optional
    session_id = data.get('session_id') # For guest tracking

    if not message:
        return jsonify({"msg": "Message is required."}), 400
    
    # 1. Save to Database
    try:
        new_ticket = SupportWidgetMessage(
            email=email,
            message=message,
            user_id=user_id if user_id else None,
            session_id=session_id,
            sender_type='user'
        )
        db.session.add(new_ticket)
        db.session.commit()
    except Exception as e:
        return jsonify({"msg": f"Failed to save message: {str(e)}"}), 500

    # 2. Send email notification to admin
    _notify_admin_of_widget_message(email, message)
    
    return jsonify({"msg": "Message sent successfully!"}), 200

@support_bp.route('/history', methods=['GET'])
def get_chat_history():
    session_id = request.args.get('session_id')
    user_id = request.args.get('user_id')

    # Must provide either a session_id or a user_id
    if not session_id and not user_id:
        return jsonify({"msg": "Session ID or User ID required"}), 400

    query = SupportWidgetMessage.query

    if user_id:
        # If user is logged in, show their messages OR messages from their session
        # This covers case where they started chatting as guest then logged in
        query = query.filter((SupportWidgetMessage.user_id == user_id) | (SupportWidgetMessage.session_id == session_id))
    elif session_id:
        query = query.filter(SupportWidgetMessage.session_id == session_id)
    
    # Get all messages sorted by time
    messages = query.order_by(SupportWidgetMessage.created_at.asc()).all()
    
    history = []
    for msg in messages:
        sender_name = "You"
        if msg.sender_type == 'admin':
            sender_name = "Support Team"
        elif msg.sender_type == 'user':
             sender_name = "You"

        history.append({
            'id': msg.id,
            'message': msg.message,
            'sender': msg.sender_type,
            'sender_name': sender_name,
            'created_at': msg.created_at.isoformat()
        })
        
    return jsonify({'history': history}), 200