#!/bin/bash
# Quick Start Script for Job Scraper
# This script sets up dependencies and runs the job scraper

echo ""
echo "================================================"
echo "Job Scraper - Quick Start"
echo "================================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.9+"
    exit 1
fi

echo "[1/4] Upgrading pip..."
python3 -m pip install --upgrade pip -q

echo "[2/4] Installing dependencies..."
python3 -m pip install -r requirements.txt -q

echo "[3/4] Installing Playwright browser..."
python3 -m playwright install chromium -q

echo "[4/4] Running Indeed + Built In scrapers and comparison..."
echo ""
python3 multi_job_scraper.py

echo ""
echo "================================================"
echo "Complete! Check results/ folder for indeed, builtin, and comparison output"
echo "================================================"
