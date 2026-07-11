#!/bin/bash
set -e

echo "=== YouTube Transcript API ==="
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Creating storage directories..."
mkdir -p storage/jobs

echo "Starting server..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
