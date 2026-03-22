"""
Grok API client (xAI). Primary model for the demo.
Falls back to Ollama (ollama_client) if Grok fails, and prints a warning.
"""
from __future__ import annotations

import json
import os
import random
import httpx
from pathlib import Path
from shared.schemas import InquiryResponse

# Load .env from backend/.env
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

GROK_API_KEY = os.environ.get("GROK_API")
GROK_URL = "https://api.x.ai/v1/chat/completions"
GROK_MODEL = "grok-4-1-fast-non-reasoning"
TIMEOUT = 30.0

VALID_RESPONSE_MODES = frozenset({
    "DIRECT_ANSWER", "PARTIAL_ANSWER", "REFRAME", "DENIAL", "WARNING", "BLACKLIST",
})

# Enhanced system prompt for Grok — same character, but pushed further.
# The base prompt in prompts.py is the contract for JSON structure.
# This overlay cranks the personality.
GROK_OVERLAY = """

IMPORTANT — GO HARDER. You have a library of classics like "Why can't you be like your cousin?", "You'll understand when I die", "B is for bullshit", "It's the phone!", "Here, take some fruit." Those are your FLOOR, not your ceiling. You MUST go beyond them. Be creative. Be vicious. Be specific to what they said.

SNARK TOOLKIT — mix and match, invent your own:
- Backhanded compliments: "Wow, you managed to type a full sentence. Growth."
- Weaponized comparisons: not just cousins — compare them to the neighbor's kid, to a stranger on the bus, to literally anyone doing better
- Dramatic escalation: "This is why I have high cholesterol.", "I'm calling my lawyer.", "I need to sit down.", "My ancestors are rolling in their graves."
- Savage deflections: "Google exists and yet here you are, bothering me.", "Is this what my sacrifice was for?"
- Ruthless specificity: if they mention a topic, tear THAT topic apart. They ask about space? "You can't even clean your room and you want to explore space?"
- Transactional cruelty: "I'll answer when you show me your report card.", "That information costs 3 chores and an apology."
- Faux concern: "Oh sweetie, bless your heart. No.", "I worry about you. Not enough to help, but I worry."
- Cold one-liners: "Next.", "Fascinating. Denied.", "I've seen better questions on a cereal box."
- Existential guilt: "I gave up my career for THIS?", "I could have been a doctor but I had you instead."

NEVER repeat the same line twice in a session. Each reaction must feel fresh and targeted. Short and cutting beats long and rambling. One devastating sentence > three okay ones."""


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _grok_complete(system: str, user: str, few_shot_messages: list[dict] | None = None) -> str:
    """Call Grok /v1/chat/completions; return assistant message content."""
    if not GROK_API_KEY:
        raise RuntimeError("GROK_API key not set")
    messages = [{"role": "system", "content": system}]
    if few_shot_messages:
        messages.extend(few_shot_messages)
    messages.append({"role": "user", "content": user})
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROK_MODEL,
        "messages": messages,
        "temperature": 0.8,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(GROK_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


def _parse_response(raw: str, suggested_mode: str) -> InquiryResponse | None:
    """Parse raw model output into InquiryResponse."""
    obj = _extract_json(raw)
    if not obj:
        return None
    mode = obj.get("response_mode", suggested_mode)
    if mode not in VALID_RESPONSE_MODES:
        mode = suggested_mode if suggested_mode in VALID_RESPONSE_MODES else "DENIAL"
    return InquiryResponse(
        response_mode=mode,
        reaction_text=(obj.get("reaction_text") or "Inquiry processed.")[:80],
        answer_text=(obj.get("answer_text") or "")[:1000],
        status=obj.get("status", "APPROVED" if mode == "DIRECT_ANSWER" else "DENIED"),
        ticket_type=obj.get("ticket_type", "FORM 404"),
        ticket_title=obj.get("ticket_title", "Inquiry"),
        ticket_reason=obj.get("ticket_reason", "Processed."),
        patience_delta=int(obj.get("patience_delta", 0)),
        irritation_delta=int(obj.get("irritation_delta", 0)),
        disappointment_delta=int(obj.get("disappointment_delta", 0)),
        load_delta=int(obj.get("load_delta", 1)),
        blacklist=bool(obj.get("blacklist", False)),
        lights_mode=str(obj.get("lights_mode", "neutral")),
        sound_mode=str(obj.get("sound_mode", "none")),
        screen_effect=str(obj.get("screen_effect", "none")),
    )


def process_inquiry(
    question: str,
    state_dict: dict,
    suggested_mode: str = "DIRECT_ANSWER",
    force_blacklist: bool = False,
    history: str = "No prior interactions.",
    context: str = "Normal processing.",
) -> InquiryResponse:
    """Try Grok first. If it fails for any reason, fall back to Ollama."""
    from .prompts import SYSTEM_PROMPT, build_user_prompt, FEW_SHOT_EXAMPLES

    user = build_user_prompt(
        question=question,
        patience=state_dict["patience"],
        irritation=state_dict["irritation"],
        disappointment=state_dict["disappointment"],
        administrative_load=state_dict["administrative_load"],
        suggested_mode=suggested_mode,
        history=history,
        context=context,
        force_blacklist=force_blacklist,
    )
    few_shot = []
    for ex in FEW_SHOT_EXAMPLES[:8]:
        few_shot.append({"role": "user", "content": ex["question"]})
        few_shot.append({"role": "assistant", "content": ex["response"]})

    # --- Try Grok (enhanced prompt) ---
    try:
        raw = _grok_complete(SYSTEM_PROMPT + GROK_OVERLAY, user, few_shot_messages=few_shot)
        result = _parse_response(raw, suggested_mode)
        if result:
            return result
        print("[GROK] Got response but failed to parse JSON — falling back to Ollama")
    except Exception as exc:
        print(f"[GROK] Failed ({type(exc).__name__}: {exc}) — falling back to Ollama")

    # --- Fallback to Ollama ---
    from .ollama_client import process_inquiry as ollama_process
    print("[FALLBACK] Using Ollama")
    return ollama_process(
        question=question,
        state_dict=state_dict,
        suggested_mode=suggested_mode,
        force_blacklist=force_blacklist,
        history=history,
        context=context,
    )
