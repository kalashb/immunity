"""
Hardware adapter stubs. Log to console for now.
Later: connect to Arduino/serial for lights, physical button; USB for thermal printer.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

# Directory for ticket logs (thermal payloads) and blacklist wall data
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WALL_LOG = DATA_DIR / "blacklist_wall.jsonl"
TICKET_LOG = DATA_DIR / "tickets.jsonl"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def trigger_lights(mode: str) -> None:
    """Set cop/signal lights. mode: neutral, yellow, red_alert, etc."""
    print(f"[HARDWARE] Lights -> {mode}")


def trigger_sound(mode: str) -> None:
    """Play sound. mode: none, printer_whirr, alarm, beep, etc."""
    print(f"[HARDWARE] Sound -> {mode}")


def print_ticket(ticket_data: dict) -> None:
    """Send ticket to thermal printer. For now: append to tickets log."""
    _ensure_data_dir()
    with open(TICKET_LOG, "a") as f:
        f.write(json.dumps(ticket_data) + "\n")
    print(f"[HARDWARE] Ticket printed (logged): {ticket_data.get('case_number', '?')}")


def log_blacklist_to_wall(ticket_data: dict) -> None:
    """Append to wall-of-blacklisted log for physical display later."""
    _ensure_data_dir()
    with open(WALL_LOG, "a") as f:
        f.write(json.dumps({**ticket_data, "wall_logged_at": datetime.utcnow().isoformat()}) + "\n")
    print(f"[HARDWARE] Blacklist wall updated: {ticket_data.get('case_number', '?')}")


def read_physical_button() -> bool:
    """Poll physical submit button. For now: always False (UI button used)."""
    return False
