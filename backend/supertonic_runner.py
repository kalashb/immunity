"""Helper entrypoint that runs inside the dedicated Supertonic virtualenv."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from supertonic import TTS


def main() -> int:
    payload = json.load(sys.stdin)

    output_path = Path(payload["output_path"]).expanduser().resolve()
    model_dir = Path(payload["model_dir"]).expanduser().resolve()

    tts = TTS(
        model=payload.get("model", "supertonic-2"),
        model_dir=model_dir,
        auto_download=bool(payload.get("auto_download", True)),
    )
    style = tts.get_voice_style(payload.get("voice_name", "M1"))
    wav, duration = tts.synthesize(
        payload["text"],
        voice_style=style,
        total_steps=int(payload.get("total_steps", 5)),
        speed=float(payload.get("speed", 1.0)),
        lang=payload.get("lang", "en"),
    )
    tts.save_audio(wav, str(output_path))

    result = {
        "output_path": str(output_path),
        "duration_seconds": float(duration[0]) if len(duration) else 0.0,
        "sample_rate": tts.sample_rate,
        "voice_name": payload.get("voice_name", "M1"),
    }
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
