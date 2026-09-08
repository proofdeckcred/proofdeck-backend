import os
from datetime import datetime, timedelta, timezone
from celery_app import celery
from ..models import db, User, EmailLog, EmailPreference, BroadcastCampaign, Certificate
from ..services.email_renderer import (
    render_weekly_digest_for_user,
    render_winback_for_user,
    render_broadcast_campaign,
    get_iso_week_key
)
from ..services.resend_service import send_promotional_email

@celery.task(name='pkg.tasks.email_tasks.send_user_weekly_digest', bind=True, max_retries=3, default_retry_delay=60)
def send_user_weekly_digest(self, user_id, force=False):
    """
    Sends a personalized weekly digest to an issuer.
    Enforces ISO week idempotency so retries or redeployments never double-send.
    """
    user = User.query.get(user_id)
    if not user or user.role == 'suspended':
        return {"status": "skipped", "reason": "User not eligible or suspended"}

    current_week_key = get_iso_week_key()

    # Idempotency check
    if not force:
        already_sent = EmailLog.query.filter_by(
            user_id=user.id,
            template_name='weekly-digest',
            period_key=current_week_key
        ).first()
        if already_sent:
            return {"status": "already_sent", "period_key": current_week_key}

    rendered = render_weekly_digest_for_user(user)

    # Optional zero-state rule: if user has 0 all-time certs and 0 this week, skip or light variant
    if rendered.get('is_zero_state') and Certificate.query.filter_by(user_id=user.id).count() == 0:
        # User has never used the platform yet, let win-back or onboarding handle them
        return {"status": "skipped_zero_state", "user_id": user.id}

    result = send_promotional_email(
        to_email=user.email,
        subject=rendered['subject'],
        html_content=rendered['html'],
        text_content=rendered['text'],
        template_name='weekly-digest',
        user_id=user.id,
        period_key=current_week_key
    )
    return result

@celery.task(name='pkg.tasks.email_tasks.scan_and_enqueue_weekly_digests')
def scan_and_enqueue_weekly_digests():
    """
    Celery Beat cron task: Runs every Monday at 8:00 AM UTC.
    Finds all active users and enqueues individual send tasks.
    """
    now = datetime.now(timezone.utc)
    cutoff_active = now - timedelta(days=90)
    cutoff_created = now - timedelta(days=30)

    # Active issuers: issued at least one cert in last 90 days, or account created in last 30 days
    users = User.query.filter(
        User.role != 'suspended',
        (User.last_active_at >= cutoff_active) | (User.created_at >= cutoff_created)
    ).all()

    enqueued_count = 0
    for user in users:
        send_user_weekly_digest.delay(user.id)
        enqueued_count += 1

    return {"status": "enqueued", "total_users": enqueued_count}

@celery.task(name='pkg.tasks.email_tasks.send_user_winback', bind=True, max_retries=3, default_retry_delay=60)
def send_user_winback(self, user_id, force=False):
    """
    Sends a win-back feature showcase to an inactive user.
    Enforces a strict 60-day cooldown to prevent spamming.
    """
    user = User.query.get(user_id)
    if not user or user.role == 'suspended':
        return {"status": "skipped", "reason": "User not eligible or suspended"}

    now = datetime.now(timezone.utc)

    # Cooldown check
    if not force and user.last_winback_sent_at:
        # SQLite / Postgres may return naive datetime, ensure comparison is safe
        last_sent = user.last_winback_sent_at
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        if (now - last_sent).days < 60:
            return {"status": "skipped_cooldown", "user_id": user.id}

    rendered = render_winback_for_user(user)

    result = send_promotional_email(
        to_email=user.email,
        subject=rendered['subject'],
        html_content=rendered['html'],
        text_content=rendered['text'],
        template_name='winback-inactive',
        user_id=user.id
    )

    if result.get('status') == 'sent':
        user.last_winback_sent_at = now
        db.session.commit()

    return result

@celery.task(name='pkg.tasks.email_tasks.scan_and_enqueue_winbacks')
def scan_and_enqueue_winbacks():
    """
    Celery Beat cron task: Runs daily at 10:00 AM UTC.
    Finds users who haven't logged in or issued certificates in 30 days
    and who haven't received a win-back in the last 60 days.
    """
    now = datetime.now(timezone.utc)
    inactivity_cutoff = now - timedelta(days=30)
    cooldown_cutoff = now - timedelta(days=60)

    # Find inactive users
    candidates = User.query.filter(
        User.role != 'suspended',
        (User.last_active_at <= inactivity_cutoff) | ((User.last_active_at == None) & (User.created_at <= inactivity_cutoff)),
        (User.last_winback_sent_at == None) | (User.last_winback_sent_at <= cooldown_cutoff)
    ).all()

    enqueued_count = 0
    for user in candidates:
        send_user_winback.delay(user.id)
        enqueued_count += 1

    return {"status": "enqueued", "total_users": enqueued_count}

@celery.task(name='pkg.tasks.email_tasks.dispatch_broadcast_batch', bind=True)
def dispatch_broadcast_batch(self, campaign_id, recipient_ids):
    """
    Dispatches an admin broadcast campaign to a batch of users.
    Logs every send and updates campaign metrics.
    """
    campaign = BroadcastCampaign.query.get(campaign_id)
    if not campaign:
        return {"status": "error", "message": f"Campaign {campaign_id} not found"}

    users = User.query.filter(User.id.in_(recipient_ids), User.role != 'suspended').all()
    sent_count = 0

    for user in users:
        rendered = render_broadcast_campaign(campaign, user=user)
        res = send_promotional_email(
            to_email=user.email,
            subject=rendered['subject'],
            html_content=rendered['html'],
            text_content=rendered['text'],
            template_name='broadcast',
            user_id=user.id,
            campaign_id=campaign.id
        )
        if res.get('status') == 'sent':
            sent_count += 1

    campaign.sent_count = (campaign.sent_count or 0) + sent_count
    if campaign.sent_count >= (campaign.total_recipients or len(recipient_ids)):
        campaign.status = 'sent'
        campaign.sent_at = datetime.now(timezone.utc)
    else:
        campaign.status = 'sending'

    db.session.commit()
    return {"status": "completed", "batch_sent": sent_count, "campaign_id": campaign_id}
