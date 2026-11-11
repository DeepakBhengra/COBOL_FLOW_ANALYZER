"""JSON query interface for the COBOL Flow Analyzer.

The COBOL analyst agent calls this script. It reads one JSON object from
stdin and writes one JSON object to stdout.

Commands
  samples     list bundled sample programs
  analyze     program overview
  paragraph   one paragraph: callers, decisions, source
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analyzer.paragraph_analyzer import paragraph_detail  # noqa: E402
from src.copybooks import CopybookLibrary  # noqa: E402
from src.pipeline import analyze_source  # noqa: E402
from src.summary.paragraph_summary import paragraph_summary  # noqa: E402

SAMPLES = (ROOT / "sample_programs").resolve()
COPYBOOKS = SAMPLES / "copybooks"
MAX_SOURCE_CHARS = 400_000
MAX_TRACE = 40
MAX_OUTLINE = 60
MAX_SOURCE_RETURN = 6_000
SAMPLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")
PROGRAM_SUFFIXES = {".cbl", ".cob", ".cobol", ".txt"}


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return _emit({"ok": False, "error": "Expected a JSON object on stdin."})
        request = json.loads(raw)
        if not isinstance(request, dict):
            return _emit({"ok": False, "error": "Request must be a JSON object."})
        command = str(request.get("command") or "")
        if command == "samples":
            return _emit({"ok": True, "samples": list_samples()})
        if command == "analyze":
            return _emit(analyze(request))
        if command == "paragraph":
            return _emit(inspect_paragraph(request))
        return _emit({"ok": False, "error": f"Unknown command {command!r}."})
    except json.JSONDecodeError as exc:
        return _emit({"ok": False, "error": f"Request is not JSON: {exc.msg}."})
    except Exception as exc:  # the agent must get a JSON error, not a traceback
        return _emit({"ok": False, "error": str(exc) or exc.__class__.__name__})


def list_samples() -> list[dict]:
    found = []
    if not SAMPLES.is_dir():
        return found
    for path in sorted(SAMPLES.iterdir()):
        if path.is_file() and path.suffix.lower() in PROGRAM_SUFFIXES:
            found.append({"name": path.name, "bytes": path.stat().st_size})
    return found


def analyze(request: dict) -> dict:
    source_name, text = load_program(request)
    analysis = run(text, source_name)
    program = analysis.program
    statements = sum(para.statement_count for para in program.paragraphs)
    paragraphs = []
    for para in program.paragraphs:
        status = analysis.statuses[para.name]
        paragraphs.append({
            "name": para.name,
            "section": para.section or "",
            "start_line": para.start_line,
            "end_line": para.end_line,
            "statements": para.statement_count,
            "status": status.label,
            "is_entry": status.is_entry,
            "reachable": status.reachable,
            "never_called": status.never_called,
            "callers": status.callers,
            "call_count": status.call_count,
        })
    copybooks = analysis.copybooks
    used = []
    missing: list[str] = []
    problems: list[str] = []
    expanded = False
    if copybooks is not None:
        expanded = bool(copybooks.expanded)
        used = [{"name": item.name, "source": item.source, "line": item.line} for item in copybooks.used[:50]]
        missing = list(dict.fromkeys(copybooks.missing))
        problems = list(copybooks.problems[:20])
    trace = [
        {
            "seq": event.seq,
            "depth": event.depth,
            "kind": event.kind,
            "paragraph": event.paragraph,
            "detail": event.detail,
            "condition": event.condition_path,
        }
        for event in analysis.trace[:MAX_TRACE]
    ]
    external = [
        {"caller": call.caller, "program": call.target, "line": call.line, "conditions": call.conditions}
        for call in analysis.external_calls
    ]
    return {
        "ok": True,
        "program": program.name,
        "source_name": program.source_name,
        "line_count": program.line_count,
        "data_item_count": program.data_item_count,
        "procedure_start_line": program.procedure_start_line,
        "statement_count": statements,
        "entry_paragraph": program.entry_paragraph.name if program.entry_paragraph else None,
        "divisions": [{"name": item.name, "start_line": item.start_line} for item in program.divisions],
        "sections": [
            {"name": item.name, "division": item.division, "start_line": item.start_line,
             "paragraphs": item.paragraph_count}
            for item in program.sections
        ],
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
        "never_called": analysis.never_called,
        "unreachable": analysis.unreachable,
        "external_calls": external,
        "copybooks": {
            "expanded": expanded,
            "used": used,
            "missing": missing,
            "problems": problems,
        },
        "commarea": commarea_headline(analysis.commarea),
        "trace": trace,
        "trace_truncated": len(analysis.trace) > MAX_TRACE,
        "static_analysis": (
            "Every branch is possible. The trace expands each paragraph once. "
            "ALTER and dynamic GO TO are not followed. External CALL bodies are not analyzed."
        ),
    }


def inspect_paragraph(request: dict) -> dict:
    requested = str(request.get("paragraph") or "").strip()
    if not requested:
        return {"ok": False, "error": "paragraph is required."}
    source_name, text = load_program(request)
    analysis = run(text, source_name)
    resolved = resolve_paragraph(analysis, requested)
    if resolved is None:
        names = [para.name for para in analysis.program.paragraphs]
        return {
            "ok": False,
            "error": f"No paragraph named {requested}.",
            "program": analysis.program.name,
            "paragraphs": names[:200],
        }
    summary = paragraph_summary(analysis, resolved)
    detail = paragraph_detail(analysis, resolved)
    if summary is None or detail is None:
        return {"ok": False, "error": f"No detail for {resolved}."}
    source = detail["source"] or ""
    truncated = len(source) > MAX_SOURCE_RETURN
    outline = detail["outline"][:MAX_OUTLINE]
    return {
        "ok": True,
        "program": analysis.program.name,
        "source_name": analysis.program.source_name,
        "paragraph": summary["paragraph"],
        "origin": summary["origin"],
        "status": detail["status"],
        "is_entry": detail["is_entry"],
        "reachable": detail["reachable"],
        "never_called": detail["never_called"],
        "start_line": detail["start_line"],
        "end_line": detail["end_line"],
        "section": detail["section"],
        "statement_count": detail["statement_count"],
        "reached_from": summary["reached_from"],
        "calls": summary["calls"],
        "external_calls": detail["external_calls"],
        "decisions": summary["decisions"],
        "changes": summary["changes"],
        "fields_tested": summary["fields_tested"],
        "after_completion": summary["after_completion"],
        "summary": summary["summary"],
        "falls_through_to": detail["falls_through_to"],
        "outline": outline,
        "outline_truncated": len(detail["outline"]) > MAX_OUTLINE,
        "source": source[:MAX_SOURCE_RETURN],
        "source_truncated": truncated,
    }


def load_program(request: dict) -> tuple[str, str]:
    sample = str(request.get("sample") or "").strip()
    source = request.get("source")
    has_source = isinstance(source, str) and bool(source.strip())
    if bool(sample) == has_source:
        raise ValueError("Pass exactly one of sample or source.")
    if sample:
        return read_sample(sample)
    text = str(source)
    if len(text) > MAX_SOURCE_CHARS:
        raise ValueError(f"Source is longer than {MAX_SOURCE_CHARS} characters.")
    name = str(request.get("source_name") or "program.cbl").strip() or "program.cbl"
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("source_name must be a file name, not a path.")
    return name, text


def read_sample(name: str) -> tuple[str, str]:
    if not SAMPLE_NAME.fullmatch(name):
        raise ValueError("Sample name is not allowed.")
    path = (SAMPLES / name).resolve()
    if path.parent != SAMPLES or not path.is_file():
        known = ", ".join(item["name"] for item in list_samples()) or "(none)"
        raise ValueError(f"No bundled sample named {name}. Known samples: {known}.")
    return name, path.read_text(encoding="utf-8", errors="replace")


def run(text: str, source_name: str):
    extra = [str(COPYBOOKS)] if COPYBOOKS.is_dir() else []
    library = CopybookLibrary.from_environment(extra=extra)
    return analyze_source(text, source_name=source_name, library=library)


def resolve_paragraph(analysis, name: str) -> str | None:
    if name in analysis.program.paragraph_map:
        return name
    folded = name.upper()
    for para in analysis.program.paragraphs:
        if para.name.upper() == folded:
            return para.name
    return None


def commarea_headline(report) -> dict:
    if report is None or not report.applicable:
        return {"applicable": False}
    return {
        "applicable": True,
        "area_name": report.area_name,
        "area_length": report.area_length,
        "area_location": report.area_location,
        "pseudo_conversational": report.pseudo_conversational,
        "tests_eibcalen": report.tests_eibcalen,
        "transids": list(report.transids),
        "linked_programs": list(report.linked_programs),
        "uses_channels": report.uses_channels,
        "field_count": len(report.fields),
        "standards": [
            {"standard": item.standard, "status": item.status, "detail": item.detail}
            for item in report.standards
        ],
        "findings": [
            {"severity": item.severity, "code": item.code, "message": item.message,
             "paragraph": item.paragraph, "line": item.line}
            for item in report.findings[:20]
        ],
    }


def _emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
