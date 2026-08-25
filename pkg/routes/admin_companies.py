from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from ..models import db, Admin, Tenant, User, Certificate, AdminActionLog, Membership
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased

admin_companies_bp = Blueprint('admin_companies', __name__)

@admin_companies_bp.route('/companies', methods=['GET'])
@jwt_required()
def get_companies():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search = request.args.get('search', '')
    
    Owner = aliased(User)
    
    query = db.session.query(
        Tenant,
        Owner.name.label('owner_name'),
        func.count(Membership.id).label('member_count')
    ).join(
        Owner, Tenant.owner_id == Owner.id
    ).outerjoin(
        Membership, Tenant.id == Membership.tenant_id
    )

    if search:
        search_term = f'%{search}%'
        query = query.filter(or_(Tenant.name.ilike(search_term), Owner.name.ilike(search_term)))
        
    query = query.group_by(Tenant.id, Owner.name).order_by(Tenant.created_at.desc())
    
    paginated_results = query.paginate(page=page, per_page=limit, error_out=False)
    
    results = [{
        'id': tenant.id,
        'name': tenant.name,
        'owner_name': owner_name,
        'member_count': member_count,
        'created_at': tenant.created_at.isoformat()
    } for tenant, owner_name, member_count in paginated_results.items]

    return jsonify({
        'companies': results,
        'total': paginated_results.total,
        'pages': paginated_results.pages,
        'current_page': paginated_results.page
    }), 200

@admin_companies_bp.route('/companies/<int:company_id>', methods=['GET'])
@jwt_required()
def get_company_details(company_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    company = Tenant.query.get_or_404(company_id)
    
    memberships = Membership.query.filter_by(tenant_id=company_id, status='active').all()
    members = [{
        'id': m.user.id,
        'name': m.user.name,
        'email': m.user.email,
        'role': m.role.title()
    } for m in memberships]

    certificates = Certificate.query.filter_by(tenant_id=company_id).order_by(Certificate.created_at.desc()).limit(20).all()
    cert_list = [{
        'id': c.id,
        'recipient_name': c.recipient_name,
        'course_title': c.course_title,
        'status': c.status,
        'issue_date': c.issue_date.isoformat()
    } for c in certificates]

    return jsonify({
        'id': company.id,
        'name': company.name,
        'owner': {'id': company.owner.id, 'name': company.owner.name, 'email': company.owner.email},
        'created_at': company.created_at.isoformat(),
        'cert_quota': company.cert_quota,
        'members': members,
        'recent_certificates': cert_list
    }), 200

@admin_companies_bp.route('/companies/<int:company_id>/adjust-quota', methods=['POST'])
@jwt_required()
def adjust_company_quota(company_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    data = request.get_json()
    adjustment = data.get('adjustment')
    reason = data.get('reason')

    if not isinstance(adjustment, int) or not reason:
        return jsonify({"msg": "Adjustment amount (integer) and reason are required"}), 400

    company = Tenant.query.get_or_404(company_id)
    
    if company.cert_quota + adjustment < 0:
        return jsonify({"msg": "Cannot adjust quota below zero"}), 400
        
    company.cert_quota += adjustment

    log_entry = AdminActionLog(
        admin_id=current_user.id,
        action=f"Adjusted tenant quota for {company.name} by {adjustment}. Reason: {reason}",
        target_type='tenant',
        target_id=company.id
    )
    db.session.add(log_entry)
    db.session.commit()

    return jsonify({
        "msg": "Company quota adjusted successfully",
        "new_quota": company.cert_quota
    }), 200

@admin_companies_bp.route('/companies/<int:company_id>/delete', methods=['DELETE'])
@jwt_required()
def delete_company(company_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    company = Tenant.query.get_or_404(company_id)
    company_name = company.name

    # Nullify tenant_id on certificates and templates
    Certificate.query.filter_by(tenant_id=company_id).update({'tenant_id': None})
    db.session.delete(company)

    # Log the action
    log = AdminActionLog(
        admin_id=current_user.id,
        action=f"Deleted tenant: {company_name} (ID: {company_id})",
        target_type='tenant',
        target_id=company_id
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"msg": "Organization has been deleted successfully."}), 200