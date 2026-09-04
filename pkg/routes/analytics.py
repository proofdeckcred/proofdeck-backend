# backend/pkg/routes/analytics.py

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, current_user
from ..models import Certificate, User, db, Template, Group
from sqlalchemy import func, distinct
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import calendar
from ..utils.helpers import get_active_context

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/dashboard', methods=['GET'])
@jwt_required()
def get_user_performance_insights():
    user = current_user

    # For free users, return a specific payload to trigger the upgrade prompt on the frontend.
    if user.role == 'free':
        return jsonify({"upgrade_required": True}), 200

    # Resolve active workspace context
    is_comp, tenant_id, _, _ = get_active_context(user)
    
    if is_comp:
        cert_filter = (Certificate.tenant_id == tenant_id)
        template_filter = (Template.tenant_id == tenant_id)
        group_filter = (Group.tenant_id == tenant_id)
    else:
        cert_filter = (Certificate.user_id == user.id) & (Certificate.tenant_id.is_(None))
        template_filter = (Template.user_id == user.id) & (Template.tenant_id.is_(None))
        group_filter = (Group.user_id == user.id) & (Group.tenant_id.is_(None))

    # --- 1. GATHER CORE METRICS ---
    total_certs_user = db.session.query(func.count(Certificate.id))\
        .filter(cert_filter).scalar() or 0

    total_programs_user = db.session.query(func.count(distinct(Certificate.course_title)))\
        .filter(cert_filter).scalar() or 0
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    certs_last_30d_user = db.session.query(func.count(Certificate.id)).filter(
        cert_filter,
        Certificate.created_at >= thirty_days_ago
    ).scalar() or 0

    # --- 2. GATHER PEER BENCHMARK METRICS ---
    peer_stats_subquery = db.session.query(
        User.id,
        func.count(distinct(Certificate.id)).label('total_certs'),
        func.count(distinct(Certificate.course_title)).label('total_programs')
    ).join(Certificate, User.id == Certificate.user_id, isouter=True)\
    .filter(User.role == user.role)\
    .group_by(User.id).subquery()

    peer_averages = db.session.query(
        func.avg(peer_stats_subquery.c.total_certs).label('avg_certs'),
        func.avg(peer_stats_subquery.c.total_programs).label('avg_programs')
    ).one()

    avg_certs_peer = float(peer_averages.avg_certs or 0)
    avg_programs_peer = float(peer_averages.avg_programs or 0)
    
    # --- 3. CALCULATE PERCENTILE RANK ---
    peers_with_fewer_certs = db.session.query(func.count(peer_stats_subquery.c.id))\
        .filter(peer_stats_subquery.c.total_certs < total_certs_user).scalar() or 0
    total_peers = db.session.query(func.count(User.id)).filter(User.role == user.role).scalar() or 1
    percentile_rank = (peers_with_fewer_certs / total_peers) * 100 if total_peers > 0 else 0

    # --- 4. CALCULATE ISSUER PERFORMANCE SCORE ---
    norm_certs = min((total_certs_user / (avg_certs_peer * 2)) * 100, 100) if avg_certs_peer > 0 else (100 if total_certs_user > 0 else 0)
    norm_programs = min((total_programs_user / (avg_programs_peer * 2)) * 100, 100) if avg_programs_peer > 0 else (100 if total_programs_user > 0 else 0)
    norm_recent_activity = min((certs_last_30d_user / 50) * 100, 100)
    performance_score = (norm_certs * 0.5) + (norm_programs * 0.3) + (norm_recent_activity * 0.2)

    # --- 5. CERTIFICATES OVER TIME ---
    twelve_months_ago = datetime.utcnow() - relativedelta(months=11)
    start_of_month = twelve_months_ago.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    issuance_by_month_query = db.session.query(
        func.extract('year', Certificate.created_at).label('year'),
        func.extract('month', Certificate.created_at).label('month'),
        func.count(Certificate.id).label('count')
    ).filter(
        cert_filter,
        Certificate.created_at >= start_of_month
    ).group_by('year', 'month').order_by('year', 'month').all()
    issuance_map = {(r.year, r.month): r.count for r in issuance_by_month_query}
    certs_over_time = {'labels': [], 'data': []}
    current_date = datetime.utcnow()
    for i in range(12):
        month_date = current_date - relativedelta(months=11-i)
        certs_over_time['labels'].append(f"{calendar.month_abbr[month_date.month]} {month_date.year}")
        certs_over_time['data'].append(issuance_map.get((month_date.year, month_date.month), 0))

    # --- 6. TOP 5 PROGRAMS ---
    top_programs_query = db.session.query(
        Certificate.course_title,
        func.count(Certificate.id).label('count')
    ).filter(
        cert_filter
    ).group_by(Certificate.course_title).order_by(func.count(Certificate.id).desc()).limit(5).all()

    # Certificate Status Breakdown
    status_query = db.session.query(
        Certificate.status,
        func.count(Certificate.id).label('count')
    ).filter(
        cert_filter
    ).group_by(Certificate.status).all()
    status_breakdown = {
        "labels": [s.status for s in status_query],
        "data": [s.count for s in status_query]
    }

    # Top Recipients
    top_recipient_query = db.session.query(
        Certificate.recipient_name,
        func.count(Certificate.id).label('count')
    ).filter(
        cert_filter
    ).group_by(Certificate.recipient_name).order_by(func.count(Certificate.id).desc()).limit(5).all()
    top_recipient = {
        "labels": [r.recipient_name for r in top_recipient_query],
        "data": [r.count for r in top_recipient_query]
    }

    # Template Usage
    template_usage_query = db.session.query(
        Template.title,
        func.count(Certificate.id).label('count')
    ).join(
        Certificate, Certificate.template_id == Template.id
    ).filter(
        template_filter
    ).group_by(Template.id).order_by(func.count(Certificate.id).desc()).limit(5).all()
    template_usage = {
        "labels": [t.title for t in template_usage_query],
        "data": [t.count for t in template_usage_query]
    }

    # Group Stats
    num_groups = db.session.query(func.count(Group.id)).filter(group_filter).scalar() or 0
    subq = db.session.query(
        Group.id,
        func.count(Certificate.id).label('cert_count')
    ).outerjoin(
        Certificate, Certificate.group_id == Group.id
    ).filter(
        group_filter
    ).group_by(Group.id).subquery()
    avg_certs_per_group = db.session.query(func.avg(subq.c.cert_count)).scalar() or 0
    group_stats = {
        "num_groups": num_groups,
        "avg_certs_per_group": round(avg_certs_per_group, 1)
    }

    # Email Metrics
    sent_count = db.session.query(func.count(Certificate.id)).filter(
        cert_filter,
        Certificate.sent_at.isnot(None)
    ).scalar() or 0
    email_metrics = {
        "sent": sent_count,
        "unsent": total_certs_user - sent_count,
        "send_rate": round((sent_count / total_certs_user * 100) if total_certs_user > 0 else 0, 1)
    }

    # Recent Activity Extension
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    certs_last_7d = db.session.query(func.count(Certificate.id)).filter(
        cert_filter,
        Certificate.created_at >= seven_days_ago
    ).scalar() or 0
    recent_activity = {
        "last_7_days": certs_last_7d,
        "last_30_days": certs_last_30d_user
    }

    # Program Insights Table
    program_insights = []
    program_counts = db.session.query(
        Certificate.course_title,
        func.count(Certificate.id).label('issued_count')
    ).filter(cert_filter).group_by(Certificate.course_title).order_by(func.count(Certificate.id).desc()).all()

    for item in program_counts:
        issued = item.issued_count
        cac_credits = issued * 1
        roas_shares = int(issued * 0.85) if issued > 0 else 0
        program_insights.append({
            "name": item.course_title,
            "type": "Credential",
            "issued": issued,
            "cac": f"{cac_credits} Credits",
            "roas": f"{roas_shares} Shares",
            "performance": min(100, max(20, issued * 10))
        })

    verification_clicks_est = total_certs_user * 3
    social_shares_est = int(total_certs_user * 1.4)

    return jsonify({
        "upgrade_required": False,
        "kpis": {
            "performance_score": round(performance_score),
            "percentile_rank": round(percentile_rank),
            "total_certificates": total_certs_user,
            "total_programs": total_programs_user
        },
        "benchmarking": {
            "labels": ["Certificate Volume", "Program Diversity", "Recent Activity"],
            "user_data": [total_certs_user, total_programs_user, certs_last_30d_user],
            "peer_average_data": [round(avg_certs_peer, 1), round(avg_programs_peer, 1), 10]
        },
        "charts": {
            "certs_over_time": certs_over_time,
            "top_programs": {
                "labels": [p.course_title for p in top_programs_query],
                "data": [p.count for p in top_programs_query]
            }
        },
        "status_breakdown": status_breakdown,
        "top_recipient": top_recipient,
        "template_usage": template_usage,
        "group_stats": group_stats,
        "email_metrics": email_metrics,
        "recent_activity": recent_activity,
        "program_insights": program_insights,
        "engagement": {
            "social_shares": social_shares_est,
            "verification_clicks": verification_clicks_est
        }
    }), 200