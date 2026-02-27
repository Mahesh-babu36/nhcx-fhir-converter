"""
pipeline/fhir_builder.py
------------------------
Builds NHCX-compliant FHIR R4 document bundles.

Key ABDM compliance points:
  • Bundle type = "document" (NOT "collection")
  • First entry = Composition with ABDM SNOMED HI type code
  • All resources carry NRCeS profile URLs in meta.profile
  • DocumentReference embeds the original PDF as base64
  • Provenance records extraction metadata
  • Supports both Claim and CoverageEligibilityRequest use cases
"""

import os
import base64
from utils import generate_id, current_timestamp, safe_parse_date, age_to_birth_year, logger
from pipeline.abdm_profiles import get_hi_type, get_profile, SYSTEMS


class FHIRBundleBuilder:

    def build(
        self,
        clinical_data: dict,
        doc_type: str,
        use_case: str = "claim",
        source_pdf_paths: list = None,
    ) -> dict:
        """
        Build a complete NHCX FHIR document bundle.

        Args:
            clinical_data  — extracted and fused clinical data dict
            doc_type       — 'discharge_summary' | 'diagnostic_report' | ...
            use_case       — 'claim' | 'preauthorization'
            source_pdf_paths — list of original PDF paths for DocumentReference

        Returns:
            FHIR Bundle dict
        """
        source_pdf_paths = source_pdf_paths or []
        hi_type = get_hi_type(doc_type)

        # Generate IDs for all resources
        ids = {k: generate_id() for k in [
            "bundle", "composition", "patient", "organization",
            "practitioner", "encounter", "condition",
            "diagnostic_report", "claim", "provenance",
        ]}

        entries = []
        all_resource_ids = []

        # ── Patient ──────────────────────────────────────────────────────────
        patient = self._build_patient(clinical_data, ids["patient"])
        entries.append(self._entry(ids["patient"], patient))
        all_resource_ids.append(ids["patient"])

        # ── Organization ─────────────────────────────────────────────────────
        org = self._build_organization(clinical_data, ids["organization"])
        entries.append(self._entry(ids["organization"], org))
        all_resource_ids.append(ids["organization"])

        # ── Practitioner ─────────────────────────────────────────────────────
        practitioner = self._build_practitioner(clinical_data, ids["practitioner"])
        entries.append(self._entry(ids["practitioner"], practitioner))
        all_resource_ids.append(ids["practitioner"])

        # ── Encounter ────────────────────────────────────────────────────────
        encounter = self._build_encounter(
            clinical_data, ids["encounter"],
            ids["patient"], ids["organization"], ids["practitioner"]
        )
        entries.append(self._entry(ids["encounter"], encounter))
        all_resource_ids.append(ids["encounter"])

        # ── Condition (primary diagnosis) ────────────────────────────────────
        condition = self._build_condition(clinical_data, ids["condition"], ids["patient"])
        entries.append(self._entry(ids["condition"], condition))
        all_resource_ids.append(ids["condition"])

        # ── Observations (lab tests) ─────────────────────────────────────────
        observation_ids = []
        tests = clinical_data.get("tests", [])
        for i, test in enumerate(tests):
            obs_id = generate_id()
            obs = self._build_observation(test, obs_id, ids["patient"])
            entries.append(self._entry(obs_id, obs))
            observation_ids.append(obs_id)
            all_resource_ids.append(obs_id)

        # ── DiagnosticReport (for lab results) ──────────────────────────────
        if tests or doc_type in ("diagnostic_report", "lab_report"):
            dr = self._build_diagnostic_report(
                clinical_data, ids["diagnostic_report"],
                ids["patient"], ids["practitioner"], observation_ids
            )
            entries.append(self._entry(ids["diagnostic_report"], dr))
            all_resource_ids.append(ids["diagnostic_report"])

        # ── MedicationRequests ───────────────────────────────────────────────
        meds = clinical_data.get("medications_at_discharge", [])
        med_ids = []
        for med in meds:
            med_id = generate_id()
            med_res = self._build_medication_request(med, med_id, ids["patient"])
            entries.append(self._entry(med_id, med_res))
            med_ids.append(med_id)
            all_resource_ids.append(med_id)

        # ── Claim or CoverageEligibilityRequest ──────────────────────────────
        if use_case == "preauthorization":
            coverage_id = generate_id()
            coverage = self._build_coverage(clinical_data, ids["patient"], coverage_id)
            entries.append(self._entry(coverage_id, coverage))
            all_resource_ids.append(coverage_id)

            claim = self._build_coverage_eligibility_request(
                clinical_data, ids["claim"],
                ids["patient"], ids["organization"], coverage_id
            )
        else:
            claim = self._build_claim(
                clinical_data, ids["claim"],
                ids["patient"], ids["organization"], ids["practitioner"],
                ids["encounter"], ids["condition"]
            )
        entries.append(self._entry(ids["claim"], claim))
        all_resource_ids.append(ids["claim"])

        # ── DocumentReference (embeds original PDFs) ─────────────────────────
        doc_ref_ids = []
        for pdf_path in source_pdf_paths:
            dr_id = generate_id()
            doc_ref = self._build_document_reference(
                pdf_path, ids["patient"], doc_type, dr_id
            )
            entries.append(self._entry(dr_id, doc_ref))
            doc_ref_ids.append(dr_id)
            all_resource_ids.append(dr_id)

        # ── Provenance ───────────────────────────────────────────────────────
        prov = self._build_provenance(
            all_resource_ids, ids["practitioner"], ids["provenance"],
            source_pdf_paths
        )
        entries.append(self._entry(ids["provenance"], prov))

        # ── Composition (MUST be first entry) ────────────────────────────────
        resource_refs = {
            "patient": ids["patient"],
            "practitioner": ids["practitioner"],
            "organization": ids["organization"],
            "encounter": ids["encounter"],
            "condition": ids["condition"],
            "observations": observation_ids,
            "claim": ids["claim"],
            "doc_refs": doc_ref_ids,
        }
        composition = self._build_composition(
            clinical_data, hi_type, doc_type,
            ids["composition"], ids["patient"],
            ids["practitioner"], ids["organization"],
            resource_refs
        )
        # Insert Composition as the FIRST entry (ABDM mandate)
        entries.insert(0, self._entry(ids["composition"], composition))

        # ── Bundle ───────────────────────────────────────────────────────────
        bundle = {
            "resourceType": "Bundle",
            "id": ids["bundle"],
            "meta": {
                "lastUpdated": current_timestamp(),
                "profile": [get_profile("Bundle")],
            },
            "identifier": {
                "system": SYSTEMS["ndhm_bundle"],
                "value": ids["bundle"],
            },
            "type": "document",          # ABDM requires "document" not "collection"
            "timestamp": current_timestamp(),
            "entry": entries,
        }

        logger.info(
            f"Built FHIR bundle: {len(entries)} resources, "
            f"use_case={use_case}, doc_type={doc_type}"
        )
        return bundle

    # ── Resource builders ─────────────────────────────────────────────────────

    def _build_composition(
        self, data, hi_type, doc_type,
        comp_id, patient_id, practitioner_id, org_id, refs
    ) -> dict:
        return {
            "resourceType": "Composition",
            "id": comp_id,
            "meta": {"profile": [hi_type["composition_profile"]]},
            "status": "final",
            "type": {
                "coding": [{
                    "system": hi_type["snomed_system"],
                    "code": hi_type["snomed_code"],
                    "display": hi_type["snomed_display"],
                }]
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "date": current_timestamp(),
            "author": [{"reference": f"urn:uuid:{practitioner_id}"}],
            "custodian": {"reference": f"urn:uuid:{org_id}"},
            "title": hi_type["display"],
            "section": self._build_sections(doc_type, data, refs),
        }

    def _build_sections(self, doc_type, data, refs) -> list:
        sections = []
        if doc_type == "discharge_summary":
            sections += [
                {
                    "title": "Chief Complaint",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "10154-3", "display": "Chief complaint"}]},
                    "text": {"status": "generated", "div": f"<div>{data.get('chief_complaint','')}</div>"},
                },
                {
                    "title": "Diagnoses",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "29548-5", "display": "Diagnosis"}]},
                    "entry": [{"reference": f"urn:uuid:{refs.get('condition')}"}],
                    "text": {"status": "generated", "div": f"<div>{data.get('primary_diagnosis','')}</div>"},
                },
                {
                    "title": "Medications on Discharge",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "75311-1", "display": "Discharge medications"}]},
                    "text": {"status": "generated", "div": "<div>See MedicationRequest resources</div>"},
                },
            ]
        elif doc_type in ("diagnostic_report", "lab_report"):
            sections.append({
                "title": "Laboratory Results",
                "code": {"coding": [{"system": "http://loinc.org", "code": "30954-2", "display": "Relevant diagnostic tests"}]},
                "entry": [{"reference": f"urn:uuid:{oid}"} for oid in refs.get("observations", [])],
                "text": {"status": "generated", "div": "<div>See Observation resources</div>"},
            })
        return sections

    def _build_patient(self, data, patient_id) -> dict:
        birth_date = safe_parse_date(data.get("patient_dob", ""))
        if not birth_date and data.get("patient_age"):
            birth_date = age_to_birth_year(data["patient_age"])

        resource = {
            "resourceType": "Patient",
            "id": patient_id,
            "meta": {"profile": [get_profile("Patient")]},
            "identifier": [
                {
                    "system": SYSTEMS["ndhm_patient"],
                    "value": str(data.get("patient_id", generate_id()[:8])),
                }
            ],
            "name": [{"use": "official", "text": data.get("patient_name", "Unknown")}],
            "gender": data.get("patient_gender", "unknown"),
        }
        if birth_date:
            resource["birthDate"] = birth_date
        if data.get("patient_phone"):
            resource["telecom"] = [{"system": "phone", "value": str(data["patient_phone"])}]
        if data.get("patient_address"):
            resource["address"] = [{"text": str(data["patient_address"])}]
        return resource

    def _build_organization(self, data, org_id) -> dict:
        return {
            "resourceType": "Organization",
            "id": org_id,
            "meta": {"profile": [get_profile("Organization")]},
            "identifier": [
                {
                    "system": SYSTEMS["nhcx_provider"],
                    "value": data.get("hospital_name", "UNKNOWN_HOSPITAL")
                              .upper().replace(" ", "_")[:30],
                }
            ],
            "name": data.get("hospital_name", "Unknown Hospital"),
            "address": [{"text": data.get("hospital_address", "")}],
            "telecom": [{"system": "phone", "value": data.get("hospital_phone", "")}]
            if data.get("hospital_phone") else [],
        }

    def _build_practitioner(self, data, prac_id) -> dict:
        name = data.get("treating_doctor") or data.get("referring_doctor", "Unknown Doctor")
        qualification = data.get("doctor_qualification", "MBBS")
        return {
            "resourceType": "Practitioner",
            "id": prac_id,
            "meta": {"profile": [get_profile("Practitioner")]},
            "identifier": [
                {
                    "system": "https://ndhm.gov.in/practitioners",
                    "value": data.get("doctor_registration", generate_id()[:8]),
                }
            ],
            "name": [{"use": "official", "text": str(name)}],
            "qualification": [
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v2-0360",
                                "code": "MD",
                                "display": str(qualification),
                            }
                        ]
                    }
                }
            ],
        }

    def _build_encounter(self, data, enc_id, patient_id, org_id, prac_id) -> dict:
        enc = {
            "resourceType": "Encounter",
            "id": enc_id,
            "meta": {"profile": [get_profile("Encounter")]},
            "status": "finished",
            "class": {
                "system": SYSTEMS["encounter_class"],
                "code": "IMP",
                "display": "Inpatient",
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "serviceProvider": {"reference": f"urn:uuid:{org_id}"},
            "participant": [
                {
                    "individual": {"reference": f"urn:uuid:{prac_id}"}
                }
            ],
        }
        period = {}
        adm = safe_parse_date(data.get("admission_date", ""))
        dis = safe_parse_date(data.get("discharge_date", ""))
        if adm:
            period["start"] = adm + "T00:00:00Z"
        if dis:
            period["end"] = dis + "T23:59:00Z"
        if period:
            enc["period"] = period
        return enc

    def _build_condition(self, data, cond_id, patient_id) -> dict:
        coding = {
            "system": SYSTEMS["snomed"],
            "display": data.get("primary_diagnosis", "Unspecified condition"),
        }

        diag_coding = data.get("primary_diagnosis_coding", {})
        if diag_coding.get("matched"):
            coding = {
                "system": diag_coding.get("system_uri", SYSTEMS["icd10"]),
                "code": diag_coding["code"],
                "display": diag_coding["display"],
            }
        elif data.get("primary_diagnosis_icd10"):
            coding = {
                "system": SYSTEMS["icd10"],
                "code": data["primary_diagnosis_icd10"],
                "display": data.get("primary_diagnosis", ""),
            }

        return {
            "resourceType": "Condition",
            "id": cond_id,
            "meta": {"profile": [get_profile("Condition")]},
            "clinicalStatus": {
                "coding": [{
                    "system": SYSTEMS["condition_clinical"],
                    "code": "resolved",
                    "display": "Resolved",
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }]
            },
            "category": [
                {
                    "coding": [{
                        "system": SYSTEMS["condition_category"],
                        "code": "encounter-diagnosis",
                        "display": "Encounter Diagnosis",
                    }]
                }
            ],
            "code": {
                "coding": [coding],
                "text": data.get("primary_diagnosis", ""),
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
        }

    def _build_observation(self, test: dict, obs_id: str, patient_id: str) -> dict:
        loinc_coding = test.get("loinc_coding", {})

        code_coding = {
            "display": test.get("test_name", "Unknown test"),
        }
        if loinc_coding.get("matched"):
            code_coding = {
                "system": SYSTEMS["loinc"],
                "code": loinc_coding["code"],
                "display": loinc_coding["display"],
            }

        obs = {
            "resourceType": "Observation",
            "id": obs_id,
            "meta": {"profile": [get_profile("Observation")]},
            "status": "final",
            "code": {
                "coding": [code_coding],
                "text": test.get("test_name", ""),
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
        }

        # Result value
        val = test.get("result_value")
        unit = test.get("unit", "")
        if val is not None:
            try:
                obs["valueQuantity"] = {
                    "value": float(str(val).replace(",", "")),
                    "unit": str(unit),
                    "system": SYSTEMS["ucum"],
                }
            except ValueError:
                obs["valueString"] = str(val)

        # Reference range
        ref_range = test.get("reference_range")
        if ref_range:
            obs["referenceRange"] = [{"text": str(ref_range)}]

        # Abnormal flag
        flag = test.get("abnormal_flag", "")
        if flag and flag.upper() in ("HIGH", "LOW"):
            obs["interpretation"] = [
                {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": "H" if flag.upper() == "HIGH" else "L",
                        "display": flag.upper(),
                    }]
                }
            ]

        return obs

    def _build_diagnostic_report(
        self, data, dr_id, patient_id, prac_id, obs_ids
    ) -> dict:
        return {
            "resourceType": "DiagnosticReport",
            "id": dr_id,
            "meta": {"profile": [get_profile("DiagnosticReport")]},
            "status": "final",
            "code": {
                "coding": [{
                    "system": SYSTEMS["loinc"],
                    "code": "11502-2",
                    "display": "Laboratory report",
                }]
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "performer": [{"reference": f"urn:uuid:{prac_id}"}],
            "result": [{"reference": f"urn:uuid:{oid}"} for oid in obs_ids],
            "conclusion": data.get("impression", ""),
        }

    def _build_medication_request(self, med, med_id, patient_id) -> dict:
        if isinstance(med, dict):
            name = med.get("name", str(med))
            dose = med.get("dose", "")
            freq = med.get("frequency", "")
        else:
            name = str(med)
            dose = freq = ""

        return {
            "resourceType": "MedicationRequest",
            "id": med_id,
            "meta": {"profile": [get_profile("MedicationRequest")]},
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {
                "text": name,
                "coding": [{
                    "system": SYSTEMS["rxnorm"],
                    "display": name,
                }],
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "dosageInstruction": [
                {
                    "text": f"{dose} {freq}".strip(),
                    "doseAndRate": [
                        {
                            "doseQuantity": {
                                "value": 1,
                                "unit": dose,
                            }
                        }
                    ] if dose else [],
                }
            ],
        }

    def _build_claim(
        self, data, claim_id,
        patient_id, org_id, prac_id, enc_id, cond_id
    ) -> dict:
        insurer_value = (
            data.get("insurer_name", "UNKNOWN_INSURER")
            .upper().replace(" ", "_")
            if data.get("insurer_name") else "UNKNOWN_INSURER"
        )

        claim = {
            "resourceType": "Claim",
            "id": claim_id,
            "meta": {"profile": [get_profile("Claim")]},
            "status": "active",
            "type": {
                "coding": [{
                    "system": SYSTEMS["claim_type"],
                    "code": "institutional",
                    "display": "Institutional",
                }]
            },
            "use": "claim",
            "patient": {"reference": f"urn:uuid:{patient_id}"},
            "created": current_timestamp(),
            "insurer": {
                "identifier": {
                    "system": SYSTEMS["nhcx_insurer"],
                    "value": insurer_value,
                }
            },
            "provider": {"reference": f"urn:uuid:{org_id}"},
            "priority": {
                "coding": [{
                    "system": SYSTEMS["process_priority"],
                    "code": "normal",
                }]
            },
            "diagnosis": [
                {
                    "sequence": 1,
                    "diagnosisReference": {"reference": f"urn:uuid:{cond_id}"},
                }
            ],
            "insurance": [
                {
                    "sequence": 1,
                    "focal": True,
                    "identifier": {
                        "system": SYSTEMS["nhcx_insurer"],
                        "value": data.get("insurance_id", "UNKNOWN_POLICY"),
                    },
                    "coverage": {
                        "display": data.get("insurer_name", "Unknown Insurer")
                    },
                }
            ],
            "item": [
                {
                    "sequence": i + 1,
                    "productOrService": {
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/ex-USCLS",
                            "display": str(proc),
                        }]
                    },
                }
                for i, proc in enumerate(
                    data.get("procedures_performed", ["Inpatient Treatment"])
                )
            ],
        }

        if data.get("claim_amount"):
            try:
                claim["total"] = {
                    "value": float(str(data["claim_amount"]).replace(",", "")),
                    "currency": "INR",
                }
            except ValueError:
                pass

        return claim

    def _build_coverage(self, data, patient_id, coverage_id) -> dict:
        return {
            "resourceType": "Coverage",
            "id": coverage_id,
            "status": "active",
            "subscriber": {"reference": f"urn:uuid:{patient_id}"},
            "beneficiary": {"reference": f"urn:uuid:{patient_id}"},
            "subscriberId": data.get("insurance_id", ""),
            "payor": [{
                "identifier": {
                    "system": SYSTEMS["nhcx_insurer"],
                    "value": data.get("insurer_name", "UNKNOWN_INSURER")
                              .upper().replace(" ", "_")
                              if data.get("insurer_name") else "UNKNOWN_INSURER",
                },
                "display": data.get("insurer_name", "Unknown Insurer"),
            }],
        }

    def _build_coverage_eligibility_request(
        self, data, req_id, patient_id, org_id, coverage_id
    ) -> dict:
        return {
            "resourceType": "CoverageEligibilityRequest",
            "id": req_id,
            "meta": {"profile": [get_profile("CoverageEligibilityRequest")]},
            "status": "active",
            "purpose": ["benefits"],
            "patient": {"reference": f"urn:uuid:{patient_id}"},
            "created": current_timestamp(),
            "provider": {"reference": f"urn:uuid:{org_id}"},
            "insurer": {
                "identifier": {
                    "system": SYSTEMS["nhcx_insurer"],
                    "value": data.get("insurer_name", "UNKNOWN_INSURER")
                              .upper().replace(" ", "_")
                              if data.get("insurer_name") else "UNKNOWN_INSURER",
                }
            },
            "insurance": [
                {
                    "focal": True,
                    "coverage": {"reference": f"urn:uuid:{coverage_id}"},
                }
            ],
            "item": [
                {
                    "category": {
                        "coding": [{
                            "system": SYSTEMS["benefit_category"],
                            "code": "medical",
                            "display": "Medical",
                        }]
                    },
                    "productOrService": {"text": str(proc)},
                }
                for proc in data.get("procedures_performed", ["Proposed Treatment"])
            ],
        }

    def _build_document_reference(
        self, pdf_path, patient_id, doc_type, dr_id
    ) -> dict:
        """Embed original PDF as base64 in DocumentReference."""
        pdf_b64 = ""
        try:
            if os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    pdf_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not encode PDF {pdf_path}: {e}")

        type_map = {
            "discharge_summary": ("34105-7", "Hospital Discharge summary"),
            "diagnostic_report": ("11502-2", "Laboratory report"),
            "lab_report": ("11502-2", "Laboratory report"),
        }
        loinc_code, loinc_display = type_map.get(
            doc_type, ("34105-7", "Hospital Discharge summary")
        )

        return {
            "resourceType": "DocumentReference",
            "id": dr_id,
            "meta": {"profile": [get_profile("DocumentReference")]},
            "status": "current",
            "type": {
                "coding": [{
                    "system": SYSTEMS["loinc"],
                    "code": loinc_code,
                    "display": loinc_display,
                }]
            },
            "subject": {"reference": f"urn:uuid:{patient_id}"},
            "date": current_timestamp(),
            "content": [{
                "attachment": {
                    "contentType": "application/pdf",
                    "data": pdf_b64,
                    "title": os.path.basename(pdf_path) if pdf_path else "source.pdf",
                }
            }],
        }

    def _build_provenance(
        self, resource_ids, practitioner_id, prov_id, source_paths
    ) -> dict:
        return {
            "resourceType": "Provenance",
            "id": prov_id,
            "meta": {"profile": [get_profile("Provenance")]},
            "target": [{"reference": f"urn:uuid:{rid}"} for rid in resource_ids],
            "recorded": current_timestamp(),
            "reason": [
                {
                    "coding": [{
                        "system": SYSTEMS["act_reason"],
                        "code": "TREAT",
                        "display": "Treatment",
                    }]
                }
            ],
            "activity": {
                "coding": [{
                    "system": SYSTEMS["data_operation"],
                    "code": "CREATE",
                    "display": "Create",
                }]
            },
            "agent": [
                {
                    "type": {
                        "coding": [{
                            "system": SYSTEMS["provenance_agent"],
                            "code": "author",
                            "display": "Author",
                        }]
                    },
                    "who": {"reference": f"urn:uuid:{practitioner_id}"},
                    "onBehalfOf": {"display": "NHCX FHIR Converter v1.0.0"},
                }
            ],
            "entity": [
                {
                    "role": "source",
                    "what": {
                        "display": f"Source PDF: {os.path.basename(p) if p else 'unknown'}"
                    },
                }
                for p in source_paths
            ],
        }

    def _entry(self, resource_id, resource) -> dict:
        return {
            "fullUrl": f"urn:uuid:{resource_id}",
            "resource": resource,
        }
