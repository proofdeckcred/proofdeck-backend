from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt
import shutil
import os
from ..models import User, Certificate, db

admin_system_bp = Blueprint('admin_system', __name__)

def super_admin_required():
    claims = get_jwt()
    if claims.get('role') != 'super_admin':
        return False
    return True

@admin_system_bp.route('/system/stats', methods=['GET'])
@jwt_required()
def get_system_stats():
    """
    Returns lightweight system stats:
    - Disk Usage (for PythonAnywhere quota monitoring)
    - DB Counts (Users, Certs)
    """
    if not super_admin_required():
        return jsonify({"msg": "Access denied"}), 403

    stats = {}

    # 1. Disk Usage
    # On PythonAnywhere, /home/username is the main limit usually. 
    # But generally checking the current working directory's volume is a good proxy.
    try:
        total, used, free = shutil.disk_usage(os.getcwd())
        stats['disk'] = {
            'total_gb': round(total / (2**30), 2),
            'used_gb': round(used / (2**30), 2),
            'free_gb': round(free / (2**30), 2),
            'percent_used': round((used / total) * 100, 1)
        }
    except Exception as e:
        stats['disk'] = {"error": str(e)}

    # 2. Database Stats (Lightweight count)
    try:
        user_count = db.session.query(User).count()
        cert_count = db.session.query(Certificate).count()
        stats['db'] = {
            'users': user_count,
            'certificates': cert_count
        }
    except Exception as e:
        stats['db'] = {"error": str(e)}

    return jsonify(stats), 200
