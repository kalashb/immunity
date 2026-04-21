"""
FastAPI server for I Have Immunity.
Blacklist is subjective (LLM-driven). Arduino buzzer as input, LEDs as output.
"""
from __future__ import annotations

import os
import random
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.state import BureaucraticState
from backend.grok_client import process_inquiry, synthesize_speech
from shared.schemas import InquiryResponse, SessionState, TicketPayload
from hardware.adapters import (
    init_arduino,
    init_printer,
    trigger_lights,
    trigger_sound,
    print_ticket,
    log_inquiry,
    log_blacklist_to_wall,
    clear_logs,
    clear_inquiry_log,
    read_physical_button,
    cleanup_hardware,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    port = os.environ.get("ARDUINO_PORT")
    if port:
        init_arduino(port)
    try:
        init_printer()
    except Exception as exc:
        print(f"[PRINTER] Init failed (non-fatal): {exc}")
    yield
    try:
        cleanup_hardware()
    except Exception:
        pass


app = FastAPI(title="I Have Immunity", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/api/buzzer")
def buzzer_poll() -> dict:
    """Frontend polls this to detect physical buzzer presses."""
    return {"pressed": read_physical_button()}


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

    context_parts = []
    if is_long:
        context_parts.append("Very long inquiry.")
    if is_repeated:
        context_parts.append("Repeated or similar inquiry.")
    if is_rapid:
        context_parts.append("Rapid submissions.")

    # Cheat code preserved
    force_blacklist = question.strip().lower() == "0blacklist"

    # Blacklist decision is now subjective — let the LLM decide.
    # We only hint via suggested_mode; the model reads conversation history and vibes it out.
    # The one hard rule: can't blacklist before MIN_INTERACTIONS_FOR_BLACKLIST exchanges.
    allow_blacklist = state.blacklist_eligible()

    suggested_mode = state.suggest_response_mode(question, force_blacklist)
    history = state.get_history_summary()
    context = " ".join(context_parts) if context_parts else "Normal processing."

    if allow_blacklist and not force_blacklist:
        context += " Blacklist is allowed if you feel they deserve it."

    response: InquiryResponse = process_inquiry(
        question,
        state.to_dict(),
        suggested_mode=suggested_mode,
        force_blacklist=force_blacklist,
        history=history,
        context=context,
    )

    # Only hard gate: no blacklist before minimum interactions (unless cheat code)
    if not force_blacklist and not allow_blacklist:
        if response.blacklist or response.response_mode == "BLACKLIST":
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

    state.record_exchange(question, response.reaction_text, response.blacklist)

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

    # TTS: speak the reaction text
    tts_text = response.reaction_text
    if response.answer_text:
        tts_text += " " + response.answer_text
    audio_b64 = synthesize_speech(tts_text)
    if audio_b64:
        print(f"[TTS] Generated audio for: {tts_text[:50]}...")
    else:
        print(f"[TTS] No audio generated")

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
        "audio_b64": audio_b64,
    }


@app.post("/api/reset")
def reset_state(secret: str = "immunity-reset"):
    """Reset session state (e.g. after blacklist so next user can use the booth)."""
    global state, _case_counter
    state = BureaucraticState()
    _case_counter = 0
    trigger_lights("green")
    return {"ok": True, "message": "State reset."}


@app.post("/api/clear-logs")
def api_clear_logs(clear_inquiries: bool = False):
    """Clear ticket and blacklist wall logs. Optionally clear inquiry log too."""
    clear_logs()
    if clear_inquiries:
        clear_inquiry_log()
    return {"ok": True, "message": "Logs cleared."}


frontend_path = ROOT / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="static")
