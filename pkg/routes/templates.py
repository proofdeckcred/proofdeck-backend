import os
import base64
import uuid
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from ..models import db, Template, Certificate, User
from ..utils.helpers import get_active_context
import json
from sqlalchemy.orm.attributes import flag_modified

template_bp = Blueprint('templates', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_and_save_base64_images(layout_data, user_id):
    """
    Extracts base64 data URLs from elements and background, saves them as real files in uploads/,
    and replaces them with lightweight /uploads/... paths to prevent MySQL packet limits and payload bloating.
    """
    if not isinstance(layout_data, dict):
        return layout_data

    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    if not upload_folder:
        return layout_data

    os.makedirs(upload_folder, exist_ok=True)

    # 1. Check background image
    bg = layout_data.get('background')
    if isinstance(bg, dict):
        bg_img = bg.get('image')
        if bg_img and isinstance(bg_img, str) and bg_img.startswith('data:image/'):
            try:
                header, encoded = bg_img.split(';base64,', 1)
                ext = 'png'
                if 'jpeg' in header or 'jpg' in header:
                    ext = 'jpg'
                elif 'webp' in header:
                    ext = 'webp'
                filename = secure_filename(f"{user_id}_bg_{uuid.uuid4().hex[:8]}.{ext}")
                filepath = os.path.join(upload_folder, filename)
                with open(filepath, 'wb') as f:
                    f.write(base64.b64decode(encoded))
                layout_data['background']['image'] = f"/uploads/{filename}"
            except Exception as e:
                current_app.logger.warning(f"Could not save base64 background: {e}")

    # 2. Check elements
    elements = layout_data.get('elements', [])
    for el in elements:
        src = el.get('src')
        if src and isinstance(src, str) and src.startswith('data:image/'):
            try:
                header, encoded = src.split(';base64,', 1)
                ext = 'png'
                if 'jpeg' in header or 'jpg' in header:
                    ext = 'jpg'
                elif 'webp' in header:
                    ext = 'webp'
                filename = secure_filename(f"{user_id}_asset_{uuid.uuid4().hex[:8]}.{ext}")
                filepath = os.path.join(upload_folder, filename)
                with open(filepath, 'wb') as f:
                    f.write(base64.b64decode(encoded))
                el['src'] = f"/uploads/{filename}"
            except Exception as e:
                current_app.logger.warning(f"Could not save base64 element asset: {e}")

    return layout_data

@template_bp.route('/upload-custom', methods=['POST'])
@jwt_required()
def create_custom_template():
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    
    if 'title' not in request.form or not request.form.get('title').strip():
        return jsonify({"msg": "Missing template title."}), 400
    if 'layout_data' not in request.form:
        return jsonify({"msg": "Missing template layout data."}), 400

    title = request.form.get('title')
    layout_data_str = request.form.get('layout_data')
    
    try:
        layout_data = json.loads(layout_data_str)
    except json.JSONDecodeError:
        return jsonify({"msg": "Invalid layout data format."}), 400

    layout_data = extract_and_save_base64_images(layout_data, user_id)

    background_url = None

    if 'template_image' in request.files:
        file = request.files['template_image']
        if file and allowed_file(file.filename):
            upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
            os.makedirs(upload_folder, exist_ok=True)
            filename = secure_filename(f"{user_id}_custom_{file.filename}")
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            background_url = f"/uploads/{filename}"
            if 'background' not in layout_data:
                layout_data['background'] = {}
            layout_data['background']['image'] = background_url
        else:
            return jsonify({"msg": "Invalid file type. Please use PNG or JPG."}), 400
    else:
        # Check if layout_data has a background image (preset or uploaded data URL or path)
        background_img = layout_data.get('background', {}).get('image')
        if background_img:
            background_url = background_img
        else:
            # Blank canvas or color-based template from scratch
            background_url = None
    
    is_comp, tenant_id, _, _ = get_active_context(user)
    new_template = Template(
        user_id=user_id,
        tenant_id=tenant_id if is_comp else None,
        title=title,
        background_url=background_url,
        layout_style='visual',
        layout_data=layout_data,
        is_public=False
    )
    db.session.add(new_template)
    db.session.commit()
    
    return jsonify({"msg": "Template created successfully", "template_id": new_template.id}), 201

@template_bp.route('/upload-custom/<int:template_id>', methods=['PUT'])
@jwt_required()
def update_custom_template(template_id):
    user_id = int(get_jwt_identity())
    template = Template.query.get_or_404(template_id)
    user = User.query.get(user_id)

    if template.is_public or template.layout_style != 'visual':
        return jsonify({"msg": "Permission denied"}), 403

    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        if template.tenant_id != tenant_id:
            return jsonify({"msg": "Permission denied"}), 403
    else:
        if template.user_id != user_id or template.tenant_id is not None:
            return jsonify({"msg": "Permission denied"}), 403

    title = request.form.get('title', '').strip()
    if title:
        template.title = title
    
    layout_data = {}
    if 'layout_data' in request.form:
        try:
            layout_data = json.loads(request.form.get('layout_data'))
        except json.JSONDecodeError:
            return jsonify({"msg": "Invalid layout data format."}), 400
        layout_data = extract_and_save_base64_images(layout_data, user_id)

    if 'template_image' in request.files:
        file = request.files['template_image']
        if file and allowed_file(file.filename):
            upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
            os.makedirs(upload_folder, exist_ok=True)
            filename = secure_filename(f"{user_id}_custom_{template.id}_{file.filename}")
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            
            background_url = f"/uploads/{filename}"
            template.background_url = background_url
            
            if 'background' not in layout_data:
                layout_data['background'] = {}
            layout_data['background']['image'] = background_url
    else:
        # Preserve existing background image if not explicitly provided in layout_data
        bg_image = layout_data.get('background', {}).get('image')
        if not bg_image and template.background_url:
            if 'background' not in layout_data:
                layout_data['background'] = {}
            layout_data['background']['image'] = template.background_url
        elif bg_image:
            template.background_url = bg_image
            
    template.layout_data = layout_data
    flag_modified(template, "layout_data")

    db.session.commit()
    return jsonify({"msg": "Template updated successfully", "template_id": template.id}), 200


@template_bp.route('/', methods=['POST'])
@jwt_required(locations=["headers"])
def create_template():
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    if 'title' not in request.form:
        return jsonify({"msg": "Missing title part"}), 400

    data = request.form
    
    custom_text_data = {
        "title": data.get('custom_title', 'Certificate of Completion'),
        "body": data.get('custom_body', 'has successfully completed the course')
    }

    logo_url, background_url = None, None
    if 'logo' in request.files:
        logo_file = request.files['logo']
        if logo_file and allowed_file(logo_file.filename):
            filename = secure_filename(f"{user_id}_logo_{logo_file.filename}")
            logo_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            logo_url = f"/uploads/{filename}"

    if 'background' in request.files:
        bg_file = request.files['background']
        if bg_file and allowed_file(bg_file.filename):
            filename = secure_filename(f"{user_id}_bg_{bg_file.filename}")
            bg_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            background_url = f"/uploads/{filename}"

    is_comp, tenant_id, _, _ = get_active_context(user)
    new_template = Template(
        user_id=user_id,
        tenant_id=tenant_id if is_comp else None,
        title=data.get('title'),
        logo_url=logo_url,
        background_url=background_url,
        primary_color=data.get('primary_color', '#2563EB'),
        secondary_color=data.get('secondary_color', '#64748B'),
        body_font_color=data.get('body_font_color', '#333333'),
        font_family=data.get('font_family', 'Georgia'),
        layout_style=data.get('layout_style', 'modern'),
        custom_text=custom_text_data
    )
    db.session.add(new_template)
    db.session.commit()
    return jsonify({"msg": "Template created successfully", "template_id": new_template.id}), 201

@template_bp.route('/', methods=['GET'])
@jwt_required(locations=["headers"])
def get_user_templates():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        templates = Template.query.filter(
            (Template.tenant_id == tenant_id) | (Template.is_public == True)
        ).order_by(Template.is_public.asc(), Template.created_at.desc()).all()
    else:
        templates = Template.query.filter(
            ((Template.user_id == user_id) & (Template.tenant_id == None)) | (Template.is_public == True)
        ).order_by(Template.is_public.asc(), Template.created_at.desc()).all()

    templates_data = []
    for t in templates:
        ld = t.layout_data
        if isinstance(ld, str):
            try: ld = json.loads(ld)
            except Exception: pass
        templates_data.append({
            'id': t.id,
            'title': t.title,
            'logo_url': t.logo_url,
            'background_url': t.background_url,
            'primary_color': t.primary_color,
            'secondary_color': t.secondary_color,
            'body_font_color': t.body_font_color,
            'font_family': t.font_family,
            'layout_style': t.layout_style,
            'layout_data': ld,
            'is_public': t.is_public,
            'custom_text': t.custom_text
        })
    
    return jsonify({"templates": templates_data}), 200


@template_bp.route('/<int:template_id>', methods=['GET'])
@jwt_required(locations=["headers"])
def get_template(template_id):
    user_id = int(get_jwt_identity())
    template = Template.query.get_or_404(template_id)
    user = User.query.get(user_id)
    
    if not template.is_public:
        is_comp, tenant_id, _, _ = get_active_context(user)
        if is_comp:
            if template.tenant_id != tenant_id:
                return jsonify({"msg": "Permission denied"}), 403
        else:
            if template.user_id != user_id or template.tenant_id is not None:
                return jsonify({"msg": "Permission denied"}), 403

    ld = template.layout_data
    if isinstance(ld, str):
        try: ld = json.loads(ld)
        except Exception: pass

    return jsonify({
        'id': template.id,
        'title': template.title,
        'logo_url': template.logo_url,
        'background_url': template.background_url,
        'primary_color': template.primary_color,
        'secondary_color': template.secondary_color,
        'body_font_color': template.body_font_color,
        'font_family': template.font_family,
        'layout_style': template.layout_style,
        'layout_data': ld,
        'is_public': template.is_public,
        'custom_text': template.custom_text
    }), 200


@template_bp.route('/<int:template_id>', methods=['PUT'])
@jwt_required(locations=["headers"])
def update_template(template_id):
    user_id = int(get_jwt_identity())
    template = Template.query.get_or_404(template_id)
    user = User.query.get(user_id)
    
    if template.is_public:
        return jsonify({"msg": "Permission denied"}), 403
        
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        if template.tenant_id != tenant_id:
            return jsonify({"msg": "Permission denied"}), 403
    else:
        if template.user_id != user_id or template.tenant_id is not None:
            return jsonify({"msg": "Permission denied"}), 403

    data = request.form
    
    if 'title' in data: template.title = data.get('title')
    if 'primary_color' in data: template.primary_color = data.get('primary_color')
    if 'secondary_color' in data: template.secondary_color = data.get('secondary_color')
    if 'body_font_color' in data: template.body_font_color = data.get('body_font_color')
    if 'font_family' in data: template.font_family = data.get('font_family')
    if 'layout_style' in data: template.layout_style = data.get('layout_style')

    custom_text_data = template.custom_text or {}
    if 'custom_title' in data: custom_text_data['title'] = data.get('custom_title')
    if 'custom_body' in data: custom_text_data['body'] = data.get('custom_body')
    template.custom_text = custom_text_data

    if 'logo' in request.files:
        logo_file = request.files['logo']
        if logo_file and allowed_file(logo_file.filename):
            filename = secure_filename(f"{user_id}_logo_{logo_file.filename}")
            logo_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            template.logo_url = f"/uploads/{filename}"

    if 'background' in request.files:
        bg_file = request.files['background']
        if bg_file and allowed_file(bg_file.filename):
            filename = secure_filename(f"{user_id}_bg_{bg_file.filename}")
            bg_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            template.background_url = f"/uploads/{filename}"

    db.session.commit()
    return jsonify({"msg": "Template updated successfully"}), 200
    
@template_bp.route('/<int:template_id>', methods=['DELETE'])
@jwt_required(locations=["headers"])
def delete_template(template_id):
    user_id = int(get_jwt_identity())
    template = Template.query.get_or_404(template_id)
    user = User.query.get(user_id)

    if template.is_public:
        return jsonify({"msg": "Permission denied"}), 403
        
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        if template.tenant_id != tenant_id:
            return jsonify({"msg": "Permission denied"}), 403
    else:
        if template.user_id != user_id or template.tenant_id is not None:
            return jsonify({"msg": "Permission denied"}), 403

    if Certificate.query.filter_by(template_id=template.id).first():
        return jsonify({"msg": "Cannot delete template as it is currently in use by one or more certificates."}), 409

    db.session.delete(template)
    db.session.commit()
    return jsonify({"msg": "Template deleted successfully"}), 200