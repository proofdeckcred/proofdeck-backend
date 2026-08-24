
import os
import sys
from flask import Flask, render_template

# Add backend directory to sys.path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# Create a minimal Flask app to mimic the real app
# Assuming this script is run from the project root, but resides in backend/
# We want template_folder to resolve to backend/templates
app = Flask(__name__, template_folder='templates')

# Mock data usually passed to templates
def react_style_to_css_map(style_dict):
    if not style_dict or not isinstance(style_dict, dict):
         return {}
    css_map = {}
    for k, v in style_dict.items():
        kebab_key = "".join(['-' + c.lower() if c.isupper() else c for c in k])
        css_map[kebab_key] = v
    return css_map

# Mock data usually passed to templates
background_style_dict = {'backgroundColor': '#f0f0f0', 'border': '1px solid black'}
text_style_dict = {'color': '#333', 'fontFamily': 'Arial', 'fontSize': '12px', 'fontWeight': 'bold'}

mock_context = {
    'primary_color': '#FFD700',
    'primary_color_alpha': '#FFD70022',
    'secondary_color': '#C0C0C0',
    'background_style': 'background-color: #f0f0f0;',
    'text_style': 'color: #333;',
    'background_style_map': react_style_to_css_map(background_style_dict),
    'text_style_map': react_style_to_css_map(text_style_dict),
    'font_family': 'Arial',
    'body_font_color': '#000',
    'recipient_name': 'John Doe',
    'issuer_name': 'Test Issuer',
    'course_title': 'Test Course',
    'issue_date': '2023-01-01',
    'verification_id': '12345678',
    'logo_base64': '',
    'qr_base64': '',
    'signature': 'Signed',
    'custom_text': {'title': 'Certificate', 'body': 'For completing'},
    'amount': '$100.00',
    'recipient_email': 'test@example.com'
}

def test_template(template_name):
    print(f"Testing {template_name}...")
    try:
        with app.app_context():
            rendered = render_template(f"certificates/{template_name}", **mock_context)
            print(f"SUCCESS: {template_name} rendered successfully.")
            # We could also try to write it to a file or parse it if needed
            # For now, just rendering is a good first step to check for Jinja errors
    except Exception as e:
        print(f"ERROR: Failed to render {template_name}")
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    templates_to_test = [
        'award_gold.html',
        'tech_dark.html',
        'receipt.html', 
        'achievement_star.html',
        'badge_cert.html',
        'classic.html',
        'creative_art.html',
        'diploma_classic.html',
        'elegant_serif.html',
        'minimalist_bold.html',
        'modern.html',
        'modern_landscape.html',
        'corporate_blue.html'
    ]
    
    for t in templates_to_test:
        test_template(t)
