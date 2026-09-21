from quiz_router.models import ProviderAnswer, QuizQuestion
from quiz_router.pipeline import QuizPipeline
from quiz_router.providers import AnswerProvider


class FixedProvider(AnswerProvider):
    def __init__(self, answer: str, confidence: float, model: str):
        self.value = ProviderAnswer(
            answer=answer,
            confidence=confidence,
            probabilities={"A": 1 - confidence, "B": confidence},
            model=model,
            latency_ms=2,
        )

    async def answer(self, question):
        return self.value


async def test_low_confidence_routes_to_reasoner():
    question = QuizQuestion(id="1", stem="1+1=?", options={"A": "1", "B": "2"})
    pipeline = QuizPipeline(
        jev=FixedProvider("A", 0.6, "jev-test"),
        reasoner=FixedProvider("B", 0.95, "reason-test"),
        confidence_threshold=0.85,
    )
    record = await pipeline.answer_one(question)
    assert record.answer == "B"
    assert record.route == "reasoning"


async def test_high_confidence_stays_on_jev():
    question = QuizQuestion(id="1", stem="1+1=?", options={"A": "1", "B": "2"})
    pipeline = QuizPipeline(
        jev=FixedProvider("B", 0.95, "jev-test"),
        reasoner=FixedProvider("A", 0.99, "reason-test"),
        confidence_threshold=0.85,
    )
    record = await pipeline.answer_one(question)
    assert record.answer == "B"
    assert record.route == "jev"
