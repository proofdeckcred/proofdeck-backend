import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from pkg import create_app
from pkg.models import db, BlogPost
from datetime import datetime

app = create_app()

INITIAL_POSTS = [
    {
        "title": "How to Issue & Verify Digital Certificates with Instant QR Codes",
        "slug": "how-to-issue-verify-digital-certificates",
        "excerpt": "Step-by-step tutorial on designing certificates, importing recipients via Excel, and setting up tamper-proof QR code verification that resolves to an immutable ledger.",
        "category": "How to",
        "tags": ["how-to", "tutorial", "qr-code", "certificates"],
        "author_name": "Omobolaji Durojaiye",
        "author_role": "Founder & Lead Architect",
        "featured_image": "/images/blog/verify-certificate-guide.png",
        "meta_title": "How to Issue & Verify Digital Certificates Online | ProofDeck Guide",
        "meta_description": "Learn how to bulk issue verifiable credentials with QR codes and tamper-proof verification pages to protect institutional credibility.",
        "canonical_url": "https://blog.proofdeck.app/how-to-issue-verify-digital-certificates",
        "is_published": True,
        "published_at": datetime.utcnow(),
        "read_time_minutes": 6,
        "content": """## The Modern Standard for Verifiable Credentials

Issuing certificates used to mean exporting static PDFs, manually emailing individual files, and hoping third parties wouldn't easily alter recipient names with desktop editing tools.

Today, forward-thinking academies, universities, and enterprise training departments use cryptographic verification to issue certificates that are 100% tamper-proof.

> "A certificate is only as valuable as the ease with which a hiring manager or third party can prove it was legitimately issued."
> — Omobolaji Durojaiye, ProofDeck Founder

---

## Watch the Complete Video Walkthrough

Watch our step-by-step video guide below on creating customized certificate templates and testing live QR verification in under 5 minutes:

https://www.youtube.com/watch?v=dQw4w9WgXcQ

---

## 3 Simple Steps to Issue Your First Batch

### 1. Design or Upload Your Custom Template
Use our drag-and-drop visual builder or upload an existing branded SVG or high-resolution PNG template. You can position dynamic text variables such as:
- `{{recipient_name}}`
- `{{course_title}}`
- `{{issue_date}}`
- `{{certificate_id}}`
- `{{qr_code}}`

### 2. Bulk Import Recipients via Excel or CSV
Download our prepared Excel template, populate your student or attendee roster, and drag it into ProofDeck. The batch engine validates email syntax and certificate parameters automatically.

### 3. Dispatch Automated Delivery & QR Verification
Click **Issue Batch**. ProofDeck generates encrypted PDFs, records cryptographic hashes to our ledger, and delivers personalized emails containing 1-click LinkedIn badges and instant QR codes.

---

## Why Employers Prefer ProofDeck Verifiable Links

- **Instant Scan**: Recipient or employer points their smartphone camera directly at the printed or digital certificate.
- **Zero Phishing**: Verification runs strictly on verified ProofDeck infrastructure.
- **Audit Trails**: Issuing organizations can track total verification attempts in their dashboard analytics.

Ready to automate your credential workflow? [Create your free account on ProofDeck today](https://www.proofdeck.app/signup)."""
    },
    {
        "title": "Integrating the ProofDeck REST API: Automated Credential Issuance in Python & Node.js",
        "slug": "integrating-proofdeck-rest-api",
        "excerpt": "A complete guide for developers integrating programmatic certificate creation, automated batch triggers, and webhook events into LMS platforms and event software.",
        "category": "For devs",
        "tags": ["api", "developer", "python", "nodejs", "webhooks"],
        "author_name": "ProofDeck Engineering",
        "author_role": "Core Platform Team",
        "featured_image": "/images/blog/api-integration.png",
        "meta_title": "Integrating the ProofDeck REST API for Developers | ProofDeck Blog",
        "meta_description": "Connect your LMS, edtech platform, or payment gateway directly to ProofDeck to automatically issue verified certificates via REST API.",
        "canonical_url": "https://blog.proofdeck.app/integrating-proofdeck-rest-api",
        "is_published": True,
        "published_at": datetime.utcnow(),
        "read_time_minutes": 8,
        "content": """## Building Automated Credential Pipelines

When scaling an online learning platform, bootcamps, or enterprise compliance software, manual certificate issuance quickly becomes a bottleneck.

The ProofDeck REST API enables you to programmatically trigger certificate generation, deliver email notifications, and query verification statuses with simple HTTPS requests.

> "Developers can hook ProofDeck into any LMS webhook, completion trigger, or Stripe payment event in less than 30 lines of code."
> — ProofDeck API Docs

---

## Generating Your Developer API Key

1. Log into your [ProofDeck Dashboard](https://www.proofdeck.app/dashboard).
2. Navigate to **Settings** > **Developer & API**.
3. Click **Create Secret Key** (keep this token confidential).

---

## Example: Issuing a Certificate in Python

Here is a complete, minimal example using Python `requests`:

```python
import requests

API_KEY = "pd_live_secret_your_token_here"
ENDPOINT = "https://api.proofdeck.app/v1/certificates"

payload = {
    "template_id": 142,
    "recipient_name": "Alexander Hayes",
    "recipient_email": "alex.hayes@example.com",
    "course_title": "Advanced Distributed Systems",
    "issue_date": "2026-09-24",
    "send_email": True
}

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

response = requests.post(ENDPOINT, json=payload, headers=headers)
data = response.json()

print(f"Certificate issued! Verification URL: {data['verification_url']}")
```

---

## Webhook Events for Real-Time Synchronization

ProofDeck can dispatch real-time webhooks to your server for the following events:
- `certificate.issued`: Triggered immediately after rendering is finalized.
- `certificate.verified`: Fired whenever an employer or verifier scans the QR code.
- `certificate.shared_linkedin`: Track recipient engagement when added to LinkedIn.

Explore our full interactive endpoint documentation at [ProofDeck Developer Docs](https://www.proofdeck.app/docs)."""
    },
    {
        "title": "The Future of Credential Fraud Prevention: Why Static PDFs Are Obsolete",
        "slug": "future-of-credential-fraud-prevention",
        "excerpt": "As remote hiring accelerates, fraudulent diplomas and doctored PDF credentials have skyrocketed. Here is why tamper-proof verification registries are becoming mandatory.",
        "category": "General",
        "tags": ["credential-fraud", "security", "hr-tech", "verification"],
        "author_name": "ProofDeck Research",
        "author_role": "Security & Trust Division",
        "featured_image": "/images/blog/credential-fraud-stats.png",
        "meta_title": "Why Static PDFs Are Obsolete in Credential Verification | ProofDeck",
        "meta_description": "Explore the growing risk of certificate forgery in hiring and why cryptographic digital ledgers are replacing static PDF attachments.",
        "canonical_url": "https://blog.proofdeck.app/future-of-credential-fraud-prevention",
        "is_published": True,
        "published_at": datetime.utcnow(),
        "read_time_minutes": 5,
        "content": """## The Crisis of Unverified Credentials in Modern Hiring

In an increasingly globalized and remote workforce, credentials serve as the primary proxy for trust. However, conventional verification methods have completely failed to keep pace with modern graphic manipulation software.

Recent industry surveys indicate that over **35% of resumes and credential submissions feature unauthorized modifications or completely fabricated achievements**.

> "Anyone with basic design software can alter a name on a standard PDF certificate in under 60 seconds. Trust without cryptographic verification is simply a liability."
> — ProofDeck Trust & Safety Report

---

## The 4 Vulnerabilities of Traditional PDF Certificates

1. **No Authoritative Source Check**: An email attachment carries no link back to the issuing institution's database.
2. **Metadata Tampering**: PDF creation and author tags can be effortlessly modified using free web utilities.
3. **No Revocation Mechanism**: If a student is expelled or certification is rescinded, the recipient still retains the static file indefinitely.
4. **Recruiter Fatigue**: Reaching out to registrars via manual email or phone calls takes days, leading many hiring teams to skip verification entirely.

---

## How ProofDeck Reinvents Institutional Trust

ProofDeck combines instant QR scanning with a tamper-proof digital registry. Every certificate is cryptographically bound to the issuing institution's official account.

When a hiring manager scans the QR code or clicks the verification link, ProofDeck instantly checks our immutable database to confirm:
- The exact student name assigned by the institution.
- The authentic graduation or completion date.
- That the issuer is an authenticated organization with a verified identity.

Protect your graduates and bolster your organization's credibility. [Join hundreds of organizations issuing verified credentials with ProofDeck](https://www.proofdeck.app/signup)."""
    }
]

with app.app_context():
    print("Ensuring database tables exist...")
    db.create_all()

    print("Seeding/updating initial blog posts...")
    for post_data in INITIAL_POSTS:
        existing = BlogPost.query.filter_by(slug=post_data["slug"]).first()
        if not existing:
            post = BlogPost(**post_data)
            db.session.add(post)
            print(f"  [+] Added: {post_data['title']}")
        else:
            for k, v in post_data.items():
                setattr(existing, k, v)
            print(f"  [*] Updated: {post_data['title']}")
    
    db.session.commit()
    print("Blog seeding complete!")
