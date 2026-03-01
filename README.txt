# NHCX FHIR Converter

Open-source microservice that converts clinical PDFs (discharge summaries, diagnostic reports) into **ABDM/NHCX-compliant FHIR R4 bundles** for insurance claim submission and pre-authorization.

Built for **NHCX Hackathon — IIT Hyderabad**.

---

## What It Does

Upload PDF → Detect HI Type → AI Extraction → ICD-10/LOINC Coding → FHIR Bundle → Validate → Download

---

## Unique Features

| Feature | Generic Tools | This Tool |
|---|---|---|
| Bundle type | `collection` (wrong) | `document` (ABDM correct) ✅ |
| Composition resource | Missing | Full ABDM SNOMED codes ✅ |
| Validation response | Custom JSON | FHIR OperationOutcome ✅ |
| Diagnosis coding | AI text copied | Offline ICD-10 engine ✅ |
| Lab test coding | AI text copied | Offline LOINC engine ✅ |
| Multi-document | Missing | Fusion + conflict detection ✅ |
| Pre-authorization | Missing | CoverageEligibilityRequest ✅ |
| Original PDF | Discarded | Embedded in DocumentReference ✅ |
| Data provenance | None | Provenance resource ✅ |
| Readiness score | Binary valid/invalid | 0–100 with breakdown ✅ |

---

## Quick Start (Mac)

```bash
cd nhcx-fhir-converter
chmod +x setup.sh && ./setup.sh
source venv/bin/activate
export GEMINI_API_KEY=your_key_here
uvicorn main:app --reload --port 8000
open http://localhost:8000
