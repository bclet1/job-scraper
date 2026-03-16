@echo off
REM Quick Start Script for Job Scraper
REM This script sets up dependencies and runs the job scraper

setlocal enabledelayedexpansion

REM Handle UNC paths (network drives)
if "%CD:~0,2%"=="\\" (
    for /f "tokens=3" %%a in ('net use ^| find /I "job-scraper"') do (
        if not "%%a"=="" (
            set "MAPPED_DRIVE=%%a"
        )
    )
)

echo.
echo ================================================
echo Job Scraper - Quick Start
echo ================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.9+
    pause
    exit /b 1
)

echo [1/4] Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1

echo [2/4] Installing dependencies...
if exist requirements.txt (
    python -m pip install -r requirements.txt >nul 2>&1
) else (
    echo Installing packages individually...
    python -m pip install playwright beautifulsoup4 pandas pydantic sentence-transformers scikit-learn PyPDF2 python-docx requests python-dotenv torch >nul 2>&1
)

echo [3/4] Installing Playwright browser...
python -m playwright install chromium >nul 2>&1

echo [4/4] Running job scraper...
echo.
python job_scraper.py

echo.
echo ================================================
echo Complete! Check results/ folder for output
echo ================================================
pause
