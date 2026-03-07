#!/usr/bin/env bash
# Run from project root. Requires: venv with pip install -r requirements.txt, Ollama running.
set -e
cd "$(dirname "$0")"
if [ -d venv ]; then
  source venv/bin/activate
fi
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
