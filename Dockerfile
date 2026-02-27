FROM python:3.11-slim

# System packages: Tesseract OCR + PDF rendering libs
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data is the Render.com persistent disk mountPath for SQLite fallback
RUN mkdir -p /data

EXPOSE 8000

# Use gunicorn + uvicorn worker for production-grade serving
CMD ["gunicorn", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", \
    "main:app", "--bind", "0.0.0.0:8000", "--timeout", "120"]
