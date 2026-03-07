"""
FastAPI server for I Have Immunity. Session state, submit inquiry, state poll, reset.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path when running uvicorn backend.main:app
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.state import BureaucraticState
from backend.ollama_client import process_inquiry
from shared.schemas import InquiryResponse, SessionState, TicketPayload
from hardware.adapters import (
    trigger_lights,
    trigger_sound,
    print_ticket,
    log_blacklist_to_wall,
)

app = FastAPI(title="I Have Immunity")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single session state (in-memory; one booth)
state = BureaucraticState()
_case_counter = 0


def next_case_number() -> str:
    global _case_counter
    _case_counter += 1
    return f"CAS-{datetime.utcnow().strftime('%Y%m%d')}-{_case_counter:05d}"


class SubmitInquiry(BaseModel):
    question: str


class ResetQuery(BaseModel):
    secret: str = ""


@app.get("/api/state")
def get_state() -> dict:
    return state.to_dict()


@app.post("/api/submit")
def submit_inquiry(body: SubmitInquiry) -> dict:
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Empty inquiry.")
    if state.is_blacklisted:
        return {
            "reaction_text": "Access denied. Citizen blacklisted.",
            "status": "BLACKLISTED",
            "ticket": None,
            "state": state.to_dict(),
            "blacklisted": True,
            "lights_mode": "red_alert",
            "sound_mode": "alarm",
            "screen_effect": "full_flash",
        }

    state.record_inquiry(question)
    is_repeated = state.is_repeated_question(question)
    is_rapid = state.is_rapid_fire()
    is_long = state.is_very_long(question)
    consider_blacklist = state.should_consider_blacklist()

    # Rule-based overrides: nudge deltas before calling model
    context_parts = []
    if is_long:
        context_parts.append("Very long inquiry.")
    if is_repeated:
        context_parts.append("Repeated or similar inquiry.")
    if is_rapid:
        context_parts.append("Rapid submissions.")

    # Blacklist: rare. Only when state says so and either repeated/spam or random rare chance
    force_blacklist = False
    if consider_blacklist and (is_repeated or is_rapid):
        force_blacklist = random.random() < 0.4
    elif consider_blacklist and state.irritation >= 80:
        force_blacklist = random.random() < 0.15

    suggested_mode = state.suggest_response_mode(question, force_blacklist)
    response: InquiryResponse = process_inquiry(
        question,
        state.to_dict(),
        suggested_mode=suggested_mode,
        force_blacklist=force_blacklist,
    )

    state.apply_deltas(
        patience_delta=response.patience_delta,
        irritation_delta=response.irritation_delta,
        curiosity_delta=response.curiosity_delta,
        load_delta=response.load_delta,
    )
    if response.blacklist:
        state.is_blacklisted = True
        state.blacklist_count += 1

    case_num = next_case_number()
    ticket = TicketPayload(
        case_number=case_num,
        status=response.status,
        ticket_type=response.ticket_type,
        title=response.ticket_title,
        reason=response.ticket_reason,
        timestamp=datetime.utcnow().isoformat(),
        patience=state.patience,
        irritation=state.irritation,
        curiosity=state.curiosity,
        administrative_load=state.administrative_load,
        blacklisted=response.blacklist,
    )
    ticket_dict = ticket.model_dump()

    trigger_lights(response.lights_mode)
    trigger_sound(response.sound_mode)
    print_ticket(ticket_dict)
    if response.blacklist:
        log_blacklist_to_wall(ticket_dict)

    return {
        "response_mode": response.response_mode,
        "reaction_text": response.reaction_text,
        "answer_text": response.answer_text or "",
        "status": response.status,
        "ticket": ticket_dict,
        "state": state.to_dict(),
        "blacklisted": response.blacklist,
        "lights_mode": response.lights_mode,
        "sound_mode": response.sound_mode,
        "screen_effect": response.screen_effect,
    }


@app.post("/api/reset")
def reset_state(secret: str = "immunity-reset"):
    """Admin/dev: reset session state. In production, protect this."""
    global state, _case_counter
    state = BureaucraticState()
    _case_counter = 0
    return {"ok": True, "message": "State reset."}


# Serve frontend from frontend/ at /
frontend_path = ROOT / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="static")
