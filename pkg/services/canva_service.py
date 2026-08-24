import requests
import os
import base64
import hashlib
from flask import current_app
from datetime import datetime, timedelta
from urllib.parse import urlencode
from ..models import db, User

CANVA_API_BASE_URL = "https://api.canva.com/v1"

def generate_pkce_pair():
    """Generates a URL-safe PKCE code_verifier and code_challenge."""
    verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8').rstrip('=')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return verifier, challenge

def get_canva_auth_url(user_id):
    """Generates the full Canva authorization URL including PKCE parameters."""
    client_id = current_app.config['CANVA_CLIENT_ID']
    redirect_uri = "https://checkless-tabitha-isagogically.ngrok-free.dev/api/canva/callback" 
    
    verifier, challenge = generate_pkce_pair()

    user = User.query.get(user_id)
    if user:
        user.canva_code_verifier = verifier
        db.session.commit()
    else:
        raise ValueError("User not found for PKCE generation")

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'state': f"user:{user_id}",
        # --- THIS IS THE FINAL FIX ---
        # The scope is 'design:content:write' not 'design.content:write'
        'scope': "asset:read design:content:write design:meta:read",
        # --- END OF FIX ---
        'prompt': 'consent',
        'code_challenge': challenge,
        'code_challenge_method': 'S256'
    }
    
    query_string = urlencode(params)
    return f"https://www.canva.com/api/oauth/authorize?{query_string}"

def exchange_code_for_token(code, user_id):
    """Exchanges the authorization code for an access token, including the code_verifier."""
    client_id = current_app.config['CANVA_CLIENT_ID']
    client_secret = current_app.config['CANVA_CLIENT_SECRET']
    redirect_uri = "https://checkless-tabitha-isagogically.ngrok-free.dev/api/canva/callback"

    user = User.query.get(user_id)
    if not user or not user.canva_code_verifier:
        raise ValueError("Code verifier not found for user")
    
    code_verifier = user.canva_code_verifier

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'client_secret': client_secret,
        'code_verifier': code_verifier
    }
    
    response = requests.post(f"{CANVA_API_BASE_URL}/oauth/token", data=payload)
    response.raise_for_status()

    user.canva_code_verifier = None
    db.session.commit()

    return response.json()

def save_canva_tokens(user_id, token_data):
    user = User.query.get(user_id)
    if not user:
        raise ValueError("User not found")

    user.canva_access_token = token_data['access_token']
    user.canva_refresh_token = token_data.get('refresh_token')
    
    expires_in = token_data.get('expires_in', 3600) 
    user.canva_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    db.session.commit()