"""
pipeline/validator.py
---------------------
Validates FHIR bundles and returns errors as FHIR OperationOutcome resources.
OperationOutcome is the standard FHIR format for validation results —
this is what NHCX and NRCeS systems actually expect.

Three levels of validation:
  1. Structural  — correct resourceType, required fields present
  2. Terminology — correct coding systems, valid value sets
  3. Reference   — all urn:uuid references resolve inside the bundle
"""

from utils import logger


class FHIRValidator:

    # ── valid value sets ──────────────────────────────────────────────────────
    VALID_GENDERS = {"male", "female", "other", "unknown"}
    VALID_CLAIM_USE = {"claim", "preauthorization", "predetermination"}
    VALID_CONDITION_CLINICAL = {"active","recurrence","relapse","inactive","remission","resolved"}
    VALID_BUNDLE_TYPES = {"document","collection","transaction"}
    VALID_OBS_STATUS = {"registered","preliminary","final","amended","cancelled"}

    # ── official FHIR coding system prefixes ─────────────────────────────────
    VALID_SYSTEM_PREFIXES = [
        "http://hl7.org/fhir/sid/icd-10",
        "http://loinc.org",
        "http://snomed.info/sct",
        "http://terminology.hl7.org",
        "https://nrces.in/ndhm/fhir",
        "http://unitsofmeasure.org",
        "https://ndhm.gov.in",
        "https://nhcx.health.gov.in",
        "http://www.nlm.nih.gov/research/umls/rxnorm",
        "http://terminology.hl7.org/CodeSystem/ex-benefitcategory",
        "http://terminology.hl7.org/CodeSystem/claim-type",
    ]

    # ── ABDM mandatory SNOMED codes ───────────────────────────────────────────
    ABDM_SNOMED_CODES = {"373942005", "4241000179101", "371530004", "440545006"}

    def validate(self, bundle: dict) -> dict:
        """
        Main entry point.
        Returns dict with OperationOutcome, readiness score, all issues.
        """
        issues = []

        if not bundle:
            return self._build_result([self._issue(
                "error", "required",
                "Bundle is empty or null", "Bundle",
                "Ensure the FHIR builder produced output"
            )])

        resources, full_urls = self._collect(bundle)

        self._check_bundle(bundle, issues)
        self._check_required_resources(resources, issues)
        self._check_composition(resources.get("Composition", []), issues)
        self._check_patient(resources.get("Patient", []), issues)
        self._check_claim(resources.get("Claim", []), issues)
        self._check_condition(resources.get("Condition", []), issues)
        self._check_observations(resources.get("Observation", []), issues)
        self._check_medication_requests(resources.get("MedicationRequest", []), issues)
        self._check_diagnostic_report(resources.get("DiagnosticReport", []), issues)
        self._check_references(bundle.get("entry", []), full_urls, issues)
        self._check_coding_systems(bundle.get("entry", []), issues)
        self._check_profiles(bundle.get("entry", []), issues)

        return self._build_result(issues, resources)

    # ── collection helpers ────────────────────────────────────────────────────
    def _collect(self, bundle):
        resources, full_urls = {}, {}
        for entry in bundle.get("entry", []):
            res = entry.get("resource", {})
            rt = res.get("resourceType")
            if rt:
                resources.setdefault(rt, []).append(res)
            if entry.get("fullUrl"):
                full_urls[entry["fullUrl"]] = res
        return resources, full_urls

    # ── individual checks ─────────────────────────────────────────────────────
    def _check_bundle(self, bundle, issues):
        if bundle.get("resourceType") != "Bundle":
            issues.append(self._issue("error","structure",
                "resourceType must be 'Bundle'","Bundle.resourceType",
                "Set root resourceType to 'Bundle'"))

        bt = bundle.get("type")
        if bt not in self.VALID_BUNDLE_TYPES:
            issues.append(self._issue("error","value",
                f"Bundle.type '{bt}' is invalid","Bundle.type",
                "ABDM requires Bundle.type = 'document'"))
        elif bt != "document":
            issues.append(self._issue("warning","business-rule",
                "ABDM clinical bundles must use type 'document'","Bundle.type",
                "Change Bundle.type from 'collection' to 'document'"))

        if not bundle.get("timestamp"):
            issues.append(self._issue("warning","required",
                "Bundle.timestamp missing","Bundle.timestamp",
                "Add ISO 8601 UTC timestamp"))

        nhcx_profile = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/ClaimBundle"
        if nhcx_profile not in bundle.get("meta",{}).get("profile",[]):
            issues.append(self._issue("warning","value",
                "Bundle should declare NHCX ClaimBundle profile","Bundle.meta.profile",
                f"Add '{nhcx_profile}' to Bundle.meta.profile"))

    def _check_required_resources(self, resources, issues):
        # Composition is mandatory — ABDM document bundle requirement
        if "Composition" not in resources:
            issues.append(self._issue("error","required",
                "Composition resource missing — ABDM mandate for document bundles",
                "Bundle.entry[0]",
                "Add Composition as FIRST entry with ABDM SNOMED HI type codes"))

        required = {
            "Patient": "Patient demographics required for all NHCX claims",
            "Claim": "Claim resource mandatory for NHCX submission",
            "Organization": "Provider Organization resource required",
            "Practitioner": "Treating doctor Practitioner resource required",
        }
        for rt, fix in required.items():
            if rt not in resources:
                issues.append(self._issue("error","required",
                    f"Required resource missing: {rt}",f"Bundle.entry",fix))

        recommended = {
            "Encounter": "Add Encounter with admission/discharge dates",
            "Condition": "Add Condition with ICD-10 coded primary diagnosis",
            "DocumentReference": "Embed original PDF for complete audit trail",
            "Provenance": "Record extraction metadata and data lineage",
        }
        for rt, fix in recommended.items():
            if rt not in resources:
                issues.append(self._issue("information","required",
                    f"Recommended resource missing: {rt}","Bundle.entry",fix))

    def _check_composition(self, compositions, issues):
        for comp in compositions:
            if not comp.get("status"):
                issues.append(self._issue("error","required",
                    "Composition.status required","Composition.status",
                    "Set to 'final' for completed documents"))

            codings = comp.get("type",{}).get("coding",[])
            if not codings:
                issues.append(self._issue("error","required",
                    "Composition.type must have SNOMED CT coding for ABDM HI type",
                    "Composition.type.coding",
                    "Use SNOMED 373942005 (Discharge Summary) or 4241000179101 (Diagnostic Report)"))
            else:
                valid = any(
                    c.get("system") == "http://snomed.info/sct" and
                    c.get("code") in self.ABDM_SNOMED_CODES
                    for c in codings
                )
                if not valid:
                    issues.append(self._issue("error","value",
                        "Composition.type must use official ABDM SNOMED HI type code",
                        "Composition.type.coding",
                        "Use system='http://snomed.info/sct' code='373942005' or '4241000179101'"))

            if not comp.get("subject"):
                issues.append(self._issue("error","required",
                    "Composition.subject (patient reference) required",
                    "Composition.subject","Add reference to Patient resource"))

            if not comp.get("author"):
                issues.append(self._issue("error","required",
                    "Composition.author required","Composition.author",
                    "Add reference to Practitioner resource"))

    def _check_patient(self, patients, issues):
        for patient in patients:
            if not patient.get("name") or not patient["name"][0].get("text",""):
                issues.append(self._issue("error","required",
                    "Patient.name missing","Patient.name",
                    "Ensure patient name is present in source document"))

            gender = patient.get("gender","")
            if not gender:
                issues.append(self._issue("warning","required",
                    "Patient.gender missing","Patient.gender",
                    "Check document for M/F indicator"))
            elif gender not in self.VALID_GENDERS:
                issues.append(self._issue("error","value",
                    f"Patient.gender '{gender}' invalid","Patient.gender",
                    f"Must be one of: {', '.join(self.VALID_GENDERS)}"))

            if not patient.get("birthDate"):
                issues.append(self._issue("warning","required",
                    "Patient.birthDate missing (age approximation used)",
                    "Patient.birthDate","Provide exact date of birth"))

    def _check_claim(self, claims, issues):
        for claim in claims:
            if claim.get("use") not in self.VALID_CLAIM_USE:
                issues.append(self._issue("error","value",
                    f"Claim.use '{claim.get('use')}' invalid","Claim.use",
                    "Set to 'claim' or 'preauthorization'"))

            if not claim.get("insurer"):
                issues.append(self._issue("error","required",
                    "Claim.insurer required for NHCX submission","Claim.insurer",
                    "Add insurer identifier from policy document"))

            if not claim.get("diagnosis"):
                issues.append(self._issue("error","required",
                    "Claim has no diagnosis linked","Claim.diagnosis",
                    "Link primary Condition resource"))

            if not claim.get("item"):
                issues.append(self._issue("warning","required",
                    "Claim has no items (procedures/services)","Claim.item",
                    "List procedures performed during hospitalisation"))

    def _check_condition(self, conditions, issues):
        for cond in conditions:
            if not cond.get("clinicalStatus"):
                issues.append(self._issue("error","required",
                    "Condition.clinicalStatus required","Condition.clinicalStatus",
                    "Set to 'resolved' for post-discharge diagnoses"))
            else:
                codes = [
                    c.get("code") for c in
                    cond.get("clinicalStatus",{}).get("coding",[])
                ]
                if not any(c in self.VALID_CONDITION_CLINICAL for c in codes):
                    issues.append(self._issue("error","value",
                        "Condition.clinicalStatus code invalid",
                        "Condition.clinicalStatus.coding.code",
                        f"Must be one of: {', '.join(self.VALID_CONDITION_CLINICAL)}"))

            icd_present = any(
                c.get("system") == "http://hl7.org/fhir/sid/icd-10"
                for c in cond.get("code",{}).get("coding",[])
            )
            if not icd_present:
                issues.append(self._issue("warning","value",
                    "Condition not ICD-10 coded","Condition.code.coding",
                    "ICD-10 code improves claim processing. Auto-coding was attempted."))

    def _check_observations(self, observations, issues):
        for obs in observations:
            has_value = any(
                obs.get(k) for k in
                ["valueQuantity","valueString","valueCodeableConcept","valueBoolean"]
            )
            if not has_value:
                issues.append(self._issue("warning","required",
                    "Observation has no result value","Observation.value[x]",
                    "Ensure lab result value present on the report"))

            if obs.get("status") not in self.VALID_OBS_STATUS:
                issues.append(self._issue("warning","value",
                    f"Observation.status invalid","Observation.status",
                    "Set to 'final' for submitted results"))

    def _check_medication_requests(self, meds, issues):
        for med in meds:
            if not med.get("medicationCodeableConcept") and not med.get("medicationReference"):
                issues.append(self._issue("error","required",
                    "MedicationRequest must identify medication",
                    "MedicationRequest.medication[x]","Add medication name"))
            if not med.get("status"):
                issues.append(self._issue("error","required",
                    "MedicationRequest.status required","MedicationRequest.status",
                    "Set to 'active'"))
            if not med.get("intent"):
                issues.append(self._issue("error","required",
                    "MedicationRequest.intent required","MedicationRequest.intent",
                    "Set to 'order' for discharge prescriptions"))

    def _check_diagnostic_report(self, reports, issues):
        for report in reports:
            if report.get("status") != "final":
                issues.append(self._issue("warning","value",
                    "DiagnosticReport.status should be 'final'",
                    "DiagnosticReport.status","Set to 'final'"))
            if not report.get("result"):
                issues.append(self._issue("warning","required",
                    "DiagnosticReport has no Observation results linked",
                    "DiagnosticReport.result",
                    "Link each lab result as an Observation"))

    def _check_references(self, entries, full_urls, issues):
        for entry in entries:
            rt = entry.get("resource",{}).get("resourceType","Unknown")
            self._walk_refs(entry.get("resource",{}), full_urls, issues, rt)

    def _walk_refs(self, obj, full_urls, issues, rt):
        if isinstance(obj, dict):
            if "reference" in obj:
                ref = obj["reference"]
                if ref and ref.startswith("urn:uuid:") and ref not in full_urls:
                    issues.append(self._issue("error","not-found",
                        f"Broken reference '{ref}' in {rt}",
                        f"{rt}.reference",
                        "All urn:uuid references must resolve inside this bundle"))
            for v in obj.values():
                self._walk_refs(v, full_urls, issues, rt)
        elif isinstance(obj, list):
            for item in obj:
                self._walk_refs(item, full_urls, issues, rt)

    def _check_coding_systems(self, entries, issues):
        for entry in entries:
            rt = entry.get("resource",{}).get("resourceType","Unknown")
            self._walk_systems(entry.get("resource",{}), issues, rt)

    def _walk_systems(self, obj, issues, rt):
        if isinstance(obj, dict):
            if "coding" in obj and isinstance(obj["coding"], list):
                for c in obj["coding"]:
                    system = c.get("system","")
                    if system and not any(
                        system.startswith(p) for p in self.VALID_SYSTEM_PREFIXES
                    ):
                        issues.append(self._issue("warning","value",
                            f"Non-standard coding system '{system}' in {rt}",
                            f"{rt}.coding.system",
                            "Use official systems: ICD-10, LOINC, SNOMED CT, NHCX"))
            for v in obj.values():
                self._walk_systems(v, issues, rt)
        elif isinstance(obj, list):
            for item in obj:
                self._walk_systems(item, issues, rt)

    def _check_profiles(self, entries, issues):
        nrces = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/"
        for entry in entries:
            res = entry.get("resource",{})
            rt = res.get("resourceType")
            profiles = res.get("meta",{}).get("profile",[])
            if rt and not profiles:
                issues.append(self._issue("information","value",
                    f"{rt} has no NRCeS profile in meta.profile",
                    f"{rt}.meta.profile",
                    f"Add profile URL: {nrces}{rt}"))

    # ── readiness score ───────────────────────────────────────────────────────
    def _readiness(self, resources, errors, warnings) -> dict:
        weights = {
            "Patient":10, "Claim":15, "Organization":8,
            "Practitioner":8, "Condition":8, "Composition":12,
            "Encounter":5, "DocumentReference":5, "Provenance":5,
            "DiagnosticReport":5, "Observation":5, "MedicationRequest":5,
        }
        score = 100
        for rt, w in weights.items():
            if rt not in resources:
                score -= w
        score -= min(len(errors) * 3, 25)
        score -= min(len(warnings), 10)
        score = max(0, score)

        if score >= 90:
            status, color = "Ready for NHCX submission", "green"
        elif score >= 75:
            status, color = "Review warnings before submitting", "yellow"
        elif score >= 50:
            status, color = "Fix errors — not ready for submission", "orange"
        else:
            status, color = "Critical issues — major rework needed", "red"

        return {
            "score": score,
            "status": status,
            "color": color,
            "resources_present": list(resources.keys()),
            "resources_missing": [r for r in weights if r not in resources],
        }

    # ── output builders ───────────────────────────────────────────────────────
    def _build_result(self, issues, resources=None) -> dict:
        resources = resources or {}
        errors   = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]
        infos    = [i for i in issues if i["severity"] == "information"]

        operation_outcome = {
            "resourceType": "OperationOutcome",
            "id": "validation-result",
            "issue": [
                {
                    "severity": i["severity"],
                    "code": i["code"],
                    "details": {"text": i["message"]},
                    "diagnostics": i.get("fix",""),
                    "expression": [i.get("location","")],
                }
                for i in issues
            ],
        }

        readiness = self._readiness(resources, errors, warnings)
        is_valid = len(errors) == 0

        logger.info(
            f"Validation — valid:{is_valid} errors:{len(errors)} "
            f"warnings:{len(warnings)} score:{readiness['score']}"
        )

        return {
            "valid": is_valid,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "info_count": len(infos),
            "errors": errors,
            "warnings": warnings,
            "suggestions": infos,
            "operation_outcome": operation_outcome,
            "readiness": readiness,
            "summary": readiness["status"],
        }

    def _issue(self, severity, code, message, location, fix) -> dict:
        return {
            "severity": severity,
            "code": code,
            "message": message,
            "location": location,
            "fix": fix,
        }
