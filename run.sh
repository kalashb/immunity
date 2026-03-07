#!/usr/bin/env bash
# Run from project root. Requires: venv with pip install -r requirements.txt, Ollama running.
set -e
cd "$(dirname "$0")"
if [ -d venv ]; then
  source venv/bin/activate
fi
python -m uvicorn backend.main:app --reload --reload-exclude venv --reload-exclude '*.pyc' --host 0.0.0.0 --port 8000
