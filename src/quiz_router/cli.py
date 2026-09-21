from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress

from .cache import ResultCache
from .io import load_questions, save_results
from .pipeline import QuizPipeline
from .providers import DemoProvider, JevProvider, OpenAICompatibleReasoner

app = typer.Typer(help="Jev-first automated quiz answering system")
console = Console()


@app.callback()
def main() -> None:
    """Batch quiz automation powered by Jev and an optional reasoning model."""


@app.command()
def run(
    input_file: Annotated[Path, typer.Argument(help="CSV/XLSX question bank")],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("results/answers.xlsx"),
    threshold: Annotated[float, typer.Option(min=0.0, max=1.0)] = 0.85,
    concurrency: Annotated[int, typer.Option(min=1, max=64)] = 8,
    no_reasoner: Annotated[
        bool, typer.Option(help="Do not send low-confidence items to System 2")
    ] = False,
    demo: Annotated[
        bool, typer.Option(help="Use deterministic fake providers; no API keys needed")
    ] = False,
    cache_file: Annotated[Path, typer.Option()] = Path("results/cache.sqlite3"),
) -> None:
    """Answer a question bank and export the results."""
    load_dotenv()
    questions = load_questions(input_file)
    cache = ResultCache(cache_file)

    if demo:
        jev = DemoProvider("jev-demo")
        reasoner = None if no_reasoner else DemoProvider("reasoning-demo")
    else:
        jev = JevProvider(
            api_key=os.getenv("TYPESAFE_API_KEY", ""),
            model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
            base_url=os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1"),
        )
        reasoning_key = os.getenv("REASONING_API_KEY", "")
        reasoner = None
        if not no_reasoner and reasoning_key:
            reasoner = OpenAICompatibleReasoner(
                api_key=reasoning_key,
                model=os.getenv("REASONING_MODEL", "gpt-5.6"),
                base_url=os.getenv("REASONING_BASE_URL", "https://api.openai.com/v1"),
            )

    async def execute():
        pipeline = QuizPipeline(
            jev=jev,
            reasoner=reasoner,
            confidence_threshold=threshold,
            concurrency=concurrency,
            cache=cache,
            demo=demo,
        )
        with Progress() as progress:
            task = progress.add_task("答题中", total=len(questions))

            def update(done, total, record):
                progress.update(task, completed=done, description=f"答题中 · {record.status}")

            try:
                return await pipeline.run(questions, progress=update)
            finally:
                await pipeline.aclose()

    try:
        records = asyncio.run(execute())
        destination = save_results(output, questions, records)
        answered = sum(record.status == "answered" for record in records)
        review = sum(record.status == "needs_review" for record in records)
        failed = sum(record.status == "failed" for record in records)
        console.print(f"[green]完成[/green] {answered}，待复核 {review}，失败 {failed}")
        console.print(f"结果：{destination.resolve()}")
    finally:
        cache.close()


if __name__ == "__main__":
    app()
