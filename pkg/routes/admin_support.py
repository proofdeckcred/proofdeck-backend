import os
import uuid
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, current_user
from werkzeug.utils import secure_filename
from ..models import db, Admin, User, SupportTicket, SupportMessage, SupportWidgetMessage
from sqlalchemy import case

admin_support_bp = Blueprint('admin_support', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_support_image(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(f"support_{uuid.uuid4().hex[:12]}.{file.filename.rsplit('.', 1)[1].lower()}")
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return f"/uploads/{filename}"
    return None

@admin_support_bp.route('/support/tickets/<int:ticket_id>', methods=['GET'])
@jwt_required()
def get_admin_ticket_details(ticket_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    ticket = SupportTicket.query.get_or_404(ticket_id)
    messages = ticket.messages.order_by(SupportMessage.created_at.asc()).all()
    
    return jsonify({
        'id': ticket.id,
        'subject': ticket.subject,
        'status': ticket.status,
        'user': {
            'id': ticket.user.id,
            'name': ticket.user.name,
            'email': ticket.user.email,
            'role': ticket.user.role
        },
        'messages': [{
            'id': m.id,
            'content': m.content,
            # Construct the full, absolute URL for the image
            'image_url': f"{request.url_root.rstrip('/')}{m.image_url}" if m.image_url else None,
            'created_at': m.created_at.isoformat(),
            'sender_type': 'admin' if m.admin_id else 'user',
            'sender_name': m.sender_admin.name if m.admin_id else m.sender_user.name
        } for m in messages]
    }), 200

@admin_support_bp.route('/support/tickets/<int:ticket_id>/reply', methods=['POST'])
@jwt_required()
def admin_reply_to_ticket(ticket_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    ticket = SupportTicket.query.get_or_404(ticket_id)
    content = request.form.get('message')
    file = request.files.get('file')
    
    if not content:
        return jsonify({"msg": "Message content is required"}), 400

    image_url = save_support_image(file)

    new_message = SupportMessage(
        ticket_id=ticket.id, 
        admin_id=current_user.id, 
        content=content,
        image_url=image_url
    )
    
    if ticket.status == 'open':
        ticket.status = 'in_progress'

    db.session.add(new_message)
    db.session.commit()
    
    return jsonify({"msg": "Reply sent successfully"}), 200


@admin_support_bp.route('/support/tickets', methods=['GET'])
@jwt_required()
def get_all_tickets():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    status = request.args.get('status')

    priority_order = case(
        (User.role == 'enterprise', 0),
        (User.role == 'pro', 1),
        (User.role == 'growth', 2),
        (User.role == 'starter', 3),
        (User.role == 'free', 4),
        else_=5
    ).label('priority')

    query = db.session.query(SupportTicket, User.name, User.role, priority_order) \
                      .join(User, SupportTicket.user_id == User.id)

    if status:
        query = query.filter(SupportTicket.status == status)
    
    query = query.order_by(priority_order, SupportTicket.updated_at.desc())

    paginated_tickets = query.paginate(page=page, per_page=limit, error_out=False)
    
    ticket_list = []
    for ticket, user_name, user_role, priority in paginated_tickets.items:
        ticket_list.append({
            'id': ticket.id,
            'subject': ticket.subject,
            'user_name': user_name,
            'user_role': user_role,
            'status': ticket.status,
            'updated_at': ticket.updated_at.isoformat()
        })

    return jsonify({
        'tickets': ticket_list,
        'total': paginated_tickets.total,
        'pages': paginated_tickets.pages
    }), 200

@admin_support_bp.route('/support/tickets/open-count', methods=['GET'])
@jwt_required()
def get_open_tickets_count():
    """Returns the count of tickets with 'open' status."""
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    # Count tickets that require admin attention ('open')
    count = SupportTicket.query.filter(SupportTicket.status == 'open').count()
    
    return jsonify({'count': count}), 200

@admin_support_bp.route('/support/tickets/<int:ticket_id>/status', methods=['PUT'])
@jwt_required()
def update_ticket_status(ticket_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    ticket = SupportTicket.query.get_or_404(ticket_id)
    data = request.get_json()
    new_status = data.get('status')

    if new_status not in ['open', 'in_progress', 'closed']:
        return jsonify({"msg": "Invalid status"}), 400

    ticket.status = new_status
    db.session.commit()
    
    return jsonify({"msg": f"Ticket status updated to {new_status}"}), 200

# --- WIDGET MESSAGES ENDPOINTS ---

@admin_support_bp.route('/support/widget-messages', methods=['GET'])
@jwt_required()
def get_widget_messages():
    """Returns all messages sent via the Support Widget."""
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    status = request.args.get('status')

    query = SupportWidgetMessage.query

    if status:
        query = query.filter(SupportWidgetMessage.status == status)

    # Order by oldest first (FIFO queue)
    query = query.order_by(SupportWidgetMessage.created_at.asc())

    paginated_msgs = query.paginate(page=page, per_page=limit, error_out=False)

    msg_list = []
    for msg in paginated_msgs.items:
        sender_name = "Guest"
        email = msg.email
        if msg.user_id:
            user = User.query.get(msg.user_id)
            if user:
                sender_name = user.name
                email = user.email # Use user email if available

        msg_list.append({
            'id': msg.id,
            'email': email,
            'message': msg.message,
            'status': msg.status,
            'sender_name': sender_name,
            'created_at': msg.created_at.isoformat()
        })

    return jsonify({
        'messages': msg_list,
        'total': paginated_msgs.total,
        'pages': paginated_msgs.pages
    }), 200

@admin_support_bp.route('/support/widget-messages/<int:msg_id>', methods=['DELETE'])
@jwt_required()
def delete_widget_message(msg_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    msg = SupportWidgetMessage.query.get_or_404(msg_id)
    db.session.delete(msg)
    db.session.commit()
    return jsonify({"msg": "Message deleted"}), 200

@admin_support_bp.route('/support/widget-messages/<int:msg_id>/status', methods=['PUT'])
@jwt_required()
def update_widget_message_status(msg_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    msg = SupportWidgetMessage.query.get_or_404(msg_id)
    data = request.get_json()
    new_status = data.get('status') # 'new', 'read', 'replied'
    
    if new_status:
        msg.status = new_status
        db.session.commit()
    
    return jsonify({"msg": "Status updated"}), 200

@admin_support_bp.route('/support/widget-messages/reply', methods=['POST'])
@jwt_required()
def reply_to_widget_message():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    data = request.get_json()
    original_msg_id = data.get('message_id')
    message_content = data.get('message')
    
    if not original_msg_id or not message_content:
        return jsonify({"msg": "Message ID and content are required"}), 400
        
    original_msg = SupportWidgetMessage.query.get_or_404(original_msg_id)
    
    # Create reply message
    reply = SupportWidgetMessage(
        email=original_msg.email,
        message=message_content,
        user_id=original_msg.user_id,
        session_id=original_msg.session_id,
        sender_type='admin',
        admin_id=current_user.id,
        status='replied' # Replies are automatically 'replied' or 'read' contextually
    )
    
    # Update original message status to replied
    original_msg.status = 'replied'
    
    db.session.add(reply)
    db.session.commit()
    
    return jsonify({"msg": "Reply sent successfully"}), 200