"""
Session state for the bureaucratic entity.
Values persist across messages; used for counters and blacklist logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Deque
from collections import deque

MIN_VAL = 0
MAX_VAL = 100
RECENT_MAX = 10
SPAM_THRESHOLD = 3  # same/similar question repeated
LONG_QUESTION_CHARS = 200
RAPID_WINDOW_SEC = 5
RAPID_COUNT = 3


@dataclass
class BureaucraticState:
    patience: int = 70
    irritation: int = 10
    curiosity: int = 20
    administrative_load: int = 0
    inquiry_count: int = 0
    blacklist_count: int = 0
    is_blacklisted: bool = False
    recent_questions: Deque[str] = field(default_factory=lambda: deque(maxlen=RECENT_MAX))
    recent_timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=RAPID_COUNT + 2))

    def clamp(self, key: str, value: int) -> int:
        return max(MIN_VAL, min(MAX_VAL, value))

    def apply_deltas(
        self,
        patience_delta: int = 0,
        irritation_delta: int = 0,
        curiosity_delta: int = 0,
        load_delta: int = 0,
    ) -> None:
        self.patience = self.clamp("patience", self.patience + patience_delta)
        self.irritation = self.clamp("irritation", self.irritation + irritation_delta)
        self.curiosity = self.clamp("curiosity", self.curiosity + curiosity_delta)
        self.administrative_load = self.clamp(
            "administrative_load", self.administrative_load + load_delta
        )

    def record_inquiry(self, question: str) -> None:
        import time
        self.inquiry_count += 1
        self.recent_questions.append(question.strip().lower()[:100])
        self.recent_timestamps.append(time.time())

    def _repetition_count(self, question: str) -> int:
        q = question.strip().lower()[:100]
        if not q:
            return 0
        return sum(1 for r in self.recent_questions if r == q or (r in q or q in r))

    def is_repeated_question(self, question: str) -> bool:
        return self._repetition_count(question) >= SPAM_THRESHOLD

    def is_rapid_fire(self) -> bool:
        import time
        if len(self.recent_timestamps) < RAPID_COUNT:
            return False
        return self.recent_timestamps[-1] - self.recent_timestamps[-RAPID_COUNT] < RAPID_WINDOW_SEC

    def is_very_long(self, question: str) -> bool:
        return len(question.strip()) > LONG_QUESTION_CHARS

    def should_consider_blacklist(self) -> bool:
        return self.patience <= 20 and self.irritation >= 60

    def get_classification_hints(self, question: str) -> dict:
        """Rule-based classification inputs for response mode selection."""
        return {
            "repetition": self._repetition_count(question) >= 2,
            "length_ok": not self.is_very_long(question),
            "rapid_fire": self.is_rapid_fire(),
            "patience_low": self.patience <= 30,
            "irritation_high": self.irritation >= 50,
            "curiosity_high": self.curiosity >= 40,
            "load_high": self.administrative_load >= 70,
        }

    def suggest_response_mode(
        self,
        question: str,
        force_blacklist: bool,
    ) -> str:
        """
        Rule-based suggestion for response mode. Counters influence outcome.
        Returns one of: DIRECT_ANSWER, PARTIAL_ANSWER, REFRAME, DENIAL, WARNING, BLACKLIST.
        """
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
            return "PARTIAL_ANSWER" if self.curiosity >= 30 else "REFRAME"
        if hints["curiosity_high"] and not hints["irritation_high"]:
            return "DIRECT_ANSWER"
        if hints["patience_low"] and hints["irritation_high"]:
            return "WARNING"
        return "DIRECT_ANSWER"

    def to_dict(self) -> dict:
        return {
            "patience": self.patience,
            "irritation": self.irritation,
            "curiosity": self.curiosity,
            "administrative_load": self.administrative_load,
            "inquiry_count": self.inquiry_count,
            "blacklist_count": self.blacklist_count,
            "is_blacklisted": self.is_blacklisted,
        }
