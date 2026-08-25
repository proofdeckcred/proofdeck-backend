import os
import base64
import qrcode
from io import BytesIO
from flask import current_app, render_template_string, render_template
from weasyprint import HTML, default_url_fetcher
from functools import lru_cache

# --- CACHED URL FETCHER FOR WEASYPRINT ---
_weasyprint_url_cache = {}

def memoized_url_fetcher(url, *args, **kwargs):
    if url in _weasyprint_url_cache:
        cached = _weasyprint_url_cache[url]
        return {
            'string': cached['string'],
            'mime_type': cached['mime_type'],
            'encoding': cached['encoding'],
            'redirect_url': cached['redirect_url']
        }
    
    res = default_url_fetcher(url, *args, **kwargs)
    _weasyprint_url_cache[url] = {
        'string': res.get('string'),
        'mime_type': res.get('mime_type'),
        'encoding': res.get('encoding'),
        'redirect_url': res.get('redirect_url')
    }
    return res


@lru_cache(maxsize=256)
def get_image_as_base64(image_path):
    if not image_path:
        return None
    
    # Check if it's already a base64 string (starts with data:image)
    if image_path.startswith('data:image'):
        if 'base64,' in image_path:
            return image_path.split('base64,')[1]
        elif 'utf8,' in image_path:
            # It is a raw SVG string (percent encoded)
            raw_data = image_path.split('utf8,')[1]
            from urllib.parse import unquote
            decoded_svg = unquote(raw_data)
            # Base64 encode it so it becomes a valid base64 image data block
            return base64.b64encode(decoded_svg.encode('utf-8')).decode('utf-8')
        else:
            # Generic data URL
            if ',' in image_path:
                header, data = image_path.split(',', 1)
                if 'base64' in header:
                    return data
                else:
                    from urllib.parse import unquote
                    decoded = unquote(data)
                    return base64.b64encode(decoded.encode('utf-8')).decode('utf-8')
            return image_path

    # Check if it is a complete URL (http/https)
    if image_path.startswith('http'):
        import requests
        try:
            response = requests.get(image_path)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
             current_app.logger.error(f"Error fetching image from URL {image_path}: {e}")
             return None

    # Fallback to local file system
    # Strip leading /uploads/ if present
    if image_path.startswith('/uploads/'):
        filename = image_path[9:]  # Remove '/uploads/' prefix
    else:
        filename = os.path.basename(image_path)  # Get just the filename
    
    # Build full path to upload folder
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    full_path = os.path.join(upload_folder, filename)

    if os.path.exists(full_path):
        with open(full_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode('utf-8')
    
    # Log warning if file doesn't exist
    current_app.logger.warning(f"Image file not found: {full_path} (from path: {image_path})")
    return None

def react_style_to_css(style_dict):
    """Convert React camelCase style dict to standard CSS string."""
    if not style_dict or not isinstance(style_dict, dict):
        return ""
    css_parts = []
    for k, v in style_dict.items():
        # Convert camelCase to kebab-case
        kebab_key = "".join(['-' + c.lower() if c.isupper() else c for c in k])
        css_parts.append(f"{kebab_key}: {v}")
    return "; ".join(css_parts)

def generate_certificate_pdf(certificate, template, issuer):
    """
    Main entry point for PDF generation.
    Decides whether to use Visual (Canvas) or HTML templates.
    """
    if template.layout_style == 'visual':
        return _generate_visual_pdf(certificate, template, issuer)
    
    return _generate_html_pdf(certificate, template, issuer)

def _generate_visual_pdf(certificate, template, issuer):
    layout_data = template.layout_data or {}
    elements = layout_data.get('elements', [])
    background = layout_data.get('background', {})
    canvas_config = layout_data.get('canvas', {'width': 842, 'height': 595})
    page_width = canvas_config.get('width', 842)
    page_height = canvas_config.get('height', 595)

    # Prepare dynamic data
    extra = certificate.extra_fields or {}
    amount_text = extra.get('amount', 'PAID')

    dynamic_data = {
        "{{recipient_name}}": certificate.recipient_name,
        "{{course_title}}": certificate.course_title,
        "{{issue_date}}": certificate.issue_date.strftime('%B %d, %Y'),
        "{{issuer_name}}": certificate.issuer_name,
        "{{verification_id}}": certificate.verification_id,
        "{{signature}}": certificate.signature or certificate.issuer_name,
        "{{amount}}": amount_text
    }
    
    # Merge any other extra fields into dynamic data
    for key, val in extra.items():
        dynamic_data[f"{{{{{key}}}}}"] = val

    # Generate QR
    qr_base64 = _generate_qr_base64(certificate.verification_id)
    dynamic_data["{{qr_code}}"] = f'<img src="data:image/png;base64,{qr_base64}" style="width: 100%; height: 100%;" />'

    html_elements = []
    for el in elements:
        style = (
            f'position: absolute; left: {el["x"]}px; top: {el["y"]}px; '
            f'width: {el["width"]}px; height: {el["height"]}px; '
            f'transform-origin: 0 0; transform: rotate({el.get("rotation", 0)}deg); '
        )
        content = ''
        el_type = el.get('type')

        if el_type == 'text' or el_type == 'placeholder':
            text = el.get('text', '')
            for placeholder, value in dynamic_data.items():
                 if placeholder in text:
                    text = text.replace(placeholder, str(value))

            font_style_val = el.get("fontStyle", "normal")
            font_weight = "bold" if "bold" in font_style_val else "normal"
            font_style = "italic" if "italic" in font_style_val else "normal"

            style += (
                f'font-family: {el.get("fontFamily", "sans-serif")}; '
                f'font-size: {el.get("fontSize", 16)}px; '
                f'color: {el.get("fill", "#000")}; '
                f'text-align: {el.get("align", "left")}; '
                f'font-style: {font_style}; '
                f'font-weight: {font_weight}; '
                'line-height: 1.2; word-wrap: break-word; display: flex; align-items: center; '
            )
            
            # Vertical alignment helper
            if el.get('align') == 'center': style += 'justify-content: center;'
            elif el.get('align') == 'right': style += 'justify-content: flex-end;'
                
            content = text.replace('\\n', '<br>').replace('\n', '<br>')

        elif el_type == 'image':
            src = el.get('src')
            if src:
                base64_img = get_image_as_base64(src)
                if base64_img:
                    content = f'<img src="data:image/png;base64,{base64_img}" style="width: 100%; height: 100%; object-fit: contain;">'

        html_elements.append(f'<div style="{style}">{content}</div>')

    background_style = ''
    if background.get('fill'):
        background_style += f'background-color: {background["fill"]};'
    if background.get('image'):
         base64_bg = get_image_as_base64(background["image"])
         if base64_bg:
            mime_type = "image/png"
            bg_image_str = background["image"]
            if bg_image_str.startswith("data:image/svg+xml") or bg_image_str.endswith(".svg"):
                mime_type = "image/svg+xml"
            background_style += f"background-image: url('data:{mime_type};base64,{base64_bg}'); background-size: cover; background-position: center;"

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Alex+Brush&family=Cinzel:wght@400;600;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400&family=Great+Vibes&family=Inter:wght@400;500;600;700&family=Lato:ital,wght@0,300;0,400;0,700;1,400&family=Lexend:wght@300;400;500;600;700&family=Merriweather:ital,wght@0,300;0,400;0,700;1,400&family=Montserrat:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300;1,400;1,700&family=Open+Sans:ital,wght@0,300;0,400;0,600;0,700;1,400&family=Oswald:wght@400;600;700&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Roboto:ital,wght@0,300;0,400;0,700;1,400&family=Sacramento&display=swap">
        <style>
            @page {{ size: {page_width}px {page_height}px; margin: 0; }}
            body {{ margin: 0; padding: 0; font-family: sans-serif; }}
            .certificate-container {{
                width: {page_width}px; height: {page_height}px;
                position: relative; overflow: hidden;
                {background_style}
            }}
            @font-face {{
              font-family: 'Product Sans';
              font-style: normal;
              font-weight: 400;
              src: url(https://fonts.gstatic.com/s/productsans/v5/HYvgU2fE2nRJvZ5JFAumwegdm0LZxxJZkbJ7NDDPsr0.woff2) format('woff2');
            }}
            @font-face {{
              font-family: 'Product Sans';
              font-style: normal;
              font-weight: 750;
              src: url(https://fonts.gstatic.com/s/productsans/v5/ea8acIL1mXDmi1A-4C2hnT9-pQURs1S4Uo3Al709Yuw.woff2) format('woff2');
            }}
        </style>
    </head>
    <body>
        <div class="certificate-container">{''.join(html_elements)}</div>
    </body>
    </html>
    """
    return _render_pdf_bytes(html_template)

def _generate_html_pdf(certificate, template, issuer):
    qr_base64 = _generate_qr_base64(certificate.verification_id)
    logo_base64 = get_image_as_base64(template.logo_url)
    background_base64 = get_image_as_base64(template.background_url)
    signature_image_base64 = None
    if not certificate.signature and issuer.signature_image_url:
        signature_image_base64 = get_image_as_base64(issuer.signature_image_url)
    
    # Handle amount logic for receipts
    extra = certificate.extra_fields or {}
    amount = extra.get('amount')
    
    # If no amount in extra_fields, try parsing from course title if it looks like currency
    if not amount and certificate.course_title:
        import re
        match = re.search(r'[$₦]\s?[\d,]+(\.\d{2})?', certificate.course_title)
        amount = match.group(0) if match else "PAID"

    context = {
        "recipient_name": certificate.recipient_name,
        "recipient_email": certificate.recipient_email,
        "course_title": certificate.course_title,
        "issue_date": certificate.issue_date.strftime('%B %d, %Y'),
        "signature": certificate.signature or certificate.issuer_name,
        "issuer_name": certificate.issuer_name,
        "verification_id": certificate.verification_id,
        "frontend_url": (current_app.config.get('FRONTEND_URL') or "proofdeck.app").replace('https://', '').replace('http://', ''),
        "logo_base64": logo_base64,
        "background_base64": background_base64,
        "primary_color": template.primary_color,
        "primary_color_alpha": f"{template.primary_color}22",
        "secondary_color": template.secondary_color,
        "body_font_color": template.body_font_color,
        "font_family": {
            "Georgia": "'Merriweather', serif",
            "Times New Roman": "'Playfair Display', serif",
            "Arial": "'Open Sans', sans-serif",
            "Verdana": "'Lato', sans-serif",
            "Lato": "'Lato', sans-serif",
            "Roboto": "'Roboto', sans-serif"
        }.get(template.font_family, template.font_family),
        "qr_base64": qr_base64,
        "custom_text": template.custom_text or {},
        "signature_image_base64": signature_image_base64,
        "extra_fields": extra,
        "amount": amount
    }
    
    # Process layout_data for styles
    layout_data = template.layout_data or {}
    context['text_style'] = react_style_to_css(layout_data.get('textStyle'))
    context['background_style'] = react_style_to_css(layout_data.get('backgroundStyle'))
    
    # helper for explicit map
    def react_style_to_css_map(style_dict):
        if not style_dict or not isinstance(style_dict, dict):
             return {}
        css_map = {}
        for k, v in style_dict.items():
            kebab_key = "".join(['-' + c.lower() if c.isupper() else c for c in k])
            css_map[kebab_key] = v
        return css_map

    context['text_style_map'] = react_style_to_css_map(layout_data.get('textStyle'))
    context['background_style_map'] = react_style_to_css_map(layout_data.get('backgroundStyle'))


    # Use Modular Templates if available
    file_templates = {
        'classic': 'certificates/classic.html',
        'award_gold': 'certificates/award_gold.html',
        'modern': 'certificates/modern.html',
        'receipt': 'certificates/receipt.html',
        'modern_landscape': 'certificates/modern_landscape.html',
        'elegant_serif': 'certificates/elegant_serif.html',
        'minimalist_bold': 'certificates/minimalist_bold.html',
        'corporate_blue': 'certificates/corporate_blue.html',
        'tech_dark': 'certificates/tech_dark.html',
        'creative_art': 'certificates/creative_art.html',
        'badge_cert': 'certificates/badge_cert.html',
        'diploma_classic': 'certificates/diploma_classic.html',
        'achievement_star': 'certificates/achievement_star.html',
    }
    
    # Use Modular Templates or default to modern
    template_file = file_templates.get(template.layout_style, 'certificates/modern.html')
    
    try:
        html_content = render_template(template_file, **context)
        
        # Inject Product Sans font-face definition globally
        font_inject = """
        <style>
            @font-face {
              font-family: 'Product Sans';
              font-style: normal;
              font-weight: 400;
              src: url(https://fonts.gstatic.com/s/productsans/v5/HYvgU2fE2nRJvZ5JFAumwegdm0LZxxJZkbJ7NDDPsr0.woff2) format('woff2');
            }
            @font-face {
              font-family: 'Product Sans';
              font-style: normal;
              font-weight: 750;
              src: url(https://fonts.gstatic.com/s/productsans/v5/ea8acIL1mXDmi1A-4C2hnT9-pQURs1S4Uo3Al709Yuw.woff2) format('woff2');
            }
        </style>
        """
        if "</head>" in html_content:
            html_content = html_content.replace("</head>", f"{font_inject}</head>")
            
        return _render_pdf_bytes(html_content)
    except Exception as e:
        current_app.logger.error(f"Error rendering file template: {e}")
        raise e

def _generate_qr_base64(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    verification_url = f"{current_app.config['FRONTEND_URL']}/verify/{data}"
    qr.add_data(verification_url)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO(); qr_img.save(qr_buffer, format="PNG")
    return base64.b64encode(qr_buffer.getvalue()).decode('utf-8')

def _render_pdf_bytes(html_content):
    pdf_buffer = BytesIO()
    try:
        HTML(string=html_content).write_pdf(pdf_buffer, url_fetcher=memoized_url_fetcher)
        pdf_buffer.seek(0)
        return pdf_buffer
    except Exception as e:
        current_app.logger.error(f"WeasyPrint PDF generation error: {e}")
        raise