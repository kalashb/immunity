"""
Hardware adapter stubs. Log to console for now.
Later: connect to Arduino/serial for lights, physical button; USB for thermal printer.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

# Directory for ticket logs (thermal payloads), blacklist wall, and inquiry log
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WALL_LOG = DATA_DIR / "blacklist_wall.jsonl"
TICKET_LOG = DATA_DIR / "tickets.jsonl"
INQUIRIES_LOG = DATA_DIR / "inquiries.jsonl"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def trigger_lights(mode: str) -> None:
    """Set cop/signal lights. mode: neutral, yellow, red_alert, etc."""
    print(f"[HARDWARE] Lights -> {mode}")


def trigger_sound(mode: str) -> None:
    """Play sound. mode: none, printer_whirr, alarm, beep, etc."""
    print(f"[HARDWARE] Sound -> {mode}")


def format_ticket_for_printer(ticket_data: dict) -> str:
    """Format ticket body for thermal printer: \"<question>\"\\n- <name>\\n<status>"""
    q = (ticket_data.get("question") or "").strip() or "(no question)"
    name = (ticket_data.get("name") or "").strip() or "Anonymous"
    status = "BLACKLIST" if ticket_data.get("blacklisted") else (ticket_data.get("status") or "—")
    return f'"{q}"\n- {name}\n{status}'


def print_ticket(ticket_data: dict) -> None:
    """Send ticket to thermal printer. ticket_data includes question, name for format:
    \"<question>\"\\n- <name>\\n<status/BLACKLIST>. Use format_ticket_for_printer() for body."""
    _ensure_data_dir()
    with open(TICKET_LOG, "a") as f:
        f.write(json.dumps(ticket_data) + "\n")
    print(f"[HARDWARE] Ticket printed (logged): {ticket_data.get('case_number', '?')}")


def log_inquiry(record: dict) -> None:
    """Append one inquiry to local log for operator review (all interactions)."""
    _ensure_data_dir()
    with open(INQUIRIES_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def clear_logs() -> None:
    """Truncate ticket and blacklist wall logs (e.g. after reset for next person)."""
    _ensure_data_dir()
    for path in (TICKET_LOG, WALL_LOG):
        if path.exists():
            path.write_text("")
    print("[HARDWARE] Ticket and blacklist wall logs cleared.")


def clear_inquiry_log() -> None:
    """Truncate the inquiry log (optional, for full wipe)."""
    _ensure_data_dir()
    if INQUIRIES_LOG.exists():
        INQUIRIES_LOG.write_text("")
    print("[HARDWARE] Inquiry log cleared.")


def log_blacklist_to_wall(ticket_data: dict) -> None:
    """Append to wall-of-blacklisted log for physical display later."""
    _ensure_data_dir()
    with open(WALL_LOG, "a") as f:
        f.write(json.dumps({**ticket_data, "wall_logged_at": datetime.utcnow().isoformat()}) + "\n")
    print(f"[HARDWARE] Blacklist wall updated: {ticket_data.get('case_number', '?')}")


def read_physical_button() -> bool:
    """Poll physical submit button. For now: always False (UI button used)."""
    return False
