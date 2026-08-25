import os
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from pkg import create_app
from pkg.utils.email_utils import send_password_reset_email
from pkg.models import User

app = create_app()

with app.app_context():
    print("Testing email sending via Resend SMTP...")
    print(f"Mail Server: {app.config.get('MAIL_SERVER')}:{app.config.get('MAIL_PORT')}")
    print(f"Sender: {app.config.get('MAIL_DEFAULT_SENDER')}")
    
    # Create a mock user object to test sending
    class MockUser:
        name = "Omobolaji Durojaiye"
        email = "omobolajidurojaiye57@gmail.com"
        
    user = MockUser()
    test_reset_url = "https://www.proofdeck.app/reset-password/test_token_12345"
    
    try:
        send_password_reset_email(user, test_reset_url)
        print("SUCCESS! Test email sent successfully to omobolajidurojaiye57@gmail.com")
    except Exception as e:
        print(f"FAILED to send email: {e}")
