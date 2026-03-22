"""
Session state for the bureaucratic entity.
Counters track mood. Blacklist decisions are subjective (LLM-driven), not threshold-based.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Deque
from collections import deque

MIN_VAL = 0
MAX_VAL = 100
RECENT_MAX = 10
LONG_QUESTION_CHARS = 200
RAPID_WINDOW_SEC = 5
RAPID_COUNT = 3

# Minimum interactions before the LLM is even allowed to consider blacklisting.
# Prevents snap blacklists on the first message.
MIN_INTERACTIONS_FOR_BLACKLIST = 3


@dataclass
class BureaucraticState:
    patience: int = 70
    irritation: int = 10
    disappointment: int = 20
    administrative_load: int = 0
    inquiry_count: int = 0
    blacklist_count: int = 0
    is_blacklisted: bool = False
    recent_questions: Deque[str] = field(default_factory=lambda: deque(maxlen=RECENT_MAX))
    recent_timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=RAPID_COUNT + 2))
    conversation_history: list[dict] = field(default_factory=list)

    def clamp(self, key: str, value: int) -> int:
        return max(MIN_VAL, min(MAX_VAL, value))

    def apply_deltas(
        self,
        patience_delta: int = 0,
        irritation_delta: int = 0,
        disappointment_delta: int = 0,
        load_delta: int = 0,
    ) -> None:
        self.patience = self.clamp("patience", self.patience + patience_delta)
        self.irritation = self.clamp("irritation", self.irritation + irritation_delta)
        self.disappointment = self.clamp("disappointment", self.disappointment + disappointment_delta)
        self.administrative_load = self.clamp(
            "administrative_load", self.administrative_load + load_delta
        )

    def record_inquiry(self, question: str) -> None:
        import time
        self.inquiry_count += 1
        self.recent_questions.append(question.strip().lower()[:100])
        self.recent_timestamps.append(time.time())

    def record_exchange(self, question: str, reaction: str, was_blacklisted: bool = False) -> None:
        """Store a summary of each exchange so the LLM can read the conversation arc."""
        self.conversation_history.append({
            "q": question[:120],
            "r": reaction[:120],
            "bl": was_blacklisted,
        })

    def get_history_summary(self, max_entries: int = 8) -> str:
        """Concise conversation history for the LLM to judge vibe."""
        if not self.conversation_history:
            return "No prior interactions."
        entries = self.conversation_history[-max_entries:]
        lines = []
        for i, ex in enumerate(entries, 1):
            lines.append(f'{i}. User: "{ex["q"]}" → You: "{ex["r"]}"')
        return "\n".join(lines)

    def blacklist_eligible(self) -> bool:
        """Soft guard: at least N interactions before blacklist is on the table."""
        return self.inquiry_count >= MIN_INTERACTIONS_FOR_BLACKLIST

    def _repetition_count(self, question: str) -> int:
        q = question.strip().lower()[:100]
        if not q:
            return 0
        return sum(1 for r in self.recent_questions if r == q or (r in q or q in r))

    def is_repeated_question(self, question: str) -> bool:
        return self._repetition_count(question) >= 3

    def is_rapid_fire(self) -> bool:
        import time
        if len(self.recent_timestamps) < RAPID_COUNT:
            return False
        return self.recent_timestamps[-1] - self.recent_timestamps[-RAPID_COUNT] < RAPID_WINDOW_SEC

    def is_very_long(self, question: str) -> bool:
        return len(question.strip()) > LONG_QUESTION_CHARS

    def get_classification_hints(self, question: str) -> dict:
        return {
            "repetition": self._repetition_count(question) >= 2,
            "length_ok": not self.is_very_long(question),
            "rapid_fire": self.is_rapid_fire(),
            "patience_low": self.patience <= 30,
            "irritation_high": self.irritation >= 50,
            "disappointment_high": self.disappointment >= 40,
            "load_high": self.administrative_load >= 70,
        }

    def suggest_response_mode(
        self,
        question: str,
        force_blacklist: bool,
    ) -> str:
        if force_blacklist:
            return "BLACKLIST"
        hints = self.get_classification_hints(question)
        if hints["repetition"] and self.irritation >= 40:
            return "DENIAL" if self.patience <= 25 else "WARNING"
        if hints["rapid_fire"]:
            return "WARNING" if self.patience > 20 else "DENIAL"
        if hints["irritation_high"] and self.patience <= 25:
            return "DENIAL"
        if hints["load_high"] and not hints["length_ok"]:
            return "REFRAME"
        if not hints["length_ok"]:
            return "PARTIAL_ANSWER" if self.disappointment >= 30 else "REFRAME"
        if hints["disappointment_high"] and not hints["irritation_high"]:
            return "DIRECT_ANSWER"
        if hints["patience_low"] and hints["irritation_high"]:
            return "WARNING"
        return "DIRECT_ANSWER"

    def to_dict(self) -> dict:
        return {
            "patience": self.patience,
            "irritation": self.irritation,
            "disappointment": self.disappointment,
            "administrative_load": self.administrative_load,
            "inquiry_count": self.inquiry_count,
            "blacklist_count": self.blacklist_count,
            "is_blacklisted": self.is_blacklisted,
        }
