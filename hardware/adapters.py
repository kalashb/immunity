"""
Hardware adapters. Routes light/sound/button calls to the Arduino when connected,
falls back to console stubs otherwise. File-based logging for tickets/blacklist/inquiries.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from hardware.arduino import arduino
from hardware.printer import printer

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WALL_LOG = DATA_DIR / "blacklist_wall.jsonl"
TICKET_LOG = DATA_DIR / "tickets.jsonl"
INQUIRIES_LOG = DATA_DIR / "inquiries.jsonl"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def init_arduino(port: str | None = None) -> bool:
    """Call once at startup to connect to the Arduino. Returns True if connected."""
    ok = arduino.connect(port)
    if ok:
        arduino.start_reading()
    return ok


def init_printer(port: str | None = None) -> bool:
    """Call once at startup to connect to the receipt printer over serial."""
    return printer.connect(port)


def trigger_lights(mode: str) -> None:
    """Set LEDs via Arduino. Falls back to console log."""
    if arduino.connected:
        if mode == "red_alert":
            arduino.flash_red(times=3)
        else:
            arduino.set_lights(mode)
    print(f"[HARDWARE] Lights -> {mode}")


def trigger_sound(mode: str) -> None:
    """Play sound. Currently console-only; extend for Arduino piezo if needed."""
    print(f"[HARDWARE] Sound -> {mode}")


def read_physical_button() -> bool:
    """Check if the physical buzzer/button was pressed since last poll."""
    if arduino.connected:
        return arduino.read_button()
    return False


def format_ticket_for_printer(ticket_data: dict) -> str:
    """Format ticket body for thermal printer: \"<question>\"\\n- <name>\\n<status>"""
    q = (ticket_data.get("question") or "").strip() or "(no question)"
    name = (ticket_data.get("name") or "").strip() or "Anonymous"
    status = "BLACKLIST" if ticket_data.get("blacklisted") else (ticket_data.get("status") or "—")
    return f'"{q}"\n- {name}\n{status}'


def print_ticket(ticket_data: dict) -> None:
    """Log ticket to file (and eventually thermal printer)."""
    _ensure_data_dir()
    with open(TICKET_LOG, "a") as f:
        f.write(json.dumps(ticket_data) + "\n")
    print(f"[HARDWARE] Ticket printed (logged): {ticket_data.get('case_number', '?')}")


def log_inquiry(record: dict) -> None:
    """Append one inquiry to local log for operator review."""
    _ensure_data_dir()
    with open(INQUIRIES_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def clear_logs() -> None:
    """Truncate ticket and blacklist wall logs."""
    _ensure_data_dir()
    for path in (TICKET_LOG, WALL_LOG):
        if path.exists():
            path.write_text("")
    print("[HARDWARE] Ticket and blacklist wall logs cleared.")


def clear_inquiry_log() -> None:
    """Truncate the inquiry log."""
    _ensure_data_dir()
    if INQUIRIES_LOG.exists():
        INQUIRIES_LOG.write_text("")
    print("[HARDWARE] Inquiry log cleared.")


def log_blacklist_to_wall(ticket_data: dict) -> None:
    """Append to wall-of-blacklisted log. Trigger full blacklist spectacle (buzz + flash + print)."""
    _ensure_data_dir()
    with open(WALL_LOG, "a") as f:
        f.write(json.dumps({**ticket_data, "wall_logged_at": datetime.utcnow().isoformat()}) + "\n")
    if arduino.connected:
        arduino.trigger_blacklist()
    if printer.connected:
        printer.print_blacklist_receipt(ticket_data)
    print(f"[HARDWARE] Blacklist wall updated: {ticket_data.get('case_number', '?')}")


def cleanup_hardware() -> None:
    """Call on shutdown."""
    arduino.cleanup()
    printer.cleanup()
