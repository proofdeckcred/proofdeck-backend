from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Notification

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('', methods=['GET'], strict_slashes=False)
@notifications_bp.route('/', methods=['GET'], strict_slashes=False)
@jwt_required()
def list_notifications():
    user_id = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    unread_only = request.args.get('unread_only', type=lambda v: str(v).lower() == 'true')
    
    query = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
        
    pagination = query.order_by(Notification.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    
    unread_count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    total_all = Notification.query.filter_by(user_id=user_id).count()
    
    notifications = [{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'type': n.type,
        'category': n.category,
        'is_read': n.is_read,
        'created_at': n.created_at.isoformat()
    } for n in pagination.items]
    
    return jsonify({
        'notifications': notifications,
        'total': pagination.total,
        'total_all': total_all,
        'unread_count': unread_count,
        'page': pagination.page,
        'pages': pagination.pages
    }), 200

@notifications_bp.route('/unread-count', methods=['GET'], strict_slashes=False)
@jwt_required()
def unread_count():
    user_id = int(get_jwt_identity())
    count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    return jsonify({'unread_count': count}), 200

@notifications_bp.route('/<int:notification_id>/read', methods=['PATCH', 'POST', 'PUT'], strict_slashes=False)
@jwt_required()
def mark_read(notification_id):
    user_id = int(get_jwt_identity())
    notif = Notification.query.get_or_404(notification_id)
    
    if notif.user_id != user_id:
        return jsonify({"msg": "Permission denied"}), 403
        
    notif.is_read = True
    db.session.commit()
    return jsonify({"msg": "Notification marked as read", "id": notif.id, "is_read": True}), 200

@notifications_bp.route('/read-all', methods=['PATCH', 'POST', 'PUT'], strict_slashes=False)
@jwt_required()
def mark_all_read():
    user_id = int(get_jwt_identity())
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({"msg": "All notifications marked as read"}), 200
