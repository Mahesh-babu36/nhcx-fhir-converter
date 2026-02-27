"""
utils.py  —  Shared utility functions used across all pipeline files.
"""

import uuid
import logging
import re
from datetime import datetime, date

# ── Logger ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nhcx")


# ── ID / timestamp ────────────────────────────────────────────────────────────
def generate_id() -> str:
    return str(uuid.uuid4())

def current_timestamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def today_str() -> str:
    return date.today().isoformat()


# ── Safe parsers ──────────────────────────────────────────────────────────────
def safe_parse_date(raw: str) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d %b %Y", "%d %B %Y", "%B %d, %Y",
        "%d.%m.%Y", "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw

def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return default

def safe_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default

def age_to_birth_year(age_raw) -> str:
    try:
        age = safe_int(str(age_raw).split()[0])
        if age > 0:
            return f"{datetime.utcnow().year - age}-01-01"
    except Exception:
        pass
    return ""

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove non-printable characters (keep printable ASCII, newlines, tabs)
    text = re.sub(r'[^\x20-\x7E\n\t]+', ' ', str(text))
    # Collapse extra spaces within each line — but PRESERVE newlines
    # so that multi-line lab tables remain parseable by Gemini AI.
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
