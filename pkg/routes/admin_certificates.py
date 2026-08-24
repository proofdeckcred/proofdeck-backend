from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from ..models import Certificate, Template, db, User, Admin
from sqlalchemy import func, or_
from datetime import datetime

admin_certificates_bp = Blueprint('admin_certificates', __name__)

@admin_certificates_bp.route('/certificates/overview', methods=['GET'])
@jwt_required()
def get_certificates_overview():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    total_certificates = Certificate.query.count()
    by_user = db.session.query(Certificate.user_id, func.count(Certificate.id).label('count')).group_by(Certificate.user_id).order_by(func.count(Certificate.id).desc()).all()
    by_template = db.session.query(Certificate.template_id, func.count(Certificate.id).label('count')).group_by(Certificate.template_id).order_by(func.count(Certificate.id).desc()).all()

    user_breakdown = [{'user_id': uid, 'user_name': User.query.get(uid).name if User.query.get(uid) else 'Unknown', 'count': count} for uid, count in by_user]
    template_breakdown = [{'template_id': tid, 'title': Template.query.get(tid).title if Template.query.get(tid) else 'Unknown', 'count': count} for tid, count in by_template]

    return jsonify({
        'total': total_certificates,
        'by_user': user_breakdown,
        'by_template': template_breakdown
    }), 200

# --- THIS IS THE NEW FEATURE ---
# Route to get a paginated, searchable, and filterable list of all certificates.
@admin_certificates_bp.route('/certificates', methods=['GET'])
@jwt_required()
def list_certificates():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search = request.args.get('search', '')
    status = request.args.get('status')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # Start with a base query and join with User to get issuer name
    query = db.session.query(Certificate, User.name.label('issuer_name')) \
                      .join(User, Certificate.user_id == User.id)

    if search:
        search_term = f'%{search}%'
        query = query.filter(
            or_(
                Certificate.recipient_name.ilike(search_term),
                Certificate.course_title.ilike(search_term),
                User.name.ilike(search_term) # Also search by issuer name
            )
        )
    
    if status:
        query = query.filter(Certificate.status == status)
    
    if start_date_str:
        try:
            start_date = datetime.fromisoformat(start_date_str).date()
            query = query.filter(Certificate.issue_date >= start_date)
        except ValueError:
            pass # Ignore invalid date format
            
    if end_date_str:
        try:
            end_date = datetime.fromisoformat(end_date_str).date()
            query = query.filter(Certificate.issue_date <= end_date)
        except ValueError:
            pass # Ignore invalid date format

    query = query.order_by(Certificate.created_at.desc())

    paginated_results = query.paginate(page=page, per_page=limit, error_out=False)
    
    results_list = []
    for cert, issuer_name in paginated_results.items:
        results_list.append({
            'id': cert.id,
            'recipient_name': cert.recipient_name,
            'course_title': cert.course_title,
            'issuer_name': issuer_name,
            'issue_date': cert.issue_date.isoformat(),
            'status': cert.status,
            'verification_id': cert.verification_id
        })
    
    return jsonify({
        'certificates': results_list,
        'total': paginated_results.total,
        'pages': paginated_results.pages,
        'current_page': paginated_results.page
    }), 200
# --- END OF NEW FEATURE ---

@admin_certificates_bp.route('/certificates/<int:cert_id>/revoke', methods=['POST'])
@jwt_required()
def revoke_certificate(cert_id):
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    cert = Certificate.query.get_or_404(cert_id)
    cert.status = 'revoked'
    db.session.commit()
    return jsonify({'msg': 'Certificate revoked'}), 200