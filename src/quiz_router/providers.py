from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod

import httpx

from .models import ProviderAnswer, QuizQuestion


class AnswerProvider(ABC):
    @abstractmethod
    async def answer(self, question: QuizQuestion) -> ProviderAnswer:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class JevProvider(AnswerProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        base_url: str = "https://api.typesafe.ai/v1",
        timeout: float = 30,
    ) -> None:
        if not api_key:
            raise ValueError("TYPESAFE_API_KEY 未配置")
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def answer(self, question: QuizQuestion) -> ProviderAnswer:
        started = time.perf_counter()
        payload = {
            "state": {
                "question": question.stem,
                "subject": question.subject,
            },
            "model": self.model,
            "questions": {
                "answer": {
                    "type": "choice",
                    "instructions": (
                        "Choose the single best answer to this exam question. "
                        "Use the option meanings, not the option letters."
                    ),
                    "criteria": question.options,
                }
            },
        }
        response = await self.client.post("/systemone", json=payload)
        response.raise_for_status()
        body = response.json()
        answer = body["answers"]["answer"]
        choice = str(answer["choice"]).upper()
        if choice not in question.options:
            raise ValueError(f"Jev returned an unknown option: {choice}")
        return ProviderAnswer(
            answer=choice,
            confidence=float(answer["confidence"]),
            probabilities={str(k).upper(): float(v) for k, v in answer["probabilities"].items()},
            model=str(body.get("model", self.model)),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    async def aclose(self) -> None:
        await self.client.aclose()


class OpenAICompatibleReasoner(AnswerProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120,
    ) -> None:
        if not api_key:
            raise ValueError("REASONING_API_KEY 未配置")
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def answer(self, question: QuizQuestion) -> ProviderAnswer:
        started = time.perf_counter()
        option_text = "\n".join(f"{key}. {value}" for key, value in question.options.items())
        prompt = f"""Solve this single-choice exam question carefully.

Question: {question.stem}
Options:
{option_text}

Return JSON only with exactly these fields:
{{"answer":"A", "confidence":0.0, "explanation":"concise Chinese explanation", "knowledge_point":"short topic"}}
The answer must be one of: {", ".join(question.options)}.
"""
        response = await self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        data = json.loads(content)
        answer = str(data["answer"]).strip().upper()
        if answer not in question.options:
            raise ValueError(f"Reasoning model returned an unknown option: {answer}")
        return ProviderAnswer(
            answer=answer,
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            explanation=str(data.get("explanation", "")).strip() or None,
            knowledge_point=str(data.get("knowledge_point", "")).strip() or None,
            model=str(body.get("model", self.model)),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    async def aclose(self) -> None:
        await self.client.aclose()


class DemoProvider(AnswerProvider):
    """Deterministic fake provider for UI and pipeline testing. Never claims real accuracy."""

    def __init__(self, role: str = "jev-demo") -> None:
        self.role = role

    async def answer(self, question: QuizQuestion) -> ProviderAnswer:
        digest = hashlib.sha256(question.fingerprint.encode()).digest()
        letters = list(question.options)
        answer = letters[digest[0] % len(letters)]
        confidence = 0.55 + (digest[1] / 255) * 0.44
        if self.role == "reasoning-demo":
            confidence = max(confidence, 0.8)
        remainder = (1 - confidence) / max(1, len(letters) - 1)
        probabilities = {letter: remainder for letter in letters}
        probabilities[answer] = confidence
        return ProviderAnswer(
            answer=answer,
            confidence=confidence,
            probabilities=probabilities,
            explanation="演示模式生成的占位结果，不代表真实解题能力。"
            if self.role == "reasoning-demo"
            else None,
            knowledge_point="demo" if self.role == "reasoning-demo" else None,
            model=self.role,
            latency_ms=1,
        )
