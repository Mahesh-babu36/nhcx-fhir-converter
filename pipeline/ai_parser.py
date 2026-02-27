"""
pipeline/ai_parser.py
---------------------
Uses Google Gemini to extract structured clinical data from raw PDF text.
Gemini is the only part of the pipeline that requires internet.
"""

import os
import json
import re
from utils import logger, clean_text

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai not installed. Run: pip install google-genai")


# ── Gemini model config ───────────────────────────────────────────────────────
# Try models in order — first one that works is used
MODEL_CANDIDATES = [
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-pro-latest",
    "gemini-pro",
]
MAX_TEXT_CHARS = 12000      # limit tokens sent to Gemini


# ── Extraction prompts per document type ─────────────────────────────────────
PROMPTS = {
    "discharge_summary": """
You are a clinical data extraction specialist. Extract ALL available information
from this Indian hospital discharge summary and return ONLY valid JSON.

Required fields (use null if not found):
{
  "patient_name": "full name",
  "patient_age": "age as number",
  "patient_gender": "male|female|other",
  "patient_id": "UHID or MRD number",
  "patient_address": "address",
  "patient_phone": "phone number",
  "admission_date": "DD/MM/YYYY format",
  "discharge_date": "DD/MM/YYYY format",
  "hospital_name": "full hospital name",
  "hospital_address": "address",
  "hospital_phone": "phone",
  "ward": "ward name",
  "bed_number": "bed number",
  "treating_doctor": "Dr. name",
  "doctor_qualification": "MBBS, MD etc",
  "doctor_registration": "MCI/NMC number",
  "primary_diagnosis": "main diagnosis text",
  "secondary_diagnoses": ["list", "of", "other", "diagnoses"],
  "chief_complaint": "presenting complaint",
  "history_of_illness": "brief HPI",
  "examination_findings": "clinical findings",
  "investigations_summary": "summary of tests done",
  "procedures_performed": ["list", "of", "procedures"],
  "medications_at_discharge": [
    {"name": "drug name", "dose": "dose", "frequency": "frequency", "duration": "duration"}
  ],
  "condition_at_discharge": "stable|critical|improved|unchanged",
  "follow_up_instructions": "instructions",
  "follow_up_date": "date",
  "insurer_name": "insurance company name",
  "insurance_id": "policy or member ID",
  "claim_amount": "amount in INR"
}

Discharge summary text:
""",

    "diagnostic_report": """
You are a clinical data extraction specialist. This is an Indian hospital laboratory/diagnostic report.
Extract ALL data and return ONLY valid JSON.

IMPORTANT: The report text may come from OCR of a scanned table.
Lab result rows look like this (space-separated from OCR):
  TestName ResultValue ReferenceRange Unit
Example: "Hemoglobin 11.5 12 - 15 g/dl"

Extract EVERY test row as a separate entry in the "tests" array.
For abnormal_flag: compare result to reference range. Mark HIGH/LOW/NORMAL appropriately.

Required JSON fields (use null if not found):
{
  "patient_name": "full patient name",
  "patient_age": "age as number",
  "patient_gender": "male or female or other",
  "patient_id": "lab ID, UHID, or patient number",
  "hospital_name": "hospital or laboratory name",
  "hospital_address": "address",
  "referring_doctor": "referring or treating doctor name",
  "report_date": "report date in DD/MM/YYYY",
  "sample_collection_date": "collection date in DD/MM/YYYY",
  "sample_type": "blood or urine or stool or tissue or other",
  "tests": [
    {
      "test_name": "exact test name from the report",
      "result_value": "numeric or text result value",
      "unit": "unit of measurement (g/dl, %, x10^3/L etc)",
      "reference_range": "normal reference range as text",
      "abnormal_flag": "HIGH or LOW or NORMAL"
    }
  ],
  "impression": "overall lab impression, conclusion or diagnosis",
  "recommendations": "doctor recommendations if any",
  "insurer_name": "insurance company name if present",
  "insurance_id": "policy or member ID if present"
}

Report text:
""",

    "unknown": """
Extract any clinical or patient information from this document and return valid JSON.
Include: patient_name, patient_age, patient_gender, hospital_name, primary_diagnosis,
treating_doctor, admission_date, discharge_date, medications_at_discharge.
Use null for missing fields.

Document text:
""",
}


class AIParser:
    """
    Extracts structured clinical data from raw text using Gemini.
    Falls back to regex-based extraction if Gemini is unavailable.
    """

    def __init__(self):
        self.model = None
        self._init_gemini()

    def _init_gemini(self):
        if not GEMINI_AVAILABLE:
            return
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            logger.warning(
                "GEMINI_API_KEY not set. "
                "Add it to .env file: GEMINI_API_KEY=your_key"
            )
            return
        try:
            client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error(f"Gemini client init failed: {e}")
            return

        # Try each model in order — use the first one that actually responds
        for model_name in MODEL_CANDIDATES:
            try:
                client.models.generate_content(
                    model=model_name,
                    contents="ping",
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=5, temperature=0
                    )
                )
                self.model = (client, model_name)
                logger.info(f"Gemini model ready: {model_name}")
                return
            except Exception as e:
                logger.warning(f"Model {model_name} unavailable: {e}")
                continue

        logger.error(
            "No Gemini model responded. Check API key/billing. "
            "Using regex extraction only."
        )

    def parse(self, text: str, doc_type: str) -> dict:
        """
        Parse clinical text and return structured dict.
        Uses Gemini if available; merges regex fallback for any missing lab tests.
        """
        if not text:
            return {}

        # Truncate text to avoid Gemini token limits
        truncated = text[:MAX_TEXT_CHARS]

        if self.model:
            result = self._parse_with_gemini(truncated, doc_type)
            if result:
                logger.info(f"Gemini extracted {len(result)} fields")
                # If Gemini didn't extract tests (common with numeric lab tables),
                # supplement with regex-based lab table parser
                if not result.get("tests") and doc_type in ("diagnostic_report", "lab_report"):
                    regex_data = self._parse_with_regex(text)
                    if regex_data.get("tests"):
                        result["tests"] = regex_data["tests"]
                        logger.info(f"Regex supplemented {len(result['tests'])} lab tests")
                return result

        logger.warning("Falling back to regex extraction")
        return self._parse_with_regex(text)

    def _parse_with_gemini(self, text: str, doc_type: str) -> dict:
        """Call Gemini and parse JSON response."""
        prompt_template = PROMPTS.get(doc_type, PROMPTS["unknown"])
        prompt = prompt_template + text + "\n\nReturn ONLY the JSON object, no other text."
        client, model_name = self.model

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=4096,
                )
            )
            raw = response.text.strip()

            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            data = json.loads(raw)
            return self._normalise(data)

        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON: {e}")
            return {}
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return {}

    def _parse_with_regex(self, text: str) -> dict:
        """
        Fallback extraction using simple regex patterns.
        Catches the most common fields in Indian hospital documents.
        """
        data = {}
        lower = text.lower()

        patterns = {
            "patient_name": [
                r"patient\s*name\s*[:\-]\s*([A-Za-z\s\.]+)",
                r"name\s*[:\-]\s*([A-Za-z\s\.]{3,40})",
                r"mr\.?\s+([A-Za-z\s\.]{3,30})",
                r"mrs\.?\s+([A-Za-z\s\.]{3,30})",
            ],
            "patient_age": [
                r"age\s*[:\-]\s*(\d{1,3})\s*(?:years|yrs|y)?",
                r"(\d{1,3})\s*(?:years|yrs)\s*(?:old)?",
            ],
            "patient_gender": [
                r"(?:sex|gender)\s*[:\-]\s*(male|female|m|f)",
                r"\b(male|female)\b",
            ],
            "hospital_name": [
                r"([A-Za-z\s]+hospital[A-Za-z\s]*)",
                r"([A-Za-z\s]+clinic[A-Za-z\s]*)",
                r"([A-Za-z\s]+medical centre[A-Za-z\s]*)",
            ],
            "admission_date": [
                r"(?:date\s+of\s+admission|admitted\s+on|doa)\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
                r"admission\s+date\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            ],
            "discharge_date": [
                r"(?:date\s+of\s+discharge|discharged\s+on|dod)\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
                r"discharge\s+date\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            ],
            "treating_doctor": [
                r"(?:treating|attending|consultant)\s+(?:physician|doctor|surgeon|dr\.?)\s*[:\-]?\s*(dr\.?\s*[A-Za-z\s\.]{3,40})",
                r"(?:dr\.)\s*([A-Za-z\s\.]{3,40})",
            ],
            "primary_diagnosis": [
                r"(?:final\s+diagnosis|primary\s+diagnosis|diagnosis)\s*[:\-]\s*([^\n]{5,100})",
                r"(?:admitted\s+for|presenting\s+with)\s*[:\-]\s*([^\n]{5,80})",
            ],
        }

        for field, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, lower)
                if m:
                    value = clean_text(m.group(1))
                    if field == "patient_gender":
                        value = "male" if value.startswith("m") else "female"
                    data[field] = value
                    break

        # ── Lab test extraction from columnar format ──────────────────────────
        # Handles Indian lab report tables where each row is:
        #   TestName  NumericValue  RefRangeLow-RefRangeHigh  Unit
        # Example: "Hemoglobin 11.5 12 - 15 g/dl"
        test_pattern = re.compile(
            r"^([A-Za-z][A-Za-z0-9\s\(\)/\-\.]{2,45}?)\s+"   # test name
            r"(\d+\.?\d*)\s+"                                   # numeric result
            r"([\d\.\s\-–]+(?:x10\^?\d+)?(?:\s*/\s*\w+)?)\s+" # ref range
            r"([a-zA-Z%°/\^0-9\.µ]{1,20})\s*$",               # unit
            re.MULTILINE,
        )
        tests = []
        for m in test_pattern.finditer(text):
            name = m.group(1).strip()
            value = m.group(2).strip()
            ref = m.group(3).strip()
            unit = m.group(4).strip()
            # Determine abnormal flag by comparing to range
            flag = "NORMAL"
            try:
                nums = re.findall(r"\d+\.?\d*", ref)
                if len(nums) >= 2:
                    lo, hi = float(nums[0]), float(nums[-1])
                    v = float(value)
                    if v < lo:
                        flag = "LOW"
                    elif v > hi:
                        flag = "HIGH"
            except Exception:
                pass
            tests.append({
                "test_name": name,
                "result_value": value,
                "unit": unit,
                "reference_range": ref,
                "abnormal_flag": flag,
            })
        if tests:
            data["tests"] = tests

        return data

    def _normalise(self, data: dict) -> dict:
        """Clean nulls and normalise common field values."""
        cleaned = {}
        for k, v in data.items():
            if v is None or v == "" or v == "null":
                continue
            if isinstance(v, str):
                v = clean_text(v)
            cleaned[k] = v

        # Normalise gender
        gender = str(cleaned.get("patient_gender", "")).lower()
        if gender.startswith("m"):
            cleaned["patient_gender"] = "male"
        elif gender.startswith("f"):
            cleaned["patient_gender"] = "female"
        elif gender:
            cleaned["patient_gender"] = "other"

        return cleaned
