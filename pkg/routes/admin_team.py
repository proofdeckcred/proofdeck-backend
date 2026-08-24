from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from ..models import Admin, db
from bcrypt import hashpw, gensalt

admin_team_bp = Blueprint('admin_team', __name__)

def super_admin_required():
    claims = get_jwt()
    if claims.get('role') != 'super_admin':
        return False
    return True

@admin_team_bp.route('/admins', methods=['GET'])
@jwt_required()
def get_admins():
    """List all admins. Restricted to Super Admin."""
    if not super_admin_required():
        return jsonify({"msg": "Access denied: Super Admin only"}), 403
        
    admins = Admin.query.all()
    result = []
    for admin in admins:
        result.append({
            "id": admin.id,
            "name": admin.name,
            "email": admin.email,
            "role": admin.role,
            "is_verified": admin.is_verified,
            "created_at": admin.created_at,
            "permissions": admin.permissions
        })
    return jsonify(result), 200

@admin_team_bp.route('/admins', methods=['POST'])
@jwt_required()
def create_admin():
    """Create a new admin account (Business/Support). Super Admin only."""
    if not super_admin_required():
        return jsonify({"msg": "Access denied: Super Admin only"}), 403
        
    data = request.get_json()
    
    required = ['name', 'email', 'password', 'role']
    if not all(k in data for k in required):
        return jsonify({"msg": "Missing required fields"}), 400
        
    if Admin.query.filter_by(email=data['email']).first():
        return jsonify({"msg": "Email already in use"}), 409
        
    hashed_pw = hashpw(data['password'].encode('utf-8'), gensalt()).decode('utf-8')
    
    new_admin = Admin(
        name=data['name'],
        email=data['email'],
        password_hash=hashed_pw,
        role=data['role'],
        permissions=data.get('permissions', {}),
        is_verified=True # auto-verified when created by super admin
    )
    
    db.session.add(new_admin)
    db.session.commit()
    
    return jsonify({"msg": "Admin created successfully", "id": new_admin.id}), 201

@admin_team_bp.route('/admins/<int:admin_id>', methods=['DELETE'])
@jwt_required()
def delete_admin(admin_id):
    if not super_admin_required():
        return jsonify({"msg": "Access denied"}), 403
        
    admin = Admin.query.get_or_404(admin_id)
    if admin.role == 'super_admin' and admin.id == 1: # Prevent deleting main super admin
        return jsonify({"msg": "Cannot delete the primary Super Admin"}), 403
        
    db.session.delete(admin)
    db.session.commit()
    return jsonify({"msg": "Admin deleted"}), 200
    
@admin_team_bp.route('/admins/<int:admin_id>', methods=['PUT'])
@jwt_required()
def update_admin(admin_id):
    if not super_admin_required():
        return jsonify({"msg": "Access denied"}), 403
        
    admin = Admin.query.get_or_404(admin_id)
    data = request.get_json()
    
    if 'role' in data:
        admin.role = data['role']
    if 'permissions' in data:
        admin.permissions = data['permissions']
    if 'password' in data and data['password']:
        admin.password_hash = hashpw(data['password'].encode('utf-8'), gensalt()).decode('utf-8')
        
    db.session.commit()
    return jsonify({"msg": "Admin updated"}), 200
