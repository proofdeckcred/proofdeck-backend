import os
import re
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader
import mjml

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'mjml')

_jinja_env = None

def get_jinja_env():
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )
    return _jinja_env

def html_to_plain_text(html_content):
    """
    Converts compiled HTML into a readable plain-text email version
    suitable for multipart/alternative.
    """
    # Remove head, style, and script tags completely
    text = re.sub(r'<head[^>]*>.*?</head>', '', html_content, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Replace links with text (url)
    text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.IGNORECASE | re.DOTALL)
    # Replace break and paragraph tags with newlines
    text = re.sub(r'<(br|p|div|tr|section|mj-[^>]+)[^>]*>', '\n', text, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&bull;', '•')
    # Collapse multiple blank lines
    text = re.sub(r'\n\s*\n+', '\n\n', text).strip()
    return text

def render_email(template_name, context=None):
    """
    Renders an email template from MJML + Jinja2 to inlined HTML and plain text.
    
    :param template_name: Name of template (e.g. 'weekly-digest.mjml', 'winback-inactive.mjml')
    :param context: Dictionary of variables for the template
    :return: dict with 'html', 'text', and 'errors'
    """
    if context is None:
        context = {}
    
    # Inject standard defaults
    context.setdefault('current_year', datetime.now(timezone.utc).year)
    context.setdefault('preferences_url', 'https://www.proofdeck.app/dashboard/settings')
    context.setdefault('unsubscribe_url', 'https://www.proofdeck.app/email/unsubscribe')

    env = get_jinja_env()
    template = env.get_template(template_name)
    raw_mjml = template.render(**context)

    # Compile MJML to HTML
    mjml_result = mjml.mjml_to_html(raw_mjml)
    html_output = mjml_result.html if hasattr(mjml_result, 'html') else str(mjml_result)
    errors = getattr(mjml_result, 'errors', [])

    text_output = html_to_plain_text(html_output)

    return {
        "html": html_output,
        "text": text_output,
        "errors": errors,
        "mjml": raw_mjml
    }

if __name__ == '__main__':
    test_context = {
        "user_name": "Bolaji",
        "headline": "3 people checked Tunde's certificate this week",
        "opening_why": "Every certificate you issue is one less phone call someone has to make to prove they are real.",
        "issued_count": 14,
        "verifications_count": 38,
        "all_time_issued": 1420,
        "top_certificate_title": "Full-Stack Web Engineering Diploma",
        "top_certificate_recipient": "Tunde Bakare",
        "top_certificate_views": 19,
        "credits_remaining": 450,
        "cta_text": "Issue More Certificates",
        "cta_url": "https://www.proofdeck.app/dashboard/issue",
        "is_zero_state": False
    }
    result = render_email('weekly-digest.mjml', test_context)
    print(f"HTML rendered: {len(result['html'])} bytes")
