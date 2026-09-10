import os
import requests
from flask import current_app
from flask_mail import Message
from ..extensions import db, mail
from ..models import EmailLog, EmailPreference, User
from datetime import datetime, timezone

RESEND_API_URL = "https://api.resend.com/emails"

def get_promotions_sender():
    """
    Returns the promotional sender identity strictly isolated to mail.proofdeck.app.
    """
    return os.environ.get('MAIL_PROMOTIONS_SENDER', 'ProofDeck <hello@mail.proofdeck.app>')

def get_reply_to_email():
    """
    Returns the email address where direct recipient replies are routed.
    Defaults to support@proofdeck.app (or ADMIN_EMAIL).
    """
    return os.environ.get('MAIL_REPLY_TO') or os.environ.get('ADMIN_EMAIL') or 'support@proofdeck.app'

def get_resend_api_key():
    """
    Retrieves the Resend API key from RESEND_API_KEY or MAIL_PASSWORD if it is a Resend key.
    """
    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        mail_password = current_app.config.get('MAIL_PASSWORD') or os.environ.get('MAIL_PASSWORD', '')
        if mail_password.startswith('re_'):
            api_key = mail_password
    return api_key

def check_user_email_permission(user_id, category='promotions'):
    """
    Checks if a user is permitted to receive emails in a given category.
    Categories: 'weekly_digest', 'promotions', 'winback'
    """
    if not user_id:
        return True, None

    pref = EmailPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        user = User.query.get(user_id)
        if user:
            pref = user.get_or_create_email_preferences()
        else:
            return True, None

    if pref.unsubscribed_all:
        return False, "User has globally unsubscribed."

    if category == 'weekly_digest' and not pref.weekly_digest_opt_in:
        return False, "User opted out of weekly digests."

    if category in ['promotions', 'broadcast', 'winback'] and not pref.promotions_opt_in:
        return False, "User opted out of promotional communications."

    return True, pref

def send_promotional_email(
    to_email,
    subject,
    html_content,
    text_content=None,
    template_name='broadcast',
    user_id=None,
    campaign_id=None,
    period_key=None,
    unsubscribe_token=None
):
    """
    Sends an email originating from mail.proofdeck.app using Resend API (or SMTP fallback).
    Enforces deliverability standards:
    - List-Unsubscribe and List-Unsubscribe-Post headers
    - Plain text alternative
    - Suppression checks
    - Audit logging in EmailLog
    """
    # 1. Suppression / Preferences check
    category = 'weekly_digest' if template_name == 'weekly-digest' else 'promotions'
    can_send, pref = check_user_email_permission(user_id, category)
    if not can_send:
        current_app.logger.info(f"Skipping email to {to_email} ({template_name}): suppressed by preferences.")
        return {"status": "suppressed", "reason": pref}

    # Resolve token for unsubscribe links
    token = unsubscribe_token or (pref.unsubscribe_token if pref else None)
    frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app')
    unsub_url = f"{frontend_url}/email/unsubscribe?token={token}" if token else f"{frontend_url}/email/unsubscribe"

    sender = get_promotions_sender()
    reply_to = get_reply_to_email()
    api_key = get_resend_api_key()
    provider_message_id = None

    headers = {
        "List-Unsubscribe": f"<{unsub_url}>, <mailto:unsubscribe@mail.proofdeck.app?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "Reply-To": reply_to
    }

    # 2. Dispatch via Resend REST API if key is available
    if api_key:
        payload = {
            "from": sender,
            "to": [to_email],
            "reply_to": reply_to,
            "subject": subject,
            "html": html_content,
            "headers": headers,
            "tags": [{"name": "template", "value": template_name}]
        }
        if text_content:
            payload["text"] = text_content

        try:
            res = requests.post(
                RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                timeout=15
            )
            if res.status_code in [200, 201]:
                res_data = res.json()
                provider_message_id = res_data.get('id')
                current_app.logger.info(f"Successfully sent {template_name} to {to_email} via Resend API (ID: {provider_message_id})")
            else:
                current_app.logger.warning(f"Resend API returned {res.status_code}: {res.text}. Falling back to Flask-Mail.")
                provider_message_id = _send_via_flask_mail(to_email, subject, html_content, text_content, sender, headers, reply_to=reply_to)
        except Exception as e:
            current_app.logger.warning(f"Resend API request failed: {e}. Falling back to Flask-Mail.")
            provider_message_id = _send_via_flask_mail(to_email, subject, html_content, text_content, sender, headers, reply_to=reply_to)
    else:
        # 3. Dispatch via Flask-Mail SMTP
        provider_message_id = _send_via_flask_mail(to_email, subject, html_content, text_content, sender, headers, reply_to=reply_to)

    # 4. Log send to EmailLog table
    try:
        valid_user_id = user_id
        if valid_user_id:
            db_user = User.query.get(valid_user_id)
            if not db_user:
                valid_user_id = None

        log_entry = EmailLog(
            user_id=valid_user_id,
            recipient_email=to_email,
            template_name=template_name,
            campaign_id=campaign_id,
            period_key=period_key,
            provider_message_id=provider_message_id,
            sent_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to record EmailLog for {to_email}: {e}")

    return {
        "status": "sent",
        "to": to_email,
        "provider_message_id": provider_message_id
    }

def _send_via_flask_mail(to_email, subject, html_content, text_content, sender, extra_headers, reply_to=None):
    clean_sender = sender
    sender_name = "ProofDeck"
    if '<' in sender and '>' in sender:
        sender_name = sender.split('<')[0].strip()
        clean_sender = sender.split('<')[1].split('>')[0].strip()

    msg = Message(
        subject=subject,
        sender=(sender_name, clean_sender),
        recipients=[to_email],
        reply_to=reply_to,
        html=html_content,
        body=text_content,
        extra_headers=extra_headers
    )
    mail.send(msg)
    current_app.logger.info(f"Sent email to {to_email} via Flask-Mail SMTP.")
    return f"smtp-{int(datetime.now(timezone.utc).timestamp())}"
