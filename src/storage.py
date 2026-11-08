"""SQLite persistence for analysed programs (one row per program analysis)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    program_name  TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    analysed_at   TEXT NOT NULL,
    paragraphs    INTEGER NOT NULL,
    call_sites    INTEGER NOT NULL,
    never_called  TEXT NOT NULL,
    result_json   TEXT NOT NULL
);
"""


def save_analysis(db_path: str, analysis, source_text: str) -> int:
    from .export.report_generator import to_json_text

    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cursor = conn.execute(
            "INSERT INTO analyses (program_name, source_name, source_sha256, analysed_at, "
            "paragraphs, call_sites, never_called, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                analysis.program.name,
                analysis.program.source_name,
                digest,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                len(analysis.program.paragraphs),
                len(analysis.call_sites),
                json.dumps(analysis.never_called),
                to_json_text(analysis),
            ),
        )
        return int(cursor.lastrowid)


def list_analyses(db_path: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            "SELECT id, program_name, source_name, analysed_at, paragraphs, call_sites, never_called "
            "FROM analyses ORDER BY id DESC"
        ).fetchall()
    return [
        {"id": r[0], "program": r[1], "source": r[2], "analysed_at": r[3],
         "paragraphs": r[4], "call_sites": r[5], "never_called": json.loads(r[6])}
        for r in rows
    ]
