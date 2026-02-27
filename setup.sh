#!/bin/bash
# setup.sh
# --------
# One-command setup script for Mac (works on Intel and Apple Silicon).
# Run this once inside the project folder:
#   chmod +x setup.sh && ./setup.sh

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   NHCX FHIR Converter — Mac Setup        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ───────────────────────────────────────────────────────────
echo "→ Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "  Python3 not found. Install from https://python.org"
    exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PYVER found ✓"

# ── 2. Install Homebrew if missing ────────────────────────────────────────────
echo ""
echo "→ Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    echo "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "  Homebrew found ✓"
fi

# ── 3. Install Tesseract OCR ──────────────────────────────────────────────────
echo ""
echo "→ Installing Tesseract OCR (for scanned PDFs)..."
if ! command -v tesseract &>/dev/null; then
    brew install tesseract
    echo "  Tesseract installed ✓"
else
    echo "  Tesseract found ✓"
fi

# ── 4. Create Python virtual environment ──────────────────────────────────────
echo ""
echo "→ Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  venv created ✓"
else
    echo "  venv already exists ✓"
fi

# ── 5. Activate venv and install packages ─────────────────────────────────────
echo ""
echo "→ Installing Python packages..."
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  Packages installed ✓"

# ── 6. Create .env file if not present ───────────────────────────────────────
echo ""
echo "→ Checking environment configuration..."
if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
# Get your free Gemini API key at: https://aistudio.google.com
GEMINI_API_KEY=paste_your_key_here
EOF
    echo "  .env file created ✓"
    echo ""
    echo "  ⚠️  IMPORTANT: Open .env and paste your Gemini API key"
    echo "  Get a free key at: https://aistudio.google.com"
else
    echo "  .env file found ✓"
fi

# ── 7. Create profiles directory ──────────────────────────────────────────────
mkdir -p profiles static

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Setup complete!                        ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Add your Gemini API key to .env file"
echo "  2. Run the tool:"
echo ""
echo "     source venv/bin/activate"
echo "     source .env"
echo "     uvicorn main:app --reload --port 8000"
echo ""
echo "  3. Open browser: http://localhost:8000"
echo ""
