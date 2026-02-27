"""
pipeline/abdm_profiles.py
--------------------------
Single source of truth for all official ABDM and NHCX profile URLs,
SNOMED codes, coding system URIs, and resource profile mappings.

Never hardcode profile URLs anywhere else — always import from here.
"""

# ── ABDM Health Information Types ─────────────────────────────────────────────
# Official SNOMED CT codes as defined in ABDM FHIR Implementation Guide
ABDM_HI_TYPES = {
    "DischargeSummary": {
        "code": "DischargeSummary",
        "display": "Discharge Summary",
        "bundle_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DischargeSummaryRecord",
        "composition_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DischargeSummary",
        "snomed_code": "373942005",
        "snomed_display": "Discharge summary",
        "snomed_system": "http://snomed.info/sct",
        "loinc_code": "18842-5",
        "loinc_display": "Discharge summary",
    },
    "DiagnosticReport": {
        "code": "DiagnosticReport",
        "display": "Diagnostic Report",
        "bundle_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord",
        "composition_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportComposition",
        "snomed_code": "4241000179101",
        "snomed_display": "Diagnostic report",
        "snomed_system": "http://snomed.info/sct",
        "loinc_code": "11502-2",
        "loinc_display": "Laboratory report",
    },
    "OPConsultation": {
        "code": "OPConsultation",
        "display": "OP Consultation",
        "bundle_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/OPConsultRecord",
        "composition_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/OPConsultation",
        "snomed_code": "371530004",
        "snomed_display": "Clinical consultation report",
        "snomed_system": "http://snomed.info/sct",
        "loinc_code": "11488-4",
        "loinc_display": "Consultation note",
    },
    "Prescription": {
        "code": "Prescription",
        "display": "Prescription",
        "bundle_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/PrescriptionRecord",
        "composition_profile": "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Prescription",
        "snomed_code": "440545006",
        "snomed_display": "Prescription record",
        "snomed_system": "http://snomed.info/sct",
        "loinc_code": "57833-6",
        "loinc_display": "Prescription for medication",
    },
}

# ── NRCeS Resource Profile URLs ───────────────────────────────────────────────
NHCX_PROFILES = {
    "Bundle":                    "https://nrces.in/ndhm/fhir/r4/StructureDefinition/ClaimBundle",
    "Composition":               "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DischargeSummary",
    "Patient":                   "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Patient",
    "Organization":              "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Organization",
    "Practitioner":              "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Practitioner",
    "Encounter":                 "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Encounter",
    "Condition":                 "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Condition",
    "Observation":               "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Observation",
    "DiagnosticReport":          "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportLab",
    "MedicationRequest":         "https://nrces.in/ndhm/fhir/r4/StructureDefinition/MedicationRequest",
    "Claim":                     "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Claim",
    "CoverageEligibilityRequest":"https://nrces.in/ndhm/fhir/r4/StructureDefinition/CoverageEligibilityRequest",
    "DocumentReference":         "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentReference",
    "Provenance":                "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Provenance",
}

# ── Official FHIR Coding Systems ──────────────────────────────────────────────
SYSTEMS = {
    "icd10":              "http://hl7.org/fhir/sid/icd-10",
    "loinc":              "http://loinc.org",
    "snomed":             "http://snomed.info/sct",
    "rxnorm":             "http://www.nlm.nih.gov/research/umls/rxnorm",
    "ucum":               "http://unitsofmeasure.org",
    "condition_clinical": "http://terminology.hl7.org/CodeSystem/condition-clinical",
    "condition_category": "http://terminology.hl7.org/CodeSystem/condition-category",
    "encounter_class":    "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "claim_type":         "http://terminology.hl7.org/CodeSystem/claim-type",
    "process_priority":   "http://terminology.hl7.org/CodeSystem/processpriority",
    "benefit_category":   "http://terminology.hl7.org/CodeSystem/ex-benefitcategory",
    "provenance_agent":   "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
    "data_operation":     "http://terminology.hl7.org/CodeSystem/v3-DataOperation",
    "act_reason":         "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "coverage_class":     "http://terminology.hl7.org/CodeSystem/coverage-class",
    "nhcx_provider":      "https://nhcx.health.gov.in/providers",
    "nhcx_insurer":       "https://nhcx.health.gov.in/insurers",
    "ndhm_patient":       "https://ndhm.gov.in/patients",
    "ndhm_bundle":        "https://ndhm.gov.in",
    "ndhm_org":           "https://ndhm.gov.in/organizations",
}

# ── Document type → ABDM HI type mapping ────────────────────────────────────
DOC_TYPE_TO_HI_TYPE = {
    "discharge_summary":  "DischargeSummary",
    "diagnostic_report":  "DiagnosticReport",
    "lab_report":         "DiagnosticReport",
    "op_consultation":    "OPConsultation",
    "prescription":       "Prescription",
    "unknown":            "DischargeSummary",
}

def get_hi_type(doc_type: str) -> dict:
    """Return ABDM HI type definition for a detected document type."""
    hi_key = DOC_TYPE_TO_HI_TYPE.get(doc_type, "DischargeSummary")
    return ABDM_HI_TYPES[hi_key]

def get_profile(resource_type: str) -> str:
    """Return NRCeS profile URL for a FHIR resource type."""
    return NHCX_PROFILES.get(resource_type, "")
