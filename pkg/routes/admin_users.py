from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt, current_user
from datetime import datetime, timedelta
from ..models import User, Payment, Admin, db, AdminActionLog, Certificate, Company
from sqlalchemy import or_

admin_users_bp = Blueprint('admin_users', __name__)

@admin_users_bp.route('/users/me', methods=['GET'])
@jwt_required()
def get_current_admin():
    """
    Fetches the profile of the currently logged-in admin.
    """
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Administration rights required"}), 403

    if not current_user.is_verified:
         return jsonify({"msg": "Admin not verified"}), 403

    return jsonify({
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "permissions": current_user.permissions,
        "is_admin": True
    }), 200

@admin_users_bp.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search = request.args.get('search', '')
    role = request.args.get('role')
    status = request.args.get('status')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = User.query.outerjoin(Company, User.company_id == Company.id)
    if search:
        query = query.filter(or_(User.name.ilike(f'%{search}%'), User.email.ilike(f'%{search}%')))
    if role:
        query = query.filter(User.role == role)
    if status == 'active':
        query = query.filter(User.role != 'suspended')
    elif status == 'inactive':
        query = query.filter(User.role == 'suspended')
    
    if start_date:
        query = query.filter(User.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        # Add a day to the end date to include the entire day
        end_date_obj = datetime.fromisoformat(end_date)
        query = query.filter(User.created_at < end_date_obj + timedelta(days=1))

    users = query.paginate(page=page, per_page=limit, error_out=False)
    user_list = [{
        'id': u.id,
        'name': u.name,
        'email': u.email,
        'role': u.role,
        'cert_quota': u.cert_quota,
        'signup_date': u.created_at.isoformat(),
        'last_login': u.last_login.isoformat() if u.last_login else None,
        'subscription_expiry': u.subscription_expiry.isoformat() if u.subscription_expiry else None,
        'company_name': u.company.name if u.company else 'N/A'
    } for u in users.items]

    return jsonify({
        'users': user_list,
        'total': users.total,
        'pages': users.pages
    }), 200

@admin_users_bp.route('/users/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_details(user_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    user = User.query.get_or_404(user_id)
    certs = Certificate.query.filter_by(user_id=user.id).order_by(Certificate.created_at.desc()).all()
    cert_list = [{
        'id': c.id,
        'recipient_name': c.recipient_name,
        'course_title': c.course_title,
        'status': c.status,
        'issue_date': c.issue_date.isoformat(),
        'verification_id': c.verification_id
    } for c in certs]

    payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    payment_list = [{
        'id': p.id,
        'plan': p.plan,
        'amount': float(p.amount),
        'currency': p.currency,
        'status': p.status,
        'date': p.created_at.isoformat(),
        'provider': p.provider
    } for p in payments]
    
    user_data = {
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'cert_quota': user.cert_quota,
        'signup_date': user.created_at.isoformat(),
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'subscription_expiry': user.subscription_expiry.isoformat() if user.subscription_expiry else None,
        'company': {'id': user.company.id, 'name': user.company.name} if user.company else None
    }

    return jsonify({
        'user': user_data,
        'certificates': cert_list,
        'payments': payment_list
    }), 200

@admin_users_bp.route('/users/<int:user_id>/adjust-quota', methods=['POST'])
@jwt_required()
def adjust_user_quota(user_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    data = request.get_json()
    adjustment = data.get('adjustment')
    reason = data.get('reason')

    if not isinstance(adjustment, int) or not reason:
        return jsonify({"msg": "Adjustment amount (integer) and reason are required"}), 400

    user = User.query.get_or_404(user_id)
    
    if user.cert_quota + adjustment < 0:
        return jsonify({"msg": "Cannot adjust quota below zero"}), 400
        
    user.cert_quota += adjustment

    log_entry = AdminActionLog(
        admin_id=current_user.id,
        action=f"Adjusted quota by {adjustment}. Reason: {reason}",
        target_type='user',
        target_id=user.id
    )
    db.session.add(log_entry)
    db.session.commit()

    return jsonify({
        "msg": "User quota adjusted successfully",
        "new_quota": user.cert_quota
    }), 200

@admin_users_bp.route('/users/<int:user_id>/delete', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    user = User.query.get_or_404(user_id)

    # Prevent deleting a user who owns a company
    if user.owned_company:
        return jsonify({"msg": f"Cannot delete user. They own the company '{user.owned_company.name}'. Please delete the company first or transfer ownership."}), 400

    # Nullify FKs on associated records
    Payment.query.filter_by(user_id=user.id).update({'user_id': None})
    Certificate.query.filter_by(user_id=user.id).update({'user_id': None})
    
    # Cascade deletion will handle Templates, Groups, SupportTickets
    db.session.delete(user)
    
    # Log the action
    log = AdminActionLog(admin_id=current_user.id, action=f"Deleted user: {user.email} (ID: {user.id})", target_type='user', target_id=user.id)
    db.session.add(log)
    
    db.session.commit()

    return jsonify({"msg": "User has been deleted successfully."}), 200

@admin_users_bp.route('/users/<int:user_id>/suspend', methods=['POST'])
@jwt_required()
def suspend_user(user_id):
    if not get_jwt().get("is_admin"):
        return jsonify({"msg": "Admin access required"}), 403

    user = User.query.get_or_404(user_id)
    user.role = 'suspended'
    db.session.commit()
    return jsonify({'msg': 'User suspended'}), 200

@admin_users_bp.route('/users/<int:user_id>/unsuspend', methods=['POST'])
@jwt_required()
def unsuspend_user(user_id):
    if not get_jwt().get("is_admin"):
        return jsonify({"msg": "Admin access required"}), 403

    user = User.query.get_or_404(user_id)
    user.role = 'free'
    db.session.commit()
    return jsonify({'msg': 'User unsuspended'}), 200

@admin_users_bp.route('/users/<int:user_id>/plan', methods=['PUT'])
@jwt_required()
def update_user_plan(user_id):
    if not get_jwt().get("is_admin"):
        return jsonify({"msg": "Admin access required"}), 403

    user = User.query.get_or_404(user_id)
    data = request.get_json()
    new_plan = data.get('plan')
    if new_plan in ['free', 'starter', 'growth', 'pro', 'enterprise']:
        user.role = new_plan
        user.subscription_expiry = datetime.utcnow().replace(year=datetime.utcnow().year + 1)
        db.session.commit()
        return jsonify({'msg': 'Plan updated'}), 200
    return jsonify({'msg': 'Invalid plan'}), 400