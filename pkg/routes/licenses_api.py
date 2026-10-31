import os
import hashlib
import platform
import socket
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from ..models import db, EnterpriseLicense, LicenseActivation

licenses_api_bp = Blueprint('licenses_api', __name__)

def _get_request_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

@licenses_api_bp.route('/activate', methods=['POST'])
def activate_workstation():
    """
    Called by the desktop app when the user enters their License Key.
    Verifies key, ensures workstation limit isn't exceeded, registers machine,
    and returns full institution metadata + offline grant token.
    """
    data = request.get_json() or {}
    license_key = (data.get('license_key') or '').strip().upper()
    machine_id = (data.get('machine_id') or '').strip()
    machine_name = (data.get('machine_name') or socket.gethostname()).strip()
    os_name = (data.get('operating_system') or platform.platform()).strip()
    app_version = (data.get('app_version') or '1.0.0').strip()

    if not license_key:
        return jsonify({"msg": "License key is required."}), 400
    if not machine_id:
        # Fallback generate machine_id from request IP + machine_name
        machine_id = hashlib.sha256(f"{machine_name}_{_get_request_ip()}".encode()).hexdigest()[:32]

    lic = EnterpriseLicense.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify({"msg": "Invalid license key. Please check with your administrator."}), 404

    if lic.status != 'active':
        return jsonify({"msg": f"This enterprise license is currently {lic.status}."}), 403

    if lic.expires_at and datetime.utcnow() > lic.expires_at:
        lic.status = 'expired'
        db.session.commit()
        return jsonify({"msg": "This enterprise license has expired. Please contact support or renew."}), 403

    # Check existing activation on this machine
    act = LicenseActivation.query.filter_by(license_id=lic.id, machine_id=machine_id).first()
    if not act:
        active_count = LicenseActivation.query.filter_by(license_id=lic.id, status='active').count()
        if active_count >= lic.max_workstations:
            return jsonify({
                "msg": f"Workstation limit reached ({active_count}/{lic.max_workstations} active machines). Contact support to add seats."
            }), 403

        act = LicenseActivation(
            license_id=lic.id,
            machine_id=machine_id,
            machine_name=machine_name,
            operating_system=os_name,
            app_version=app_version,
            status='active',
            activated_at=datetime.utcnow(),
            last_ping_at=datetime.utcnow(),
            ip_address=_get_request_ip()
        )
        db.session.add(act)
    else:
        act.status = 'active'
        act.machine_name = machine_name
        act.operating_system = os_name
        act.app_version = app_version
        act.last_ping_at = datetime.utcnow()
        act.ip_address = _get_request_ip()

    lic.last_verified_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "success": True,
        "msg": f"License successfully activated for {lic.institution_name}.",
        "license": {
            "key": lic.license_key,
            "institution_name": lic.institution_name,
            "contact_person": lic.contact_person or "",
            "signatory_name": lic.contact_person or "Prof. Academic Registrar",
            "plan_tier": lic.plan_tier,
            "expires_at": lic.expires_at.strftime("%Y-%m-%d"),
            "status": lic.status,
            "max_workstations": lic.max_workstations,
            "modules": {
                "sis_connector": lic.enable_sis_connector,
                "custom_qr": lic.enable_custom_qr,
                "bulk_documents": lic.enable_bulk_documents
            }
        },
        "machine_id": machine_id
    }), 200

@licenses_api_bp.route('/ping', methods=['POST'])
def heartbeat_ping():
    """
    Periodic lightweight background heartbeat ping sent by the desktop app
    whenever an internet connection is detected.
    """
    data = request.get_json() or {}
    license_key = (data.get('license_key') or '').strip().upper()
    machine_id = (data.get('machine_id') or '').strip()
    app_version = (data.get('app_version') or '1.0.0').strip()

    if not license_key or not machine_id:
        return jsonify({"msg": "Missing parameters"}), 400

    lic = EnterpriseLicense.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify({"valid": False, "msg": "License not found"}), 404

    act = LicenseActivation.query.filter_by(license_id=lic.id, machine_id=machine_id).first()
    if act:
        act.last_ping_at = datetime.utcnow()
        act.app_version = app_version
        act.ip_address = _get_request_ip()

    lic.last_verified_at = datetime.utcnow()
    db.session.commit()

    is_active = lic.status == 'active' and (not lic.expires_at or datetime.utcnow() <= lic.expires_at)
    return jsonify({
        "valid": is_active,
        "status": lic.status,
        "expires_at": lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at else None,
        "latest_version": "1.0.0"
    }), 200
