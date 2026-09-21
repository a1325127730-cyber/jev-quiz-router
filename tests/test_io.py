import pandas as pd

from quiz_router.io import dataframe_to_questions, export_excel_bytes
from quiz_router.models import AnswerRecord


def test_parse_chinese_columns_and_export():
    frame = pd.DataFrame(
        [{"题号": 1, "题干": "1+1=?", "A": "1", "B": "2", "C": "3", "正确答案": "B"}]
    )
    questions = dataframe_to_questions(frame)
    assert questions[0].options == {"A": "1", "B": "2", "C": "3"}
    record = AnswerRecord(
        question_id="1",
        fingerprint=questions[0].fingerprint,
        answer="B",
        confidence=0.99,
        route="jev",
        status="answered",
        correct_answer="B",
    )
    payload = export_excel_bytes(questions, [record])
    assert payload.startswith(b"PK")
