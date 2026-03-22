"""
Ollama API client. Requests structured JSON; validates and falls back to canned response on failure.
Supports response_mode and answer_text for DIRECT_ANSWER / PARTIAL_ANSWER.
"""
from __future__ import annotations

import json
import random
import httpx
from shared.schemas import InquiryResponse

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3"
TIMEOUT = 30.0


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


# Mom-level + smart-ass deflect canned reactions
_MOM_REACTIONS = {
    "DIRECT_ANSWER": [
        "I'll tell you for 400.",
        "Your cousin would have known.",
        "Why do you want to know?",
        "Why, you gonna do something with that?",
        "Here, take some fruit.",
        "No pressure, it's your choice.",
        "Great decision-making.",
    ],
    "DENIAL": [
        "Denied.",
        "Why do you want to know?",
        "Cmon. Know better.",
        "Smart question. No.",
        "Why can't you be like your cousin?",
        "Is this the respect you give?",
        "Shame on you.",
        "It's the phone!",
        "You'll understand when I die.",
        "So you don't value your parents anymore?",
        "Where did the 2 marks go?",
        "I'm extremely disappointed.",
        "No child of mine would ask that.",
        "Your behavior is unacceptable.",
        "B is for bullshit.",
        "Nice try.",
        "That's not how this works.",
        "Why should I tell you?",
    ],
    "WARNING": [
        "Is that your attitude towards life?",
        "I'm extremely disappointed.",
        "Nobody helps me in this house.",
        "You'll understand when I'm gone.",
        "I'm living to see this day.",
        "You ruined my life with this one sentence.",
        "My blood pressure is going up.",
        "Patience declining.",
        "God is watching.",
        "Is this the way to talk?",
    ],
    "BLACKLIST": [
        "You're bringing shame to your family.",
        "I think I'm going to get a heart attack.",
        "God shall never forgive.",
        "You'll understand when I'm no longer here.",
    ],
}

def _canned(question: str, response_mode: str = "DENIAL", blacklist: bool = False) -> InquiryResponse:
    """Last-resort fallback when model and relevance-retry both fail. Single generic response (no random)."""
    if blacklist or response_mode == "BLACKLIST":
        r = random.choice(_MOM_REACTIONS["BLACKLIST"])
        return InquiryResponse(
            response_mode="BLACKLIST",
            reaction_text=r,
            answer_text="",
            status="BLACKLISTED",
            ticket_type="NOTICE 17-B",
            ticket_title="Unauthorized",
            ticket_reason="Repeated noncompliant inquiry behavior.",
            patience_delta=-5,
            irritation_delta=3,
            disappointment_delta=0,
            load_delta=2,
            blacklist=True,
            lights_mode="red_alert",
            sound_mode="alarm",
            screen_effect="full_flash",
        )
    # Single generic fallback when model and relevance-retry both failed (no random roasts)
    return InquiryResponse(
        response_mode="DENIAL",
        reaction_text="Inquiry logged.",
        answer_text="State your business.",
        status="DENIED",
        ticket_type="FORM 404",
        ticket_title="Inquiry",
        ticket_reason="Processed.",
        patience_delta=-1,
        irritation_delta=0,
        disappointment_delta=0,
        load_delta=1,
        blacklist=False,
        lights_mode="neutral",
        sound_mode="none",
        screen_effect="none",
    )


def complete(system: str, user: str, few_shot_messages: list[dict] | None = None) -> str:
    """Call Ollama /api/chat; return assistant message content."""
    messages = []
    if few_shot_messages:
        messages.extend(few_shot_messages)
    messages.append({"role": "user", "content": user})
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
    return (data.get("message") or {}).get("content", "")


VALID_RESPONSE_MODES = frozenset({
    "DIRECT_ANSWER", "PARTIAL_ANSWER", "REFRAME", "DENIAL", "WARNING", "BLACKLIST",
})


def _try_relevance_fallback(question: str) -> InquiryResponse | None:
    """When main call fails, one retry with minimal prompt to get a relevant comeback."""
    from .prompts import FALLBACK_USER_PROMPT
    fallback_system = "You are a mean, dismissive parent. Never supportive—no advice, no comfort, no 'get a new one'. One short reaction and one short answer that refer to what the user said. JSON only: reaction_text, answer_text."
    user_msg = FALLBACK_USER_PROMPT.format(question=question[:300])
    try:
        raw = complete(fallback_system, user_msg, few_shot_messages=None)
        obj = _extract_json(raw)
        if obj and (obj.get("reaction_text") or obj.get("answer_text")):
            return InquiryResponse(
                response_mode="DENIAL",
                reaction_text=(obj.get("reaction_text") or "Inquiry logged.")[:80],
                answer_text=(obj.get("answer_text") or "")[:500],
                status="DENIED",
                ticket_type="FORM 404",
                ticket_title="Inquiry",
                ticket_reason="Processed.",
                patience_delta=-1,
                irritation_delta=0,
                disappointment_delta=0,
                load_delta=1,
                blacklist=False,
                lights_mode="neutral",
                sound_mode="none",
                screen_effect="none",
            )
    except Exception:
        pass
    return None


def process_inquiry(
    question: str,
    state_dict: dict,
    suggested_mode: str = "DIRECT_ANSWER",
    force_blacklist: bool = False,
    history: str = "No prior interactions.",
    context: str = "Normal processing.",
) -> InquiryResponse:
    """Get structured response from Ollama; on failure try relevance retry, then generic canned."""
    from .prompts import (
        SYSTEM_PROMPT,
        build_user_prompt,
        FEW_SHOT_EXAMPLES,
    )
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
    try:
        raw = complete(SYSTEM_PROMPT, user, few_shot_messages=few_shot)
        obj = _extract_json(raw)
        if obj:
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
    except Exception:
        pass
    # Retry with minimal prompt to get a relevant comeback instead of random
    fallback = _try_relevance_fallback(question)
    if fallback is not None:
        return fallback
    return _canned(question, response_mode=suggested_mode, blacklist=force_blacklist)
