from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, current_user
from datetime import datetime, timedelta, timezone
from ..models import db, Admin, User, BroadcastCampaign, EmailLog, Tenant, Membership
from ..services.email_renderer import render_broadcast_campaign
from ..services.resend_service import send_promotional_email
from ..tasks.email_tasks import dispatch_broadcast_batch

admin_broadcasts_bp = Blueprint('admin_broadcasts', __name__)

@admin_broadcasts_bp.route('/broadcasts', methods=['GET'])
@jwt_required()
def list_broadcast_campaigns():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    campaigns = BroadcastCampaign.query.order_by(BroadcastCampaign.created_at.desc()).all()
    results = []
    for c in campaigns:
        # Pull stats from email_logs
        opens = EmailLog.query.filter(EmailLog.campaign_id == c.id, EmailLog.opened_at != None).count()
        clicks = EmailLog.query.filter(EmailLog.campaign_id == c.id, EmailLog.clicked_at != None).count()
        bounces = EmailLog.query.filter(EmailLog.campaign_id == c.id, EmailLog.bounced_at != None).count()

        meta_block = next((b for b in (c.content_blocks or []) if isinstance(b, dict) and b.get('type') == '_meta'), None)
        target_companies = meta_block.get('target_companies', []) if meta_block else []
        target_users = meta_block.get('target_users', []) if meta_block else []
        clean_blocks = [b for b in (c.content_blocks or []) if not (isinstance(b, dict) and b.get('type') == '_meta')]

        results.append({
            "id": c.id,
            "title": c.title,
            "subject": c.subject,
            "tag": c.tag,
            "opening_why": c.opening_why,
            "content_blocks": clean_blocks,
            "segment": c.segment,
            "target_companies": target_companies,
            "target_users": target_users,
            "status": c.status,
            "total_recipients": c.total_recipients,
            "sent_count": c.sent_count,
            "test_sent_to": c.test_sent_to,
            "test_sent_at": c.test_sent_at.isoformat() if c.test_sent_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "sent_at": c.sent_at.isoformat() if c.sent_at else None,
            "stats": {
                "opens": opens,
                "clicks": clicks,
                "bounces": bounces
            }
        })
    return jsonify(results), 200

@admin_broadcasts_bp.route('/broadcasts/<int:campaign_id>', methods=['GET'])
@jwt_required()
def get_broadcast_campaign(campaign_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    c = BroadcastCampaign.query.get_or_404(campaign_id)
    meta_block = next((b for b in (c.content_blocks or []) if isinstance(b, dict) and b.get('type') == '_meta'), None)
    target_companies = meta_block.get('target_companies', []) if meta_block else []
    target_users = meta_block.get('target_users', []) if meta_block else []
    clean_blocks = [b for b in (c.content_blocks or []) if not (isinstance(b, dict) and b.get('type') == '_meta')]

    return jsonify({
        "id": c.id,
        "title": c.title,
        "subject": c.subject,
        "tag": c.tag,
        "opening_why": c.opening_why,
        "content_blocks": clean_blocks,
        "segment": c.segment,
        "target_companies": target_companies,
        "target_users": target_users,
        "status": c.status,
        "total_recipients": c.total_recipients,
        "sent_count": c.sent_count,
        "test_sent_to": c.test_sent_to,
        "test_sent_at": c.test_sent_at.isoformat() if c.test_sent_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "sent_at": c.sent_at.isoformat() if c.sent_at else None
    }), 200

@admin_broadcasts_bp.route('/broadcasts', methods=['POST'])
@jwt_required()
def save_broadcast_campaign():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    data = request.get_json() or {}
    campaign_id = data.get('id')
    title = data.get('title')
    subject = data.get('subject')
    tag = data.get('tag', 'ANNOUNCEMENT')
    opening_why = data.get('opening_why', '')
    content_blocks = data.get('content_blocks', [])
    if isinstance(content_blocks, str):
        import json
        try:
            content_blocks = json.loads(content_blocks)
        except Exception:
            content_blocks = []
    segment = data.get('segment', 'all')
    target_companies = data.get('target_companies', [])
    target_users = data.get('target_users', [])

    if not title or not subject:
        return jsonify({"msg": "Title and subject line are required"}), 400

    if campaign_id:
        campaign = BroadcastCampaign.query.get_or_404(campaign_id)
        if campaign.status == 'sent':
            return jsonify({"msg": "Cannot edit a campaign that has already been sent"}), 400
        if campaign.status == 'sending':
            campaign.status = 'draft'
    else:
        campaign = BroadcastCampaign(created_by=current_user.id)
        db.session.add(campaign)

    clean_blocks = [b for b in content_blocks if not (isinstance(b, dict) and b.get('type') == '_meta')]
    if target_companies or target_users:
        clean_blocks.insert(0, {
            'type': '_meta',
            'target_companies': target_companies,
            'target_users': target_users
        })

    campaign.title = title
    campaign.subject = subject
    campaign.tag = tag
    campaign.opening_why = opening_why
    campaign.content_blocks = clean_blocks
    campaign.segment = segment
    db.session.commit()

    return jsonify({
        "msg": "Campaign saved successfully",
        "id": campaign.id,
        "status": campaign.status
    }), 200

@admin_broadcasts_bp.route('/broadcasts/preview', methods=['POST'])
@jwt_required()
def preview_broadcast():
    """
    Renders the broadcast blocks into full compiled MJML HTML in real-time.
    """
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    data = request.get_json() or {}
    class TempCampaign:
        title = data.get('title', 'Preview Headline')
        subject = data.get('subject', 'Preview Subject Line')
        tag = data.get('tag', 'ANNOUNCEMENT')
        opening_why = data.get('opening_why', '')
        content_blocks = data.get('content_blocks', [])

    rendered = render_broadcast_campaign(TempCampaign())
    return jsonify({
        "html": rendered['html'],
        "text": rendered['text'],
        "errors": rendered.get('errors')
    }), 200

@admin_broadcasts_bp.route('/broadcasts/<int:campaign_id>/test-send', methods=['POST'])
@jwt_required()
def test_send_broadcast(campaign_id):
    """
    Sends a test preview email to an admin address. Mandatory before full send.
    """
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    data = request.get_json() or {}
    test_email = data.get('test_email') or getattr(current_user, 'email', None)
    if not test_email:
        return jsonify({"msg": "Recipient test email is required"}), 400

    try:
        campaign = BroadcastCampaign.query.get_or_404(campaign_id)
        test_user = User.query.filter_by(email=test_email).first()
        rendered = render_broadcast_campaign(campaign, user=test_user)

        test_subject = f"[TEST PREVIEW] {rendered['subject']}"
        res = send_promotional_email(
            to_email=test_email,
            subject=test_subject,
            html_content=rendered['html'],
            text_content=rendered['text'],
            template_name='broadcast-preview',
            campaign_id=campaign.id
        )

        campaign.test_sent_to = test_email
        campaign.test_sent_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            "msg": f"Test email successfully dispatched to {test_email}",
            "provider_message_id": res.get('provider_message_id') if isinstance(res, dict) else None,
            "test_sent_at": campaign.test_sent_at.isoformat() if campaign.test_sent_at else None
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in test_send_broadcast: {e}", exc_info=True)
        return jsonify({"msg": f"Failed to send test email: {str(e)}"}), 500

@admin_broadcasts_bp.route('/broadcasts/<int:campaign_id>/send', methods=['POST'])
@jwt_required()
def trigger_broadcast(campaign_id):
    """
    Launches broadcast dispatching to the chosen user segment.
    Enforces that a test send was completed prior to full sending.
    """
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    campaign = BroadcastCampaign.query.get_or_404(campaign_id)
    if campaign.status == 'sent':
        return jsonify({"msg": "Campaign has already completed dispatching to all recipients."}), 400

    force = (request.get_json() or {}).get('force', False)
    if campaign.status == 'sending' and not force:
        # If it has sent some emails and is actively sending, warn the admin:
        if (campaign.sent_count or 0) > 0 and campaign.sent_count < (campaign.total_recipients or 0):
            return jsonify({"msg": f"Campaign is currently dispatching ({campaign.sent_count}/{campaign.total_recipients})."}), 400
        # If stuck on 0 sent, allow auto-recovery

    # Mandatory Test-Send Safeguard
    if not campaign.test_sent_at:
        return jsonify({
            "msg": "Test send required: You must send a test preview to your email before dispatching to real users."
        }), 400

    # Determine recipient query based on segment
    now = datetime.utcnow()
    base_query = User.query.filter(User.role != 'suspended')

    if campaign.segment in ['companies', 'users', 'custom']:
        meta_block = next((b for b in (campaign.content_blocks or []) if isinstance(b, dict) and b.get('type') == '_meta'), None)
        target_ids = set()
        if meta_block:
            if campaign.segment in ['companies', 'custom']:
                company_ids = meta_block.get('target_companies', [])
                if company_ids:
                    tenant_owners = db.session.query(Tenant.owner_id).filter(Tenant.id.in_(company_ids)).all()
                    target_ids.update([t[0] for t in tenant_owners])
                    members = db.session.query(Membership.user_id).filter(
                        Membership.tenant_id.in_(company_ids),
                        Membership.status == 'active'
                    ).all()
                    target_ids.update([m[0] for m in members])

            if campaign.segment in ['users', 'custom']:
                user_ids = meta_block.get('target_users', [])
                if user_ids:
                    target_ids.update(user_ids)

        if target_ids:
            users = base_query.filter(User.id.in_(list(target_ids))).all()
        else:
            users = []
    elif campaign.segment == 'active':
        cutoff = now - timedelta(days=60)
        users = base_query.filter(
            (User.last_active_at >= cutoff) | (User.created_at >= cutoff)
        ).all()
    elif campaign.segment == 'inactive':
        cutoff = now - timedelta(days=60)
        users = base_query.filter(
            (User.last_active_at <= cutoff) | ((User.last_active_at == None) & (User.created_at <= cutoff))
        ).all()
    else:  # 'all'
        users = base_query.all()

    recipient_ids = [u.id for u in users]
    if not recipient_ids:
        return jsonify({
            "msg": "No eligible recipients found for this target selection. Please select at least one active user or company."
        }), 400

    campaign.total_recipients = len(recipient_ids)
    campaign.status = 'sending'
    db.session.commit()

    # Batch dispatch via Celery
    batch_size = 200
    for i in range(0, len(recipient_ids), batch_size):
        chunk = recipient_ids[i:i + batch_size]
        dispatch_broadcast_batch.delay(campaign.id, chunk)

    return jsonify({
        "msg": f"Broadcast enqueued for {len(recipient_ids)} recipients.",
        "campaign_id": campaign.id,
        "total_recipients": len(recipient_ids)
    }), 200

@admin_broadcasts_bp.route('/broadcasts/<int:campaign_id>/reset', methods=['POST'])
@jwt_required()
def reset_broadcast_campaign(campaign_id):
    """
    Resets a campaign that was stuck in 'sending' back to 'draft'
    so it can be edited, re-targeted, and re-dispatched.
    """
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    campaign = BroadcastCampaign.query.get_or_404(campaign_id)
    if campaign.status == 'sent':
        return jsonify({"msg": "Cannot reset a campaign that has already completed sending."}), 400

    campaign.status = 'draft'
    campaign.sent_count = 0
    campaign.total_recipients = 0
    db.session.commit()

    return jsonify({
        "msg": f"Campaign '{campaign.title}' has been reset to draft. You can now edit and re-send it.",
        "id": campaign.id,
        "status": campaign.status
    }), 200
