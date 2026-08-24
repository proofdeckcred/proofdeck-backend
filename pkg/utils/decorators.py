from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import User

def admin_required():
    """
    A custom decorator that verifies the JWT is present and the user has the 'admin' role.
    """
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = User.query.get(current_user_id)
            if user and user.role == 'admin':
                return fn(*args, **kwargs)
            else:
                return jsonify({"msg": "Admins only!"}), 403
        return decorator
    return wrapper