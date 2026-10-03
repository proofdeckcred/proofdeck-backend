import os
import requests
import logging
from flask import current_app

logger = logging.getLogger(__name__)

def _get_headers():
    token = current_app.config.get('CLOUDFLARE_API_TOKEN') or os.getenv('CLOUDFLARE_API_TOKEN')
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def _get_zone_id():
    return current_app.config.get('CLOUDFLARE_ZONE_ID') or os.getenv('CLOUDFLARE_ZONE_ID')

def create_custom_hostname(domain: str):
    """
    Registers a new custom hostname in Cloudflare for SaaS.
    """
    zone_id = _get_zone_id()
    if not zone_id:
        raise ValueError("CLOUDFLARE_ZONE_ID is not configured")

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/custom_hostnames"
    payload = {
        "hostname": domain.lower().strip(),
        "ssl": {
            "method": "http",
            "type": "dv",
            "settings": {
                "min_tls_version": "1.2"
            }
        }
    }

    try:
        response = requests.post(url, json=payload, headers=_get_headers(), timeout=15)
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            error_msg = "; ".join([e.get("message", "Unknown error") for e in errors])
            logger.error(f"Cloudflare create_custom_hostname error: {error_msg}")
            return {"success": False, "error": error_msg, "details": data}
        
        return {"success": True, "result": data.get("result", {})}
    except Exception as e:
        logger.error(f"Cloudflare API connection failed: {e}")
        return {"success": False, "error": str(e)}

def get_custom_hostname_status(hostname_id: str):
    """
    Fetches live verification & SSL status for a custom hostname from Cloudflare.
    """
    zone_id = _get_zone_id()
    if not zone_id:
        raise ValueError("CLOUDFLARE_ZONE_ID is not configured")

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/custom_hostnames/{hostname_id}"
    try:
        response = requests.get(url, headers=_get_headers(), timeout=15)
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            error_msg = "; ".join([e.get("message", "Unknown error") for e in errors])
            return {"success": False, "error": error_msg}

        result = data.get("result", {})
        hostname_status = result.get("status") # 'active', 'pending', etc.
        ssl_status = result.get("ssl", {}).get("status") # 'active', 'initializing', 'pending_validation'

        is_active = (hostname_status == "active" and ssl_status == "active")

        return {
            "success": True,
            "is_active": is_active,
            "hostname_status": hostname_status,
            "ssl_status": ssl_status,
            "ownership_verification": result.get("ownership_verification"),
            "ssl_validation_records": result.get("ssl", {}).get("validation_records"),
            "result": result
        }
    except Exception as e:
        logger.error(f"Cloudflare get_custom_hostname_status error: {e}")
        return {"success": False, "error": str(e)}

def delete_custom_hostname(hostname_id: str):
    """
    Removes a custom hostname from Cloudflare when a tenant detaches or changes their domain.
    """
    zone_id = _get_zone_id()
    if not zone_id:
        return {"success": False, "error": "CLOUDFLARE_ZONE_ID not configured"}

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/custom_hostnames/{hostname_id}"
    try:
        response = requests.delete(url, headers=_get_headers(), timeout=15)
        data = response.json()
        return {"success": data.get("success", False), "result": data}
    except Exception as e:
        logger.error(f"Cloudflare delete_custom_hostname error: {e}")
        return {"success": False, "error": str(e)}
