from __future__ import annotations

import asyncio
from collections.abc import Callable

from .cache import ResultCache
from .models import AnswerRecord, QuizQuestion
from .providers import AnswerProvider

ProgressCallback = Callable[[int, int, AnswerRecord], None]


class QuizPipeline:
    def __init__(
        self,
        jev: AnswerProvider,
        reasoner: AnswerProvider | None = None,
        confidence_threshold: float = 0.85,
        concurrency: int = 8,
        retries: int = 2,
        cache: ResultCache | None = None,
        demo: bool = False,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.jev = jev
        self.reasoner = reasoner
        self.confidence_threshold = confidence_threshold
        self.semaphore = asyncio.Semaphore(max(1, concurrency))
        self.retries = max(0, retries)
        self.cache = cache
        self.demo = demo

    def _cache_key(self, question: QuizQuestion) -> str:
        jev_id = getattr(self.jev, "model", getattr(self.jev, "role", type(self.jev).__name__))
        if self.reasoner:
            reasoner_id = getattr(
                self.reasoner, "model", getattr(self.reasoner, "role", type(self.reasoner).__name__)
            )
        else:
            reasoner_id = "none"
        return (
            f"{question.fingerprint}:jev={jev_id}:reasoner={reasoner_id}:"
            f"threshold={self.confidence_threshold}:demo={self.demo}"
        )

    async def _with_retry(self, provider: AnswerProvider, question: QuizQuestion):
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with self.semaphore:
                    return await provider.answer(question)
            except Exception as error:  # provider errors are captured per question
                last_error = error
                if attempt < self.retries:
                    await asyncio.sleep(min(2**attempt, 4))
        assert last_error is not None
        raise last_error

    async def answer_one(self, question: QuizQuestion) -> AnswerRecord:
        if self.cache:
            cached = self.cache.get(self._cache_key(question))
            if cached and cached.status == "answered":
                return cached.model_copy(
                    update={
                        "question_id": question.id,
                        "route": "cache",
                        "correct_answer": question.correct_answer,
                    }
                )

        try:
            fast = await self._with_retry(self.jev, question)
        except Exception as error:
            if not self.reasoner:
                return AnswerRecord(
                    question_id=question.id,
                    fingerprint=question.fingerprint,
                    route="manual",
                    status="failed",
                    error=f"Jev failed: {error}",
                    correct_answer=question.correct_answer,
                )
            fast = None

        if fast and fast.confidence >= self.confidence_threshold:
            record = AnswerRecord(
                question_id=question.id,
                fingerprint=question.fingerprint,
                answer=fast.answer,
                confidence=fast.confidence,
                probabilities=fast.probabilities,
                route="demo" if self.demo else "jev",
                status="answered",
                model=fast.model,
                latency_ms=fast.latency_ms,
                correct_answer=question.correct_answer,
            )
        elif self.reasoner:
            try:
                deep = await self._with_retry(self.reasoner, question)
                record = AnswerRecord(
                    question_id=question.id,
                    fingerprint=question.fingerprint,
                    answer=deep.answer,
                    confidence=deep.confidence,
                    probabilities=fast.probabilities if fast else {},
                    route="demo" if self.demo else "reasoning",
                    status="answered",
                    explanation=deep.explanation,
                    knowledge_point=deep.knowledge_point,
                    model=deep.model,
                    latency_ms=(fast.latency_ms if fast else 0) + deep.latency_ms,
                    correct_answer=question.correct_answer,
                )
            except Exception as error:
                record = AnswerRecord(
                    question_id=question.id,
                    fingerprint=question.fingerprint,
                    answer=fast.answer if fast else None,
                    confidence=fast.confidence if fast else None,
                    probabilities=fast.probabilities if fast else {},
                    route="manual",
                    status="needs_review" if fast else "failed",
                    model=fast.model if fast else None,
                    latency_ms=fast.latency_ms if fast else 0,
                    error=f"Reasoning fallback failed: {error}",
                    correct_answer=question.correct_answer,
                )
        else:
            record = AnswerRecord(
                question_id=question.id,
                fingerprint=question.fingerprint,
                answer=fast.answer if fast else None,
                confidence=fast.confidence if fast else None,
                probabilities=fast.probabilities if fast else {},
                route="manual",
                status="needs_review",
                model=fast.model if fast else None,
                latency_ms=fast.latency_ms if fast else 0,
                error="Low Jev confidence and no reasoning provider configured",
                correct_answer=question.correct_answer,
            )

        if self.cache and record.status == "answered":
            self.cache.put(record, self._cache_key(question))
        return record

    async def run(
        self, questions: list[QuizQuestion], progress: ProgressCallback | None = None
    ) -> list[AnswerRecord]:
        completed = 0

        async def wrapped(question: QuizQuestion) -> AnswerRecord:
            nonlocal completed
            record = await self.answer_one(question)
            completed += 1
            if progress:
                progress(completed, len(questions), record)
            return record

        return await asyncio.gather(*(wrapped(question) for question in questions))

    async def aclose(self) -> None:
        await self.jev.aclose()
        if self.reasoner:
            await self.reasoner.aclose()
