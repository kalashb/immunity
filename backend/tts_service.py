"""Supertonic bridge for generating cached response audio through a helper venv."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TTS_ROOT_DIR = DATA_DIR / "tts"
DEFAULT_HELPER_PYTHON = ROOT / ".venv-supertonic" / "bin" / "python"
HELPER_SCRIPT = Path(__file__).resolve().with_name("supertonic_runner.py")
VALID_AUDIO_ID = re.compile(r"^[a-f0-9]{24}$")

_SYNTHESIS_LOCK = threading.Lock()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to %s", name, value, default)
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to %s", name, value, default)
        return default


TTS_ENABLED = _env_bool("IMMUNITY_TTS_ENABLED", True)
TTS_HELPER_PYTHON = Path(os.getenv("IMMUNITY_TTS_HELPER_PYTHON", str(DEFAULT_HELPER_PYTHON)))
TTS_MODEL = os.getenv("IMMUNITY_TTS_MODEL", "supertonic-2")
TTS_AUDIO_DIR = Path(os.getenv("IMMUNITY_TTS_AUDIO_DIR", str(TTS_ROOT_DIR / "audio")))
TTS_MODEL_DIR = Path(os.getenv("IMMUNITY_TTS_MODEL_DIR", str(TTS_ROOT_DIR / "models" / TTS_MODEL)))
TTS_VOICE = os.getenv("IMMUNITY_TTS_VOICE", "M1")
TTS_LANG = os.getenv("IMMUNITY_TTS_LANG", "en")
TTS_SPEED = _env_float("IMMUNITY_TTS_SPEED", 1.0)
TTS_TOTAL_STEPS = _env_int("IMMUNITY_TTS_TOTAL_STEPS", 5)
TTS_TIMEOUT_SECONDS = _env_float("IMMUNITY_TTS_TIMEOUT_SECONDS", 180.0)
TTS_AUTO_DOWNLOAD = _env_bool("IMMUNITY_TTS_AUTO_DOWNLOAD", True)
DEFAULT_VOICE_NAMES = ("F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5")


@dataclass(frozen=True)
class SpeechAsset:
    audio_id: str
    audio_path: Path
    duration_seconds: float | None

    @property
    def audio_url(self) -> str:
        return f"/api/tts/{self.audio_id}"


def _ensure_tts_dirs() -> None:
    TTS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TTS_MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)


def list_available_voice_names() -> list[str]:
    voice_styles_dir = TTS_MODEL_DIR / "voice_styles"
    if voice_styles_dir.exists():
        voices = sorted(path.stem for path in voice_styles_dir.glob("*.json"))
        if voices:
            return voices
    return list(DEFAULT_VOICE_NAMES)


def normalize_voice_name(voice_name: str | None) -> str:
    available = list_available_voice_names()
    fallback = TTS_VOICE if TTS_VOICE in available else available[0]
    candidate = (voice_name or "").strip()
    return candidate if candidate in available else fallback


def _normalize_spoken_fragment(text: str) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def build_spoken_text(reaction_text: str, answer_text: str) -> str:
    parts: list[str] = []

    reaction = _normalize_spoken_fragment(reaction_text)
    if reaction:
        parts.append(reaction)

    answer = _normalize_spoken_fragment(answer_text)
    if answer and answer != reaction:
        parts.append(answer)

    return " ".join(parts).strip()


def _payload_for_text(text: str, voice_name: str | None = None) -> dict[str, Any]:
    return {
        "text": text,
        "model": TTS_MODEL,
        "model_dir": str(TTS_MODEL_DIR),
        "voice_name": normalize_voice_name(voice_name),
        "lang": TTS_LANG,
        "speed": TTS_SPEED,
        "total_steps": TTS_TOTAL_STEPS,
        "auto_download": TTS_AUTO_DOWNLOAD,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.rfind("{")
    while start != -1:
        try:
            parsed = json.loads(text[start:])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            start = text.rfind("{", 0, start)
    return None


def _audio_id_for_payload(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return digest[:24]


def _run_synthesis(payload: dict[str, Any], output_path: Path) -> float | None:
    helper = TTS_HELPER_PYTHON
    if not helper.exists():
        logger.info("TTS helper missing at %s; skipping synthesis", helper)
        return None

    _ensure_tts_dirs()

    try:
        process = subprocess.run(
            [str(helper), str(HELPER_SCRIPT)],
            input=json.dumps({**payload, "output_path": str(output_path)}),
            text=True,
            capture_output=True,
            check=False,
            timeout=TTS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Supertonic synthesis timed out after %ss", TTS_TIMEOUT_SECONDS)
        return None
    except OSError as exc:
        logger.warning("Failed to launch Supertonic helper: %s", exc)
        return None
    if process.returncode != 0:
        logger.warning(
            "Supertonic synthesis failed with code %s: %s",
            process.returncode,
            process.stderr.strip() or process.stdout.strip(),
        )
        return None

    result = _extract_json_object(process.stdout)
    if result is None:
        logger.warning("Supertonic synthesis returned invalid JSON: %r", process.stdout)
        return None

    if not output_path.exists():
        logger.warning("Supertonic reported success but %s was not created", output_path)
        return None

    duration = result.get("duration_seconds")
    return float(duration) if isinstance(duration, (int, float)) else None


def synthesize_response_audio(
    reaction_text: str,
    answer_text: str,
    voice_name: str | None = None,
) -> SpeechAsset | None:
    if not TTS_ENABLED:
        return None

    spoken_text = build_spoken_text(reaction_text, answer_text)
    if not spoken_text:
        return None

    payload = _payload_for_text(spoken_text, voice_name=voice_name)
    audio_id = _audio_id_for_payload(payload)
    output_path = TTS_AUDIO_DIR / f"{audio_id}.wav"

    duration_seconds: float | None = None
    with _SYNTHESIS_LOCK:
        if not output_path.exists():
            duration_seconds = _run_synthesis(payload, output_path)
            if not output_path.exists():
                return None

    return SpeechAsset(
        audio_id=audio_id,
        audio_path=output_path,
        duration_seconds=duration_seconds,
    )


def get_audio_file(audio_id: str) -> Path | None:
    if not VALID_AUDIO_ID.fullmatch(audio_id):
        return None

    audio_path = TTS_AUDIO_DIR / f"{audio_id}.wav"
    return audio_path if audio_path.exists() else None
