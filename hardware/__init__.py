"""
Hardware abstraction for I Have Immunity.
Replace these implementations with real serial/USB/GPIO when connecting
physical button, lights, thermal printer.
"""
from .adapters import (
    trigger_lights,
    trigger_sound,
    print_ticket,
    read_physical_button,
)

__all__ = [
    "trigger_lights",
    "trigger_sound",
    "print_ticket",
    "read_physical_button",
]
