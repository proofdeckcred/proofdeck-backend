import os
import datetime
from flask import Flask
from pkg.services.pdf_service import generate_certificate_pdf

# Mock classes
class MockCertificate:
    def __init__(self):
        self.recipient_name = "John Doe"
        self.course_title = "Creative Arts Masterclass"
        self.issue_date = datetime.date.today()
        self.issuer_name = "Art School"
        self.verification_id = "123-456-789"
        self.signature = "John Smith"
        self.extra_fields = {}
        self.recipient_email = "john@example.com"

class MockTemplate:
    def __init__(self):
        self.layout_style = "creative_art"
        self.logo_url = None
        self.background_url = None
        self.primary_color = "#FF5733"
        self.secondary_color = "#C70039"
        self.body_font_color = "#000000"
        self.font_family = "Inter"
        self.custom_text = {"title": "Certificate of Excellence"}
        self.layout_data = {}

class MockIssuer:
    def __init__(self):
        self.signature_image_url = None
        self.issuer_name = "Art School"

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = os.path.abspath('uploads')
app.config['FRONTEND_URL'] = 'http://localhost:5173'

def run_test():
    with app.app_context():
        cert = MockCertificate()
        tmpl = MockTemplate()
        issuer = MockIssuer()
        
        try:
            print("Attempting to generate PDF...")
            pdf_bytes = generate_certificate_pdf(cert, tmpl, issuer)
            print("PDF generated successfully! Size:", len(pdf_bytes.getvalue()))
        except Exception as e:
            print(f"Error generating PDF: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    run_test()
