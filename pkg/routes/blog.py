from flask import Blueprint, jsonify, request
from datetime import datetime
from ..models import BlogPost, db
from sqlalchemy import or_

blog_bp = Blueprint('blog', __name__)

@blog_bp.route('/posts', methods=['GET'])
def get_published_posts():
    """
    Fetches paginated list of published blog posts.
    """
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 12, type=int)
    category = request.args.get('category')
    search = request.args.get('search', '').strip()

    query = BlogPost.query.filter_by(is_published=True)

    if category and category.lower() != 'all':
        query = query.filter(BlogPost.category.ilike(f"%{category}%"))

    if search:
        query = query.filter(
            or_(
                BlogPost.title.ilike(f"%{search}%"),
                BlogPost.excerpt.ilike(f"%{search}%")
            )
        )

    # Order by published_at descending
    query = query.order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc())

    pagination = query.paginate(page=page, per_page=limit, error_out=False)

    return jsonify({
        "posts": [p.to_dict(include_content=False) for p in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev
    }), 200

@blog_bp.route('/posts/<slug>', methods=['GET'])
def get_post_by_slug(slug):
    """
    Fetches a single published post with full content.
    """
    post = BlogPost.query.filter_by(slug=slug, is_published=True).first()
    if not post:
        return jsonify({"msg": "Article not found"}), 404

    # Increment view count
    try:
        post.view_count = (post.view_count or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(post.to_dict(include_content=True)), 200

@blog_bp.route('/slugs', methods=['GET'])
def get_all_slugs():
    """
    Lightweight endpoint returning all published slugs and last modified timestamps.
    Used by Next.js generateStaticParams and dynamic sitemap.xml.
    """
    posts = BlogPost.query.filter_by(is_published=True).with_entities(
        BlogPost.slug, BlogPost.updated_at, BlogPost.published_at
    ).all()

    return jsonify([
        {
            "slug": p.slug,
            "updated_at": (p.updated_at or p.published_at or datetime.utcnow()).isoformat()
        }
        for p in posts
    ]), 200

@blog_bp.route('/categories', methods=['GET'])
def get_categories():
    """
    Returns list of categories with published post counts.
    """
    categories = db.session.query(
        BlogPost.category, db.func.count(BlogPost.id)
    ).filter_by(is_published=True).group_by(BlogPost.category).all()

    return jsonify([
        {"name": cat, "count": count}
        for cat, count in categories
    ]), 200
