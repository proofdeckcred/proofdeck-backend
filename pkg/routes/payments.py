import os
import requests
import hmac
import uuid
import hashlib
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Payment
from datetime import datetime, timedelta
import json

payments_bp = Blueprint('payments', __name__)

PAYSTACK_API_URL = "https://api.paystack.co"

PLANS = {
    "starter": {"amount_ngn": 25000, "amount_usd": 18.00, "certificates": 500, "role": "starter"},
    "growth": {"amount_ngn": 60000, "amount_usd": 42.00, "certificates": 2000, "role": "growth"},
    "pro": {"amount_ngn": 100000, "amount_usd": 70.00, "certificates": 5000, "role": "pro"},
    "enterprise": {"amount_ngn": 300000, "amount_usd": 200.00, "certificates": 20000, "role": "enterprise"}
}

role_order = {
    'free': 0,
    'starter': 1,
    'growth': 2,
    'pro': 3,
    'enterprise': 4
}

def get_usd_to_ngn_rate():
    try:
        response = requests.get('https://api.exchangerate-api.com/v4/latest/USD')
        response.raise_for_status()
        data = response.json()
        rate = data.get('rates', {}).get('NGN')
        if rate:
            return rate
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Could not fetch exchange rate: {e}")
    return 1500.0 

def fulfill_payment(payment):
    """Upgrades the user's role and adds certificate quota upon successful payment."""
    if not payment or payment.status == 'paid':
        return
    payment.status = 'paid'
    user = User.query.get(payment.user_id)
    if user:
        plan_details = PLANS.get(payment.plan, {})
        if plan_details:
            user.cert_quota = (user.cert_quota or 0) + plan_details.get('certificates', 0)
            user.role = plan_details.get('role', user.role)
            if hasattr(user, 'owned_tenant') and user.owned_tenant:
                user.owned_tenant.cert_quota = (user.owned_tenant.cert_quota or 0) + plan_details.get('certificates', 0)
    db.session.commit()

@payments_bp.route('/initialize', methods=['POST'])
@jwt_required()
def initialize_payment():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    plan = data.get('plan')
    provider = data.get('provider', 'paystack').lower()
    
    if plan not in PLANS:
        return jsonify({"msg": "Invalid plan"}), 400
    user = User.query.get(user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404
    
    plan_details = PLANS[plan]
    unique_suffix = f"{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:6]}"
    transaction_ref = f"PD_{user_id}_{plan}_{unique_suffix}"
    
    if provider == 'bachs':
        bachs_key = current_app.config.get('BACHS_SECRET_KEY', '').strip()
        if not bachs_key:
            return jsonify({"msg": "Bachs payment gateway is not configured."}), 500
        
        base_url = "https://sandbox-api.bachs.io" if bachs_key.startswith("sk_sandbox_") else "https://api.bachs.io"
        frontend_url = (current_app.config.get('FRONTEND_URL') or "https://proofdeck.app").rstrip('/')
        
        success_url = f"{frontend_url}/dashboard/settings?payment=success&provider=bachs&reference={transaction_ref}"
        cancel_url = f"{frontend_url}/dashboard/settings?payment=cancelled&provider=bachs"
        
        bachs_payload = {
            "pricing": {
                "currency": "USD",
                "amount": f"{plan_details['amount_usd']:.2f}",
                "currency_options": {
                    "NGN": f"{plan_details['amount_ngn']:.2f}"
                }
            },
            "customer": {
                "email": user.email,
                "name": user.name or user.email
            },
            "reference": transaction_ref,
            "metadata": {
                "user_id": str(user_id),
                "plan": plan,
                "amount_usd": str(plan_details['amount_usd'])
            },
            "success_url": success_url,
            "cancel_url": cancel_url
        }
        
        headers = {
            "Authorization": f"Bearer {bachs_key}",
            "Content-Type": "application/json"
        }
        
        try:
            res = requests.post(f"{base_url}/v1/checkout-sessions", json=bachs_payload, headers=headers, timeout=20)
            if not res.ok:
                current_app.logger.error(f"Bachs checkout creation error: {res.status_code} - {res.text}")
                error_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("detail") or "Failed to initiate Bachs checkout."
                return jsonify({"msg": error_msg}), 400
            
            res_data = res.json()
            
            new_payment = Payment(
                user_id=user_id,
                provider='bachs',
                plan=plan,
                amount=plan_details['amount_usd'],
                currency='USD',
                status='pending',
                transaction_ref=transaction_ref
            )
            db.session.add(new_payment)
            db.session.commit()
            
            return jsonify({
                "provider": "bachs",
                "checkout_url": res_data.get("checkout_url"),
                "checkout_id": res_data.get("checkout_id"),
                "reference": transaction_ref,
                "amount": plan_details['amount_usd'],
                "currency": "USD",
                "metadata": { "user_id": user_id, "plan": plan, "amount_usd": plan_details['amount_usd'] }
            }), 200
            
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Bachs request failed: {e}")
            return jsonify({"msg": "Unable to connect to Bachs payment server."}), 500
        except Exception as e:
            current_app.logger.error(f"Unexpected error during Bachs init: {e}")
            return jsonify({"msg": "Internal error setting up checkout."}), 500

    else:
        # Default: Paystack provider
        paystack_key = current_app.config.get('PAYSTACK_SECRET_KEY', '')
        is_ngn_account = paystack_key.startswith('sk_test_') or paystack_key.startswith('sk_live_')

        if is_ngn_account:
            amount_to_charge = int(plan_details['amount_ngn'] * 100) # In Kobo
            currency_to_charge = "NGN"
            amount_in_usd = plan_details['amount_usd']
        else:
            amount_to_charge = int(plan_details['amount_usd'] * 100) # In Cents
            currency_to_charge = "USD"
            amount_in_usd = plan_details['amount_usd']
        
        new_payment = Payment(
            user_id=user_id,
            provider='paystack',
            plan=plan,
            amount=amount_in_usd,
            currency='USD',
            status='pending',
            transaction_ref=transaction_ref
        )
        db.session.add(new_payment)
        db.session.commit()

        return jsonify({
            "provider": "paystack",
            "email": user.email,
            "amount": amount_to_charge,
            "reference": transaction_ref,
            "currency": currency_to_charge,
            "publicKey": current_app.config.get('PAYSTACK_PUBLIC_KEY'),
            "metadata": { "user_id": user_id, "plan": plan, "amount_usd": amount_in_usd }
        }), 200

@payments_bp.route('/verify/<string:reference>', methods=['GET'])
@jwt_required()
def verify_payment(reference):
    user_id = int(get_jwt_identity())
    payment = Payment.query.filter_by(transaction_ref=reference, user_id=user_id).first()
    
    if not payment:
        return jsonify({"msg": "Transaction reference not found."}), 404
        
    # If already verified (e.g. by webhook), return success immediately
    if payment.status == 'paid':
        return jsonify({"msg": "Payment already verified successfully.", "status": "paid"}), 200

    if payment.provider == 'bachs':
        bachs_key = current_app.config.get('BACHS_SECRET_KEY', '').strip()
        base_url = "https://sandbox-api.bachs.io" if bachs_key.startswith("sk_sandbox_") else "https://api.bachs.io"
        headers = {
            "Authorization": f"Bearer {bachs_key}",
            "Content-Type": "application/json"
        }
        try:
            # Query payments by client reference
            response = requests.get(f"{base_url}/v1/payments", params={"reference": reference}, headers=headers, timeout=20)
            if response.ok:
                data = response.json()
                items = data.get("items", [])
                for item in items:
                    if item.get("status") == "succeeded":
                        fulfill_payment(payment)
                        return jsonify({"msg": "Payment successful. Account upgraded and credits added.", "status": "paid"}), 200
            
            return jsonify({"msg": "Payment verification pending or not completed.", "status": payment.status}), 400
        except Exception as e:
            current_app.logger.error(f"Bachs verification error: {e}")
            return jsonify({"msg": "Could not verify payment with Bachs."}), 500

    else:
        # Paystack verification
        headers = {
            "Authorization": f"Bearer {current_app.config.get('PAYSTACK_SECRET_KEY')}",
        }
        
        try:
            response = requests.get(f"{PAYSTACK_API_URL}/transaction/verify/{reference}", headers=headers, timeout=20)
            response.raise_for_status()
            response_data = response.json()
            
            if response_data['data']['status'] == 'success':
                fulfill_payment(payment)
                return jsonify({"msg": "Payment successful. Account upgraded and credits added.", "status": "paid"}), 200
            
            return jsonify({"msg": "Payment verification failed or still pending.", "status": response_data['data']['status']}), 400

        except requests.exceptions.HTTPError as e:
            current_app.logger.error(f"Paystack API Error: {e.response.text}")
            return jsonify({"msg": "Could not verify payment with provider."}), 500
        except Exception as e:
            current_app.logger.error(f"Verification Error: {e}")
            return jsonify({"msg": "An unexpected error occurred during verification."}), 500

@payments_bp.route('/webhook', methods=['POST'])
def paystack_webhook():
    secret_key = current_app.config.get('PAYSTACK_SECRET_KEY')
    payload = request.data
    signature = request.headers.get('x-paystack-signature')
    
    if secret_key and signature:
        try:
            hash_ = hmac.new(secret_key.encode('utf-8'), payload, hashlib.sha512).hexdigest()
            if not hmac.compare_digest(hash_, signature):
                return jsonify({"status": "error", "msg": "Invalid signature"}), 400
        except Exception as e:
            return jsonify({"status": "error", "msg": "Signature verification failed"}), 400
    
    event = json.loads(payload)
    
    if event.get('event') == 'charge.success':
        reference = event.get('data', {}).get('reference')
        if reference:
            payment = Payment.query.filter_by(transaction_ref=reference).first()
            if payment:
                fulfill_payment(payment)
    
    return jsonify({"status": "ok"}), 200

@payments_bp.route('/bachs/webhook', methods=['POST'])
@payments_bp.route('/webhook/bachs', methods=['POST'])
def bachs_webhook():
    secret_key = current_app.config.get('BACHS_WEBHOOK_SECRET')
    payload_bytes = request.get_data()
    timestamp = request.headers.get('X-Bachs-Timestamp')
    signature = request.headers.get('X-Bachs-Signature')
    
    if secret_key:
        if not timestamp or not signature:
            current_app.logger.warning("Bachs webhook missing signature headers")
            return jsonify({"status": "error", "msg": "Missing signature headers"}), 400
        
        try:
            if abs(datetime.utcnow().timestamp() - int(timestamp)) > 300:
                return jsonify({"status": "error", "msg": "Timestamp expired"}), 400
        except ValueError:
            return jsonify({"status": "error", "msg": "Invalid timestamp format"}), 400
        
        try:
            message = f"{timestamp}.{payload_bytes.decode('utf-8')}"
            expected_sig = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_sig, signature):
                return jsonify({"status": "error", "msg": "Invalid Bachs signature"}), 400
        except Exception as e:
            current_app.logger.error(f"Bachs signature verification exception: {e}")
            return jsonify({"status": "error", "msg": "Signature verification failed"}), 400
    
    try:
        event = json.loads(payload_bytes.decode('utf-8'))
    except Exception as e:
        return jsonify({"status": "error", "msg": "Invalid JSON payload"}), 400
    
    event_type = event.get('type')
    event_data = event.get('data', {})
    
    current_app.logger.info(f"Received Bachs webhook event: {event_type}")
    
    if event_type in ['collection.succeeded', 'checkout.completed']:
        reference = event_data.get('reference')
        checkout_id = event_data.get('checkout_id')
        
        payment = None
        if reference:
            payment = Payment.query.filter_by(transaction_ref=reference).first()
        
        if payment:
            fulfill_payment(payment)
            current_app.logger.info(f"Successfully fulfilled payment for reference {reference}")
        else:
            current_app.logger.warning(f"Payment with reference {reference} or checkout_id {checkout_id} not found in DB")
            
    return jsonify({"status": "ok"}), 200