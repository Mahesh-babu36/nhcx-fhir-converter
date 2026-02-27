"""
tests/test_pipeline.py
-----------------------
Automated test suite for the NHCX FHIR Converter pipeline.
Tests are grouped into:
  1. Unit tests — detector, coding engine, FHIR validator
  2. Integration tests — full API endpoints
Run with:  python -m pytest tests/ -v
"""

import sys
import os
import json
import pytest

# Make sure project root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.detector import DocumentTypeDetector
from pipeline.coding_engine import ClinicalCodingEngine
from pipeline.validator import FHIRValidator
from pipeline.fhir_builder import FHIRBundleBuilder


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def detector():
    return DocumentTypeDetector()

@pytest.fixture
def coder():
    return ClinicalCodingEngine()

@pytest.fixture
def validator():
    return FHIRValidator()

@pytest.fixture
def builder():
    return FHIRBundleBuilder()

DISCHARGE_SAMPLE = """
DISCHARGE SUMMARY
Patient Name: Rajesh Kumar  Age: 45 Years  Gender: Male
Hospital: City General Hospital
Date of Admission: 01/01/2024  Date of Discharge: 07/01/2024
Chief Complaint: Chest pain with breathlessness
Final Diagnosis: Acute Myocardial Infarction
Treating Doctor: Dr. Priya Sharma, MD (Cardiology)
Condition at Discharge: Stable
Medications on Discharge: Aspirin 75mg, Atorvastatin 40mg, Metoprolol 50mg
"""

DIAGNOSTIC_SAMPLE = """
LABORATORY DIAGNOSTIC REPORT
Patient: Sita Devi  Age: 32  Gender: Female
Lab: Metro Diagnostics, Mumbai
Report Date: 15/02/2024
Complete Blood Count (CBC)
Hemoglobin 11.5 12 - 15 g/dl
HCT 36.5 36 - 46 %
Platelet Count 1.50 1.5 - 4.0 x10^3 / L
Total Leukocyte Count 8.5 4 - 10 x10^3 / L
Impression: Mild anaemia noted.
"""

PRESCRIPTION_SAMPLE = """
PRESCRIPTION
Dr. Anil Mehta MBBS, MD
Patient: Rahul Verma  Age: 28
Date: 10/02/2024
Rx: Tab. Metformin 500mg BD x 1 month
    Tab. Glimepiride 1mg OD x 1 month
Diagnosis: Type 2 Diabetes Mellitus
"""


# ── 1. Document Type Detector ──────────────────────────────────────────────────

class TestDocumentTypeDetector:

    def test_discharge_summary_detected(self, detector):
        result = detector.detect(DISCHARGE_SAMPLE)
        assert result["doc_type"] == "discharge_summary", \
            f"Expected discharge_summary, got {result['doc_type']}"

    def test_diagnostic_report_detected(self, detector):
        result = detector.detect(DIAGNOSTIC_SAMPLE)
        assert result["doc_type"] == "diagnostic_report", \
            f"Expected diagnostic_report, got {result['doc_type']}"

    def test_discharge_confidence_high(self, detector):
        result = detector.detect(DISCHARGE_SAMPLE)
        assert result["confidence_percent"] >= 70, \
            f"Confidence too low: {result['confidence_percent']}"

    def test_result_has_abdm_hi_type(self, detector):
        result = detector.detect(DISCHARGE_SAMPLE)
        assert "abdm_hi_type" in result
        assert result["abdm_hi_type"] == "DischargeSummary"

    def test_diagnostic_abdm_hi_type(self, detector):
        result = detector.detect(DIAGNOSTIC_SAMPLE)
        assert result["abdm_hi_type"] == "DiagnosticReport"


# ── 2. Clinical Coding Engine ──────────────────────────────────────────────────

class TestClinicalCodingEngine:

    def test_icd10_diabetes(self, coder):
        result = coder.code_diagnosis("Type 2 diabetes mellitus")
        assert result["matched"] is True
        assert result["code"] == "E11.9"

    def test_icd10_hypertension(self, coder):
        result = coder.code_diagnosis("Essential hypertension")
        assert result["matched"] is True
        assert result["code"] == "I10"

    def test_icd10_myocardial_infarction(self, coder):
        result = coder.code_diagnosis("Acute myocardial infarction")
        assert result["matched"] is True
        assert result["code"] == "I21.9"

    def test_icd10_fuzzy_match(self, coder):
        # Should fuzzy-match "acute MI" to myocardial infarction
        result = coder.code_diagnosis("myocardial infarct")
        assert result["matched"] is True

    def test_loinc_hemoglobin(self, coder):
        result = coder.code_test("Hemoglobin")
        assert result["matched"] is True
        assert result["code"] == "718-7"

    def test_loinc_platelet(self, coder):
        result = coder.code_test("Platelet Count")
        assert result["matched"] is True
        assert result["code"] == "777-3"

    def test_loinc_creatinine(self, coder):
        result = coder.code_test("Serum Creatinine")
        assert result["matched"] is True
        assert result["code"] == "2160-0"

    def test_loinc_no_match_returns_structured(self, coder):
        result = coder.code_test("completely unknown test xyz")
        assert result["matched"] is False
        assert "code" in result
        assert "system" in result

    def test_code_all_tests_adds_loinc_coding(self, coder):
        tests = [
            {"test_name": "Hemoglobin", "result_value": "12.5"},
            {"test_name": "Platelet Count", "result_value": "200000"},
        ]
        coded = coder.code_all_tests(tests)
        assert len(coded) == 2
        assert coded[0]["loinc_coding"]["code"] == "718-7"
        assert coded[1]["loinc_coding"]["code"] == "777-3"


# ── 3. FHIR Bundle Builder ────────────────────────────────────────────────────

class TestFHIRBundleBuilder:

    def _minimal_data(self):
        return {
            "patient_name": "Test Patient",
            "patient_age": 45,
            "patient_gender": "male",
            "hospital_name": "Test Hospital",
            "treating_doctor": "Dr. Test",
            "primary_diagnosis": "Hypertension",
            "admission_date": "01/01/2024",
            "discharge_date": "07/01/2024",
        }

    def test_bundle_has_correct_resource_type(self, builder):
        bundle = builder.build(self._minimal_data(), "discharge_summary")
        assert bundle["resourceType"] == "Bundle"

    def test_bundle_type_is_document(self, builder):
        bundle = builder.build(self._minimal_data(), "discharge_summary")
        assert bundle["type"] == "document", \
            "ABDM requires Bundle.type = 'document'"

    def test_composition_is_first_entry(self, builder):
        bundle = builder.build(self._minimal_data(), "discharge_summary")
        first = bundle["entry"][0]["resource"]
        assert first["resourceType"] == "Composition"

    def test_bundle_has_nhcx_profile(self, builder):
        bundle = builder.build(self._minimal_data(), "discharge_summary")
        profiles = bundle.get("meta", {}).get("profile", [])
        assert any("nrces" in p or "nhcx" in p.lower() for p in profiles)

    def test_discharge_composition_snomed_code(self, builder):
        bundle = builder.build(self._minimal_data(), "discharge_summary")
        comp = bundle["entry"][0]["resource"]
        codings = comp["type"]["coding"]
        codes = [c["code"] for c in codings]
        assert "373942005" in codes, \
            "Discharge Summary must use SNOMED 373942005"

    def test_diagnostic_report_composition_snomed(self, builder):
        bundle = builder.build(self._minimal_data(), "diagnostic_report")
        comp = bundle["entry"][0]["resource"]
        codings = comp["type"]["coding"]
        codes = [c["code"] for c in codings]
        assert "4241000179101" in codes, \
            "Diagnostic Report must use SNOMED 4241000179101"

    def test_observations_generated_from_tests(self, builder):
        data = self._minimal_data()
        data["tests"] = [
            {"test_name": "Hemoglobin", "result_value": "11.5", "unit": "g/dl",
             "reference_range": "12-15", "abnormal_flag": "LOW"},
        ]
        bundle = builder.build(data, "diagnostic_report")
        resources = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "Observation" in resources
        obs = [e["resource"] for e in bundle["entry"]
               if e["resource"]["resourceType"] == "Observation"]
        assert len(obs) == 1
        assert obs[0]["status"] == "final"

    def test_claim_generated_for_claim_use_case(self, builder):
        bundle = builder.build(self._minimal_data(), "discharge_summary", use_case="claim")
        resources = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "Claim" in resources

    def test_preauthorization_generates_coverage_eligibility(self, builder):
        bundle = builder.build(
            self._minimal_data(), "discharge_summary",
            use_case="preauthorization"
        )
        resources = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "CoverageEligibilityRequest" in resources
        assert "Claim" not in resources

    def test_document_reference_embedded(self, builder):
        bundle = builder.build(
            self._minimal_data(), "discharge_summary",
            source_pdf_paths=["dummy.pdf"]
        )
        resources = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "DocumentReference" in resources


# ── 4. FHIR Validator ────────────────────────────────────────────────────────

class TestFHIRValidator:

    def _make_bundle(self, builder):
        return builder.build({
            "patient_name": "Test Patient",
            "patient_gender": "male",
            "hospital_name": "Test Hospital",
            "treating_doctor": "Dr. Test",
            "primary_diagnosis": "Hypertension",
        }, "discharge_summary")

    def test_valid_bundle_passes(self, validator, builder):
        bundle = self._make_bundle(builder)
        result = validator.validate(bundle)
        # Should have 0 errors (Patient/Org/Claim/Composition all present)
        assert result["error_count"] == 0, \
            f"Unexpected errors: {result['errors']}"

    def test_empty_bundle_fails(self, validator):
        result = validator.validate({})
        assert not result["valid"]

    def test_readiness_score_present(self, validator, builder):
        bundle = self._make_bundle(builder)
        result = validator.validate(bundle)
        assert "readiness" in result
        assert isinstance(result["readiness"]["score"], int)
        assert result["readiness"]["score"] > 0

    def test_operation_outcome_returned(self, validator, builder):
        bundle = self._make_bundle(builder)
        result = validator.validate(bundle)
        oo = result["operation_outcome"]
        assert oo["resourceType"] == "OperationOutcome"

    def test_missing_composition_is_error(self, validator):
        bundle = {"resourceType": "Bundle", "type": "document", "entry": []}
        result = validator.validate(bundle)
        msg = [e["message"] for e in result["errors"]]
        assert any("Composition" in m for m in msg)
