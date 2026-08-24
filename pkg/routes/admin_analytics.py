from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from ..models import User, Certificate, Payment, Admin, Company, db
from sqlalchemy import func, extract, cast, Date
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

admin_analytics_bp = Blueprint('admin_analytics', __name__)

@admin_analytics_bp.route('/dashboard-stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    # Strict check to ensure only an Admin can access this
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # 1. Revenue Metrics
    total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == 'paid').scalar() or 0.0
    revenue_30d = db.session.query(func.sum(Payment.amount)).filter(
        Payment.status == 'paid', Payment.created_at >= thirty_days_ago
    ).scalar() or 0.0
    revenue_today = db.session.query(func.sum(Payment.amount)).filter(
        Payment.status == 'paid', Payment.created_at >= today_start
    ).scalar() or 0.0
    revenue_this_month = db.session.query(func.sum(Payment.amount)).filter(
        Payment.status == 'paid', Payment.created_at >= month_start
    ).scalar() or 0.0

    # Revenue by Plan
    revenue_by_plan_query = db.session.query(
        Payment.plan, func.sum(Payment.amount)
    ).filter(Payment.status == 'paid').group_by(Payment.plan).all()
    revenue_by_plan = {r[0]: float(r[1]) for r in revenue_by_plan_query}

    # 2. User & Cert Metrics
    total_users = User.query.count() or 0
    new_users_30d = User.query.filter(User.created_at >= thirty_days_ago).count() or 0
    total_certificates = Certificate.query.count() or 0
    new_certs_30d = Certificate.query.filter(Certificate.created_at >= thirty_days_ago).count() or 0
    
    # Avg Certs per User
    avg_certs_user = round(total_certificates / total_users, 1) if total_users > 0 else 0

    # 3. Engagement & Churn (The "Pulse")
    total_companies = Company.query.count() or 0
    
    # Active Orgs: Issued a cert in last 30 days
    active_companies_30d = db.session.query(func.count(func.distinct(Certificate.company_id))).filter(
        Certificate.created_at >= thirty_days_ago,
        Certificate.company_id.isnot(None)
    ).scalar() or 0

    # Churn Risk: Failed payments in last 30 days
    failed_payments_count = Payment.query.filter(
        Payment.status == 'failed', 
        Payment.created_at >= thirty_days_ago
    ).count() or 0

    # Expired Subscriptions (Churn?): Paid role but expiry in past
    expired_subs_count = User.query.filter(
        User.role.in_(['starter', 'growth', 'pro', 'enterprise']),
        User.subscription_expiry < datetime.utcnow()
    ).count() or 0

    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    # Handle cases where a payment's user might have been deleted (outerjoin)
    recent_payments = db.session.query(Payment, User.name.label('user_name')) \
                                .outerjoin(User, Payment.user_id == User.id) \
                                .filter(Payment.status == 'paid') \
                                .order_by(Payment.created_at.desc()).limit(5).all()
    
    revenue_trend = db.session.query(
        cast(Payment.created_at, Date).label('date'),
        func.sum(Payment.amount).label('daily_revenue')
    ).filter(
        Payment.status == 'paid',
        Payment.created_at >= thirty_days_ago
    ).group_by(cast(Payment.created_at, Date)).order_by('date').all()

    return jsonify({
        'kpi': {
            'total_users': total_users,
            'new_users_30d': new_users_30d,
            'total_certificates': total_certificates,
            'new_certs_30d': new_certs_30d,
            'total_revenue': float(total_revenue),
            'revenue_30d': float(revenue_30d),
            'revenue_today': float(revenue_today),
            'revenue_this_month': float(revenue_this_month),
            'total_companies': total_companies,
            'active_companies_30d': active_companies_30d,
            'avg_certs_user': avg_certs_user,
            'failed_payments_30d': failed_payments_count,
            'expired_subs_count': expired_subs_count
        },
        'revenue_by_plan': revenue_by_plan,
        'recent_users': [
            {'id': u.id, 'name': u.name, 'email': u.email, 'date': u.created_at.isoformat()}
            for u in recent_users
        ],
        'recent_payments': [
            {'id': p.id, 'user_name': user_name or "Deleted User", 'amount': float(p.amount), 'plan': p.plan, 'date': p.created_at.isoformat()}
            for p, user_name in recent_payments
        ],
        'revenue_trend_30d': [
            {'date': r.date.isoformat(), 'revenue': float(r.daily_revenue)}
            for r in revenue_trend
        ]
    }), 200

@admin_analytics_bp.route('/analytics/insights', methods=['GET'])
@jwt_required()
def get_analytics():
    if not isinstance(current_user, Admin):
        return jsonify({"msg": "Admin access required"}), 403

    total_users = User.query.count() or 0
    total_certificates = Certificate.query.count() or 0
    total_companies = Company.query.count() or 0
    total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == 'paid').scalar() or 0.0
    
    kpi_stats = {
        'total_users': total_users,
        'total_certificates': total_certificates,
        'total_revenue': float(total_revenue),
        'avg_certs_per_user': round(total_certificates / total_users if total_users > 0 else 0, 2),
        'total_companies': total_companies,
    }

    period = request.args.get('period', '1y')
    end_date = datetime.utcnow()
    
    if period == '30d':
        start_date = end_date - timedelta(days=30)
    elif period == '90d':
        start_date = end_date - timedelta(days=90)
    elif period == 'all':
        start_date = None
    else: 
        start_date = end_date - relativedelta(months=12)

    user_growth_query = db.session.query(
        extract('year', User.created_at).label('year'),
        extract('month', User.created_at).label('month'),
        func.count(User.id).label('count')
    ).group_by('year', 'month').order_by('year', 'month')

    cert_growth_query = db.session.query(
        extract('year', Certificate.created_at).label('year'),
        extract('month', Certificate.created_at).label('month'),
        func.count(Certificate.id).label('count')
    ).group_by('year', 'month').order_by('year', 'month')
    
    revenue_growth_query = db.session.query(
        extract('year', Payment.created_at).label('year'),
        extract('month', Payment.created_at).label('month'),
        func.sum(Payment.amount).label('total')
    ).filter(Payment.status == 'paid').group_by('year', 'month').order_by('year', 'month')

    if start_date:
        user_growth_query = user_growth_query.filter(User.created_at >= start_date)
        cert_growth_query = cert_growth_query.filter(Certificate.created_at >= start_date)
        revenue_growth_query = revenue_growth_query.filter(Payment.created_at >= start_date)

    user_growth = user_growth_query.all()
    cert_growth = cert_growth_query.all()
    revenue_growth = revenue_growth_query.all()
    
    plan_dist = db.session.query(User.role, func.count(User.id).label('count')).group_by(User.role).all()
    top_users = db.session.query(
        User.name, func.count(Certificate.id).label('cert_count')
    ).join(Certificate, User.id == Certificate.user_id).group_by(User.name).order_by(func.count(Certificate.id).desc()).limit(5).all()

    top_companies = db.session.query(
        Company.name, func.count(Certificate.id).label('cert_count')
    ).join(Certificate, Company.id == Certificate.company_id).group_by(Company.name).order_by(func.count(Certificate.id).desc()).limit(5).all()

    return jsonify({
        'kpi_stats': kpi_stats,
        'user_growth': [{'year': int(g.year), 'month': int(g.month), 'count': g.count} for g in user_growth],
        'cert_growth': [{'year': int(g.year), 'month': int(g.month), 'count': g.count} for g in cert_growth],
        'revenue_growth': [{'year': int(r.year), 'month': int(r.month), 'total': float(r.total)} for r in revenue_growth],
        'plan_distribution': [{'role': p.role, 'count': p.count} for p in plan_dist],
        'top_users': [{'name': u.name, 'cert_count': u.cert_count} for u in top_users],
        'top_companies': [{'name': c.name, 'cert_count': c.cert_count} for c in top_companies]
    }), 200