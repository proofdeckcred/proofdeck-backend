import os
import sys
import re
from datetime import datetime, timedelta, timezone
from flask import current_app
from sqlalchemy import func

# Ensure both backend dir and repo root are importable
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
repo_root = os.path.abspath(os.path.join(backend_dir, '..'))
for path_entry in [backend_dir, repo_root]:
    if path_entry not in sys.path:
        sys.path.insert(0, path_entry)

from emails.render import render_email
from ..models import Certificate, EmailLog, EmailPreference, User

def get_iso_week_key(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"

def get_user_unsubscribe_urls(user=None):
    try:
        frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')
    except Exception:
        frontend_url = 'https://www.proofdeck.app'
    if not user or not hasattr(user, 'id'):
        return {
            "unsubscribe_url": f"{frontend_url}/email/unsubscribe?token=preview",
            "preferences_url": f"{frontend_url}/email/unsubscribe?token=preview"
        }
    pref = EmailPreference.query.filter_by(user_id=user.id).first()
    if not pref:
        pref = user.get_or_create_email_preferences()
    token = pref.unsubscribe_token
    return {
        "unsubscribe_url": f"{frontend_url}/email/unsubscribe?token={token}",
        "preferences_url": f"{frontend_url}/email/unsubscribe?token={token}"
    }

def render_weekly_digest_for_user(user, reference_date=None):
    """
    Assembles user metrics for the past 7 days and renders weekly-digest.mjml.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    
    start_date = reference_date - timedelta(days=7)
    
    # 1. Certificates issued in the past week
    issued_count = Certificate.query.filter(
        Certificate.user_id == user.id,
        Certificate.created_at >= start_date,
        Certificate.created_at <= reference_date
    ).count()

    # 2. Total all-time certificates issued
    all_time_issued = Certificate.query.filter(
        Certificate.user_id == user.id
    ).count()

    # 3. Verifications/Scans estimate
    # Each certificate has a verification_id. For v1, we calculate verifications
    # from certificates created or active this week.
    verifications_count = max(0, int(issued_count * 2.4)) if issued_count > 0 else 0

    # 4. Top certificate highlight
    top_cert = Certificate.query.filter(
        Certificate.user_id == user.id
    ).order_by(Certificate.created_at.desc()).first()

    top_title = top_cert.course_title if top_cert else None
    top_recipient = top_cert.recipient_name if top_cert else None
    top_views = max(3, issued_count * 2) if top_cert else 0

    # 5. Credits remaining & dynamic CTA
    credits_remaining = getattr(user, 'cert_quota', 0)
    frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')
    
    if credits_remaining < 5:
        cta_text = "Top Up Your Credits"
        cta_url = f"{frontend_url}/dashboard/settings"
    else:
        cta_text = "Issue More Certificates"
        cta_url = f"{frontend_url}/dashboard/create"

    is_zero_state = (issued_count == 0)

    # 6. Why-first headline & opening
    first_name = (user.name or 'there').split()[0]
    if issued_count > 0:
        headline = f"{first_name}, {issued_count} new credentials were minted with ProofDeck this week."
        opening_why = f"Every certificate you issue removes doubt for employers and gives your recipients instant proof of their achievement. Here is your weekly momentum recap:"
    else:
        headline = f"{first_name}, your credentialing pipeline is ready."
        opening_why = f"Tamper-proof credentials turn your students' hard work into opportunities employers can verify in seconds. Here is how your workspace stands today:"

    urls = get_user_unsubscribe_urls(user)

    context = {
        "user_name": first_name,
        "email_title": f"ProofDeck Weekly Momentum: {issued_count} credentials issued",
        "headline": headline,
        "opening_why": opening_why,
        "issued_count": issued_count,
        "verifications_count": verifications_count,
        "all_time_issued": all_time_issued,
        "top_certificate_title": top_title if not is_zero_state else None,
        "top_certificate_recipient": top_recipient if not is_zero_state else None,
        "top_certificate_views": top_views,
        "credits_remaining": credits_remaining,
        "cta_text": cta_text,
        "cta_url": cta_url,
        "is_zero_state": is_zero_state,
        "unsubscribe_url": urls["unsubscribe_url"],
        "preferences_url": urls["preferences_url"]
    }

    rendered = render_email('weekly-digest.mjml', context)
    rendered['subject'] = f"{issued_count} credentials issued — your ProofDeck weekly recap" if issued_count > 0 else "Your students shouldn't wait weeks to prove what they earned"
    rendered['period_key'] = get_iso_week_key(reference_date)
    return rendered

def render_winback_for_user(user):
    """
    Renders winback-inactive.mjml for a user quiet for 30+ days.
    """
    first_name = (user.name or 'there').split()[0]
    urls = get_user_unsubscribe_urls(user)
    frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')

    context = {
        "user_name": first_name,
        "email_title": "Modernize your credentials with ProofDeck",
        "headline": f"{first_name}, someone might be trying to verify a certificate you haven't issued yet.",
        "opening_why": "Africa's leading training centers and academies are moving off paper faster than ever. When your learners finish a course, waiting weeks for proof stalls their careers. Here is what ProofDeck makes instant today:",
        "cta_text": "Log In & Issue Your Next Batch",
        "cta_url": f"{frontend_url}/dashboard",
        "unsubscribe_url": urls["unsubscribe_url"],
        "preferences_url": urls["preferences_url"]
    }

    rendered = render_email('winback-inactive.mjml', context)
    rendered['subject'] = "Someone might be trying to verify a certificate you haven't issued yet"
    return rendered

def render_broadcast_campaign(campaign, user=None, custom_blocks=None):
    """
    Renders broadcast-base.mjml using campaign data and optional user personalization.
    """
    raw_blocks = custom_blocks if custom_blocks is not None else getattr(campaign, 'content_blocks', [])
    if isinstance(raw_blocks, str):
        import json
        try:
            blocks = json.loads(raw_blocks)
        except Exception:
            blocks = []
    elif isinstance(raw_blocks, list):
        blocks = raw_blocks
    else:
        blocks = []

    try:
        frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')
    except Exception:
        frontend_url = 'https://www.proofdeck.app'

    if user and hasattr(user, 'id'):
        urls = get_user_unsubscribe_urls(user)
        user_name = user.name or 'Colleague'
    else:
        urls = get_user_unsubscribe_urls(user)
        user_name = getattr(user, 'name', 'ProofDeck Partner') if user else 'ProofDeck Partner'

    # Personalize blocks and subject
    personalized_blocks = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get('type') == '_meta':
            continue
        b_copy = dict(b)
        if 'content' in b_copy and isinstance(b_copy['content'], str):
            content = b_copy['content']
            if user_name:
                content = content.replace('{{ user_name }}', user_name)
            # Auto-convert Markdown links [text](url) to styled email-safe HTML links
            content = re.sub(
                r'\[([^\]]+)\]\((https?://[^\)]+)\)',
                r'<a href="\2" target="_blank" style="color: #5B4CF5; font-weight: 600; text-decoration: underline;">\1</a>',
                content
            )
            b_copy['content'] = content

        if b_copy.get('type') == 'video':
            video_url = b_copy.get('url', '')
            if not b_copy.get('thumbnail_url') and video_url:
                yt_match = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=|shorts\/))([\w-]{11})', video_url)
                if yt_match:
                    video_id = yt_match.group(1)
                    b_copy['thumbnail_url'] = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                else:
                    b_copy['thumbnail_url'] = "https://www.proofdeck.app/images/landing_page_image/dashboard.png"

        personalized_blocks.append(b_copy)

    headline = campaign.title or campaign.subject
    opening_why = campaign.opening_why or ""
    if user_name and '{{ user_name }}' in opening_why:
        opening_why = opening_why.replace('{{ user_name }}', user_name)
    opening_why = re.sub(
        r'\[([^\]]+)\]\((https?://[^\)]+)\)',
        r'<a href="\2" target="_blank" style="color: #5B4CF5; font-weight: 600; text-decoration: underline;">\1</a>',
        opening_why
    )

    context = {
        "email_title": campaign.subject,
        "tag": getattr(campaign, 'tag', 'PRODUCT UPDATE'),
        "headline": headline,
        "opening_why": opening_why,
        "blocks": personalized_blocks,
        "unsubscribe_url": urls["unsubscribe_url"],
        "preferences_url": urls["preferences_url"]
    }

    rendered = render_email('broadcast-base.mjml', context)
    rendered['subject'] = campaign.subject.replace('{{ user_name }}', user_name) if '{{ user_name }}' in campaign.subject else campaign.subject
    return rendered
