from flask import Blueprint, request, jsonify
from ..models import SupportWidgetMessage, User
from ..extensions import db
import os

support_bp = Blueprint('support', __name__)

@support_bp.route('/message', methods=['POST'])
def send_support_message():
    data = request.get_json()
    email = data.get('email') # Optional if already in session/logged in
    message = data.get('message')
    user_id = data.get('user_id') # Optional
    session_id = data.get('session_id') # For guest tracking

    if not message:
        return jsonify({"msg": "Message is required."}), 400
    
    # 1. Save to Database
    try:
        new_ticket = SupportWidgetMessage(
            email=email,
            message=message,
            user_id=user_id if user_id else None,
            session_id=session_id,
            sender_type='user'
        )
        db.session.add(new_ticket)
        db.session.commit()
    except Exception as e:
        return jsonify({"msg": f"Failed to save message: {str(e)}"}), 500
    
    return jsonify({"msg": "Message sent successfully!"}), 200

@support_bp.route('/history', methods=['GET'])
def get_chat_history():
    session_id = request.args.get('session_id')
    user_id = request.args.get('user_id')

    # Must provide either a session_id or a user_id
    if not session_id and not user_id:
        return jsonify({"msg": "Session ID or User ID required"}), 400

    query = SupportWidgetMessage.query

    if user_id:
        # If user is logged in, show their messages OR messages from their session
        # This covers case where they started chatting as guest then logged in
        query = query.filter((SupportWidgetMessage.user_id == user_id) | (SupportWidgetMessage.session_id == session_id))
    elif session_id:
        query = query.filter(SupportWidgetMessage.session_id == session_id)
    
    # Get all messages sorted by time
    messages = query.order_by(SupportWidgetMessage.created_at.asc()).all()
    
    history = []
    for msg in messages:
        sender_name = "You"
        if msg.sender_type == 'admin':
            sender_name = "Support Team"
        elif msg.sender_type == 'user':
             sender_name = "You"

        history.append({
            'id': msg.id,
            'message': msg.message,
            'sender': msg.sender_type,
            'sender_name': sender_name,
            'created_at': msg.created_at.isoformat()
        })
        
    return jsonify({'history': history}), 200