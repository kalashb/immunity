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
    log_inquiry,
    log_blacklist_to_wall,
    clear_logs,
    clear_inquiry_log,
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
    name: str = ""


class ResetQuery(BaseModel):
    secret: str = ""


@app.get("/api/state")
def get_state() -> dict:
    return state.to_dict()


@app.post("/api/submit")
def submit_inquiry(body: SubmitInquiry) -> dict:
    question = (body.question or "").strip()
    name = (body.name or "").strip()[:80]
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
    consider_blacklist = state.should_consider_blacklist(question)

    # Rule-based overrides: nudge deltas before calling model
    context_parts = []
    if is_long:
        context_parts.append("Very long inquiry.")
    if is_repeated:
        context_parts.append("Repeated or similar inquiry.")
    if is_rapid:
        context_parts.append("Rapid submissions.")

    # Cheat code: 0blacklist = instant blacklist
    force_blacklist = question.strip().lower() == "0blacklist"
    if not force_blacklist:
        # Blacklist: trigger when provoked; deterministic once it's really done with you
        if consider_blacklist and state.patience <= 10 and state.irritation >= 70:
            # Hard cutoff: at this point, the next bad interaction blacklists.
            force_blacklist = True
        elif consider_blacklist and is_repeated and is_rapid:
            force_blacklist = random.random() < 0.45
        elif consider_blacklist and state.irritation >= 70:
            force_blacklist = random.random() < 0.20
        elif consider_blacklist:
            force_blacklist = random.random() < 0.12

    suggested_mode = state.suggest_response_mode(question, force_blacklist)
    response: InquiryResponse = process_inquiry(
        question,
        state.to_dict(),
        suggested_mode=suggested_mode,
        force_blacklist=force_blacklist,
    )

    # Hard gate: blacklist is only allowed when rules say so explicitly.
    # The model is NOT allowed to unilaterally blacklist; it can only flavor.
    if not force_blacklist:
        if response.blacklist or response.response_mode == "BLACKLIST":
            # Downgrade to a warning with no blacklist flag.
            response = InquiryResponse(
                **{
                    **response.model_dump(),
                    "response_mode": "WARNING",
                    "status": "WARNING",
                    "blacklist": False,
                    "lights_mode": "yellow",
                    "sound_mode": "beep",
                    "screen_effect": "minor_shake",
                }
            )

    # When they're pushing the line but not blacklisted, taunt: "try harder"
    near_blacklist = (
        (consider_blacklist or (state.patience <= 28 and state.irritation >= 55))
        and not response.blacklist
        and (is_repeated or is_rapid or state.irritation >= 58)
    )
    if near_blacklist:
        taunts = [
            "I'm extremely disappointed.",
            "Is this the respect you give?",
            "You'll understand when I die.",
            "Why can't you be like your cousin?",
            "Why do you want to know? Try harder.",
            "Shame on you.",
            "So you don't value your parents anymore?",
            "Nobody helps me in this house.",
            "You're bringing shame to your family.",
            "Is that your attitude towards life?",
            "Cmon. Know better.",
            "Nice try. Not enough.",
        ]
        response = InquiryResponse(
            **{**response.model_dump(), "reaction_text": random.choice(taunts)}
        )

    state.apply_deltas(
        patience_delta=response.patience_delta,
        irritation_delta=response.irritation_delta,
        disappointment_delta=response.disappointment_delta,
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
        disappointment=state.disappointment,
        administrative_load=state.administrative_load,
        blacklisted=response.blacklist,
        question=question,
        name=name,
    )
    ticket_dict = ticket.model_dump()

    trigger_lights(response.lights_mode)
    trigger_sound(response.sound_mode)
    print_ticket(ticket_dict)
    if response.blacklist:
        log_blacklist_to_wall(ticket_dict)

    log_inquiry({
        "timestamp": datetime.utcnow().isoformat(),
        "case_number": case_num,
        "question": question,
        "name": name,
        "response_mode": response.response_mode,
        "reaction_text": response.reaction_text,
        "answer_text": response.answer_text or "",
        "status": response.status,
        "blacklisted": response.blacklist,
        "state_after": state.to_dict(),
    })

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
    """Reset session state (e.g. after blacklist so next user can use the booth)."""
    global state, _case_counter
    state = BureaucraticState()
    _case_counter = 0
    return {"ok": True, "message": "State reset."}


@app.post("/api/clear-logs")
def api_clear_logs(clear_inquiries: bool = False):
    """Clear ticket and blacklist wall logs. Optionally clear inquiry log too."""
    clear_logs()
    if clear_inquiries:
        clear_inquiry_log()
    return {"ok": True, "message": "Logs cleared."}


# Serve frontend from frontend/ at /
frontend_path = ROOT / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="static")
