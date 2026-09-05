from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, BackgroundJob

jobs_bp = Blueprint('jobs', __name__)

@jobs_bp.route('', methods=['GET'], strict_slashes=False)
@jobs_bp.route('/', methods=['GET'], strict_slashes=False)
@jwt_required()
def list_jobs():
    user_id = int(get_jwt_identity())
    jobs = BackgroundJob.query.filter_by(user_id=user_id).order_by(BackgroundJob.created_at.desc()).limit(20).all()
    
    return jsonify({
        'jobs': [_serialize_job(j) for j in jobs]
    }), 200

@jobs_bp.route('/<int:job_id>', methods=['GET'], strict_slashes=False)
@jwt_required()
def get_job(job_id):
    user_id = int(get_jwt_identity())
    j = BackgroundJob.query.get_or_404(job_id)
    
    if j.user_id != user_id:
        return jsonify({"msg": "Permission denied"}), 403
        
    return jsonify(_serialize_job(j)), 200


def _serialize_job(j):
    total = j.total_items or 0
    done = (j.processed_items or 0) + (j.failed_items or 0)
    percentage = round(done / total * 100, 2) if total > 0 else 0

    return {
        'id': j.id,
        'celery_task_id': j.celery_task_id,
        'job_type': j.job_type,
        'status': j.status,
        'total_items': total,
        'processed_items': j.processed_items or 0,
        'failed_items': j.failed_items or 0,
        'result_summary': j.result_summary,
        'created_at': j.created_at.isoformat(),
        'updated_at': j.updated_at.isoformat() if j.updated_at else None,
        'completed_at': j.completed_at.isoformat() if j.completed_at else None,
        'percentage': percentage
    }
