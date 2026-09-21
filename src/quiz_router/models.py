from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QuizQuestion(BaseModel):
    id: str
    stem: str
    options: dict[str, str]
    correct_answer: str | None = None
    subject: str | None = None

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {
            str(k).strip().upper(): str(v).strip() for k, v in value.items() if str(v).strip()
        }
        if len(cleaned) < 2:
            raise ValueError("A question must contain at least two non-empty options")
        return cleaned

    @field_validator("correct_answer")
    @classmethod
    def normalize_answer(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {"stem": self.stem.strip(), "options": self.options},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProviderAnswer(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float] = Field(default_factory=dict)
    explanation: str | None = None
    knowledge_point: str | None = None
    model: str
    latency_ms: int


class AnswerRecord(BaseModel):
    question_id: str
    fingerprint: str
    answer: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    route: Literal["jev", "reasoning", "manual", "demo", "cache"]
    status: Literal["answered", "needs_review", "failed"]
    explanation: str | None = None
    knowledge_point: str | None = None
    model: str | None = None
    latency_ms: int = 0
    error: str | None = None
    correct_answer: str | None = None

    @property
    def is_correct(self) -> bool | None:
        if not self.correct_answer or not self.answer:
            return None
        return self.answer.upper() == self.correct_answer.upper()
