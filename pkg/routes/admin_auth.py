from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token
from bcrypt import hashpw, gensalt, checkpw
from datetime import datetime
from ..models import Admin, User
from ..extensions import db
from ..utils.email_utils import send_admin_verification_email

admin_auth_bp = Blueprint('admin_auth', __name__)

@admin_auth_bp.route('/signup', methods=['POST'])
def admin_signup():
    """Creates the first admin user (unverified) and sends a verification code."""
    # --- NEW SECURITY CHECK ---
    if not current_app.config.get('ADMIN_EMAIL'):
        current_app.logger.error("CRITICAL: Admin signup attempted, but ADMIN_EMAIL is not configured.")
        return jsonify({"msg": "Server configuration error: Admin email not set."}), 500
    # --- END OF SECURITY CHECK ---

    # Only allow creation if no *verified* admin exists.
    if Admin.query.filter_by(is_verified=True).first():
        return jsonify({"msg": "Admin user already exists. Signup is disabled."}), 403

    data = request.get_json()
    if not all(key in data for key in ['name', 'email', 'password']):
        return jsonify({"msg": "Missing name, RS, or password"}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({"msg": "This email is already registered as a regular user."}), 409

    # If an unverified admin exists, overwrite it.
    existing_admin = Admin.query.filter_by(email=data['email']).first()
    if existing_admin:
        db.session.delete(existing_admin)
        db.session.commit()

    hashed_password = hashpw(data['password'].encode('utf-8'), gensalt())

    new_admin = Admin(
        name=data['name'],
        email=data['email'],
        password_hash=hashed_password.decode('utf-8')
    )
    new_admin.set_verification_code()
    
    db.session.add(new_admin)
    db.session.commit()

    try:
        send_admin_verification_email(new_admin)
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"Could not send verification email. Please check server configuration. Error: {e}"}), 500

    return jsonify({"msg": "Admin account created. A verification code has been sent to the registered company email."}), 201

@admin_auth_bp.route('/verify', methods=['POST'])
def verify_admin():
    """Verifies the admin's email with the provided code."""
    data = request.get_json()
    email = data.get('email')
    code = data.get('code')

    if not email or not code:
        return jsonify({"msg": "Email and code are required"}), 400

    admin = Admin.query.filter_by(email=email, is_verified=False).first()

    if not admin:
        return jsonify({"msg": "No unverified admin found for this email."}), 404

    if admin.verification_expiry < datetime.utcnow():
        return jsonify({"msg": "Verification code has expired."}), 400

    if admin.verification_code != code:
        return jsonify({"msg": "Invalid verification code."}), 400

    admin.is_verified = True
    admin.verification_code = None
    admin.verification_expiry = None
    db.session.commit()

    return jsonify({"msg": "Admin account verified successfully! You can now log in."}), 200

@admin_auth_bp.route('/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if not all(key in data for key in ['email', 'password']):
        return jsonify({"msg": "Missing email or password"}), 400

    admin = Admin.query.filter_by(email=data['email']).first()

    # CRITICAL: Check for user, correct password, AND that they are verified.
    if admin and admin.is_verified and checkpw(data['password'].encode('utf-8'), admin.password_hash.encode('utf-8')):
        # Inject Role and Permissions into JWT
        additional_claims = {
            "is_admin": True,
            "role": admin.role,
            "permissions": admin.permissions or {}
        }
        access_token = create_access_token(identity=str(admin.id), additional_claims=additional_claims)
        
        return jsonify({
            "access_token": access_token,
            "admin": {
                "id": admin.id,
                "name": admin.name,
                "email": admin.email,
                "role": admin.role,
                "permissions": admin.permissions
            }
        }), 200
    
    if admin and not admin.is_verified:
        return jsonify({"msg": "Account not verified. Please check your email."}), 403

    return jsonify({"msg": "Invalid credentials"}), 401

@admin_auth_bp.route('/status', methods=['GET'])
def admin_status():
    """Checks if a verified admin exists to determine if signup should be shown."""
    admin_exists = Admin.query.filter_by(is_verified=True).count() > 0
    return jsonify({"admin_exists": admin_exists}), 200