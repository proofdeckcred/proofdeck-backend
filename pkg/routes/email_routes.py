from flask import Blueprint, jsonify, request, current_app
from ..models import db, User, EmailPreference, EmailLog
from datetime import datetime, timezone

email_routes_bp = Blueprint('email_routes', __name__)

@email_routes_bp.route('/email/preferences', methods=['GET'])
def get_email_preferences():
    """
    Public signed endpoint: Fetches email preferences for a token.
    No password login required, as per email unsubscribe best practices.
    """
    token = request.args.get('token')
    if not token:
        return jsonify({"msg": "Missing token"}), 400

    pref = EmailPreference.query.filter_by(unsubscribe_token=token).first()
    if not pref:
        return jsonify({"msg": "Invalid or expired preferences link"}), 404

    user = User.query.get(pref.user_id)
    return jsonify({
        "email": user.email if user else None,
        "name": user.name if user else None,
        "weekly_digest_opt_in": pref.weekly_digest_opt_in,
        "promotions_opt_in": pref.promotions_opt_in,
        "unsubscribed_all": pref.unsubscribed_all
    }), 200

@email_routes_bp.route('/email/preferences', methods=['POST'])
def update_email_preferences():
    """
    Public signed endpoint: Updates email preferences using a token.
    """
    data = request.get_json() or {}
    token = data.get('token')
    if not token:
        return jsonify({"msg": "Missing token"}), 400

    pref = EmailPreference.query.filter_by(unsubscribe_token=token).first()
    if not pref:
        return jsonify({"msg": "Invalid or expired preferences link"}), 404

    if 'weekly_digest_opt_in' in data:
        pref.weekly_digest_opt_in = bool(data['weekly_digest_opt_in'])
    if 'promotions_opt_in' in data:
        pref.promotions_opt_in = bool(data['promotions_opt_in'])
    if 'unsubscribed_all' in data:
        pref.unsubscribed_all = bool(data['unsubscribed_all'])
        if pref.unsubscribed_all:
            pref.weekly_digest_opt_in = False
            pref.promotions_opt_in = False

    pref.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        "msg": "Preferences updated successfully",
        "weekly_digest_opt_in": pref.weekly_digest_opt_in,
        "promotions_opt_in": pref.promotions_opt_in,
        "unsubscribed_all": pref.unsubscribed_all
    }), 200

@email_routes_bp.route('/email/webhooks/resend', methods=['POST'])
def handle_resend_webhook():
    """
    Webhook receiver for Resend events (bounces, complaints, clicks, opens).
    Automatically suppresses recipients who bounce or submit spam complaints.
    """
    payload = request.get_json() or {}
    event_type = payload.get('type')
    data = payload.get('data', {})
    
    email_id = data.get('email_id')
    to_list = data.get('to', [])
    to_email = to_list[0] if to_list else None

    current_app.logger.info(f"Resend webhook received: {event_type} for {to_email} (ID: {email_id})")

    # Update matching email log
    if email_id:
        log_entry = EmailLog.query.filter_by(provider_message_id=email_id).first()
        now = datetime.now(timezone.utc)
        if log_entry:
            if event_type == 'email.opened':
                log_entry.opened_at = now
            elif event_type == 'email.clicked':
                log_entry.clicked_at = now
            elif event_type == 'email.bounced':
                log_entry.bounced_at = now
            elif event_type == 'email.complained':
                log_entry.complained_at = now
            db.session.commit()

    # If bounced or complained, automatically suppress user
    if event_type in ['email.bounced', 'email.complained'] and to_email:
        user = User.query.filter_by(email=to_email).first()
        if user:
            pref = user.get_or_create_email_preferences()
            pref.unsubscribed_all = True
            pref.weekly_digest_opt_in = False
            pref.promotions_opt_in = False
            pref.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            current_app.logger.info(f"Auto-suppressed user {to_email} following {event_type} event.")

    return jsonify({"received": True}), 200
