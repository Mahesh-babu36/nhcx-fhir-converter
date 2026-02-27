"""
pipeline/extractor.py
---------------------
Extracts text from PDF files.
Handles both digital PDFs (using PyMuPDF) and scanned PDFs (using Tesseract OCR).
"""

import os
import sys
import tempfile
from utils import logger, clean_text

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False
    logger.warning("PyMuPDF not installed. Run: pip install pymupdf")

try:
    import pytesseract
    from PIL import Image
    import io
    OCR_AVAILABLE = True

    # Mac: Tesseract installed via brew is at /usr/local/bin/tesseract
    # or /opt/homebrew/bin/tesseract on Apple Silicon
    for path in ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            break

except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pytesseract / Pillow not installed. Run: pip install pytesseract Pillow")


class PDFExtractor:
    """
    Extracts raw text from PDF files.
    Strategy:
      1. Try digital text extraction with PyMuPDF (fast, accurate)
      2. If page has no text (scanned), render it as image and OCR
    """

    MIN_CHARS_PER_PAGE = 50   # below this we assume the page is scanned

    def extract(self, pdf_path: str) -> dict:
        """
        Main entry point. Returns dict with:
          full_text     – combined text from all pages
          pages         – list of per-page text strings
          total_pages   – page count
          used_ocr      – True if OCR was used on any page
          total_chars   – character count
        """
        if not FITZ_AVAILABLE:
            return self._empty_result("PyMuPDF not available")

        if not os.path.exists(pdf_path):
            return self._empty_result(f"File not found: {pdf_path}")

        try:
            doc = fitz.open(pdf_path)
            pages_text = []
            used_ocr = False

            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text("text").strip()

                if len(text) < self.MIN_CHARS_PER_PAGE and OCR_AVAILABLE:
                    text = self._ocr_page(page)
                    used_ocr = True

                text = clean_text(text)
                if text:
                    pages_text.append(text)

            doc.close()

            full_text = "\n\n".join(pages_text)
            logger.info(
                f"Extracted {len(full_text)} chars from {len(pages_text)} pages "
                f"{'(OCR used)' if used_ocr else '(digital)'}"
            )

            return {
                "full_text": full_text,
                "pages": pages_text,
                "total_pages": len(pages_text),
                "used_ocr": used_ocr,
                "total_chars": len(full_text),
                "success": True,
                "error": None,
            }

        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return self._empty_result(str(e))

    def _ocr_page(self, page) -> str:
        """Render a PDF page as an image and run Tesseract OCR on it."""
        try:
            mat = fitz.Matrix(2.0, 2.0)          # 2× zoom for better OCR accuracy
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang="eng")
            return text.strip()
        except Exception as e:
            logger.warning(f"OCR failed on page: {e}")
            return ""

    def _empty_result(self, error: str) -> dict:
        return {
            "full_text": "",
            "pages": [],
            "total_pages": 0,
            "used_ocr": False,
            "total_chars": 0,
            "success": False,
            "error": error,
        }
