from pkg import create_app
from pkg.extensions import db
from pkg.models import User, Template, Company, Certificate, Payment
from bcrypt import hashpw, gensalt
from datetime import datetime, timedelta
import random

app = create_app()

def seed_data():
    with app.app_context():
        print("Starting Database Seeder...")

        # 1. Create a Test User
        test_email = "test@certifyme.io"
        user = User.query.filter_by(email=test_email).first()
        if not user:
            hashed_password = hashpw("password123".encode('utf-8'), gensalt())
            user = User(
                name="Test User",
                email=test_email,
                password_hash=hashed_password.decode('utf-8'),
                role='pro',
                cert_quota=1000,
                is_verified=True
            )
            db.session.add(user)
            db.session.commit()
            print(f"User created: {test_email}")
        
        # 1b. Create Mock Users for Analytics
        print("Seeding mock users...")
        for i in range(15):
             email = f"user{i}@example.com"
             if not User.query.filter_by(email=email).first():
                hashed = hashpw("password123".encode('utf-8'), gensalt())
                new_user = User(
                    name=f"Mock User {i}",
                    email=email,
                    password_hash=hashed.decode('utf-8'),
                    role=random.choice(['free', 'starter', 'pro']),
                    cert_quota=100,
                    is_verified=True,
                    created_at=datetime.utcnow() - timedelta(days=random.randint(0, 60))
                )
                db.session.add(new_user)
        db.session.commit()

        # 2. Create Default Public Templates

        if not Template.query.filter_by(title='Modern Blue').first():
            t1 = Template(
                title='Modern Blue',
                primary_color='#2563EB',
                secondary_color='#64748B',
                body_font_color='#1E293B',
                font_family='Lato',
                layout_style='modern',
                is_public=True,
                custom_text={"title": "Certificate of Completion", "body": "has successfully completed the course"}
            )
            db.session.add(t1)

        if not Template.query.filter_by(title='Classic Blue').first():
            t2 = Template(
                title='Classic Blue',
                primary_color='#1E3A8A',
                secondary_color='#D1D5DB',
                body_font_color='#111827',
                font_family='Georgia',
                layout_style='classic',
                is_public=True,
                custom_text={"title": "Certificate of Achievement", "body": "is hereby awarded this certificate for"}
            )
            db.session.add(t2)

        # Payment Receipt - Ensure layout_style is explicitly set
        receipt_template = Template.query.filter_by(title='Official Receipt').first()
        if not receipt_template:
            t3 = Template(
                title='Official Receipt',
                primary_color='#111827',
                secondary_color='#4B5563', 
                body_font_color='#1F2937',
                font_family='Inter',
                layout_style='receipt',
                is_public=True,
                custom_text={"title": "PAYMENT RECEIPT", "body": "PAID"}
            )
            db.session.add(t3)
        else:
            # If it exists, ensure its style is correct
            receipt_template.layout_style = 'receipt'
        
        db.session.commit()

        # 2b. Create New Premium Templates
        premium_templates = [
            {
                "title": "Modern Landscape",
                "layout_style": "modern_landscape",
                "primary_color": "#0284C7",
                "secondary_color": "#E2E8F0",
                "body_font_color": "#1E293B",
                "font_family": "Lato",
                "is_public": True,
                "custom_text": {"title": "Certificate of Completion", "body": "has successfully completed"}
            },
            {
                "title": "Elegant Serif",
                "layout_style": "elegant_serif",
                "primary_color": "#1C1917",
                "secondary_color": "#CA8A04",
                "body_font_color": "#292524",
                "font_family": "Merriweather",
                "is_public": True,
                "custom_text": {"title": "Certificate of Achievement", "body": "is hereby awarded to"}
            },
            {
                "title": "Minimalist Bold",
                "layout_style": "minimalist_bold",
                "primary_color": "#000000",
                "secondary_color": "#E5E5E5",
                "body_font_color": "#171717",
                "font_family": "Inter",
                "is_public": True,
                "custom_text": {"title": "CERTIFICATE", "body": "of completion generated for"}
            },
            {
                "title": "Corporate Blue",
                "layout_style": "corporate_blue",
                "primary_color": "#1E40AF",
                "secondary_color": "#60A5FA",
                "body_font_color": "#1E3A8A",
                "font_family": "Roboto",
                "is_public": True,
                "custom_text": {"title": "Certificate of Excellence", "body": "for outstanding performance in"}
            },
            {
                "title": "Tech Dark",
                "layout_style": "tech_dark",
                "primary_color": "#22C55E",
                "secondary_color": "#166534",
                "body_font_color": "#FFFFFF",
                "font_family": "Fira Code",
                "is_public": True,
                "custom_text": {"title": "SYSTEM CERTIFICATION", "body": "verified validation of skills in"}
            },
            {
                "title": "Creative Art",
                "layout_style": "creative_art",
                "primary_color": "#DB2777",
                "secondary_color": "#F472B6",
                "body_font_color": "#831843",
                "font_family": "Playfair Display",
                "is_public": True,
                "custom_text": {"title": "Certificate of Artistry", "body": "for creative excellence in"}
            },
            {
                "title": "Badge Certificate",
                "layout_style": "badge_cert",
                "primary_color": "#475569",
                "secondary_color": "#CBD5E1",
                "body_font_color": "#334155",
                "font_family": "Inter",
                "is_public": True,
                "custom_text": {"title": "Verified Badge", "body": "has earned the badge for"}
            },
            {
                "title": "Award Gold",
                "layout_style": "award_gold",
                "primary_color": "#B45309",
                "secondary_color": "#FCD34D",
                "body_font_color": "#78350F",
                "font_family": "Cinzel",
                "is_public": True,
                "custom_text": {"title": "Achievement Award", "body": "in recognition of success in"}
            },
            {
                "title": "Diploma Classic",
                "layout_style": "diploma_classic",
                "primary_color": "#000000",
                "secondary_color": "#FEF3C7",
                "body_font_color": "#1F2937",
                "font_family": "Old Standard TT",
                "is_public": True,
                "custom_text": {"title": "DIPLOMA", "body": "has fulfilled all requirements for"}
            },
            {
                "title": "Achievement Star",
                "layout_style": "achievement_star",
                "primary_color": "#4338CA",
                "secondary_color": "#FACC15",
                "body_font_color": "#FFFFFF",
                "font_family": "Poppins",
                "is_public": True,
                "custom_text": {"title": "Star Student", "body": "for stellar performance in"}
            }
        ]

        for tmpl in premium_templates:
            existing = Template.query.filter_by(title=tmpl["title"]).first()
            if existing:
                existing.layout_style = tmpl["layout_style"]
                existing.is_premium = True
                existing.is_public = True
                print(f"Updated template: {tmpl['title']} (Premium)")
            else:
                tmpl["is_premium"] = True
                new_t = Template(**tmpl)
                db.session.add(new_t)
                print(f"Added template: {tmpl['title']} (Premium)")
        
        db.session.commit()
        
        # 3. Seed Mock Payments
        print("Seeding mock payments...")
        users = User.query.all()
        for i in range(20):
            # Random date spanning last 60 days
            p_date = datetime.utcnow() - timedelta(days=random.randint(0, 60))
            u = random.choice(users)
            
            p = Payment(
                user_id=u.id,
                amount=random.choice([9.00, 19.00, 29.00, 49.00]),
                currency='USD',
                provider='stripe',
                status='paid',
                plan=random.choice(['starter', 'pro', 'credits']),
                transaction_ref=f"tx_mock_{i}_{random.randint(1000,9999)}",
                created_at=p_date
            )
            db.session.add(p)
        db.session.commit()

        # 4. Seed Mock Certificates
        print("Seeding mock certificates...")
        template = Template.query.filter_by(title='Modern Blue').first()
        if template:
            for i in range(30):
                verification_id = f"cert-{u.id}-{i}"
                if not Certificate.query.filter_by(verification_id=verification_id).first():
                    c_date = datetime.utcnow() - timedelta(days=random.randint(0, 60))
                    u = random.choice(users)
                    cert = Certificate(
                        user_id=u.id,
                        template_id=template.id,
                        recipient_name=f"Recipient {i}",
                        course_title="Advanced React Pattern",
                        issue_date=c_date.date(),
                        verification_id=verification_id,
                        status='valid',
                        created_at=c_date
                    )
                    db.session.add(cert)
            db.session.commit()

        print("Seeding Complete (Users, Payments, Certs, Templates)!")

if __name__ == '__main__':
    seed_data()
