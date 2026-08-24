from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
import secrets
import string
from ..models import User, Referral
from ..extensions import db

referrals_bp = Blueprint('referrals', __name__)

def generate_unique_code():
    """Generates a unique 8-character referral code."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(chars) for _ in range(8))
        if not User.query.filter_by(referral_code=code).first():
            return code

@referrals_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user:
        return jsonify({"msg": "User not found"}), 404

    # Lazy generation of referral code if not exists
    if not user.referral_code:
        user.referral_code = generate_unique_code()
        db.session.commit()

    referrals = Referral.query.filter_by(referrer_id=user.id).all()
    
    stats = {
        "referral_code": user.referral_code,
        "total_referrals": len(referrals),
        "completed_referrals": sum(1 for r in referrals if r.status == 'completed'),
        "pending_referrals": sum(1 for r in referrals if r.status == 'pending'),
        # Each completed referral gives 5 bonus credits (example mapping of $15 value)
        # Ideally this should be dynamic or stored, but for now we calculate it.
        "earned_credits": sum(1 for r in referrals if r.status == 'completed') * 5
    }
    
    return jsonify(stats), 200
