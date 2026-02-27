"""
pipeline/detector.py
--------------------
Detects the ABDM Health Information (HI) type of a clinical document
using keyword frequency analysis on the extracted text.
"""

import re
from utils import logger
from pipeline.abdm_profiles import get_hi_type, DOC_TYPE_TO_HI_TYPE


# Keyword banks per document type — weighted by importance
KEYWORD_BANKS = {
    "discharge_summary": {
        "high": [
            "date of discharge", "discharge summary", "discharge date",
            "admitted on", "date of admission", "final diagnosis",
            "condition at discharge", "discharge medication",
            "advice on discharge", "discharge advice",
        ],
        "medium": [
            "treating physician", "attending doctor", "ward", "bed number",
            "length of stay", "follow up", "follow-up", "primary diagnosis",
            "inpatient", "ip number", "uhid",
        ],
        "low": [
            "hospital", "patient", "diagnosis", "treatment", "medication",
            "doctor", "physician", "admission", "blood pressure",
        ],
    },
    "diagnostic_report": {
        "high": [
            "laboratory report", "lab report", "investigation report",
            "test report", "pathology report", "radiology report",
            "diagnostic report", "sample collected", "specimen",
            "result", "reference range", "normal range",
        ],
        "medium": [
            "haemoglobin", "hemoglobin", "blood glucose", "creatinine",
            "urea", "cholesterol", "platelet", "wbc", "rbc",
            "hba1c", "tsh", "bilirubin", "sgpt", "sgot", "urine",
            "impression", "finding", "report date", "collection date",
        ],
        "low": [
            "lab", "test", "value", "unit", "range", "sample",
            "analysis", "examination",
        ],
    },
    "prescription": {
        "high": [
            "prescription", "rx", "sig:", "dosage", "tablets",
            "capsules", "syrup", "injection", "apply topically",
            "take orally", "before food", "after food",
        ],
        "medium": [
            "refills", "dispense", "morning", "evening", "night",
            "once daily", "twice daily", "thrice daily", "sos",
            "prn", "as needed",
        ],
        "low": [
            "medicine", "drug", "dose", "frequency",
        ],
    },
    "op_consultation": {
        "high": [
            "outpatient", "op consultation", "clinic notes",
            "consultation notes", "op number", "opd",
            "chief complaint", "history of present illness",
            "hpi", "review of systems",
        ],
        "medium": [
            "vital signs", "weight", "height", "bmi", "temperature",
            "pulse", "respiratory rate", "spo2", "physical examination",
            "general examination", "systemic examination",
        ],
        "low": [
            "complaint", "history", "examination", "plan",
        ],
    },
}

WEIGHTS = {"high": 3, "medium": 2, "low": 1}


class DocumentTypeDetector:
    """
    Detects document type from raw PDF text using keyword scoring.
    Returns the detected type, confidence percentage, and matched keywords.
    """

    # Title patterns for fast-path override — checked against first 600 chars
    TITLE_PATTERNS = {
        "discharge_summary": [
            "discharge summary", "discharge summery", "dischargé summary",
            "date of discharge", "advice on discharge", "condition at discharge",
        ],
        "diagnostic_report": [
            "laboratory report", "lab report", "diagnostic report",
            "pathology report", "radiology report", "investigation report",
            "test report", "haematology report", "biochemistry report",
        ],
        "prescription": [
            "prescription", "rx:", "rx ",
        ],
        "op_consultation": [
            "op consultation", "outpatient consultation", "clinic notes",
            "consultation notes",
        ],
    }

    def detect(self, text: str) -> dict:
        if not text or len(text.strip()) < 30:
            return self._unknown("Text too short to detect")

        lower = text.lower()

        # ── Fast-path: title override ────────────────────────────────────────
        # Check the first 600 characters for an explicit document heading.
        # This is critical for scanned Indian hospital PDFs where the title
        # is printed prominently at the top.
        title_zone = lower[:1200]
        for doc_type, titles in self.TITLE_PATTERNS.items():
            for title in titles:
                if title in title_zone:
                    hi_type = get_hi_type(doc_type)
                    logger.info(
                        f"Title-override detected: {doc_type} "
                        f"(matched title: '{title}')"
                    )
                    return {
                        "doc_type": doc_type,
                        "abdm_hi_type": DOC_TYPE_TO_HI_TYPE.get(doc_type, "DischargeSummary"),
                        "hi_type_profile": hi_type,
                        "confidence_percent": 95.0,
                        "score": 999,
                        "matched_keywords": [title],
                        "all_scores": {},
                    }

        # ── Keyword scoring (fallback) ────────────────────────────────────────
        scores = {}
        for doc_type, banks in KEYWORD_BANKS.items():
            score = 0
            matched = []
            for weight_name, keywords in banks.items():
                w = WEIGHTS[weight_name]
                for kw in keywords:
                    if kw in lower:
                        score += w
                        matched.append(kw)
            scores[doc_type] = {"score": score, "matched": matched}

        best_type = max(scores, key=lambda k: scores[k]["score"])
        best_score = scores[best_type]["score"]

        if best_score == 0:
            return self._unknown("No keywords matched")

        max_possible = sum(
            WEIGHTS[wn] * len(kws)
            for wn, kws in KEYWORD_BANKS[best_type].items()
        )
        confidence = round(min((best_score / max_possible) * 100 * 2, 99.9), 1)
        hi_type = get_hi_type(best_type)

        logger.info(
            f"Detected: {best_type} | confidence: {confidence}% | "
            f"score: {best_score} | matched: {scores[best_type]['matched'][:5]}"
        )

        return {
            "doc_type": best_type,
            "abdm_hi_type": DOC_TYPE_TO_HI_TYPE.get(best_type, "DischargeSummary"),
            "hi_type_profile": hi_type,
            "confidence_percent": confidence,
            "score": best_score,
            "matched_keywords": scores[best_type]["matched"],
            "all_scores": {k: v["score"] for k, v in scores.items()},
        }

    def _unknown(self, reason: str) -> dict:
        return {
            "doc_type": "unknown",
            "abdm_hi_type": "DischargeSummary",
            "hi_type_profile": get_hi_type("unknown"),
            "confidence_percent": 0.0,
            "score": 0,
            "matched_keywords": [],
            "all_scores": {},
            "reason": reason,
        }
