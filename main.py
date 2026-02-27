"""
main.py
-------
FastAPI microservice — the central hub connecting all pipeline components.
Serves the frontend and handles all API endpoints.

Endpoints:
  GET  /              → serves index.html
  GET  /health        → service health check
  POST /convert       → single PDF conversion
  POST /convert/claim → multi-document claim bundle
  POST /validate      → validate an existing FHIR bundle
  GET  /history       → conversion history from database
  GET  /codes/icd10   → ICD-10 code search
  GET  /codes/loinc   → LOINC code search
"""

import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

# Load .env file first — works locally and on Render.com
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from pipeline.extractor import PDFExtractor
from pipeline.detector import DocumentTypeDetector
from pipeline.ai_parser import AIParser
from pipeline.coding_engine import ClinicalCodingEngine
from pipeline.fusion_engine import DocumentFusionEngine
from pipeline.fhir_builder import FHIRBundleBuilder
from pipeline.validator import FHIRValidator
from database import init_db, save_conversion, get_all_conversions, clear_all, get_stats
from utils import logger

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="NHCX FHIR Converter",
    description="Open-source PDF → ABDM/NHCX FHIR R4 bundle converter",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (index.html)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ── Pipeline instances (created once at startup) ──────────────────────────────
extractor     = PDFExtractor()
detector      = DocumentTypeDetector()
ai_parser     = AIParser()
coding_engine = ClinicalCodingEngine()
fusion_engine = DocumentFusionEngine()
fhir_builder  = FHIRBundleBuilder()
validator     = FHIRValidator()


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("NHCX FHIR Converter started — http://localhost:8000")


# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"message": "NHCX FHIR Converter API running", "version": "1.0.0"})


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "running",
        "version": "1.0.0",
        "service": "NHCX FHIR Converter",
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY")),
    }


# ── Single PDF conversion ────────────────────────────────────────────────────
@app.post("/convert")
async def convert_single(
    file: UploadFile = File(...),
    use_case: str = Form("claim"),
    hospital_template: str = Form("default"),
):
    """
    Convert a single clinical PDF to an NHCX-compliant FHIR bundle.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    tmp_path = None
    try:
        # Save upload to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        result = _process_one_pdf(tmp_path, file.filename)

        # Build FHIR bundle
        fhir_bundle = fhir_builder.build(
            result["clinical_data"],
            result["doc_type"],
            use_case=use_case,
            source_pdf_paths=[tmp_path],
        )

        # Validate
        validation = validator.validate(fhir_bundle)

        # Persist
        save_conversion(
            file.filename, result["doc_type"],
            result["clinical_data"], validation, fhir_bundle, use_case
        )

        return JSONResponse(content={
            "status": "success",
            "file_name": file.filename,
            "doc_type": result["doc_type"],
            "detection_confidence": result["detection"].get("confidence_percent", 0),
            "clinical_data": result["clinical_data"],
            "pipeline": {
                "extraction": {
                    "total_pages": result["extraction"].get("total_pages", 0),
                    "total_chars": result["extraction"].get("total_chars", 0),
                    "used_ocr": result["extraction"].get("used_ocr", False),
                },
                "detection": result["detection"],
            },
            "validation": validation,
            "fhir_bundle": fhir_bundle,
        })

    except Exception as e:
        logger.error(f"Conversion failed: {e}", exc_info=True)
        raise HTTPException(500, f"Conversion failed: {str(e)}")

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── Multi-document claim bundle ───────────────────────────────────────────────
@app.post("/convert/claim")
async def convert_claim(
    files: list[UploadFile] = File(...),
    use_case: str = Form("claim"),
):
    """
    Accept multiple PDFs and fuse them into one NHCX claim bundle.
    Supports up to 5 files (discharge summary + lab reports).
    """
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 5:
        raise HTTPException(400, "Maximum 5 files per claim")

    tmp_paths = []
    try:
        processed_docs = []

        for upload in files:
            if not upload.filename.lower().endswith(".pdf"):
                raise HTTPException(400, f"{upload.filename} is not a PDF")

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                shutil.copyfileobj(upload.file, tmp)
                tmp_paths.append(tmp.name)

            result = _process_one_pdf(tmp.name, upload.filename)
            processed_docs.append(result)

        # Fuse all documents
        fusion = fusion_engine.fuse(processed_docs)

        # Use primary document type for bundle structure
        primary_doc_type = processed_docs[0]["doc_type"]

        # Build FHIR bundle from fused data
        fhir_bundle = fhir_builder.build(
            fusion["unified_record"],
            primary_doc_type,
            use_case=use_case,
            source_pdf_paths=tmp_paths,
        )

        validation = validator.validate(fhir_bundle)

        # Save primary file
        save_conversion(
            ", ".join(f["file_name"] for f in processed_docs),
            primary_doc_type,
            fusion["unified_record"],
            validation, fhir_bundle, use_case
        )

        return JSONResponse(content={
            "status": "success",
            "file_names": [d["file_name"] for d in processed_docs],
            "doc_types": [d["doc_type"] for d in processed_docs],
            "primary_doc_type": primary_doc_type,
            "use_case": use_case,
            "clinical_data": fusion["unified_record"],
            "fusion": {
                "conflicts_detected": len(fusion["conflicts"]),
                "conflicts": fusion["conflicts"],
                "field_sources": fusion["provenance"],
                "sources": fusion["sources"],
            },
            "validation": validation,
            "fhir_bundle": fhir_bundle,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multi-doc conversion failed: {e}", exc_info=True)
        raise HTTPException(500, f"Conversion failed: {str(e)}")

    finally:
        for p in tmp_paths:
            if os.path.exists(p):
                os.unlink(p)


# ── Validate existing FHIR bundle ────────────────────────────────────────────
@app.post("/validate")
async def validate_bundle(request: Request):
    """
    Validate an existing FHIR bundle.
    Returns FHIR OperationOutcome with issues and fix suggestions.
    """
    try:
        body = await request.json()
        result = validator.validate(body)
        return JSONResponse(content=result)
    except json.JSONDecodeError:
        raise HTTPException(400, "Request body must be valid JSON")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── History ───────────────────────────────────────────────────────────────────
@app.get("/history")
async def history():
    return JSONResponse(content={"conversions": get_all_conversions()})


@app.delete("/history")
async def delete_history():
    clear_all()
    return {"message": "History cleared"}


# ── Statistics ────────────────────────────────────────────────────────────────
@app.get("/stats")
async def stats():
    """
    Returns aggregated analytics about all conversions processed.
    Useful for monitoring and demo dashboards.
    """
    return JSONResponse(content=get_stats())

# ── Code search ───────────────────────────────────────────────────────────────
@app.get("/codes/icd10")
async def search_icd10(q: str = ""):
    """Search ICD-10 codes. Example: /codes/icd10?q=diabetes"""
    if not q:
        return {"error": "Provide ?q=search_term"}
    result = coding_engine.code_diagnosis(q)
    return JSONResponse(content=result)


@app.get("/codes/loinc")
async def search_loinc(q: str = ""):
    """Search LOINC codes. Example: /codes/loinc?q=hemoglobin"""
    if not q:
        return {"error": "Provide ?q=search_term"}
    result = coding_engine.code_test(q)
    return JSONResponse(content=result)


# ── Internal helper ───────────────────────────────────────────────────────────
def _process_one_pdf(pdf_path: str, file_name: str) -> dict:
    """
    Run a single PDF through the full extraction pipeline.
    Returns dict with extraction, detection, clinical_data, doc_type.
    """
    # 1. Extract text
    extraction = extractor.extract(pdf_path)
    if not extraction["success"]:
        raise ValueError(f"PDF extraction failed: {extraction.get('error')}")

    # 2. Detect document type
    detection = detector.detect(extraction["full_text"])
    doc_type = detection["doc_type"]

    # 3. AI extraction
    clinical_data = ai_parser.parse(extraction["full_text"], doc_type)

    # 4. Auto-code diagnosis with ICD-10
    primary_dx = clinical_data.get("primary_diagnosis", "")
    if primary_dx:
        icd = coding_engine.code_diagnosis(primary_dx)
        clinical_data["primary_diagnosis_coding"] = icd
        if icd.get("matched") and not clinical_data.get("primary_diagnosis_icd10"):
            clinical_data["primary_diagnosis_icd10"] = icd["code"]

    # 5. Auto-code lab tests with LOINC
    if clinical_data.get("tests"):
        clinical_data["tests"] = coding_engine.code_all_tests(
            clinical_data["tests"]
        )

    logger.info(
        f"Processed {file_name}: doc_type={doc_type} "
        f"fields={len(clinical_data)} confidence={detection['confidence_percent']}%"
    )

    return {
        "file_name": file_name,
        "extraction": extraction,
        "detection": detection,
        "doc_type": doc_type,
        "clinical_data": clinical_data,
    }
