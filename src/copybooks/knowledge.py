"""Stores what a person has said a copybook field means.

One SQLite file holds:
  copybook_notes  one row per copybook: a description and the fingerprint of the text it describes
  field_notes     one row per field: meaning, category, tags, and the copybook fingerprint at the
                  time the note was written

A note is keyed by the copybook name and the field's declared path inside that copybook
(for example CUSTCOMM / CUST-NAME). The declared path is used, not the expanded path, so a
note still applies when REPLACING renames the field in the program that copies it.
If the copybook text later changes, the note is kept and marked stale.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "output", "copybook_knowledge.db")
ENV_VAR = "COBOL_KNOWLEDGE_DB"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS copybook_notes (
    copybook     TEXT PRIMARY KEY,
    description  TEXT NOT NULL DEFAULT '',
    fingerprint  TEXT,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_notes (
    copybook     TEXT NOT NULL,
    field_path   TEXT NOT NULL,
    meaning      TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '[]',
    fingerprint  TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (copybook, field_path)
);
"""


def default_db_path() -> str:
    return os.environ.get(ENV_VAR) or DEFAULT_DB


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _name(copybook: str) -> str:
    return copybook.strip().upper()


class KnowledgeStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------ descriptions
    def get_description(self, copybook: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM copybook_notes WHERE copybook = ?", (_name(copybook),)).fetchone()
        return dict(row) if row else None

    def set_description(self, copybook: str, description: str, fingerprint: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO copybook_notes (copybook, description, fingerprint, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(copybook) DO UPDATE SET description = excluded.description, "
                "fingerprint = excluded.fingerprint, updated_at = excluded.updated_at",
                (_name(copybook), description, fingerprint, _now()),
            )

    # ------------------------------------------------------------ fields
    def get_fields(self, copybook: str) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM field_notes WHERE copybook = ?", (_name(copybook),)).fetchall()
        result = {}
        for row in rows:
            note = dict(row)
            note["tags"] = json.loads(note["tags"] or "[]")
            result[note.pop("field_path")] = note
            note.pop("copybook", None)
        return result

    def upsert_field(self, copybook: str, field_path: str, meaning: str, category: str,
                     tags: list[str], fingerprint: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO field_notes (copybook, field_path, meaning, category, tags, fingerprint, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(copybook, field_path) DO UPDATE SET meaning = excluded.meaning, "
                "category = excluded.category, tags = excluded.tags, fingerprint = excluded.fingerprint, "
                "updated_at = excluded.updated_at",
                (_name(copybook), field_path, meaning, category, json.dumps(tags), fingerprint, _now()),
            )

    def delete_field(self, copybook: str, field_path: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM field_notes WHERE copybook = ? AND field_path = ?",
                                  (_name(copybook), field_path))
            return cursor.rowcount > 0

    def annotated_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT copybook, COUNT(*) AS n FROM field_notes GROUP BY copybook").fetchall()
        return {r["copybook"]: r["n"] for r in rows}

    def export_json(self) -> dict:
        with self._connect() as conn:
            notes = [dict(r) for r in conn.execute("SELECT * FROM copybook_notes ORDER BY copybook")]
            fields = [dict(r) for r in conn.execute("SELECT * FROM field_notes ORDER BY copybook, field_path")]
        for f in fields:
            f["tags"] = json.loads(f["tags"] or "[]")
        return {"copybooks": notes, "fields": fields}
