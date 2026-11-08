"""Program log: a record of every analysis run, plus details people add about a program.

Two SQLite tables live in output/program_log.db (override with COBOL_PROGRAM_LOG_DB):

  program_runs     one row each time a program is analysed: when, which source, the headline
                   numbers, and a summary as JSON
  program_details  extensible notes about a program. Each note has a category, a key and a value.
                   New categories and keys can be added at any time, so the log can grow with
                   what the team learns.

A program is identified by the SHA-256 of its source text (its fingerprint). The same program is
found again even if the file is renamed or uploaded from another folder.

Every run is also appended as one line to output/program_log.jsonl, a plain log that can be read
or searched without the database.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(ROOT, "output", "program_log.db")
DEFAULT_JSONL = os.path.join(ROOT, "output", "program_log.jsonl")
DB_ENV = "COBOL_PROGRAM_LOG_DB"
JSONL_ENV = "COBOL_PROGRAM_LOG_FILE"
DEFAULT_CATEGORY = "general"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS program_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sha256  TEXT NOT NULL,
    program_name   TEXT NOT NULL,
    source_name    TEXT NOT NULL,
    analysed_at    TEXT NOT NULL,
    summary_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_program_runs_sha ON program_runs (source_sha256);
CREATE TABLE IF NOT EXISTS program_details (
    source_sha256  TEXT NOT NULL,
    category       TEXT NOT NULL,
    detail_key     TEXT NOT NULL,
    detail_value   TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (source_sha256, category, detail_key)
);
CREATE TABLE IF NOT EXISTS paragraph_records (
    program_name     TEXT NOT NULL,
    source_sha256    TEXT NOT NULL,
    paragraph        TEXT NOT NULL,
    origin           TEXT NOT NULL,
    recorded_at      TEXT NOT NULL,
    summary          TEXT NOT NULL,
    after_completion TEXT NOT NULL,
    decision_count   INTEGER NOT NULL,
    change_count     INTEGER NOT NULL,
    call_count       INTEGER NOT NULL,
    changes_json     TEXT NOT NULL,
    calls_json       TEXT NOT NULL,
    PRIMARY KEY (source_sha256, paragraph)
);
CREATE INDEX IF NOT EXISTS idx_paragraph_records_program ON paragraph_records (program_name);
CREATE INDEX IF NOT EXISTS idx_paragraph_records_name ON paragraph_records (program_name, paragraph);
CREATE TABLE IF NOT EXISTS paragraph_decisions (
    program_name   TEXT NOT NULL,
    source_sha256  TEXT NOT NULL,
    paragraph      TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    line           INTEGER NOT NULL,
    condition_text TEXT NOT NULL,
    plain_text     TEXT NOT NULL,
    if_true        TEXT NOT NULL,
    fields_json    TEXT NOT NULL,
    PRIMARY KEY (source_sha256, paragraph, seq)
);
CREATE INDEX IF NOT EXISTS idx_paragraph_decisions_program ON paragraph_decisions (program_name);
CREATE INDEX IF NOT EXISTS idx_paragraph_decisions_name ON paragraph_decisions (program_name, paragraph);
CREATE TABLE IF NOT EXISTS paragraph_changes (
    program_name   TEXT NOT NULL,
    source_sha256  TEXT NOT NULL,
    paragraph      TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    field          TEXT NOT NULL,
    meaning        TEXT NOT NULL,
    set_to         TEXT NOT NULL,
    lines          TEXT NOT NULL,
    PRIMARY KEY (source_sha256, paragraph, seq)
);
CREATE INDEX IF NOT EXISTS idx_paragraph_changes_program ON paragraph_changes (program_name);
CREATE INDEX IF NOT EXISTS idx_paragraph_changes_name ON paragraph_changes (program_name, paragraph);
"""


def source_fingerprint(text: str) -> str:
    """Identifies a program by its exact source text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def summary_of(payload: dict) -> dict:
    """The part of an analysis result worth keeping in the log."""
    return {
        "program": payload["program"],
        "stats": payload["stats"],
        "copybooks": payload["copybooks"],
        "commarea": payload.get("commarea"),
        "never_called": [p["name"] for p in payload["paragraphs"] if p["never_called"]],
        "unreachable": [p["name"] for p in payload["paragraphs"] if not p["reachable"]],
        "paragraph_status": {p["name"]: p["status"] for p in payload["paragraphs"]},
    }


class ProgramLog:
    def __init__(self, db_path: str | None = None, jsonl_path: str | None = None):
        self.path = db_path or os.environ.get(DB_ENV) or DEFAULT_DB
        self.jsonl_path = jsonl_path or os.environ.get(JSONL_ENV) or DEFAULT_JSONL
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self._db() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------ runs
    def record_run(self, fingerprint: str, source_name: str, summary: dict) -> int:
        """Store one analysis run and append it to the JSON-lines log. Returns the run id."""
        analysed_at = _now()
        with self._db() as conn:
            cursor = conn.execute(
                "INSERT INTO program_runs (source_sha256, program_name, source_name, analysed_at, summary_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (fingerprint, summary["program"]["name"], source_name, analysed_at,
                 json.dumps(summary, ensure_ascii=False)),
            )
            run_id = int(cursor.lastrowid)

        os.makedirs(os.path.dirname(os.path.abspath(self.jsonl_path)), exist_ok=True)
        line = {"run_id": run_id, "fingerprint": fingerprint, "program": summary["program"]["name"],
                "source": source_name, "analysed_at": analysed_at, "summary": summary}
        with open(self.jsonl_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return run_id

    def history(self, fingerprint: str, max_runs: int = 20) -> dict:
        """Everything known about one program: its past runs and the details people added."""
        with self._db() as conn:
            run_count = conn.execute(
                "SELECT COUNT(*) FROM program_runs WHERE source_sha256 = ?", (fingerprint,)).fetchone()[0]
            runs = conn.execute(
                "SELECT id, program_name, source_name, analysed_at, summary_json FROM program_runs "
                "WHERE source_sha256 = ? ORDER BY id DESC LIMIT ?", (fingerprint, max_runs)).fetchall()
            details = conn.execute(
                "SELECT category, detail_key, detail_value, created_at, updated_at FROM program_details "
                "WHERE source_sha256 = ? ORDER BY category, detail_key", (fingerprint,)).fetchall()
        return {
            "fingerprint": fingerprint,
            "run_count": run_count,
            "runs": [{"id": r["id"], "program": r["program_name"], "source": r["source_name"],
                      "analysed_at": r["analysed_at"], "summary": json.loads(r["summary_json"])} for r in runs],
            "details": [{"category": d["category"], "key": d["detail_key"], "value": d["detail_value"],
                         "created_at": d["created_at"], "updated_at": d["updated_at"]} for d in details],
        }

    def programs(self, limit: int = 50) -> list[dict]:
        """One row per distinct program, most recently analysed first."""
        with self._db() as conn:
            rows = conn.execute(
                "SELECT r.source_sha256, r.program_name, r.source_name, r.analysed_at, g.runs "
                "FROM program_runs r JOIN ("
                "  SELECT source_sha256, MAX(id) AS last_id, COUNT(*) AS runs FROM program_runs GROUP BY source_sha256"
                ") g ON r.id = g.last_id ORDER BY r.id DESC LIMIT ?", (limit,)).fetchall()
        return [{"fingerprint": r["source_sha256"], "program": r["program_name"], "source": r["source_name"],
                 "last_analysed": r["analysed_at"], "run_count": r["runs"]} for r in rows]

    # ------------------------------------------------------------ paragraph records
    def record_paragraphs(self, fingerprint: str, program_name: str, summaries: list[dict]) -> int:
        """Replace this program's paragraph records with the summaries of its current analysis."""
        now = _now()
        with self._db() as conn:
            conn.execute("DELETE FROM paragraph_records WHERE source_sha256 = ?", (fingerprint,))
            conn.execute("DELETE FROM paragraph_decisions WHERE source_sha256 = ?", (fingerprint,))
            conn.execute("DELETE FROM paragraph_changes WHERE source_sha256 = ?", (fingerprint,))
            for item in summaries:
                conn.execute(
                    "INSERT INTO paragraph_records (program_name, source_sha256, paragraph, origin, recorded_at, "
                    "summary, after_completion, decision_count, change_count, call_count, changes_json, calls_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (program_name, fingerprint, item["paragraph"], item.get("origin", ""), now, item["summary"],
                     item["after_completion"], len(item["decisions"]), len(item["changes"]), len(item["calls"]),
                     json.dumps(item["changes"], ensure_ascii=False), json.dumps(item["calls"], ensure_ascii=False)),
                )
                for seq, c in enumerate(item["changes"], start=1):
                    conn.execute(
                        "INSERT INTO paragraph_changes (program_name, source_sha256, paragraph, seq, field, meaning, "
                        "set_to, lines) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (program_name, fingerprint, item["paragraph"], seq, c["field"], c.get("meaning") or "",
                         ", ".join(str(v) for v in c["values"]), ", ".join(str(n) for n in c["lines"])),
                    )
                for seq, d in enumerate(item["decisions"], start=1):
                    conn.execute(
                        "INSERT INTO paragraph_decisions (program_name, source_sha256, paragraph, seq, line, "
                        "condition_text, plain_text, if_true, fields_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (program_name, fingerprint, item["paragraph"], seq, d["line"], d["condition"],
                         d["plain"], (d["when_true"] or [""])[0], json.dumps(d["fields"])),
                    )
        return len(summaries)

    def paragraphs_of_program(self, program_name: str) -> list[dict]:
        """Every recorded paragraph of a program (latest analysis of each source)."""
        with self._db() as conn:
            rows = conn.execute(
                "SELECT paragraph, origin, recorded_at, decision_count, change_count, call_count, summary, "
                "source_sha256 FROM paragraph_records WHERE program_name = ? ORDER BY paragraph",
                (program_name,)).fetchall()
        return [dict(r) for r in rows]

    def paragraph_record(self, program_name: str, paragraph: str) -> dict | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM paragraph_records WHERE program_name = ? AND paragraph = ? "
                "ORDER BY recorded_at DESC LIMIT 1", (program_name, paragraph)).fetchone()
            if row is None:
                return None
            decisions = conn.execute(
                "SELECT seq, line, condition_text, plain_text, if_true, fields_json FROM paragraph_decisions "
                "WHERE source_sha256 = ? AND paragraph = ? ORDER BY seq",
                (row["source_sha256"], paragraph)).fetchall()
        record = dict(row)
        record["changes"] = json.loads(record.pop("changes_json"))
        record["calls"] = json.loads(record.pop("calls_json"))
        with self._db() as conn:
            changes = conn.execute(
                "SELECT seq, field, meaning, set_to, lines FROM paragraph_changes "
                "WHERE source_sha256 = ? AND paragraph = ? ORDER BY seq",
                (record["source_sha256"], paragraph)).fetchall()
        record["fields_changed"] = [dict(c) for c in changes]
        record["decisions"] = [{"seq": d["seq"], "line": d["line"], "condition": d["condition_text"],
                                "plain": d["plain_text"], "if_true": d["if_true"],
                                "fields": json.loads(d["fields_json"])} for d in decisions]
        return record

    # ------------------------------------------------------------ details
    def add_detail(self, fingerprint: str, key: str, value: str, category: str = DEFAULT_CATEGORY) -> None:
        """Add or replace one detail. The category and key are created the first time they are used."""
        category = (category or DEFAULT_CATEGORY).strip()
        key = key.strip()
        if not key:
            raise ValueError("A detail needs a key.")
        now = _now()
        with self._db() as conn:
            conn.execute(
                "INSERT INTO program_details (source_sha256, category, detail_key, detail_value, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_sha256, category, detail_key) DO UPDATE SET "
                "detail_value = excluded.detail_value, updated_at = excluded.updated_at",
                (fingerprint, category, key, value, now, now),
            )

    def delete_detail(self, fingerprint: str, key: str, category: str = DEFAULT_CATEGORY) -> bool:
        with self._db() as conn:
            cursor = conn.execute(
                "DELETE FROM program_details WHERE source_sha256 = ? AND category = ? AND detail_key = ?",
                (fingerprint, (category or DEFAULT_CATEGORY).strip(), key.strip()))
            return cursor.rowcount > 0
