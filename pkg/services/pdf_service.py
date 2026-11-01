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
            'mime_type': cached.get('mime_type', 'application/octet-stream'),
            'encoding': cached.get('encoding'),
            'redirect_url': cached.get('redirect_url')
        }
    
    # 1. Fast resolution for local uploads (0 network delay)
    if '/uploads/' in url or url.startswith('uploads/'):
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
        parts = url.split('uploads/', 1)
        rel_path = parts[1].lstrip('/\\')
        full_path = os.path.join(upload_folder, rel_path)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            try:
                with open(full_path, 'rb') as f:
                    content = f.read()
                mime = 'image/png'
                if full_path.lower().endswith(('.jpg', '.jpeg')):
                    mime = 'image/jpeg'
                elif full_path.lower().endswith('.svg'):
                    mime = 'image/svg+xml'
                elif full_path.lower().endswith('.webp'):
                    mime = 'image/webp'
                res = {'string': content, 'mime_type': mime}
                _weasyprint_url_cache[url] = res
                return res
            except Exception as e:
                current_app.logger.warning(f"Error reading local file in url fetcher ({full_path}): {e}")

    # 2. Network URL with strict timeout using requests to prevent Gunicorn worker abort
    import requests
    try:
        r = requests.get(url, timeout=4, headers={'User-Agent': 'Mozilla/5.0 ProofDeck-PDF'})
        if r.status_code == 200:
            content_type = r.headers.get('Content-Type', 'application/octet-stream')
            res = {
                'string': r.content,
                'mime_type': content_type.split(';')[0].strip(),
                'encoding': r.encoding,
                'redirect_url': r.url
            }
            _weasyprint_url_cache[url] = res
            return res
        return {'string': b'', 'mime_type': 'text/plain'}
    except Exception as e:
        current_app.logger.warning(f"Failed to fetch external resource for WeasyPrint ({url}): {e}")
        return {'string': b'', 'mime_type': 'text/plain'}


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
    Decides whether to use Visual (Canvas), Document (A4 HTML), or Modular Certificate HTML templates.
    """
    if template.layout_style == 'visual':
        return _generate_visual_pdf(certificate, template, issuer)
    elif template.layout_style == 'document':
        return _generate_document_pdf(certificate, template, issuer)
    
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

    # Resolve uploaded signature image (enabled by default if issuer has uploaded one)
    use_uploaded_sig = extra.get('use_uploaded_signature', True)
    sig_url = getattr(issuer, 'signature_image_url', None) if issuer else None
    if not sig_url and getattr(certificate, 'tenant_id', None):
        try:
            from ..models import Tenant
            tenant = Tenant.query.get(certificate.tenant_id)
            if tenant and tenant.owner:
                sig_url = tenant.owner.signature_image_url
        except Exception:
            pass
    signature_image_base64 = get_image_as_base64(sig_url) if (use_uploaded_sig and sig_url) else None

    dynamic_data = {
        "{{recipient_name}}": certificate.recipient_name or "",
        "{{course_title}}": certificate.course_title or "",
        "{{issue_date}}": issue_date_str,
        "{{issuer_name}}": certificate.issuer_name or "",
        "{{verification_id}}": certificate.verification_id or "",
        "{{signature}}": certificate.signature or certificate.issuer_name or "",
        "{{amount}}": amount_text
    }
    
    # Extract per-certificate style overrides (font size, font family, color, offsets, autoFit)
    cert_styles = extra.get('cert_styles') if isinstance(extra.get('cert_styles'), dict) else {}
    auto_fit_enabled = cert_styles.get('autoFit', True) is not False
    field_style_overrides = cert_styles.get('fields') if isinstance(cert_styles.get('fields'), dict) else {}
    element_style_overrides = cert_styles.get('elements') if isinstance(cert_styles.get('elements'), dict) else {}

    # Merge any other extra fields into dynamic data (both as-is and formatted)
    for key, val in extra.items():
        if key in ('use_uploaded_signature', 'cert_styles'):
            continue
        dynamic_data[f"{{{{{key}}}}}"] = str(val) if val is not None else ""
        # Also support key with spaces if user entered key with underscores, or vice versa
        clean_key = key.replace('_', ' ')
        dynamic_data[f"{{{{{clean_key}}}}}"] = str(val) if val is not None else ""

    # Generate QR
    qr_base64 = _generate_qr_base64(certificate)
    dynamic_data["{{qr_code}}"] = f'<img src="data:image/png;base64,{qr_base64}" style="width: 100%; height: 100%;" />'

    html_elements = []
    if background.get('border'):
        b_color = background.get('borderColor', '#1e3a8a')
        b_accent = background.get('borderAccent', '#d97706')
        b_width = background.get('borderWidth', 4)
        html_elements.append(
            f'<div style="position: absolute; left: 20px; top: 20px; width: {page_width - 40}px; height: {page_height - 40}px; '
            f'border: {b_width}px solid {b_color}; box-sizing: border-box; pointer-events: none;"></div>'
        )
        html_elements.append(
            f'<div style="position: absolute; left: 28px; top: 28px; width: {page_width - 56}px; height: {page_height - 56}px; '
            f'border: 1.5px dashed {b_accent}; box-sizing: border-box; pointer-events: none;"></div>'
        )

    import math
    for idx, el in enumerate(elements):
        if el.get('visible') is False:
            continue

        raw_text_check = str(el.get('text') or '')
        matched_field_key = None
        placeholder_matches = re.findall(r'\{\{\s*([^}]+?)\s*\}\}', raw_text_check)
        if placeholder_matches:
            matched_field_key = placeholder_matches[0].strip().lower().replace(' ', '_')

        el_id_str = str(el.get('id')) if el.get('id') is not None else None
        field_ovr = (
            field_style_overrides.get(matched_field_key)
            or (field_style_overrides.get(placeholder_matches[0].strip()) if placeholder_matches else None)
            or {}
        ) if matched_field_key else {}
        el_ovr = (
            (element_style_overrides.get(el_id_str) if el_id_str else None)
            or element_style_overrides.get(str(idx))
            or {}
        )
        ovr = {**(field_ovr if isinstance(field_ovr, dict) else {}), **(el_ovr if isinstance(el_ovr, dict) else {})}

        try:
            offset_x = float(ovr.get('offsetX') or 0)
        except (ValueError, TypeError):
            offset_x = 0.0
        try:
            offset_y = float(ovr.get('offsetY') or 0)
        except (ValueError, TypeError):
            offset_y = 0.0

        el_x = float(el.get("x", 0) or 0) + offset_x
        el_y = float(el.get("y", 0) or 0) + offset_y
        el_w = float(ovr.get("width") or el.get("width", 200) or 200)
        el_h = float(el.get("height", 30) or 30)
        orig_w = float(el.get("width", 200) or 200)
        h_align = ovr.get('align') or el.get('align', 'left')
        if ovr.get("width") and h_align == 'center':
            el_x -= (el_w - orig_w) / 2.0

        style = (
            f'position: absolute; left: {el_x}px; top: {el_y}px; '
            f'width: {el_w}px; height: {el_h}px; '
            f'transform-origin: 0 0; transform: rotate({el.get("rotation", 0)}deg); '
        )
        content = ''
        el_type = el.get('type')

        is_qr = el.get('isQr', False) or el.get('type') == 'qr'
        if is_qr:
            content = dynamic_data.get("{{qr_code}}", "")
            style += "display: flex; align-items: center; justify-content: center;"
        elif el_type == 'text' or el_type == 'placeholder':
            raw_text = str(el.get('text') or '')
            is_pure_sig_placeholder = raw_text.strip().lower() == '{{signature}}'

            # Vertical and horizontal alignment
            v_align = el.get('verticalAlign', 'middle')
            if v_align == 'top':
                v_align_css = 'align-items: flex-start;'
            elif v_align == 'bottom':
                v_align_css = 'align-items: flex-end;'
            else:
                v_align_css = 'align-items: center;'

            if h_align == 'center':
                h_align_css = 'justify-content: center; text-align: center;'
            elif h_align == 'right':
                h_align_css = 'justify-content: flex-end; text-align: right;'
            else:
                h_align_css = 'justify-content: flex-start; text-align: left;'

            opacity = el.get('opacity', 1.0)

            if is_pure_sig_placeholder and signature_image_base64:
                style += f'opacity: {opacity}; display: flex; {v_align_css} {h_align_css}'
                content = f'<img src="data:image/png;base64,{signature_image_base64}" style="max-width: 100%; max-height: 100%; width: auto; height: auto; object-fit: contain; display: block;" alt="Signature" />'
            else:
                text = raw_text
                for placeholder, value in dynamic_data.items():
                    if placeholder.lower() in text.lower():
                        if placeholder.lower() == '{{signature}}' and signature_image_base64:
                            sig_inline = f'<img src="data:image/png;base64,{signature_image_base64}" style="max-height: {max(32, int(el_h))}px; width: auto; object-fit: contain; vertical-align: middle; display: inline-block;" alt="Signature" />'
                            pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
                            text = pattern.sub(lambda m, v=sig_inline: str(v), text)
                        else:
                            pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
                            text = pattern.sub(lambda m, v=value: str(v), text)

                font_style_val = str(ovr.get("fontStyle") or el.get("fontStyle", "normal"))
                font_weight = "bold" if "bold" in font_style_val else "normal"
                font_style = "italic" if "italic" in font_style_val else "normal"
                text_decor = el.get("textDecoration", "")
                decor_css = ""
                if "underline" in text_decor and "line-through" in text_decor:
                    decor_css = "text-decoration: underline line-through;"
                elif "underline" in text_decor:
                    decor_css = "text-decoration: underline;"
                elif "line-through" in text_decor:
                    decor_css = "text-decoration: line-through;"

                letter_spacing = float(el.get('letterSpacing', 0) or 0)
                line_height = float(el.get('lineHeight', 1.2) or 1.2)

                has_manual_font_size = ovr.get("fontSize") is not None and str(ovr.get("fontSize")).strip() != ""
                try:
                    base_font_size = float(ovr.get("fontSize") if has_manual_font_size else (el.get("fontSize", 16) or 16))
                except (ValueError, TypeError):
                    base_font_size = float(el.get("fontSize", 16) or 16)
                    has_manual_font_size = False

                font_size = base_font_size
                plain_text = re.sub(r'<[^>]+>', '', text).splitlines()
                lines = plain_text if plain_text else ['']
                max_line_chars = max((len(line) for line in lines), default=1)
                is_dynamic_el = (el_type == 'placeholder') or ('{{' in raw_text)
                is_single_line_box = (
                    is_dynamic_el
                    and len(lines) <= 1
                    and el_h < (float(el.get("fontSize", 16) or 16) * 2.2)
                    and ovr.get('wrap') is not True
                )

                # Deterministic auto-fit so long names/values never unexpectedly wrap or overflow placeholder boxes
                if is_dynamic_el and auto_fit_enabled and not has_manual_font_size and max_line_chars > 0:
                    flat_plain = " ".join(lines)
                    upper_ratio = sum(1 for c in flat_plain if c.isupper()) / max(len(flat_plain), 1)
                    char_factor = 0.64 if upper_ratio > 0.6 else (0.59 if font_weight == "bold" else 0.54)
                    est_line_width = max_line_chars * (base_font_size * char_factor + letter_spacing)
                    if is_single_line_box:
                        if est_line_width > el_w * 0.95:
                            avail_w = max(40.0, el_w * 0.95 - max_line_chars * letter_spacing)
                            fitted = avail_w / max(max_line_chars * char_factor, 1.0)
                            font_size = max(9.0, round(min(base_font_size, fitted), 1))
                    else:
                        est_lines = max(1, math.ceil(est_line_width / max(el_w * 0.92, 1.0))) * max(len(lines), 1)
                        if est_lines * base_font_size * line_height > el_h * 0.96:
                            fitted = (el_h * 0.96) / max(est_lines * line_height, 1.0)
                            font_size = max(9.0, round(min(base_font_size, fitted), 1))

                font_family_val = ovr.get("fontFamily") or el.get("fontFamily", "sans-serif") or "sans-serif"
                if "," not in font_family_val and not font_family_val.startswith("'") and not font_family_val.startswith('"'):
                    font_family_css = f"'{font_family_val}', sans-serif"
                else:
                    font_family_css = font_family_val

                fill_color = ovr.get("color") or ovr.get("fill") or el.get("fill", "#000")
                wrap_css = "white-space: nowrap;" if is_single_line_box else "word-wrap: break-word; overflow-wrap: break-word;"

                style += (
                    f'font-family: {font_family_css}; '
                    f'font-size: {font_size}px; '
                    f'color: {fill_color}; '
                    f'font-style: {font_style}; '
                    f'font-weight: {font_weight}; '
                    f'letter-spacing: {letter_spacing}px; '
                    f'line-height: {line_height}; '
                    f'opacity: {opacity}; '
                    f'{decor_css} '
                    f'{wrap_css} display: flex; '
                    f'{v_align_css} {h_align_css} '
                )
                    
                content = text.replace('\\n', '<br>').replace('\n', '<br>')

        elif el_type == 'rect':
            fill = el.get('fill', 'transparent')
            stroke = el.get('stroke', 'transparent')
            stroke_width = el.get('strokeWidth', 0)
            corner_radius = el.get('cornerRadius', 0)
            opacity = el.get('opacity', 1.0)
            dash = el.get('dash')
            border_style = 'dashed' if dash else 'solid'
            
            style += (
                f'background-color: {fill}; '
                f'border: {stroke_width}px {border_style} {stroke}; '
                f'border-radius: {corner_radius}px; '
                f'opacity: {opacity}; box-sizing: border-box;'
            )

        elif el_type == 'circle':
            fill = el.get('fill', 'transparent')
            stroke = el.get('stroke', 'transparent')
            stroke_width = el.get('strokeWidth', 0)
            opacity = el.get('opacity', 1.0)
            dash = el.get('dash')
            border_style = 'dashed' if dash else 'solid'
            
            style += (
                f'background-color: {fill}; '
                f'border: {stroke_width}px {border_style} {stroke}; '
                f'border-radius: 50%; '
                f'opacity: {opacity}; box-sizing: border-box;'
            )

        elif el_type == 'line':
            stroke = el.get('stroke', '#000000')
            stroke_width = max(1, el.get('strokeWidth', 2))
            dash = el.get('dash')
            border_style = 'dashed' if dash else 'solid'
            opacity = el.get('opacity', 1.0)
            
            style += (
                f'border-top: {stroke_width}px {border_style} {stroke}; '
                f'height: 0px; opacity: {opacity}; box-sizing: border-box;'
            )

        elif el_type == 'star':
            fill = el.get('fill', '#f59e0b')
            stroke = el.get('stroke', 'transparent')
            stroke_width = el.get('strokeWidth', 0)
            opacity = el.get('opacity', 1.0)
            w = el.get('width', 50)
            h = el.get('height', 50)
            
            content = f'''<svg width="{w}" height="{h}" viewBox="0 0 100 100" style="width: 100%; height: 100%; overflow: visible;">
                <polygon points="50,5 64,36 98,36 70,57 81,91 50,70 19,91 30,57 2,36 36,36"
                    fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" />
            </svg>'''
            style += f'opacity: {opacity};'

        elif el_type == 'badge':
            fill = el.get('fill', '#d97706')
            stroke = el.get('stroke', '#b45309')
            stroke_width = el.get('strokeWidth', 2)
            opacity = el.get('opacity', 1.0)
            w = el.get('width', 80)
            h = el.get('height', 100)
            
            content = f'''<svg width="{w}" height="{h}" viewBox="0 0 100 120" style="width: 100%; height: 100%;">
                <polygon points="25,70 15,115 38,100 50,115 50,70" fill="{stroke}" opacity="0.85" />
                <polygon points="75,70 85,115 62,100 50,115 50,70" fill="{stroke}" opacity="0.85" />
                <circle cx="50" cy="50" r="42" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" />
                <circle cx="50" cy="50" r="34" fill="none" stroke="#ffffff" stroke-width="1.5" stroke-dasharray="3,3" />
                <polygon points="50,26 56,38 70,38 58,47 63,60 50,52 37,60 42,47 30,38 44,38" fill="#ffffff" />
            </svg>'''
            style += f'opacity: {opacity};'

        elif el_type == 'border':
            stroke = el.get('stroke', '#1e3a8a')
            stroke_width = el.get('strokeWidth', 4)
            dash = el.get('dash')
            border_style = 'dashed' if dash else 'solid'
            corner_radius = el.get('cornerRadius', 0)
            opacity = el.get('opacity', 1.0)
            
            style += (
                f'border: {stroke_width}px {border_style} {stroke}; '
                f'border-radius: {corner_radius}px; pointer-events: none; '
                f'opacity: {opacity}; box-sizing: border-box;'
            )

        elif el_type == 'image':
            src = el.get('src')
            if src:
                if src.startswith('data:'):
                    content = f'<img src="{src}" style="width: 100%; height: 100%; object-fit: contain;">'
                else:
                    base64_img = get_image_as_base64(src)
                    if base64_img:
                        content = f'<img src="data:image/png;base64,{base64_img}" style="width: 100%; height: 100%; object-fit: contain;">'

        html_elements.append(f'<div style="{style}">{content}</div>')

    background_style = ''
    if background.get('gradient'):
        background_style += f'background: {background["gradient"]};'
    elif background.get('fill'):
        background_style += f'background-color: {background["fill"]};'
    else:
        background_style += 'background-color: #ffffff;'

    bg_image_path = background.get('image') or template.background_url
    if bg_image_path:
        if bg_image_path.startswith('data:'):
            background_style += f"background-image: url('{bg_image_path}'); background-size: cover; background-position: center;"
        else:
            base64_bg = get_image_as_base64(bg_image_path)
            if base64_bg:
                mime_type = "image/png"
                if bg_image_path.startswith("data:image/svg+xml") or bg_image_path.endswith(".svg"):
                    mime_type = "image/svg+xml"
                background_style += f"background-image: url('data:{mime_type};base64,{base64_bg}'); background-size: cover; background-position: center;"

    # Only load fonts that are actually used in this certificate's elements
    STANDARD_FONTS = {'arial', 'helvetica', 'georgia', 'times new roman', 'times', 'serif', 'sans-serif', 'monospace', 'courier', 'dejavu sans', 'dejavu serif'}
    used_fonts = set()
    for el in elements:
        fn = el.get('fontFamily')
        if fn and fn.strip().lower() not in STANDARD_FONTS:
            used_fonts.add(fn.strip())
    for ovr_dict in list(field_style_overrides.values()) + list(element_style_overrides.values()):
        if isinstance(ovr_dict, dict):
            fn = ovr_dict.get('fontFamily')
            if fn and str(fn).strip().lower() not in STANDARD_FONTS:
                used_fonts.add(str(fn).strip())

    font_links = []
    google_families = [f"family={f.replace(' ', '+')}:wght@400;700" for f in sorted(used_fonts) if f.lower() != 'product sans']
    if google_families:
        font_links.append(f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{"&".join(google_families)}&display=swap">')

    product_sans_css = ""
    if 'product sans' in [f.lower() for f in used_fonts]:
        product_sans_css = """
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
        """

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        {''.join(font_links)}
        <style>
            @page {{ size: {page_width}px {page_height}px; margin: 0; }}
            body {{ margin: 0; padding: 0; font-family: sans-serif; }}
            .certificate-container {{
                width: {page_width}px; height: {page_height}px;
                position: relative; overflow: hidden;
                {background_style}
            }}
            {product_sans_css}
        </style>
    </head>
    <body>
        <div class="certificate-container">{''.join(html_elements)}</div>
    </body>
    </html>
    """
    return _render_pdf_bytes(html_template)

def _generate_html_pdf(certificate, template, issuer):
    qr_base64 = _generate_qr_base64(certificate)
    logo_base64 = get_image_as_base64(template.logo_url)
    background_base64 = get_image_as_base64(template.background_url)
    # Handle amount logic for receipts & uploaded signature preference
    extra = certificate.extra_fields or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    elif not isinstance(extra, dict):
        extra = {}

    use_uploaded_sig = extra.get('use_uploaded_signature', True)
    sig_url = getattr(issuer, 'signature_image_url', None) if issuer else None
    if not sig_url and getattr(certificate, 'tenant_id', None):
        try:
            from ..models import Tenant
            tenant = Tenant.query.get(certificate.tenant_id)
            if tenant and tenant.owner:
                sig_url = tenant.owner.signature_image_url
        except Exception:
            pass

    signature_image_base64 = None
    if use_uploaded_sig and sig_url:
        signature_image_base64 = get_image_as_base64(sig_url)

    amount = extra.get('amount')
    display_extra = {k: v for k, v in extra.items() if k not in ('use_uploaded_signature', 'cert_styles')}
    cert_styles = extra.get('cert_styles') if isinstance(extra.get('cert_styles'), dict) else {}
    auto_fit_enabled = cert_styles.get('autoFit', True) is not False
    field_style_overrides = cert_styles.get('fields') if isinstance(cert_styles.get('fields'), dict) else {}
    
    # If no amount in extra_fields, try parsing from course title if it looks like currency
    if not amount and certificate.course_title:
        import re
        match = re.search(r'[$₦]\s?[\d,]+(\.\d{2})?', certificate.course_title)
        amount = match.group(0) if match else "PAID"

    raw_custom_text = template.custom_text or {}
    if isinstance(raw_custom_text, str):
        try:
            raw_custom_text = json.loads(raw_custom_text)
        except Exception:
            raw_custom_text = {}
    elif not isinstance(raw_custom_text, dict):
        raw_custom_text = {}
    # Filter out empty strings so .get('title', 'Default') falls back properly
    clean_custom_text = {k: v for k, v in raw_custom_text.items() if v is not None and str(v).strip() != ""}

    primary_color = template.primary_color or "#0284C7"
    secondary_color = template.secondary_color or "#E2E8F0"
    body_font_color = template.body_font_color or "#1E293B"

    context = {
        "recipient_name": certificate.recipient_name or "Recipient Name",
        "recipient_email": certificate.recipient_email or "recipient@example.com",
        "course_title": certificate.course_title or "Course Title",
        "issue_date": certificate.issue_date.strftime('%B %d, %Y') if hasattr(certificate.issue_date, 'strftime') else str(certificate.issue_date),
        "signature": certificate.signature or certificate.issuer_name or "Authorized",
        "issuer_name": certificate.issuer_name or "Issuer Name",
        "verification_id": certificate.verification_id or "PENDING",
        "frontend_url": (current_app.config.get('FRONTEND_URL') or "proofdeck.app").replace('https://', '').replace('http://', ''),
        "logo_base64": logo_base64,
        "background_base64": background_base64,
        "primary_color": primary_color,
        "primary_color_alpha": f"{primary_color}22",
        "secondary_color": secondary_color,
        "body_font_color": body_font_color,
        "font_family": {
            "Georgia": "'Merriweather', Georgia, serif",
            "Times New Roman": "'Playfair Display', 'Times New Roman', serif",
            "Arial": "'Open Sans', Arial, sans-serif",
            "Verdana": "'Lato', Verdana, sans-serif",
            "Lato": "'Lato', sans-serif",
            "Roboto": "'Roboto', sans-serif"
        }.get(template.font_family, template.font_family or "'Lato', sans-serif"),
        "qr_base64": qr_base64,
        "custom_text": clean_custom_text,
        "signature_image_base64": signature_image_base64,
        "extra_fields": display_extra,
        "amount": amount
    }
    
    # Process layout_data for styles
    layout_data = template.layout_data or {}
    if isinstance(layout_data, str):
        try:
            layout_data = json.loads(layout_data)
        except Exception:
            layout_data = {}
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

        # Build per-certificate style overrides & auto-fit rules for preset HTML templates
        override_css_rules = []
        rec_ovr = field_style_overrides.get('recipient_name') if isinstance(field_style_overrides.get('recipient_name'), dict) else {}
        rec_name_str = str(context.get('recipient_name') or '')
        if auto_fit_enabled and not rec_ovr.get('fontSize') and len(rec_name_str) > 22:
            fitted_rec_size = max(20.0, round(42.0 * (22.0 / len(rec_name_str)), 1))
            override_css_rules.append(f"h2, .recipient {{ font-size: {fitted_rec_size}px !important; white-space: nowrap !important; }}")

        selector_map = {
            'recipient_name': 'h2, .recipient',
            'course_title': '.course, .course-title, p strong, p > span',
            'title': 'h1, .title',
            'signature': '.font-signature, .sig-text, .footer-bold',
            'issuer_name': '.issuer-name',
            'issue_date': '.date-line',
        }
        for f_key, css_sel in selector_map.items():
            f_ovr = field_style_overrides.get(f_key)
            if not isinstance(f_ovr, dict):
                continue
            props = []
            if f_ovr.get('fontSize'):
                props.append(f"font-size: {float(f_ovr['fontSize'])}px !important;")
                if f_key == 'recipient_name' and f_ovr.get('wrap') is not True:
                    props.append("white-space: nowrap !important;")
            if f_ovr.get('fontFamily'):
                ff = str(f_ovr['fontFamily']).strip()
                props.append(f"font-family: '{ff}', sans-serif !important;")
            if f_ovr.get('color') or f_ovr.get('fill'):
                clr = f_ovr.get('color') or f_ovr.get('fill')
                props.append(f"color: {clr} !important;")
            ox = float(f_ovr.get('offsetX') or 0)
            oy = float(f_ovr.get('offsetY') or 0)
            if ox != 0 or oy != 0:
                props.append(f"transform: translate({ox}px, {oy}px) !important;")
            if props:
                override_css_rules.append(f"{css_sel} {{ {' '.join(props)} }}")

        extra_override_css = "\n            ".join(override_css_rules)

        # Inject Google Fonts & Product Sans font-face definition globally
        font_inject = f"""
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700;900&family=Great+Vibes&family=JetBrains+Mono:wght@400;700&family=Lato:ital,wght@0,300;0,400;0,700;0,900;1,400&family=Merriweather:ital,wght@0,300;0,400;0,700;0,900;1,400&family=Montserrat:wght@300;400;600;700;800;900&family=Open+Sans:ital,wght@0,400;0,600;0,700;0,800;1,400&family=Playfair+Display:ital,wght@0,400;0,600;0,700;0,800;1,400&family=Roboto:wght@300;400;500;700;900&display=swap">
        <style>
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
            .font-script, .font-signature {{
              font-family: 'Great Vibes', cursive, serif;
            }}
            {extra_override_css}
        </style>
        """
        if "</head>" in html_content:
            html_content = html_content.replace("</head>", f"{font_inject}</head>")
            
        return _render_pdf_bytes(html_content)
    except Exception as e:
        current_app.logger.error(f"Error rendering file template: {e}")
        raise e

def _get_certificate_verification_url(certificate_or_id):
    from ..utils.helpers import get_certificate_verification_url
    return get_certificate_verification_url(certificate_or_id)

def _generate_qr_base64(certificate_or_id):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    verification_url = _get_certificate_verification_url(certificate_or_id)
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

def _generate_document_pdf(certificate, template, issuer):
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

    doc_html = layout_data.get('document_html') or layout_data.get('content') or ''
    if not doc_html:
        doc_html = f"<h1>{template.title}</h1><p>Recipient: {certificate.recipient_name}</p>"

    # Prepare merge variables
    extra = certificate.extra_fields or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    elif not isinstance(extra, dict):
        extra = {}

    issue_date_str = ""
    if certificate.issue_date:
        if hasattr(certificate.issue_date, 'strftime'):
            issue_date_str = certificate.issue_date.strftime('%B %d, %Y')
        else:
            issue_date_str = str(certificate.issue_date)

    signatory_name = (
        extra.get('signatory_name') or
        certificate.issuer_name or
        getattr(issuer, 'name', '') or
        "Authorized Signatory"
    )
    signatory_title = (
        extra.get('signatory_title') or
        "Registrar & Secretary to Council"
    )

    qr_base64 = _generate_qr_base64(certificate)
    verification_url = _get_certificate_verification_url(certificate)

    vars_dict = {
        "{{recipient_name}}": certificate.recipient_name or "",
        "{{student_id}}": str(extra.get("student_id") or extra.get("matric_number") or extra.get("matric_no") or ""),
        "{{recipient_email}}": certificate.recipient_email or "",
        "{{course_title}}": certificate.course_title or "",
        "{{faculty}}": str(extra.get("faculty") or extra.get("school") or "Faculty of Science & Technology"),
        "{{department}}": str(extra.get("department") or extra.get("programme") or "Computer Science"),
        "{{grade_or_honours}}": str(extra.get("grade_or_honours") or extra.get("degree_class") or "First Class Honours"),
        "{{cgpa}}": str(extra.get("cgpa") or "4.75 / 5.00"),
        "{{issue_date}}": issue_date_str,
        "{{approval_date}}": str(extra.get("approval_date") or issue_date_str),
        "{{ref_number}}": str(extra.get("ref_number") or f"AIT/REG/{certificate.verification_id[:8].upper()}"),
        "{{signatory_name}}": signatory_name,
        "{{signatory_title}}": signatory_title,
    }

    # Substitute into HTML
    processed_html = doc_html
    def replace_chip(match):
        var_tag = match.group(1)
        for k, v in vars_dict.items():
            if k.lower() == var_tag.lower():
                return v
        return var_tag

    processed_html = re.sub(
        r'<span[^>]*class=["\'][^"\']*pd-chip[^"\']*["\'][^>]*data-var=["\']([^"\']+)["\'][^>]*>.*?</span>',
        replace_chip,
        processed_html,
        flags=re.DOTALL | re.IGNORECASE
    )

    for k, v in vars_dict.items():
        pattern = re.compile(re.escape(k), re.IGNORECASE)
        processed_html = pattern.sub(str(v), processed_html)

    qr_enabled = layout_data.get('qr_code_enabled', True)
    qr_position = layout_data.get('qr_position', 'bottom-right')

    qr_block = ""
    if qr_enabled:
        qr_float = "float: right; margin-left: 16px;" if qr_position == 'bottom-right' else "float: left; margin-right: 16px;"
        qr_block = f"""
        <div style="{qr_float} margin-top: 24px; text-align: center; border: 1.5px solid #E2E8F0; border-radius: 8px; padding: 8px; background: #F8FAFC;">
            <img src="data:image/png;base64,{qr_base64}" style="width: 76px; height: 76px; display: block;" alt="Verification QR" />
            <div style="font-size: 7pt; font-family: sans-serif; font-weight: 700; color: #475569; margin-top: 4px;">VERIFIED VAULT</div>
            <div style="font-size: 6pt; font-family: monospace; color: #94A3B8;">{certificate.verification_id[:8].upper()}</div>
        </div>
        """

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4 portrait;
        margin: 20mm 18mm 20mm 18mm;
        @bottom-left {{
            content: "Official Academic Document — Tamper-Proof Verification: {verification_url}";
            font-size: 6.5pt;
            font-family: sans-serif;
            color: #94a3b8;
        }}
        @bottom-right {{
            content: "Page " counter(page) " of " counter(pages);
            font-size: 7.5pt;
            font-family: sans-serif;
            color: #94a3b8;
        }}
    }}
    body {{
        font-family: 'Times New Roman', 'Playfair Display', Georgia, serif;
        font-size: 11pt;
        line-height: 1.6;
        color: #111827;
        margin: 0;
        padding: 0;
    }}
    p {{
        margin: 0 0 12pt 0;
    }}
    .pd-document-container {{
        width: 100%;
        position: relative;
    }}
    .pd-page-break {{
        page-break-after: always !important;
        break-after: page !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        visibility: hidden !important;
    }}
</style>
</head>
<body>
    <div class="pd-document-container">
        {processed_html}
        {qr_block}
        <div style="clear: both;"></div>
    </div>
</body>
</html>"""

    return _render_pdf_bytes(full_html)

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