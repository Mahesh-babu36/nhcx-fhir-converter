# NHCX FHIR Converter

Open-source microservice that converts clinical PDFs (discharge summaries, diagnostic reports) into **ABDM/NHCX-compliant FHIR R4 bundles** for insurance claim submission and pre-authorization.

Built for **NHCX Hackathon — IIT Hyderabad**.

---

## What It Does

```
Upload PDF → Detect HI Type → AI Extraction → ICD-10/LOINC Coding → FHIR Bundle → Validate → Download
```

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
# 1. Clone or download the project
cd nhcx-fhir-converter

# 2. Run the setup script (installs everything)
chmod +x setup.sh && ./setup.sh

# 3. Add your free Gemini API key to .env
#    Get it at: https://aistudio.google.com

# 4. Start the server
source venv/bin/activate
export GEMINI_API_KEY=your_key_here
uvicorn main:app --reload --port 8000

# 5. Open browser
open http://localhost:8000
```

---

## Folder Structure

```
nhcx-fhir-converter/
├── main.py                    ← FastAPI server + all endpoints
├── database.py                ← SQLite conversion history
├── utils.py                   ← Shared helper functions
├── requirements.txt           ← Python dependencies
├── setup.sh                   ← One-command Mac setup
│
├── pipeline/
│   ├── abdm_profiles.py       ← Official ABDM/NHCX profile URLs & codes
│   ├── extractor.py           ← PDF text extraction (digital + OCR)
│   ├── detector.py            ← ABDM HI type detection
│   ├── ai_parser.py           ← Gemini AI clinical data extraction
│   ├── coding_engine.py       ← Offline ICD-10 + LOINC coding
│   ├── fusion_engine.py       ← Multi-document merger
│   ├── fhir_builder.py        ← FHIR R4 bundle builder
│   └── validator.py           ← OperationOutcome validation
│
├── config/
│   └── mapping.yaml           ← Configuration
│
└── static/
    └── index.html             ← Frontend UI
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Frontend UI |
| GET | `/health` | Service status |
| POST | `/convert` | Single PDF → FHIR bundle |
| POST | `/convert/claim` | Multi-PDF → claim bundle |
| POST | `/validate` | Validate existing FHIR bundle |
| GET | `/history` | Conversion history |
| GET | `/codes/icd10?q=diabetes` | ICD-10 code search |
| GET | `/codes/loinc?q=hemoglobin` | LOINC code search |

---

## Cost

Everything is free.

| Resource | Cost |
|---|---|
| Python, FastAPI, SQLite | ₹0 |
| Tesseract OCR | ₹0 |
| Gemini API (1500 req/day) | ₹0 |
| Hosting on Render.com | ₹0 |
| **Total** | **₹0** |

---

## ABDM Compliance

- Bundle type: `document` (not `collection`)
- Composition as first entry with SNOMED CT HI type codes
  - Discharge Summary: `373942005`
  - Diagnostic Report: `4241000179101`
- NRCeS profile URLs on all resources
- FHIR OperationOutcome for validation errors
- ICD-10 coded Condition resources
- LOINC coded Observation resources

---

## License

MIT — open source, free to use and modify.
