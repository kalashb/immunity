"""Shared Pydantic schemas for API and ticket data."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ResponseMode = Literal[
    "DIRECT_ANSWER",
    "PARTIAL_ANSWER",
    "REFRAME",
    "DENIAL",
    "WARNING",
    "BLACKLIST",
]


class InquiryResponse(BaseModel):
    """Structured output from the bureaucratic entity per interaction."""
    response_mode: ResponseMode = "DENIAL"
    reaction_text: str = ""
    answer_text: str = ""  # Present when DIRECT_ANSWER or PARTIAL_ANSWER
    status: Literal[
        "ACCEPTED", "APPROVED", "DENIED", "ESCALATED", "LOGGED", "BLACKLISTED", "PENDING", "WARNING"
    ] = "DENIED"
    ticket_type: str = ""
    ticket_title: str = ""
    ticket_reason: str = ""
    patience_delta: int = 0
    irritation_delta: int = 0
    disappointment_delta: int = 0
    load_delta: int = 1
    blacklist: bool = False
    lights_mode: str = "neutral"
    sound_mode: str = "none"
    screen_effect: str = "none"


class SessionState(BaseModel):
    """Current bureaucratic state exposed to frontend."""
    patience: int = Field(ge=0, le=100)
    irritation: int = Field(ge=0, le=100)
    disappointment: int = Field(ge=0, le=100)
    administrative_load: int = Field(ge=0, le=100)
    inquiry_count: int = 0
    blacklist_count: int = 0
    is_blacklisted: bool = False


class TicketPayload(BaseModel):
    """Data suitable for thermal printer or wall log."""
    case_number: str
    status: str
    ticket_type: str
    title: str
    reason: str
    timestamp: str
    patience: int
    irritation: int
    disappointment: int
    administrative_load: int
    blacklisted: bool = False
    question: str = ""
    name: str = ""  # Optional person name for printer: "<question>" - <name>
