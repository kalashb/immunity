"""
Thermal receipt printer via pyserial + raw ESC/POS commands.

Connects to the printer over serial (it shows up as /dev/cu.MPT-II on macOS).
Prints blacklisted prompts as physical receipts.

Set PRINTER_PORT env var to override the default serial port.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

DEFAULT_PORT = "/dev/cu.MPT-II"
BAUD_RATE = 9600

# ESC/POS command bytes
ESC = b"\x1b"
GS = b"\x1d"
INIT = ESC + b"@"             # reset printer
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
CENTER = ESC + b"a\x01"
LEFT = ESC + b"a\x00"
DOUBLE_SIZE = GS + b"!\x11"  # double width + double height
NORMAL_SIZE = GS + b"!\x00"
CUT = GS + b"V\x41\x00"     # partial cut
FEED = ESC + b"d\x03"        # feed 3 lines


class ReceiptPrinter:
    """Manages a USB thermal receipt printer over serial."""

    def __init__(self):
        self._ser: serial.Serial | None = None
        self._connected = False
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, port: str | None = None) -> bool:
        """Open serial connection to the printer."""
        if not HAS_SERIAL:
            print("[PRINTER] pyserial not installed — running in stub mode")
            return False
        port = port or os.environ.get("PRINTER_PORT") or DEFAULT_PORT
        try:
            self._ser = serial.Serial(port, BAUD_RATE, timeout=2)
            self._connected = True
            self._write(INIT)
            print(f"[PRINTER] Connected on {port}")
            return True
        except Exception as exc:
            print(f"[PRINTER] Connection failed ({port}): {exc}")
            self._connected = False
            return False

    def _write(self, data: bytes) -> None:
        if self._ser and self._connected:
            try:
                self._ser.write(data)
            except Exception:
                pass

    def _text(self, s: str) -> None:
        self._write(s.encode("ascii", errors="replace"))

    def print_blacklist_receipt(self, ticket_data: dict) -> None:
        """Print a blacklist receipt in a background thread."""
        if not self._connected:
            return
        threading.Thread(
            target=self._do_print,
            args=(ticket_data,),
            daemon=True,
        ).start()

    def _do_print(self, ticket_data: dict) -> None:
        question = (ticket_data.get("question") or "").strip() or "(no question)"
        name = (ticket_data.get("name") or "").strip() or "Anonymous"
        case = ticket_data.get("case_number", "---")
        reason = (ticket_data.get("reason") or "").strip() or "---"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        with self._lock:
            try:
                self._write(INIT)

                self._write(CENTER + BOLD_ON + DOUBLE_SIZE)
                self._text("BLACKLISTED\n")
                self._write(NORMAL_SIZE + BOLD_OFF)

                self._write(CENTER)
                self._text("=" * 32 + "\n")

                self._write(LEFT + BOLD_OFF)
                self._text(f'"{question}"\n')
                self._text(f"- {name}\n\n")
                self._text(f"Case: {case}\n")
                self._text(f"Reason: {reason}\n")
                self._text(f"Time: {ts}\n")

                self._write(CENTER)
                self._text("=" * 32 + "\n")
                self._write(BOLD_ON)
                self._text("I HAVE IMMUNITY\n")
                self._write(BOLD_OFF)

                self._write(FEED)
                self._write(CUT)
            except Exception as exc:
                print(f"[PRINTER] Print failed: {exc}")

    def cleanup(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        self._connected = False


printer = ReceiptPrinter()
