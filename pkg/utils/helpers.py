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

def normalize_headers(df):
    """
    Smartly renames columns to match database requirements using synonyms.
    """
    # Map of System Field -> Possible User Inputs
    synonyms = {
        "recipient_name": ["name", "student", "student_name", "full_name", "recipient", "participant", "attendee"],
        "recipient_email": ["email", "email_address", "mail", "contact"],
        "course_title": ["course", "program", "event", "title", "certification", "award", "description"],
        "issue_date": ["date", "issued_on", "award_date", "completion_date", "date_issued"],
        "issuer_name": ["issuer", "organization", "school", "company", "signed_by"],
        "signature": ["sign", "signature_text", "auth_sign"],
        "amount": ["amount", "cost", "price", "fee", "payment", "total"]
    }

    # Normalize user columns to lowercase/snake_case
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

    # Rename based on synonyms
    new_columns = {}
    for col in df.columns:
        for standard_key, variations in synonyms.items():
            if col == standard_key or col in variations:
                new_columns[col] = standard_key
                break
    
    return df.rename(columns=new_columns)