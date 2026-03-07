"""
Ollama API client. Requests structured JSON; validates and falls back to canned response on failure.
Supports response_mode and answer_text for DIRECT_ANSWER / PARTIAL_ANSWER.
"""
from __future__ import annotations

import json
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


def _canned(question: str, response_mode: str = "DENIAL", blacklist: bool = False) -> InquiryResponse:
    if blacklist or response_mode == "BLACKLIST":
        return InquiryResponse(
            response_mode="BLACKLIST",
            reaction_text="Citizen flagged.",
            answer_text="",
            status="BLACKLISTED",
            ticket_type="NOTICE 17-B",
            ticket_title="Unauthorized Curiosity",
            ticket_reason="Repeated noncompliant inquiry behavior.",
            patience_delta=-5,
            irritation_delta=3,
            curiosity_delta=0,
            load_delta=2,
            blacklist=True,
            lights_mode="red_alert",
            sound_mode="alarm",
            screen_effect="full_flash",
        )
    if response_mode == "DIRECT_ANSWER":
        return InquiryResponse(
            response_mode="DIRECT_ANSWER",
            reaction_text="Inquiry approved.",
            answer_text="Answer not available. System fallback.",
            status="APPROVED",
            ticket_type="FORM 201",
            ticket_title="Inquiry Processed",
            ticket_reason="Clear question.",
            patience_delta=0,
            irritation_delta=0,
            curiosity_delta=1,
            load_delta=1,
            blacklist=False,
            lights_mode="green",
            sound_mode="printer_whirr",
            screen_effect="minor_glow",
        )
    if response_mode == "PARTIAL_ANSWER":
        return InquiryResponse(
            response_mode="PARTIAL_ANSWER",
            reaction_text="Partial processing.",
            answer_text="Limited response. Please refine inquiry.",
            status="LOGGED",
            ticket_type="NOTE 12",
            ticket_title="Partial Response",
            ticket_reason="Insufficient clarity.",
            patience_delta=-1,
            irritation_delta=0,
            curiosity_delta=0,
            load_delta=1,
            blacklist=False,
            lights_mode="neutral",
            sound_mode="none",
            screen_effect="none",
        )
    if response_mode == "REFRAME":
        return InquiryResponse(
            response_mode="REFRAME",
            reaction_text="Reframe required.",
            answer_text="Please submit a single, focused question.",
            status="PENDING",
            ticket_type="NOTE 7",
            ticket_title="Reframe Requested",
            ticket_reason="Overbroad or unclear.",
            patience_delta=-1,
            irritation_delta=0,
            curiosity_delta=0,
            load_delta=1,
            blacklist=False,
            lights_mode="yellow",
            sound_mode="none",
            screen_effect="none",
        )
    if response_mode == "WARNING":
        return InquiryResponse(
            response_mode="WARNING",
            reaction_text="Patience reduced.",
            answer_text="",
            status="WARNING",
            ticket_type="NOTICE 3",
            ticket_title="Warning Issued",
            ticket_reason="Procedural caution.",
            patience_delta=-2,
            irritation_delta=1,
            curiosity_delta=0,
            load_delta=1,
            blacklist=False,
            lights_mode="yellow",
            sound_mode="beep",
            screen_effect="minor_shake",
        )
    return InquiryResponse(
        response_mode="DENIAL",
        reaction_text="Inquiry denied.",
        answer_text="",
        status="DENIED",
        ticket_type="FORM 404",
        ticket_title="Inquiry Denial",
        ticket_reason="Unlicensed curiosity.",
        patience_delta=-2,
        irritation_delta=1,
        curiosity_delta=0,
        load_delta=1,
        blacklist=False,
        lights_mode="yellow",
        sound_mode="printer_whirr",
        screen_effect="minor_shake",
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


def process_inquiry(
    question: str,
    state_dict: dict,
    suggested_mode: str = "DIRECT_ANSWER",
    force_blacklist: bool = False,
) -> InquiryResponse:
    """Get structured response from Ollama or canned fallback. suggested_mode from rule-based classification."""
    from .prompts import (
        SYSTEM_PROMPT,
        build_user_prompt,
        FEW_SHOT_EXAMPLES,
    )
    user = build_user_prompt(
        question=question,
        patience=state_dict["patience"],
        irritation=state_dict["irritation"],
        curiosity=state_dict["curiosity"],
        administrative_load=state_dict["administrative_load"],
        suggested_mode=suggested_mode,
        context="Normal processing.",
        force_blacklist=force_blacklist,
    )
    few_shot = []
    for ex in FEW_SHOT_EXAMPLES[:6]:
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
                curiosity_delta=int(obj.get("curiosity_delta", 0)),
                load_delta=int(obj.get("load_delta", 1)),
                blacklist=bool(obj.get("blacklist", False)),
                lights_mode=str(obj.get("lights_mode", "neutral")),
                sound_mode=str(obj.get("sound_mode", "none")),
                screen_effect=str(obj.get("screen_effect", "none")),
            )
    except Exception:
        pass
    return _canned(question, response_mode=suggested_mode, blacklist=force_blacklist)
