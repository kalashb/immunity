#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${IMMUNITY_TTS_VENV_DIR:-$ROOT_DIR/.venv-supertonic}"
PYTHON_BIN="${IMMUNITY_TTS_BOOTSTRAP_PYTHON:-python3.12}"
HELPER_PYTHON="$VENV_DIR/bin/python"
MODEL_NAME="${IMMUNITY_TTS_MODEL:-supertonic-2}"
MODEL_DIR="${IMMUNITY_TTS_MODEL_DIR:-$ROOT_DIR/data/tts/models/$MODEL_NAME}"
AUDIO_DIR="${IMMUNITY_TTS_AUDIO_DIR:-$ROOT_DIR/data/tts/audio}"
VOICE_NAME="${IMMUNITY_TTS_VOICE:-M1}"
LANG_CODE="${IMMUNITY_TTS_LANG:-en}"
BOOTSTRAP_AUDIO="$AUDIO_DIR/bootstrap.wav"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed." >&2
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "$PYTHON_BIN is required to bootstrap Supertonic." >&2
  exit 1
fi

mkdir -p "$AUDIO_DIR" "$(dirname "$MODEL_DIR")"

uv venv --python "$PYTHON_BIN" "$VENV_DIR"
uv pip install --python "$HELPER_PYTHON" supertonic==1.1.2

cat <<EOF | "$HELPER_PYTHON" "$ROOT_DIR/backend/supertonic_runner.py"
{
  "text": "Administrative voice channel initialized.",
  "output_path": "$BOOTSTRAP_AUDIO",
  "model": "$MODEL_NAME",
  "model_dir": "$MODEL_DIR",
  "voice_name": "$VOICE_NAME",
  "lang": "$LANG_CODE",
  "speed": 1.0,
  "total_steps": 5,
  "auto_download": true
}
EOF

echo
echo "Supertonic TTS ready."
echo "Helper Python: $HELPER_PYTHON"
echo "Model cache: $MODEL_DIR"
echo "Smoke-test audio: $BOOTSTRAP_AUDIO"
