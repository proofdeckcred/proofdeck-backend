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
    
    try:
        res = default_url_fetcher(url, *args, **kwargs)
        _weasyprint_url_cache[url] = {
            'string': res.get('string'),
            'mime_type': res.get('mime_type'),
            'encoding': res.get('encoding'),
            'redirect_url': res.get('redirect_url')
        }
        return res
    except Exception as e:
        current_app.logger.warning(f"Failed to fetch external resource for WeasyPrint ({url}): {e}")
        return {'string': b'', 'mime_type': 'text/plain'}


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

    # 1. If path contains '/uploads/', resolve directly against local disk first!
    if '/uploads/' in image_path or image_path.startswith('uploads/'):
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
        # Extract the relative path after 'uploads/'
        parts = image_path.split('uploads/', 1)
        rel_path = parts[1].lstrip('/\\')
        full_path = os.path.join(upload_folder, rel_path)
        if os.path.exists(full_path):
            try:
                with open(full_path, "rb") as img_file:
                    return base64.b64encode(img_file.read()).decode('utf-8')
            except Exception as e:
                current_app.logger.warning(f"Failed to read local upload image {full_path}: {e}")

    # 2. Check if it is an external URL (http/https)
    if image_path.startswith('http://') or image_path.startswith('https://'):
        import requests
        try:
            response = requests.get(image_path, timeout=5)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
             current_app.logger.error(f"Error fetching image from URL {image_path}: {e}")
             return None

    # 3. Fallback to direct local path or filename in upload folder
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    cleaned_path = image_path.lstrip('/\\')
    candidates = [
        image_path,
        os.path.join(upload_folder, cleaned_path),
        os.path.join(upload_folder, os.path.basename(image_path))
    ]
    for candidate in candidates:
        if os.path.exists(candidate) and os.path.isfile(candidate):
            try:
                with open(candidate, "rb") as img_file:
                    return base64.b64encode(img_file.read()).decode('utf-8')
            except Exception:
                continue

    current_app.logger.warning(f"Image file not found on disk or network: {image_path}")
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
    import json
    import re
    layout_data = template.layout_data or {}
    if isinstance(layout_data, str):
        try:
            layout_data = json.loads(layout_data)
        except Exception:
            layout_data = {}
    elif not isinstance(layout_data, dict):
        layout_data = {}

    elements = layout_data.get('elements', [])
    background = layout_data.get('background', {})
    canvas_config = layout_data.get('canvas', {'width': 842, 'height': 595})
    page_width = canvas_config.get('width', 842)
    page_height = canvas_config.get('height', 595)

    # Prepare dynamic data
    extra = certificate.extra_fields or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    elif not isinstance(extra, dict):
        extra = {}

    amount_text = extra.get('amount', 'PAID')

    issue_date_str = ""
    if certificate.issue_date:
        if hasattr(certificate.issue_date, 'strftime'):
            issue_date_str = certificate.issue_date.strftime('%B %d, %Y')
        else:
            issue_date_str = str(certificate.issue_date)

    dynamic_data = {
        "{{recipient_name}}": certificate.recipient_name or "",
        "{{course_title}}": certificate.course_title or "",
        "{{issue_date}}": issue_date_str,
        "{{issuer_name}}": certificate.issuer_name or "",
        "{{verification_id}}": certificate.verification_id or "",
        "{{signature}}": certificate.signature or certificate.issuer_name or "",
        "{{amount}}": amount_text
    }
    
    # Merge any other extra fields into dynamic data (both as-is and formatted)
    for key, val in extra.items():
        dynamic_data[f"{{{{{key}}}}}"] = str(val) if val is not None else ""
        # Also support key with spaces if user entered key with underscores, or vice versa
        clean_key = key.replace('_', ' ')
        dynamic_data[f"{{{{{clean_key}}}}}"] = str(val) if val is not None else ""

    # Generate QR
    qr_base64 = _generate_qr_base64(certificate.verification_id)
    dynamic_data["{{qr_code}}"] = f'<img src="data:image/png;base64,{qr_base64}" style="width: 100%; height: 100%;" />'

    html_elements = []
    for el in elements:
        style = (
            f'position: absolute; left: {el.get("x", 0)}px; top: {el.get("y", 0)}px; '
            f'width: {el.get("width", 200)}px; height: {el.get("height", 30)}px; '
            f'transform-origin: 0 0; transform: rotate({el.get("rotation", 0)}deg); '
        )
        content = ''
        el_type = el.get('type')

        if el_type == 'text' or el_type == 'placeholder':
            text = str(el.get('text') or '')
            for placeholder, value in dynamic_data.items():
                if placeholder.lower() in text.lower():
                    pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
                    text = pattern.sub(lambda m, v=value: str(v), text)

            font_style_val = el.get("fontStyle", "normal")
            font_weight = "bold" if "bold" in font_style_val else "normal"
            font_style = "italic" if "italic" in font_style_val else "normal"

            # Vertical and horizontal alignment
            v_align = el.get('verticalAlign', 'middle')
            if v_align == 'top':
                v_align_css = 'align-items: flex-start;'
            elif v_align == 'bottom':
                v_align_css = 'align-items: flex-end;'
            else:
                v_align_css = 'align-items: center;'

            h_align = el.get('align', 'left')
            if h_align == 'center':
                h_align_css = 'justify-content: center; text-align: center;'
            elif h_align == 'right':
                h_align_css = 'justify-content: flex-end; text-align: right;'
            else:
                h_align_css = 'justify-content: flex-start; text-align: left;'

            style += (
                f'font-family: {el.get("fontFamily", "sans-serif")}; '
                f'font-size: {el.get("fontSize", 16)}px; '
                f'color: {el.get("fill", "#000")}; '
                f'font-style: {font_style}; '
                f'font-weight: {font_weight}; '
                f'line-height: 1.2; word-wrap: break-word; display: flex; '
                f'{v_align_css} {h_align_css} '
            )
                
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
    bg_image_path = background.get('image') or template.background_url
    if bg_image_path:
         base64_bg = get_image_as_base64(bg_image_path)
         if base64_bg:
            mime_type = "image/png"
            if bg_image_path.startswith("data:image/svg+xml") or bg_image_path.endswith(".svg"):
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

def generate_certificate_png(certificate, template, issuer, dpi=300):
    """
    Renders the certificate directly to high-resolution PNG image bytes.
    Exclusively available for Enterprise plan members.
    """
    try:
        try:
            import fitz
        except ImportError:
            import pymupdf as fitz

        pdf_buffer = generate_certificate_pdf(certificate, template, issuer)
        pdf_bytes = pdf_buffer.getvalue() if hasattr(pdf_buffer, 'getvalue') else bytes(pdf_buffer)
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=dpi)
        png_buffer = BytesIO(pix.tobytes("png"))
        png_buffer.seek(0)
        doc.close()
        return png_buffer
    except Exception as e:
        import traceback
        current_app.logger.error(f"PNG Generation error: {e}\n{traceback.format_exc()}")
        raise