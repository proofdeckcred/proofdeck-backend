import os
import re
import uuid
import requests
from werkzeug.utils import secure_filename
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, current_user
from datetime import datetime
from ..models import BlogPost, Admin, db
from sqlalchemy import or_

admin_blog_bp = Blueprint('admin_blog', __name__)

@admin_blog_bp.route('/blog/upload-image', methods=['POST'])
@jwt_required()
def upload_blog_image():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    if 'image' not in request.files:
        return jsonify({"msg": "No image provided"}), 400

    file = request.files['image']
    if not file or file.filename == '':
        return jsonify({"msg": "Empty file uploaded"}), 400

    allowed_exts = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_exts:
        return jsonify({"msg": f"Allowed formats: {', '.join(allowed_exts)}"}), 400

    filename = f"blog_{uuid.uuid4().hex[:12]}.{ext}"
    upload_path = current_app.config.get('UPLOAD_FOLDER')
    if not upload_path:
        upload_path = os.path.abspath(os.path.join(current_app.root_path, '..', 'uploads'))
    os.makedirs(upload_path, exist_ok=True)
    file.save(os.path.join(upload_path, filename))

    base_url = request.host_url.rstrip('/')
    image_url = f"{base_url}/uploads/{filename}"

    return jsonify({
        "imageUrl": image_url,
        "url": image_url,
        "filename": filename
    }), 201

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

def calculate_read_time(content):
    words = len(re.findall(r'\w+', content or ''))
    minutes = max(1, round(words / 200))
    return minutes

def trigger_nextjs_revalidation(slug=None):
    """
    Calls Next.js on-demand revalidation webhook.
    """
    nextjs_url = os.environ.get('NEXTJS_BLOG_URL', 'http://localhost:3000')
    secret = os.environ.get('REVALIDATION_SECRET', 'proofdeck-revalidate-secret-key-2026')

    try:
        url = f"{nextjs_url.rstrip('/')}/api/revalidate"
        params = {"secret": secret}
        if slug:
            params["slug"] = slug
        resp = requests.post(url, params=params, timeout=5)
        current_app.logger.info(f"Next.js revalidate response ({resp.status_code}): {resp.text}")
        return True
    except Exception as e:
        current_app.logger.warning(f"Could not trigger Next.js revalidate webhook: {e}")
        return False

@admin_blog_bp.route('/blog/posts', methods=['GET'])
@jwt_required()
def list_admin_posts():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 15, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status') # 'published', 'draft', or 'all'

    query = BlogPost.query

    if status == 'published':
        query = query.filter_by(is_published=True)
    elif status == 'draft':
        query = query.filter_by(is_published=False)

    if search:
        query = query.filter(
            or_(
                BlogPost.title.ilike(f"%{search}%"),
                BlogPost.slug.ilike(f"%{search}%"),
                BlogPost.category.ilike(f"%{search}%")
            )
        )

    query = query.order_by(BlogPost.created_at.desc())
    pagination = query.paginate(page=page, per_page=limit, error_out=False)

    return jsonify({
        "posts": [p.to_dict(include_content=False) for p in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages
    }), 200

@admin_blog_bp.route('/blog/posts/<int:post_id>', methods=['GET'])
@jwt_required()
def get_admin_post(post_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    post = BlogPost.query.get(post_id)
    if not post:
        return jsonify({"msg": "Article not found"}), 404

    return jsonify(post.to_dict(include_content=True)), 200

@admin_blog_bp.route('/blog/posts', methods=['POST'])
@jwt_required()
def create_admin_post():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    data = request.get_json() or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({"msg": "Title is required"}), 400

    content = data.get('content', '').strip()
    if not content:
        return jsonify({"msg": "Content is required"}), 400

    slug = data.get('slug', '').strip()
    if not slug:
        slug = slugify(title)

    # Ensure unique slug
    base_slug = slug
    counter = 1
    while BlogPost.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    is_published = bool(data.get('is_published', False))
    published_at = datetime.utcnow() if is_published else None

    post = BlogPost(
        title=title,
        slug=slug,
        excerpt=data.get('excerpt', ''),
        content=content,
        featured_image=data.get('featured_image'),
        author_name=data.get('author_name', current_user.name or 'ProofDeck Team'),
        author_role=data.get('author_role', 'Credential Specialists'),
        author_avatar=data.get('author_avatar'),
        category=data.get('category', 'Guides'),
        tags=data.get('tags', []),
        meta_title=data.get('meta_title') or title,
        meta_description=data.get('meta_description') or data.get('excerpt', ''),
        canonical_url=data.get('canonical_url'),
        is_published=is_published,
        published_at=published_at,
        read_time_minutes=calculate_read_time(content)
    )

    db.session.add(post)
    db.session.commit()

    if is_published:
        trigger_nextjs_revalidation(slug)

    return jsonify({
        "msg": "Article created successfully",
        "post": post.to_dict(include_content=True)
    }), 201

@admin_blog_bp.route('/blog/posts/<int:post_id>', methods=['PUT'])
@jwt_required()
def update_admin_post(post_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    post = BlogPost.query.get(post_id)
    if not post:
        return jsonify({"msg": "Article not found"}), 404

    data = request.get_json() or {}

    if 'title' in data and data['title']:
        post.title = data['title'].strip()
    if 'content' in data:
        post.content = data['content']
        post.read_time_minutes = calculate_read_time(data['content'])
    if 'excerpt' in data:
        post.excerpt = data['excerpt']
    if 'featured_image' in data:
        post.featured_image = data['featured_image']
    if 'author_name' in data:
        post.author_name = data['author_name']
    if 'author_role' in data:
        post.author_role = data['author_role']
    if 'author_avatar' in data:
        post.author_avatar = data['author_avatar']
    if 'category' in data:
        post.category = data['category']
    if 'tags' in data:
        post.tags = data['tags']
    if 'meta_title' in data:
        post.meta_title = data['meta_title']
    if 'meta_description' in data:
        post.meta_description = data['meta_description']
    if 'canonical_url' in data:
        post.canonical_url = data['canonical_url']

    old_slug = post.slug
    if 'slug' in data and data['slug'].strip() and data['slug'].strip() != post.slug:
        new_slug = slugify(data['slug'])
        existing = BlogPost.query.filter_by(slug=new_slug).first()
        if existing and existing.id != post.id:
            return jsonify({"msg": "Slug is already in use by another article"}), 400
        post.slug = new_slug

    if 'is_published' in data:
        new_published = bool(data['is_published'])
        if new_published and not post.is_published:
            post.published_at = datetime.utcnow()
        post.is_published = new_published

    post.updated_at = datetime.utcnow()
    db.session.commit()

    # Revalidate old slug and new slug on Next.js
    trigger_nextjs_revalidation(old_slug)
    if post.slug != old_slug:
        trigger_nextjs_revalidation(post.slug)

    return jsonify({
        "msg": "Article updated successfully",
        "post": post.to_dict(include_content=True)
    }), 200

@admin_blog_bp.route('/blog/posts/<int:post_id>', methods=['DELETE'])
@jwt_required()
def delete_admin_post(post_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    post = BlogPost.query.get(post_id)
    if not post:
        return jsonify({"msg": "Article not found"}), 404

    slug = post.slug
    db.session.delete(post)
    db.session.commit()

    trigger_nextjs_revalidation(slug)

    return jsonify({"msg": "Article deleted successfully"}), 200
