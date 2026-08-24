from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token
from bcrypt import hashpw, gensalt
from datetime import datetime, timedelta
import uuid

from ..models import db, User, Tenant, TeamInvitation, Membership
from ..utils.email_utils import send_team_invitation_email
from ..utils.helpers import get_active_context

team_bp = Blueprint('team', __name__)

@team_bp.route('/invite', methods=['POST'])
@jwt_required()
def invite_member():
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    
    is_comp, tenant_id, _, active_role = get_active_context(user)
    
    if not is_comp:
        return jsonify({"msg": "You must switch to a tenant workspace to invite staff."}), 400
        
    if active_role not in ('owner', 'admin'):
        return jsonify({"msg": "Only owners and admins can invite team members."}), 403
        
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"msg": "Tenant workspace not found."}), 404
        
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({"msg": "Email is required."}), 400
        
    # Rate limit check: max 20 invites per tenant per hour
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    invite_count = TeamInvitation.query.filter(
        TeamInvitation.tenant_id == tenant_id,
        TeamInvitation.created_at >= hour_ago
    ).count()
    if invite_count >= 20:
        return jsonify({"msg": "Invitation rate limit exceeded (max 20 per hour). Please try again later."}), 429
        
    # Cancel previous active pending invitations for this email in this tenant
    TeamInvitation.query.filter_by(
        tenant_id=tenant_id, 
        email=email, 
        status='pending'
    ).update({"status": "cancelled"})
    
    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(hours=48)
    
    new_invite = TeamInvitation(
        tenant_id=tenant_id,
        email=email,
        token=token,
        status='pending',
        expires_at=expires_at
    )
    db.session.add(new_invite)
    db.session.commit()
    
    frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:3000')
    invite_url = f"{frontend_url}/join/{token}"
    
    try:
        send_team_invitation_email(email, invite_url, tenant.name)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error sending team invitation: {e}")
        return jsonify({"msg": "Failed to send email. Invite registered but not sent."}), 500
        
    return jsonify({"msg": f"Invitation sent to {email} successfully."}), 201


@team_bp.route('/invite/<token>', methods=['GET'])
def get_invitation_details(token):
    invite = TeamInvitation.query.filter_by(token=token).first()
    if not invite:
        return jsonify({"msg": "Invitation not found."}), 404
        
    if invite.status != 'pending':
        return jsonify({"msg": f"This invitation has already been {invite.status}."}), 400
        
    if invite.expires_at < datetime.utcnow():
        invite.status = 'expired'
        db.session.commit()
        return jsonify({"msg": "This invitation has expired. Please request a new invite."}), 400
        
    user_exists = User.query.filter_by(email=invite.email).first() is not None
        
    return jsonify({
        "email": invite.email,
        "company_name": invite.tenant.name,
        "user_exists": user_exists
    }), 200


@team_bp.route('/accept', methods=['POST'])
def accept_invitation():
    data = request.get_json()
    token = data.get('token')
    name = data.get('name', '').strip()
    password = data.get('password')
    
    if not token:
        return jsonify({"msg": "Token is required."}), 400
        
    invite = TeamInvitation.query.filter_by(token=token).first()
    if not invite:
        return jsonify({"msg": "Invitation not found."}), 404
        
    if invite.status != 'pending':
        return jsonify({"msg": f"This invitation has already been {invite.status}."}), 400
        
    if invite.expires_at < datetime.utcnow():
        invite.status = 'expired'
        db.session.commit()
        return jsonify({"msg": "This invitation has expired. Please request a new invite."}), 400
        
    user = User.query.filter_by(email=invite.email).first()
    
    from bcrypt import checkpw
    if user:
        if not password or not checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            return jsonify({"msg": "Incorrect password for this account."}), 401
    else:
        if not name or not password:
            return jsonify({"msg": "Name and password are required for new accounts."}), 400
            
        hashed_password = hashpw(password.encode('utf-8'), gensalt()).decode('utf-8')
        user = User(
            name=name,
            email=invite.email,
            password_hash=hashed_password,
            is_verified=True
        )
        db.session.add(user)
        db.session.flush()
        
    # Check if they are already an active member of this tenant
    existing_membership = Membership.query.filter_by(user_id=user.id, tenant_id=invite.tenant_id).first()
    if existing_membership:
        existing_membership.status = 'active'
    else:
        new_membership = Membership(
            user_id=user.id,
            tenant_id=invite.tenant_id,
            role='member',
            status='active'
        )
        db.session.add(new_membership)
        
    invite.status = 'accepted'
    db.session.commit()
    
    access_token = create_access_token(identity=str(user.id))
    return jsonify({
        "msg": "Successfully joined the organization!",
        "access_token": access_token
    }), 200


@team_bp.route('/members', methods=['GET'])
@jwt_required()
def get_team_members():
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    
    is_comp, tenant_id, _, active_role = get_active_context(user)
    
    if not is_comp:
        return jsonify({"members": [], "invitations": []}), 200
        
    memberships = Membership.query.filter_by(tenant_id=tenant_id, status='active').all()
    members_data = []
    for m in memberships:
        members_data.append({
            "id": m.user.id,
            "name": m.user.name,
            "email": m.user.email,
            "role": m.role.title(),
            "joined_at": m.joined_at.isoformat()
        })
        
    invites = TeamInvitation.query.filter_by(tenant_id=tenant_id, status='pending').all()
    invites_data = []
    for inv in invites:
        if inv.expires_at < datetime.utcnow():
            inv.status = 'expired'
            db.session.commit()
            continue
        invites_data.append({
            "id": inv.id,
            "email": inv.email,
            "status": inv.status,
            "created_at": inv.created_at.isoformat(),
            "expires_at": inv.expires_at.isoformat()
        })
        
    return jsonify({
        "members": members_data,
        "invitations": invites_data
    }), 200


@team_bp.route('/members/<int:member_id>', methods=['DELETE'])
@jwt_required()
def remove_team_member(member_id):
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    
    is_comp, tenant_id, _, active_role = get_active_context(user)
    
    if not is_comp:
        return jsonify({"msg": "Not operating in a tenant workspace context."}), 400
        
    if active_role not in ('owner', 'admin'):
        return jsonify({"msg": "Only owners and admins can remove members."}), 403
        
    member_membership = Membership.query.filter_by(tenant_id=tenant_id, user_id=member_id).first()
    if not member_membership:
        return jsonify({"msg": "Member not found in this organization."}), 404
        
    if member_membership.role == 'owner':
        return jsonify({"msg": "Cannot remove the owner of the organization."}), 400
        
    # Admins cannot remove other Admins (only Owners can)
    if active_role == 'admin' and member_membership.role == 'admin':
        return jsonify({"msg": "Admins cannot remove other admins."}), 403
        
    db.session.delete(member_membership)
    db.session.commit()
    
    return jsonify({"msg": "Member has been successfully removed from the workspace."}), 200


@team_bp.route('/invites/<int:invite_id>', methods=['DELETE'])
@jwt_required()
def cancel_invitation(invite_id):
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    
    is_comp, tenant_id, _, active_role = get_active_context(user)
    
    if not is_comp:
        return jsonify({"msg": "Not operating in a tenant workspace context."}), 400
        
    if active_role not in ('owner', 'admin'):
        return jsonify({"msg": "Only owners and admins can cancel invitations."}), 403
        
    invite = TeamInvitation.query.get(invite_id)
    if not invite or invite.tenant_id != tenant_id:
        return jsonify({"msg": "Invitation not found."}), 404
        
    if invite.status == 'pending':
        invite.status = 'cancelled'
        db.session.commit()
        return jsonify({"msg": "Invitation cancelled successfully."}), 200
    else:
        return jsonify({"msg": f"Cannot cancel invitation with status: {invite.status}."}), 400
