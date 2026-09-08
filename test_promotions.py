import os
import sys
import argparse
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pkg import create_app
from pkg.models import db, User, EmailPreference
from pkg.services.email_renderer import (
    render_weekly_digest_for_user,
    render_winback_for_user,
    render_broadcast_campaign
)
from pkg.services.resend_service import send_promotional_email, get_promotions_sender, get_resend_api_key

def get_test_mock_user(to_email, zero_state=False):
    """Returns an active user from DB or constructs a realistic mock user."""
    real_user = User.query.filter_by(email=to_email).first()
    if real_user:
        return real_user

    class MockUser:
        id = 999999
        name = "Omobolaji Durojaiye"
        email = to_email
        role = "pro"
        cert_quota = 1250 if not zero_state else 2
        created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
        last_active_at = datetime.now(timezone.utc)
        last_winback_sent_at = None

        def get_or_create_email_preferences(self):
            class MockPref:
                weekly_digest_opt_in = True
                promotions_opt_in = True
                unsubscribed_all = False
                unsubscribe_token = "mock-preview-token-xyz"
            return MockPref()

    return MockUser()

def run_test(args):
    app = create_app()
    with app.app_context():
        to_email = args.to or app.config.get('ADMIN_EMAIL') or 'omobolajidurojaiye57@gmail.com'
        user = get_test_mock_user(to_email, zero_state=args.zero_state)
        sender = get_promotions_sender()
        api_key = get_resend_api_key()

        print("=" * 65)
        print(" ProofDeck Promotions & Automated Email Test Harness")
        print("=" * 65)
        print(f" Target Recipient : {to_email}")
        print(f" Sender Identity  : {sender}")
        print(f" Resend API Key   : {'Configured (' + api_key[:7] + '...)' if api_key else 'Not Found (Using SMTP fallback)'}")
        print(f" Mode             : {args.mode.upper()}")
        print(f" Zero-State Test  : {args.zero_state}")
        print("=" * 65)

        types_to_test = ['digest', 'winback', 'broadcast'] if args.type == 'all' else [args.type]

        for email_type in types_to_test:
            print(f"\n--- Testing Surface: {email_type.upper()} ---")

            if email_type == 'digest':
                template_name = 'weekly-digest'
                if args.zero_state:
                    rendered = render_weekly_digest_for_user(user)
                    rendered['is_zero_state'] = True
                    rendered['issued_count'] = 0
                    rendered['top_certificate_title'] = None
                else:
                    # Render full active digest with stats and highlight card
                    from emails.render import render_email
                    frontend_url = app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')
                    context = {
                        "user_name": "Omobolaji",
                        "email_title": "ProofDeck Weekly Momentum: 18 credentials issued",
                        "headline": "Omobolaji, 18 new credentials were minted with ProofDeck this week.",
                        "opening_why": "Every certificate you issue removes doubt for employers and gives your recipients instant proof of their achievement. Here is your weekly momentum recap:",
                        "issued_count": 18,
                        "verifications_count": 42,
                        "all_time_issued": 1420,
                        "top_certificate_title": "Full-Stack Software Engineering Diploma",
                        "top_certificate_recipient": "Adaeze Okafor",
                        "top_certificate_views": 28,
                        "credits_remaining": 1250,
                        "cta_text": "Issue More Certificates",
                        "cta_url": f"{frontend_url}/dashboard/create",
                        "is_zero_state": False,
                        "unsubscribe_url": f"{frontend_url}/email/unsubscribe",
                        "preferences_url": f"{frontend_url}/dashboard/settings"
                    }
                    rendered = render_email('weekly-digest.mjml', context)
                    rendered['subject'] = "18 credentials issued — your ProofDeck weekly recap"
            elif email_type == 'winback':
                rendered = render_winback_for_user(user)
                template_name = 'winback-inactive'
            elif email_type == 'broadcast':
                class MockCampaign:
                    id = 1001
                    title = "New Verification API & Instant Links Live"
                    subject = "Your students shouldn't wait weeks to prove what they earned"
                    tag = "PLATFORM ANNOUNCEMENT"
                    opening_why = "Africa's talent deserves to be trusted at first glance. That is why we just rolled out a faster verification engine."
                    content_blocks = [
                        {
                            "type": "heading",
                            "content": "Instant QR Verification is Now 4x Faster"
                        },
                        {
                            "type": "paragraph",
                            "content": "Every certificate issued through ProofDeck now includes an optimized cryptographic hash that loads instantly on slow 3G mobile connections."
                        },
                        {
                            "type": "callout",
                            "title": "Pro & Enterprise Upgrade",
                            "content": "API keys are now active in your dashboard. You can issue directly from your LMS or HR software."
                        },
                        {
                            "type": "button",
                            "text": "View API Documentation",
                            "url": "https://www.proofdeck.app/docs"
                        }
                    ]
                rendered = render_broadcast_campaign(MockCampaign(), user=user)
                template_name = 'broadcast'
            else:
                print(f"Unknown email type: {email_type}")
                continue

            print(f" [OK] Subject Line     : {rendered['subject']}")
            print(f" [OK] HTML Size        : {len(rendered['html']):,} bytes")
            print(f" [OK] Plain Text Size  : {len(rendered['text']):,} bytes")
            print(f" [OK] Template Errors  : {rendered.get('errors') or 'None'}")

            # Verification of Deliverability Standards
            assert "<html" in rendered['html'].lower(), "HTML must be valid document"
            assert "unsubscribe" in rendered['html'].lower(), "Unsubscribe link missing in HTML"
            assert len(rendered['text']) > 50, "Plain-text fallback too short or empty"
            assert "hello@mail.proofdeck.app" in sender or "mail.proofdeck.app" in sender, "Sender must use mail.proofdeck.app subdomain"

            if args.mode == 'live-send':
                print(f" > Dispatching real email to {to_email} via {sender}...")
                try:
                    result = send_promotional_email(
                        to_email=to_email,
                        subject=rendered['subject'],
                        html_content=rendered['html'],
                        text_content=rendered['text'],
                        template_name=template_name,
                        user_id=getattr(user, 'id', None)
                    )
                    print(f" [OK] Dispatch Result  : {result.get('status')}")
                    print(f" [OK] Message/Ref ID   : {result.get('provider_message_id')}")
                    print(f" SUCCESS! Check {to_email} inbox to review render and formatting.")
                except Exception as ex:
                    print(f" [FAILED] Dispatch Failed : {ex}")
            else:
                print(f" [OK] DRY RUN PASSED. To send to {to_email}, run with `--mode live-send`.")

        print("\n" + "=" * 65)
        print(" All Requested Automated Email Checks Completed Successfully!")
        print("=" * 65)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Test ProofDeck Email Promotions & Automated Flows")
    parser.add_argument('--type', choices=['digest', 'winback', 'broadcast', 'all'], default='digest', help="Email surface to test")
    parser.add_argument('--mode', choices=['dry-run', 'live-send'], default='dry-run', help="Dry run render or send live email")
    parser.add_argument('--to', type=str, default=None, help="Recipient email address for test send")
    parser.add_argument('--zero-state', action='store_true', help="Force zero-state variant for digest")
    args = parser.parse_args()
    run_test(args)
