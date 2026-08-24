import secrets
from dotenv import load_dotenv
load_dotenv()

from pkg import create_app
from pkg.models import db, User, Template

app = create_app()

def create_pilot_user():
    with app.app_context():
        email = "hannacode_pilot@proofdeck.io"
        name = "HannaCode Pilot"
        
        # Check if user already exists
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Generate a secure random password (they won't need it for API access, but required by model)
            password = secrets.token_urlsafe(16)
            # Generate a secure API key
            api_key = secrets.token_hex(32)
            
            user = User(
                name=name,
                email=email,
                password_hash=password, # In a real app we'd hash this, but this is a quick script for a dummy user
                role='pro', # Give them pro access for the pilot
                cert_quota=100, # Give them 100 free certs
                api_key=api_key,
                is_verified=True
            )
            db.session.add(user)
            db.session.commit()
            print(f"User created successfully!")
        else:
            print("User already exists. Updating API key...")
            if not user.api_key:
                user.api_key = secrets.token_hex(32)
                db.session.commit()
        
        print(f"\n--- CREDENTIALS FOR HANNACODE ---")
        print(f"API Key: {user.api_key}")
        print(f"User ID: {user.id}")
        
        # Ensure they have at least one template to test with
        template = Template.query.filter_by(user_id=user.id).first()
        if not template:
            print("\nCreating a demo template for them...")
            new_template = Template(
                user_id=user.id,
                title="Dart Course Completion",
                layout_style="modern",
                custom_text={
                    "title": "Certificate of Completion",
                    "body": "has successfully completed the Dart Course"
                }
            )
            db.session.add(new_template)
            db.session.commit()
            print(f"Template ID: {new_template.id}")
        else:
            print(f"\nExisting Template ID: {template.id}")

if __name__ == "__main__":
    create_pilot_user()
