from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import AnswerRecord


class ResultCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS answers (
                fingerprint TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def get(self, fingerprint: str) -> AnswerRecord | None:
        row = self.connection.execute(
            "SELECT payload FROM answers WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return AnswerRecord.model_validate_json(row[0]) if row else None

    def put(self, record: AnswerRecord, cache_key: str | None = None) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO answers(fingerprint, payload) VALUES(?, ?)",
            (cache_key or record.fingerprint, record.model_dump_json()),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
