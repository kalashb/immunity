"""
Arduino controller via pyserial.

String-based serial protocol at 115200 baud.

Python → Arduino:
  "BLACKLIST_ON\n"  = relay ON  (active LOW: pin 9 goes LOW, 12V system fires)
  "BLACKLIST_OFF\n" = relay OFF (pin 9 goes HIGH)

Arduino → Python:
  "SUBMIT\n" = button on A2 was pressed

Physical wiring:
  - Push button: GND (analog header) → one leg, A2 → other leg (INPUT_PULLUP)
  - Relay module: GND→GND, VCC→5V, IN4→pin ~9 (active LOW)

Gracefully degrades to no-ops if the board isn't connected.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

BAUD_RATE = 9600
DEBOUNCE_MS = 300


class ArduinoController:
    """Manages Arduino over serial: button input + relay output."""

    def __init__(self, port: str | None = None):
        self.port = port
        self._ser: serial.Serial | None = None
        self._connected = False
        self._button_pressed = False
        self._lock = threading.Lock()
        self._read_thread: threading.Thread | None = None
        self._running = False
        self._on_press: Callable | None = None
        self._last_press_time = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, port: str | None = None) -> bool:
        if not HAS_SERIAL:
            print("[ARDUINO] pyserial not installed — running in stub mode")
            return False
        port = port or self.port
        if not port:
            print("[ARDUINO] No port specified — running in stub mode")
            return False
        try:
            self._ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
            time.sleep(2)
            self._ser.reset_input_buffer()
            self._connected = True
            print(f"[ARDUINO] Connected on {port}")
            return True
        except Exception as exc:
            print(f"[ARDUINO] Connection failed ({port}): {exc}")
            self._connected = False
            return False

    def _send_cmd(self, cmd: str) -> None:
        if self._ser and self._connected:
            try:
                self._ser.write(f"{cmd}\n".encode())
            except Exception:
                pass

    # -- Relay control ---------------------------------------------------------

    def set_lights(self, mode: str) -> None:
        """Only fires on blacklist. Arduino handles the 3-second duration."""
        if not self._connected:
            return
        if mode in ("red_alert", "blacklist_approved"):
            self._send_cmd("BLACKLIST")

    def trigger_blacklist(self) -> None:
        """Send BLACKLIST command. Arduino turns relay on for 3s then off."""
        if not self._connected:
            return
        self._send_cmd("BLACKLIST")

    # -- Button input ----------------------------------------------------------

    def read_button(self) -> bool:
        with self._lock:
            pressed = self._button_pressed
            self._button_pressed = False
            return pressed

    def start_reading(self, on_press: Callable | None = None) -> None:
        if not self._connected:
            return
        self._on_press = on_press
        self._running = True
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        print("[ARDUINO] Serial reader started")

    def stop_reading(self) -> None:
        self._running = False
        if self._read_thread:
            self._read_thread.join(timeout=2)

    def _read_loop(self) -> None:
        while self._running:
            if not self._ser:
                time.sleep(0.05)
                continue
            try:
                if self._ser.in_waiting:
                    line = self._ser.readline().decode(errors="ignore").strip()
                    now = time.time()
                    if line == "SUBMIT" and (now - self._last_press_time) > (DEBOUNCE_MS / 1000):
                        self._last_press_time = now
                        with self._lock:
                            self._button_pressed = True
                        if self._on_press:
                            self._on_press()
            except Exception:
                pass
            time.sleep(0.02)

    # -- Cleanup ---------------------------------------------------------------

    def cleanup(self) -> None:
        self.stop_reading()
        pass  # Arduino auto-resets on disconnect
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        self._connected = False
        print("[ARDUINO] Cleaned up")


arduino = ArduinoController()
