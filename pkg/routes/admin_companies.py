from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from ..models import db, Admin, Company, User, Certificate, AdminActionLog
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased # <--- IMPORT THIS

admin_companies_bp = Blueprint('admin_companies', __name__)

@admin_companies_bp.route('/companies', methods=['GET'])
@jwt_required()
def get_companies():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403
    
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search = request.args.get('search', '')
    
    # --- FIX: Create an alias for the User table to represent the Owner ---
    Owner = aliased(User)
    
    # --- FIX: Rebuild the query using the Owner alias for clarity ---
    query = db.session.query(
        Company,
        Owner.name.label('owner_name'),
        func.count(User.id).label('member_count')
    ).join(
        Owner, Company.owner_id == Owner.id  # Join to get the owner's name
    ).outerjoin(
        User, Company.id == User.company_id # Left Join to count all members
    )

    if search:
        search_term = f'%{search}%'
        # --- FIX: Search by Company name OR the aliased Owner's name ---
        query = query.filter(or_(Company.name.ilike(search_term), Owner.name.ilike(search_term)))
        
    # --- FIX: Group by the company and the specific owner ---
    query = query.group_by(Company.id, Owner.name).order_by(Company.created_at.desc())
    
    paginated_results = query.paginate(page=page, per_page=limit, error_out=False)
    
    # The rest of the function now works correctly with the fixed query
    results = [{
        'id': company.id,
        'name': company.name,
        'owner_name': owner_name,
        'member_count': member_count,
        'created_at': company.created_at.isoformat()
    } for company, owner_name, member_count in paginated_results.items]

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

    company = Company.query.get_or_404(company_id)
    
    members = [{
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'role': user.role
    } for user in company.users]

    certificates = Certificate.query.filter_by(company_id=company_id).order_by(Certificate.created_at.desc()).limit(20).all()
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
        'members': members,
        'recent_certificates': cert_list
    }), 200

@admin_companies_bp.route('/companies/<int:company_id>/delete', methods=['DELETE'])
@jwt_required()
def delete_company(company_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    company = Company.query.get_or_404(company_id)
    company_name = company.name

    # Disassociate users from the company
    User.query.filter_by(company_id=company_id).update({'company_id': None})
    
    # Nullify company_id on certificates and templates (handled by ondelete='SET NULL' in model but can be explicit)
    # This is not strictly needed if DB cascade is set up, but good for clarity.
    Certificate.query.filter_by(company_id=company_id).update({'company_id': None})
    db.session.delete(company)

    # Log the action
    log = AdminActionLog(
        admin_id=current_user.id,
        action=f"Deleted company: {company_name} (ID: {company_id})",
        target_type='company',
        target_id=company_id
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"msg": "Company has been deleted successfully. Associated users are now individual accounts."}), 200