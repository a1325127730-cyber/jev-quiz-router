from __future__ import annotations

import io
import json
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .models import AnswerRecord, QuizQuestion

ALIASES = {
    "id": ["id", "题号", "序号", "question_id"],
    "stem": ["question", "题目", "题干", "stem", "content"],
    "correct_answer": ["correct_answer", "answer", "标准答案", "正确答案"],
    "subject": ["subject", "科目", "分类", "知识领域"],
}


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {str(column).strip().lower(): column for column in columns}
    for alias in aliases:
        if alias.lower() in normalized:
            return normalized[alias.lower()]
    return None


def _option_column(columns: list[str], letter: str) -> str | None:
    aliases = [
        letter,
        letter.lower(),
        f"选项{letter}",
        f"option_{letter.lower()}",
        f"option{letter.lower()}",
    ]
    return _find_column(columns, aliases)


def dataframe_to_questions(frame: pd.DataFrame) -> list[QuizQuestion]:
    frame = frame.dropna(how="all")
    columns = [str(column) for column in frame.columns]
    stem_col = _find_column(columns, ALIASES["stem"])
    if not stem_col:
        raise ValueError("未找到题干列。请使用 question、题目、题干 或 stem 作为列名。")

    id_col = _find_column(columns, ALIASES["id"])
    answer_col = _find_column(columns, ALIASES["correct_answer"])
    subject_col = _find_column(columns, ALIASES["subject"])
    option_cols = {letter: _option_column(columns, letter) for letter in "ABCDEFGH"}
    if sum(column is not None for column in option_cols.values()) < 2:
        raise ValueError("至少需要两个选项列，例如 A、B、C、D。")

    questions: list[QuizQuestion] = []
    for index, row in frame.iterrows():
        if pd.isna(row[stem_col]) or not str(row[stem_col]).strip():
            continue
        options = {
            letter: str(row[column]).strip()
            for letter, column in option_cols.items()
            if column and not pd.isna(row[column]) and str(row[column]).strip()
        }
        raw_id = row[id_col] if id_col and not pd.isna(row[id_col]) else index + 1
        correct = row[answer_col] if answer_col and not pd.isna(row[answer_col]) else None
        subject = row[subject_col] if subject_col and not pd.isna(row[subject_col]) else None
        questions.append(
            QuizQuestion(
                id=str(raw_id),
                stem=str(row[stem_col]).strip(),
                options=options,
                correct_answer=str(correct) if correct is not None else None,
                subject=str(subject).strip() if subject is not None else None,
            )
        )
    if not questions:
        raise ValueError("文件中没有可读取的题目。")
    return questions


def load_questions(
    source: str | Path | BinaryIO, filename: str | None = None
) -> list[QuizQuestion]:
    name = filename or getattr(source, "name", str(source))
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        try:
            frame = pd.read_csv(source, encoding="utf-8-sig")
        except UnicodeDecodeError:
            if hasattr(source, "seek"):
                source.seek(0)
            frame = pd.read_csv(source, encoding="gb18030")
    elif suffix in {".xlsx", ".xlsm"}:
        frame = pd.read_excel(source)
    else:
        raise ValueError("目前支持 .csv、.xlsx 和 .xlsm 文件。")
    return dataframe_to_questions(frame)


def results_dataframe(questions: list[QuizQuestion], records: list[AnswerRecord]) -> pd.DataFrame:
    record_by_id = {record.question_id: record for record in records}
    rows = []
    for question in questions:
        record = record_by_id.get(question.id)
        row = {
            "题号": question.id,
            "题干": question.stem,
            **{letter: question.options.get(letter, "") for letter in "ABCDEFGH"},
            "系统答案": record.answer if record else None,
            "置信度": record.confidence if record else None,
            "处理路线": record.route if record else None,
            "状态": record.status if record else None,
            "解析": record.explanation if record else None,
            "知识点": record.knowledge_point if record else None,
            "模型": record.model if record else None,
            "耗时_ms": record.latency_ms if record else None,
            "标准答案": question.correct_answer,
            "是否正确": record.is_correct if record else None,
            "概率分布": json.dumps(record.probabilities, ensure_ascii=False) if record else None,
            "错误": record.error if record else None,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def export_excel_bytes(questions: list[QuizQuestion], records: list[AnswerRecord]) -> bytes:
    output = io.BytesIO()
    frame = results_dataframe(questions, records)
    answered = frame[frame["状态"] == "answered"]
    known = answered[answered["标准答案"].notna()]
    summary = pd.DataFrame(
        [
            {"指标": "总题数", "数值": len(frame)},
            {"指标": "已回答", "数值": len(answered)},
            {"指标": "待复核", "数值": int((frame["状态"] == "needs_review").sum())},
            {"指标": "失败", "数值": int((frame["状态"] == "failed").sum())},
            {
                "指标": "已知答案准确率",
                "数值": float(known["是否正确"].mean()) if len(known) else None,
            },
        ]
    )
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="答题结果", index=False)
        summary.to_excel(writer, sheet_name="运行摘要", index=False)
        review = frame[frame["状态"] != "answered"]
        review.to_excel(writer, sheet_name="待复核", index=False)
    return output.getvalue()


def save_results(
    path: str | Path, questions: list[QuizQuestion], records: list[AnswerRecord]
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".csv":
        results_dataframe(questions, records).to_csv(destination, index=False, encoding="utf-8-sig")
    elif destination.suffix.lower() in {".xlsx", ".xlsm"}:
        destination.write_bytes(export_excel_bytes(questions, records))
    elif destination.suffix.lower() == ".jsonl":
        with destination.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")
    else:
        raise ValueError("输出文件必须是 .xlsx、.csv 或 .jsonl。")
    return destination
