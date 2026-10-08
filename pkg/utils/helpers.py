from datetime import datetime, timedelta
import pandas as pd
import re

def parse_smart_date(date_value):
    """
    Intelligently parses dates from various formats:
    1. Excel Serial Dates (e.g., 45587)
    2. ISO Strings (2025-12-25)
    3. Common formats (12/25/2025, 25 Dec 2025)
    4. Pandas Timestamps
    """
    if pd.isna(date_value) or date_value == '':
        return datetime.utcnow().date()

    # 1. Handle Excel Serial Dates (Int/Float)
    if isinstance(date_value, (int, float)):
        # Excel base date is roughly Dec 30, 1899
        try:
            return (datetime(1899, 12, 30) + timedelta(days=date_value)).date()
        except Exception:
            return datetime.utcnow().date()

    # 2. Handle Pandas Timestamp
    if isinstance(date_value, (pd.Timestamp, datetime)):
        return date_value.date()

    # 3. Handle Strings
    s = str(date_value).strip()
    
    # Try ISO format
    try:
        return datetime.strptime(s.split('T')[0], "%Y-%m-%d").date()
    except ValueError:
        pass

    # Try common variations
    formats = [
        "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
        "%b %d, %Y", "%d %b %Y", "%B %d, %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    # If fuzzy logic is needed later, we can add it here.
    # For now, return current date or raise error depending on strictness.
    # We default to today to prevent total failure, but logging would be good.
    return datetime.utcnow().date()

def normalize_email(email):
    if not email or pd.isna(email):
        return None
    return str(email).strip().lower()

def normalize_headers(df, custom_mapping=None, batch_defaults=None):
    """
    Smartly renames columns to match database requirements using synonyms,
    custom mappings, split name auto-merge, and batch defaults.
    """
    if df.empty:
        return df

    # If custom mapping is provided (dict of source_col -> target_col)
    if custom_mapping and isinstance(custom_mapping, dict):
        rename_map = {}
        for src_col, target_field in custom_mapping.items():
            if target_field and target_field != "ignore" and src_col in df.columns:
                rename_map[src_col] = target_field
        if rename_map:
            df = df.rename(columns=rename_map)

    # Normalize existing columns to lowercase/snake_case
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

    # Map of System Field -> Expanded Generous Synonyms
    synonyms = {
        "recipient_name": [
            "name", "student", "student_name", "full_name", "recipient", "participant",
            "attendee", "employee", "candidate", "awardee", "learner", "trainee",
            "graduate", "member", "pupil", "scholar", "person", "delegate", "inductee",
            "honoree", "participant_name", "learner_name", "employee_name", "recipient_name"
        ],
        "recipient_email": [
            "email", "email_address", "mail", "contact", "contact_email", "user_email",
            "recipient_email", "attendee_email", "student_email", "electronic_mail", "email_id", "e_mail"
        ],
        "course_title": [
            "course", "program", "programme", "event", "title", "certification",
            "award", "achievement", "description", "training", "workshop", "certificate_title",
            "class", "subject", "topic", "course_title", "program_name", "webinar",
            "bootcamp", "degree", "diploma", "track", "module", "training_title", "course_name"
        ],
        "issue_date": [
            "date", "issued_on", "award_date", "completion_date", "date_issued",
            "graduation_date", "awarded_on", "date_completed", "issue_date", "event_date",
            "finish_date", "cert_date", "given_date"
        ],
        "issuer_name": [
            "issuer", "organization", "organisation", "school", "company", "signed_by",
            "institution", "academy", "facilitator", "university", "college", "provider",
            "authority", "certifier", "issued_by"
        ],
        "signature": [
            "sign", "signature_text", "auth_sign", "signature", "signed_by", "signatory",
            "director", "principal", "ceo", "authorized_by", "instructor", "dean", "president"
        ],
        "amount": ["amount", "cost", "price", "fee", "payment", "total"]
    }

    # Rename based on synonyms
    new_columns = {}
    for col in df.columns:
        for standard_key, variations in synonyms.items():
            if col == standard_key or col in variations:
                new_columns[col] = standard_key
                break
    
    if new_columns:
        df = df.rename(columns=new_columns)

    # Automatic Split Name merging: First Name + Last Name -> recipient_name
    if 'recipient_name' not in df.columns:
        first_cols = [c for c in df.columns if c in ['first_name', 'firstname', 'given_name', 'first', 'fname']]
        last_cols = [c for c in df.columns if c in ['last_name', 'lastname', 'surname', 'family_name', 'last', 'lname']]
        if first_cols and last_cols:
            f_col = first_cols[0]
            l_col = last_cols[0]
            f_series = df[f_col].fillna('').astype(str).str.strip()
            l_series = df[l_col].fillna('').astype(str).str.strip()
            df['recipient_name'] = (f_series + ' ' + l_series).str.strip()

    # Apply batch defaults for missing or blank optional fields
    if batch_defaults and isinstance(batch_defaults, dict):
        for field in ['issuer_name', 'issue_date', 'signature']:
            default_val = batch_defaults.get(field)
            if default_val:
                if field not in df.columns:
                    df[field] = default_val
                else:
                    df[field] = df[field].fillna(default_val)
                    df.loc[df[field].astype(str).str.strip() == '', field] = default_val

    return df

def get_active_context(user):
    """
    Returns (is_tenant_mode, tenant_id, quota_holder, active_role) based on the X-Workspace-Context header.
    """
    from flask import request
    from ..models import Tenant, Membership
    ws = request.headers.get('X-Workspace-Context', 'personal')
    
    try:
        tenant_id = int(ws)
    except ValueError:
        tenant_id = None
        
    if tenant_id is not None:
        membership = Membership.query.filter_by(user_id=user.id, tenant_id=tenant_id, status='active').first()
        if membership:
            active_tenant = Tenant.query.get(tenant_id)
            if active_tenant:
                return True, tenant_id, active_tenant, membership.role
            
    return False, None, user, None

def is_enterprise_context(user):
    """
    Returns True if the current user or active workspace organization is on the Enterprise plan.
    Works for both individual enterprise accounts and invited team members in an enterprise workspace.
    Honors 12-month validity with a 60-day grace period before expiration lock.
    """
    if not user:
        return False
    is_comp, tenant_id, quota_holder, _ = get_active_context(user)
    
    target_user = user
    if is_comp and quota_holder:
        owner = getattr(quota_holder, 'owner', None)
        if owner:
            target_user = owner

    if str(getattr(target_user, 'role', '')).lower() == 'enterprise':
        # Check annual subscription expiry if set
        expiry = getattr(target_user, 'subscription_expiry', None)
        if expiry:
            grace_period_end = expiry + timedelta(days=60)
            if datetime.utcnow() > grace_period_end:
                return False
        return True
    return False

def get_certificate_verification_url(certificate_or_id):
    """
    Returns the canonical verification URL for a certificate.
    Prefers the issuer organization's active custom domain (e.g. https://credentials.myorg.com/verify/UUID)
    if configured, otherwise defaults to the platform URL (e.g. https://www.proofdeck.app/verify/UUID).
    """
    from flask import current_app
    verification_id = None
    tenant = None

    if hasattr(certificate_or_id, 'verification_id'):
        verification_id = certificate_or_id.verification_id
        tenant = getattr(certificate_or_id, 'tenant', None)
        if not tenant and getattr(certificate_or_id, 'tenant_id', None):
            try:
                from ..models import Tenant
                tenant = Tenant.query.get(certificate_or_id.tenant_id)
            except Exception:
                tenant = None
    else:
        verification_id = str(certificate_or_id)

    if tenant and getattr(tenant, 'custom_domain', None) and getattr(tenant, 'domain_status', None) == 'active':
        return f"https://{tenant.custom_domain}/verify/{verification_id}"

    frontend_url = current_app.config.get('FRONTEND_URL', 'https://www.proofdeck.app').rstrip('/')
    return f"{frontend_url}/verify/{verification_id}"