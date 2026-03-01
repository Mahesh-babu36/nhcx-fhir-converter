@echo off
REM setup.bat
REM ---------
REM One-command Windows setup for NHCX FHIR Converter.
REM Double-click this file OR run it from PowerShell / CMD inside the project folder.

echo.
echo ==========================================
echo   NHCX FHIR Converter -- Windows Setup
echo ==========================================
echo.

REM -- 1. Check Python -------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Download from https://python.org
    pause
    exit /b 1
)
echo [OK] Python found.

REM -- 2. Create virtual environment -----------------------------------------
if not exist "venv\" (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    echo [OK] venv created.
) else (
    echo [OK] venv already exists.
)

REM -- 3. Activate venv & install packages -----------------------------------
echo.
echo Installing Python packages...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo [OK] Packages installed.

REM -- 4. Create .env if missing ---------------------------------------------
if not exist ".env" (
    echo.
    echo GEMINI_API_KEY=paste_your_key_here> .env
    echo [OK] .env file created.
    echo.
    echo  *** IMPORTANT: Open .env and paste your Gemini API key ***
    echo  Get a free key at: https://aistudio.google.com
) else (
    echo [OK] .env file found.
)

REM -- 5. Create folders if missing ------------------------------------------
if not exist "profiles\" mkdir profiles
if not exist "static\"   mkdir static

echo.
echo ==========================================
echo   Setup complete!
echo ==========================================
echo.
echo   To run the server:
echo.
echo     venv\Scripts\activate
echo     uvicorn main:app --reload --port 8000
echo.
echo   Then open: http://localhost:8000
echo.
pause
