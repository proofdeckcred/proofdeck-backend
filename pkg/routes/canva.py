from flask import Blueprint, request, redirect, current_app, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..services.canva_service import get_canva_auth_url, exchange_code_for_token, save_canva_tokens

canva_bp = Blueprint('canva', __name__)

@canva_bp.route('/auth', methods=['GET'])
@jwt_required()
def canva_auth_start():
    user_id = get_jwt_identity()
    try:
        auth_url = get_canva_auth_url(user_id)
        return jsonify({"auth_url": auth_url}), 200
    except Exception as e:
        current_app.logger.error(f"Canva auth URL generation error: {e}")
        return jsonify({"msg": "Could not generate Canva auth URL."}), 500

@canva_bp.route('/callback', methods=['GET'])
def canva_auth_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    
    if not code or not state or not state.startswith("user:"):
        return "Invalid callback request.", 400

    try:
        user_id = int(state.split(':')[1])
        # Pass user_id to the token exchange function
        token_data = exchange_code_for_token(code, user_id)
        save_canva_tokens(user_id, token_data)
        
        frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:5173')
        return redirect(f"{frontend_url}/dashboard/settings?canva_connected=true")

    except Exception as e:
        current_app.logger.error(f"Canva callback error: {e}")
        return "An error occurred during authentication.", 500