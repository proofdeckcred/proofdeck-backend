# backend/pkg/services/ai_column_mapper.py

import os
import re
import json
import time
import hashlib
import difflib
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

# --- CORE CONSTANTS & SYNONYMS (LAYER A) ---
TARGET_FIELDS = {
    "recipient_name": {
        "required": True,
        "description": "Full name of the credential recipient",
        "synonyms": [
            "name", "full name", "student name", "learner", "trainee", "participant",
            "attendee", "employee", "candidate", "awardee", "recipient", "graduate",
            "member", "student", "pupil", "scholar", "person", "delegate", "inductee",
            "honoree", "participant name", "learner name", "employee name", "recipient name",
            "student_full_name", "attendee name", "candidate name", "member name"
        ]
    },
    "recipient_email": {
        "required": True,
        "description": "Email address of recipient for delivery & verification",
        "synonyms": [
            "email", "e-mail", "email address", "mail", "contact email", "user email",
            "recipient email", "attendee email", "student email", "electronic mail",
            "email id", "contact mail", "learner email", "e mail", "emailaddress"
        ]
    },
    "course_title": {
        "required": True,
        "description": "Title of the course, event, training, or certification",
        "synonyms": [
            "course", "programme", "program", "training", "workshop", "certificate title",
            "award", "achievement", "event", "class", "subject", "topic", "course title",
            "program name", "programme name", "certification", "webinar", "bootcamp",
            "boot camp", "degree", "diploma", "track", "module", "event title",
            "training title", "course name", "credential title", "specialization"
        ]
    },
    "issuer_name": {
        "required": False,
        "description": "Issuing organization, school, or authority",
        "synonyms": [
            "issuer", "issued by", "organisation", "organization", "institution", "school",
            "company", "academy", "facilitator", "university", "college", "provider",
            "publisher", "authority", "entity", "certifier", "conferred by", "presented by",
            "issuing body", "training provider", "host", "organizer", "organising body"
        ]
    },
    "issue_date": {
        "required": False,
        "description": "Date of credential issuance or completion",
        "synonyms": [
            "date", "date issued", "completion date", "graduation date", "awarded on",
            "date completed", "issue date", "event date", "end date", "finish date",
            "timestamp", "cert date", "given date", "date of completion", "awarded date",
            "effective date", "date of issue", "passed on"
        ]
    },
    "signature": {
        "required": False,
        "description": "Name or title of authorized signatory",
        "synonyms": [
            "signature", "signed by", "signatory", "director", "principal", "ceo",
            "authorized by", "signatory name", "signature text", "instructor",
            "instructor signature", "dean", "president", "coordinator", "headmaster",
            "head of school", "authorized signatory", "authorized officer", "chairperson"
        ]
    }
}

SPLIT_FIRST_NAME_SYNONYMS = ["first name", "firstname", "given name", "first", "fname", "forename"]
SPLIT_LAST_NAME_SYNONYMS = ["last name", "lastname", "surname", "family name", "last", "lname", "other names", "other name"]


def normalize_string(s: str) -> str:
    """Lowercase, trim, remove special punctuation, collapse spaces."""
    if not s:
        return ""
    # Replace hyphens, underscores, slashes with spaces
    cleaned = re.sub(r'[-_/\\]+', ' ', str(s).strip().lower())
    # Remove remaining punctuation
    cleaned = re.sub(r'[^\w\s]', '', cleaned)
    # Collapse multiple whitespaces
    return re.sub(r'\s+', ' ', cleaned).strip()


def fuzzy_similarity(a: str, b: str) -> float:
    """Calculates string similarity using SequenceMatcher."""
    norm_a = normalize_string(a)
    norm_b = normalize_string(b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio()


# --- VALUE LEVEL INSPECTION ---
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
NAME_REGEX = re.compile(r'^[A-Za-z\u00C0-\u024F\u1E00-\u1EFF\s\'-]{2,50}$')

def looks_like_email(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return bool(EMAIL_REGEX.match(s))

def looks_like_date(val: Any) -> bool:
    if val is None:
        return False
    # Check numeric Excel date serials
    if isinstance(val, (int, float)) and 35000 <= val <= 65000:
        return True
    s = str(val).strip()
    if len(s) < 4 or len(s) > 30:
        return False
    # Check common date patterns
    date_patterns = [
        r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', # 2026-10-08
        r'^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}', # 08/10/2026
        r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2},? \d{4}', # Oct 8, 2026
        r'^\d{1,2} (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}', # 8 Oct 2026
    ]
    for pat in date_patterns:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False

def looks_like_person_name(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    if len(s) < 3 or len(s) > 50 or '@' in s or '/' in s:
        return False
    parts = s.split()
    if 2 <= len(parts) <= 4 and NAME_REGEX.match(s):
        # Check capitalized or titled words
        return True
    return False


# --- SCATTERED SHEET DETECTION & CLEANUP ---
def clean_scattered_sheet_data(rows: List[List[Any]]) -> Tuple[List[str], List[List[Any]], int]:
    """
    Detects if the sheet has title banners, empty rows before headings, or notes at the bottom.
    Returns: (cleaned_headers, cleaned_data_rows, header_row_index)
    """
    if not rows:
        return [], [], 0

    header_index = 0
    max_non_empty = 0

    # Look through first 10 rows to detect the true header row
    for idx, row in enumerate(rows[:10]):
        non_empty_cells = [c for c in row if c is not None and str(c).strip() != '']
        count = len(non_empty_cells)

        # Check if row looks like headers (string cells, multiple distinct values, common keywords)
        text_cells = [str(c).strip() for c in non_empty_cells if not isinstance(c, (int, float))]
        contains_known_kw = any(
            any(syn in normalize_string(tc) for syn in ['name', 'email', 'course', 'date', 'student', 'participant', 'attendee'])
            for tc in text_cells
        )

        if contains_known_kw and count >= 2:
            header_index = idx
            break

        if count > max_non_empty:
            max_non_empty = count
            header_index = idx

    raw_headers = [str(c).strip() if c is not None else f"Column_{i+1}" for i, c in enumerate(rows[header_index])]
    # Give fallback names to blank headers
    headers = [h if h else f"Column_{i+1}" for i, h in enumerate(raw_headers)]

    # Slice data rows starting immediately after the header row
    data_rows = rows[header_index + 1:]

    # Filter out empty rows and trailing summary/notes rows
    cleaned_rows = []
    for r in data_rows:
        non_empty = [c for c in r if c is not None and str(c).strip() != '']
        if not non_empty:
            continue
        first_val = str(non_empty[0]).strip().lower()
        # Drop summary notes like "Total: 50" or "Approved by:"
        if first_val.startswith(('total', 'notes:', 'summary:', 'generated by', 'approved by', 'page ')):
            continue
        cleaned_rows.append(r)

    return headers, cleaned_rows, header_index


# --- LAYER A: RULE-BASED SMART COLUMN MAPPING ---
def infer_mapping_layer_a(headers: List[str], sample_rows: List[List[Any]]) -> Dict[str, Any]:
    """
    Rule-based column mapping (Free, instant, runs for everyone).
    Inspects normalized headings, synonyms, fuzzy matching, and cell values.
    Also detects split first/last names.
    """
    result = {
        "mappings": {},
        "split_names": None,
        "is_confident": True,
        "unmapped_headers": [],
        "source": "rules"
    }

    norm_headers = [normalize_string(h) for h in headers]
    used_indices = set()

    # 1. Check for Split Name columns first (First Name + Last Name)
    first_name_idx = None
    last_name_idx = None
    for idx, nh in enumerate(norm_headers):
        if any(fn == nh or fn in nh for fn in SPLIT_FIRST_NAME_SYNONYMS):
            first_name_idx = idx
        elif any(ln == nh or ln in nh for ln in SPLIT_LAST_NAME_SYNONYMS):
            last_name_idx = idx

    if first_name_idx is not None and last_name_idx is not None and first_name_idx != last_name_idx:
        result["split_names"] = {
            "first_name_column": headers[first_name_idx],
            "last_name_column": headers[last_name_idx]
        }
        result["mappings"]["recipient_name"] = {
            "source_column": f"{headers[first_name_idx]} + {headers[last_name_idx]}",
            "confidence": 0.98,
            "type": "split_combine",
            "parts": [headers[first_name_idx], headers[last_name_idx]]
        }
        used_indices.add(first_name_idx)
        used_indices.add(last_name_idx)

    # 2. Map target fields using Synonyms + Fuzzy Match + Value Inspection
    for target_key, config in TARGET_FIELDS.items():
        if target_key == "recipient_name" and "recipient_name" in result["mappings"]:
            continue

        best_match_idx = None
        best_score = 0.0

        for idx, (orig_h, nh) in enumerate(zip(headers, norm_headers)):
            if idx in used_indices:
                continue

            score = 0.0

            # A. Exact Match to target key
            if nh == normalize_string(target_key):
                score = 1.0

            # B. Synonym Match
            if score < 1.0:
                for syn in config["synonyms"]:
                    norm_syn = normalize_string(syn)
                    if nh == norm_syn:
                        score = max(score, 0.95)
                        break
                    elif norm_syn in nh or nh in norm_syn:
                        score = max(score, 0.85)
                    else:
                        fz = fuzzy_similarity(nh, norm_syn)
                        if fz > 0.82:
                            score = max(score, 0.78)

            # C. Value Inspection Boost
            if sample_rows:
                col_samples = [row[idx] for row in sample_rows if idx < len(row) and row[idx] is not None]
                if col_samples:
                    if target_key == "recipient_email":
                        email_count = sum(1 for v in col_samples if looks_like_email(v))
                        if email_count / len(col_samples) >= 0.5:
                            score = max(score + 0.25, 0.92)
                    elif target_key == "issue_date":
                        date_count = sum(1 for v in col_samples if looks_like_date(v))
                        if date_count / len(col_samples) >= 0.5:
                            score = max(score + 0.25, 0.90)
                    elif target_key == "recipient_name" and "recipient_name" not in result["mappings"]:
                        name_count = sum(1 for v in col_samples if looks_like_person_name(v))
                        if name_count / len(col_samples) >= 0.5:
                            score = max(score + 0.20, 0.82)

            if score > best_score:
                best_score = score
                best_match_idx = idx

        if best_match_idx is not None and best_score >= 0.65:
            result["mappings"][target_key] = {
                "source_column": headers[best_match_idx],
                "confidence": round(min(best_score, 1.0), 2),
                "type": "direct"
            }
            used_indices.add(best_match_idx)
        else:
            result["mappings"][target_key] = {
                "source_column": None,
                "confidence": 0.0,
                "type": "unmapped"
            }

    # 3. Determine overall confidence
    # Mandatory fields: recipient_name, recipient_email, course_title
    mandatory_mapped = all(
        result["mappings"].get(req, {}).get("source_column") is not None and
        result["mappings"].get(req, {}).get("confidence", 0) >= 0.75
        for req in ["recipient_name", "recipient_email", "course_title"]
    )
    result["is_confident"] = mandatory_mapped

    # Track unmapped user headers
    for idx, h in enumerate(headers):
        if idx not in used_indices:
            result["unmapped_headers"].append(h)

    return result


# --- LAYER B: SWAPPABLE AI PROVIDER INTERFACES ---
class BaseAIProvider(ABC):
    @abstractmethod
    def infer_mappings(self, headers: List[str], masked_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        pass


class GeminiProvider(BaseAIProvider):
    """
    Google Gemini Provider (Gemini 2.0 Flash / 1.5 Flash via Google AI Studio).
    Free tier: 15 Requests/min, 1M Tokens/min, 1,500 Requests/day.
    Uses native JSON mode for strictly guaranteed structured JSON.
    """
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model

    def infer_mappings(self, headers: List[str], masked_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
        system_prompt = (
            "You are an expert data mapping engine for ProofDeck, a digital certificate platform. "
            "Your task is to map spreadsheet columns to ProofDeck's six standard fields:\n"
            "1. recipient_name (required: full name of student, attendee, employee, or honoree)\n"
            "2. recipient_email (required: email address)\n"
            "3. course_title (required: name of course, program, workshop, award, or certification)\n"
            "4. issuer_name (optional: school, academy, company, or organization issuing the cert)\n"
            "5. issue_date (optional: date awarded, completed, or issued)\n"
            "6. signature (optional: signer name, director, CEO, or instructor)\n\n"
            "If full name is split across First Name and Last Name columns, declare them in split_names.\n"
            "Return valid JSON matching this schema:\n"
            "{\n"
            '  "mappings": {\n'
            '    "recipient_name": {"source_column": "string or null", "confidence": float, "reasoning": "string"},\n'
            '    "recipient_email": {"source_column": "string or null", "confidence": float, "reasoning": "string"},\n'
            '    "course_title": {"source_column": "string or null", "confidence": float, "reasoning": "string"},\n'
            '    "issuer_name": {"source_column": "string or null", "confidence": float, "reasoning": "string"},\n'
            '    "issue_date": {"source_column": "string or null", "confidence": float, "reasoning": "string"},\n'
            '    "signature": {"source_column": "string or null", "confidence": float, "reasoning": "string"}\n'
            '  },\n'
            '  "split_names": {"first_name_column": "string or null", "last_name_column": "string or null"}\n'
            "}"
        )

        user_content = {
            "headers": headers,
            "sample_rows": masked_samples
        }

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": f"{system_prompt}\n\nHere is the sheet structure:\n{json.dumps(user_content)}"}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        }

        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        text_resp = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text_resp)


class GroqProvider(BaseAIProvider):
    """
    Groq Provider (llama-3.3-70b-versatile / llama-3.1-8b-instant).
    Free tier: 30 Requests/min, 14,400 Requests/day. Sub-second response time.
    """
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model

    def infer_mappings(self, headers: List[str], masked_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        system_prompt = (
            "You are an expert data mapping engine for ProofDeck. Map spreadsheet columns to ProofDeck's six fields:\n"
            "recipient_name, recipient_email, course_title, issuer_name, issue_date, signature.\n"
            "Always respond with valid JSON with keys: mappings and split_names."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"headers": headers, "sample_rows": masked_samples})}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        headers_dict = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        resp = requests.post(url, json=payload, headers=headers_dict, timeout=5)
        resp.raise_for_status()
        res_data = resp.json()
        return json.loads(res_data["choices"][0]["message"]["content"])


class OpenRouterProvider(BaseAIProvider):
    """
    OpenRouter Provider for free models (e.g. meta-llama/llama-3.2-3b-instruct:free).
    """
    def __init__(self, api_key: str, model: str = "meta-llama/llama-3.2-3b-instruct:free"):
        self.api_key = api_key
        self.model = model

    def infer_mappings(self, headers: List[str], masked_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a column mapping AI. Respond ONLY with valid JSON mapping headers to ProofDeck fields."
                },
                {"role": "user", "content": json.dumps({"headers": headers, "sample_rows": masked_samples})}
            ],
            "temperature": 0.1
        }
        headers_dict = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        resp = requests.post(url, json=payload, headers=headers_dict, timeout=5)
        resp.raise_for_status()
        res_data = resp.json()
        content = res_data["choices"][0]["message"]["content"]
        # Strip potential markdown formatting
        content = re.sub(r'^```json\s*', '', content, flags=re.MULTILINE)
        content = re.sub(r'```$', '', content, flags=re.MULTILINE).strip()
        return json.loads(content)


# --- IN-MEMORY CACHE & RATE LIMITING ---
_MAPPING_CACHE: Dict[str, Tuple[Dict[str, Any], float]] = {}
_RATE_LIMIT_COUNTER: Dict[str, List[float]] = {}
CACHE_TTL_SECONDS = 86400  # 24 hours
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 20


def _check_rate_limit(user_id: int) -> bool:
    key = str(user_id)
    now = time.time()
    timestamps = _RATE_LIMIT_COUNTER.get(key, [])
    # Filter to timestamps within current window
    valid_stamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(valid_stamps) >= MAX_REQUESTS_PER_WINDOW:
        return False
    valid_stamps.append(now)
    _RATE_LIMIT_COUNTER[key] = valid_stamps
    return True


def get_configured_ai_provider() -> Optional[BaseAIProvider]:
    """
    Selects and returns an AI provider instance based on environment configuration.
    Priority:
    1. Gemini API (if GEMINI_API_KEY is present or AI_MAPPING_PROVIDER=gemini)
    2. Groq (if GROQ_API_KEY is present or AI_MAPPING_PROVIDER=groq)
    3. OpenRouter (if OPENROUTER_API_KEY is present)
    """
    provider_name = os.environ.get("AI_MAPPING_PROVIDER", "gemini").lower()
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    if provider_name == "gemini" and gemini_key:
        return GeminiProvider(api_key=gemini_key)
    elif provider_name == "groq" and groq_key:
        return GroqProvider(api_key=groq_key)
    elif provider_name == "openrouter" and openrouter_key:
        return OpenRouterProvider(api_key=openrouter_key)

    # Auto-detect if any key exists
    if gemini_key:
        return GeminiProvider(api_key=gemini_key)
    if groq_key:
        return GroqProvider(api_key=groq_key)
    if openrouter_key:
        return OpenRouterProvider(api_key=openrouter_key)

    return None


def mask_sample_rows_for_privacy(headers: List[str], rows: List[List[Any]], max_rows: int = 4) -> List[Dict[str, Any]]:
    """
    Prepares a safe sample of 3-5 rows.
    Masks emails (e.g. j***@domain.com) to protect recipient privacy.
    """
    sample_list = []
    for r in rows[:max_rows]:
        row_dict = {}
        for idx, h in enumerate(headers):
            val = r[idx] if idx < len(r) else None
            if val is not None:
                s_val = str(val).strip()
                if looks_like_email(s_val):
                    # Mask email: show first character and domain only
                    parts = s_val.split('@')
                    if len(parts) == 2 and parts[0]:
                        masked_email = f"{parts[0][0]}***@{parts[1]}"
                    else:
                        masked_email = "[EMAIL_MASKED]"
                    row_dict[h] = masked_email
                else:
                    # Truncate overly long values
                    row_dict[h] = s_val[:80]
            else:
                row_dict[h] = None
        sample_list.append(row_dict)
    return sample_list


def infer_mapping_layer_b(
    headers: List[str],
    sample_rows: List[List[Any]],
    user_id: int
) -> Optional[Dict[str, Any]]:
    """
    Layer B: AI Fallback (Pro & Enterprise only).
    Applies privacy masking, caching, rate limiting, and timeout fallback.
    Returns AI-suggested mappings or None if unavailable.
    """
    if not _check_rate_limit(user_id):
        logger.warning(f"AI column mapper rate limit reached for user {user_id}")
        return None

    # Check cache by header signature
    cache_key = hashlib.sha256("||".join(sorted(normalize_string(h) for h in headers)).encode()).hexdigest()
    now = time.time()
    if cache_key in _MAPPING_CACHE:
        cached_result, cached_time = _MAPPING_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            logger.info("Serving AI column mapping from cache")
            return cached_result

    provider = get_configured_ai_provider()
    if not provider:
        logger.info("No AI provider API key configured; skipping Layer B")
        return None

    masked_samples = mask_sample_rows_for_privacy(headers, sample_rows, max_rows=4)

    try:
        raw_ai_result = provider.infer_mappings(headers, masked_samples)
        
        # Strict validation of AI response
        mappings = raw_ai_result.get("mappings", {})
        split_names = raw_ai_result.get("split_names")

        validated_mappings = {}
        for target_key in TARGET_FIELDS:
            ai_field = mappings.get(target_key, {})
            src_col = ai_field.get("source_column")
            # Ensure src_col actually exists in user headers
            if src_col and src_col in headers:
                validated_mappings[target_key] = {
                    "source_column": src_col,
                    "confidence": float(ai_field.get("confidence", 0.9)),
                    "type": "direct",
                    "reasoning": str(ai_field.get("reasoning", "AI detected match"))
                }
            else:
                validated_mappings[target_key] = {
                    "source_column": None,
                    "confidence": 0.0,
                    "type": "unmapped"
                }

        # Check split names
        validated_split = None
        if isinstance(split_names, dict):
            fn = split_names.get("first_name_column")
            ln = split_names.get("last_name_column")
            if fn in headers and ln in headers and fn != ln:
                validated_split = {
                    "first_name_column": fn,
                    "last_name_column": ln
                }
                validated_mappings["recipient_name"] = {
                    "source_column": f"{fn} + {ln}",
                    "confidence": 0.95,
                    "type": "split_combine",
                    "parts": [fn, ln]
                }

        ai_output = {
            "mappings": validated_mappings,
            "split_names": validated_split,
            "is_confident": all(
                validated_mappings.get(k, {}).get("source_column") is not None
                for k in ["recipient_name", "recipient_email", "course_title"]
            ),
            "source": "ai"
        }

        # Cache result
        _MAPPING_CACHE[cache_key] = (ai_output, now)
        return ai_output

    except Exception as e:
        logger.warning(f"AI column mapping failed: {e}. Gracefully falling back.")
        return None
