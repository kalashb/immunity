"""
Arduino controller via pyserial.

Python sends single-char commands over serial. The Arduino sketch reads them
and drives LEDs / reads the button, sending 'P' back when pressed.

Serial protocol (Python → Arduino):
  'R' = red LED on       'r' = red LED off
  'Y' = yellow LED on    'y' = yellow LED off
  'G' = green LED on     'g' = green LED off
  'X' = all LEDs off
  'B' = buzz (single burst — Arduino handles duration)

Serial protocol (Arduino → Python):
  'P' = button was pressed (unsolicited on rising edge)

Physical I/O (configured in the Arduino sketch):
  - Button on digital pin 2 (INPUT_PULLUP) — submit trigger
  - Buzzer on digital pin 3 (OUTPUT) — fires only on blacklist
  - Green LED on digital pin 9
  - Yellow LED on digital pin 10
  - Red LED on digital pin 11

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
DEBOUNCE_MS = 250


class ArduinoController:
    """Manages a single Arduino board over serial: button input + LED outputs."""

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
        """Open serial connection to the Arduino. Returns True on success."""
        if not HAS_SERIAL:
            print("[ARDUINO] pyserial not installed — running in stub mode")
            return False
        port = port or self.port
        if not port:
            print("[ARDUINO] No port specified — running in stub mode")
            return False
        try:
            self._ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
            time.sleep(2)  # Arduino resets on serial open; wait for it
            self._ser.reset_input_buffer()
            self._connected = True
            self._send(b"X")  # all off
            print(f"[ARDUINO] Connected on {port}")
            return True
        except Exception as exc:
            print(f"[ARDUINO] Connection failed ({port}): {exc}")
            self._connected = False
            return False

    def _send(self, data: bytes) -> None:
        if self._ser and self._connected:
            try:
                self._ser.write(data)
            except Exception:
                pass

    # -- LED control ----------------------------------------------------------

    def set_lights(self, mode: str) -> None:
        """Set LEDs based on mode string from the response pipeline."""
        if not self._connected:
            return
        self._send(b"X")  # all off first
        if mode == "red_alert" or mode == "blacklist_approved":
            self._send(b"R")
        elif mode == "yellow":
            self._send(b"Y")
        elif mode in ("green", "neutral"):
            self._send(b"G")

    def buzz(self) -> None:
        """Single buzzer burst. Arduino handles the duration."""
        if not self._connected:
            return
        self._send(b"B")

    def trigger_blacklist(self, flashes: int = 5, interval: float = 0.2) -> None:
        """Full blacklist spectacle: flash red LEDs + buzz. Runs in background."""
        if not self._connected:
            return
        def _spectacle():
            self._send(b"B")
            for _ in range(flashes):
                self._send(b"R")
                time.sleep(interval)
                self._send(b"r")
                time.sleep(interval)
            self._send(b"R")  # stay red after
        threading.Thread(target=_spectacle, daemon=True).start()

    # -- Button input ---------------------------------------------------------

    def read_button(self) -> bool:
        """Check if button was pressed since last read (edge-detected, debounced)."""
        with self._lock:
            pressed = self._button_pressed
            self._button_pressed = False
            return pressed

    def start_reading(self, on_press: Callable | None = None) -> None:
        """Start background thread that reads serial for button events."""
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
        """Continuously read serial; Arduino sends 'P' on button press edge."""
        while self._running:
            if not self._ser:
                time.sleep(0.05)
                continue
            try:
                if self._ser.in_waiting:
                    data = self._ser.read(self._ser.in_waiting)
                    now = time.time()
                    if b"P" in data and (now - self._last_press_time) > (DEBOUNCE_MS / 1000):
                        self._last_press_time = now
                        with self._lock:
                            self._button_pressed = True
                        if self._on_press:
                            self._on_press()
            except Exception:
                pass
            time.sleep(0.02)

    # -- Cleanup --------------------------------------------------------------

    def cleanup(self) -> None:
        self.stop_reading()
        if self._connected:
            self._send(b"X")
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        self._connected = False
        print("[ARDUINO] Cleaned up")


# Singleton — initialized once, importable everywhere
arduino = ArduinoController()
