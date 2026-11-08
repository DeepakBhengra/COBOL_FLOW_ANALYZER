"""Exports analysis results to Excel, CSV and JSON."""
from __future__ import annotations

import io
import json

import pandas as pd

from ..analyzer.paragraph_analyzer import statement_outline


def paragraphs_frame(analysis) -> pd.DataFrame:
    rows = []
    for para in analysis.program.paragraphs:
        status = analysis.statuses[para.name]
        rows.append({
            "Paragraph": para.name,
            "Section": para.section or "",
            "Start line": para.start_line,
            "End line": para.end_line,
            "Statements": para.statement_count,
            "Calls out to": len({s.target for s in analysis.call_sites if s.caller == para.name}),
            "Call sites in": status.call_count,
            "Called by": ", ".join(status.callers),
            "Status": status.label,
            "Reachable from entry": status.reachable,
            "Never called": status.never_called,
        })
    return pd.DataFrame(rows)


def call_sites_frame(analysis) -> pd.DataFrame:
    return pd.DataFrame([{
        "Caller": s.caller,
        "Target": s.target,
        "Kind": s.kind,
        "Line": s.line,
        "Conditional": s.is_conditional,
        "Conditions": " AND ".join(s.conditions),
        "Statement": s.statement,
    } for s in analysis.call_sites])


def statements_frame(analysis) -> pd.DataFrame:
    rows = []
    for para in analysis.program.paragraphs:
        for row in statement_outline(para.statements):
            rows.append({"Paragraph": para.name, "Depth": row["depth"], "Line": row["line"],
                         "Kind": row["kind"], "Text": row["text"]})
    return pd.DataFrame(rows)


def execution_frame(analysis) -> pd.DataFrame:
    return pd.DataFrame([{
        "Step": e.seq, "Depth": e.depth, "Event": e.kind, "Paragraph": e.paragraph,
        "Detail": e.detail, "Condition path": e.condition_path,
    } for e in analysis.trace])


def to_excel_bytes(analysis) -> bytes:
    buffer = io.BytesIO()
    summary = pd.DataFrame([
        {"Item": "Program", "Value": analysis.program.name},
        {"Item": "Source file", "Value": analysis.program.source_name},
        {"Item": "Lines", "Value": analysis.program.line_count},
        {"Item": "Paragraphs", "Value": len(analysis.program.paragraphs)},
        {"Item": "Call sites", "Value": len(analysis.call_sites)},
        {"Item": "External CALLs", "Value": len(analysis.external_calls)},
        {"Item": "Never called", "Value": ", ".join(analysis.never_called)},
        {"Item": "Unreachable from entry", "Value": ", ".join(analysis.unreachable)},
    ])
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        paragraphs_frame(analysis).to_excel(writer, sheet_name="Paragraphs", index=False)
        call_sites_frame(analysis).to_excel(writer, sheet_name="Call sites", index=False)
        statements_frame(analysis).to_excel(writer, sheet_name="Statements", index=False)
        execution_frame(analysis).to_excel(writer, sheet_name="Execution trace", index=False)
    return buffer.getvalue()


def to_json_text(analysis) -> str:
    payload = {
        "program": analysis.program.name,
        "source": analysis.program.source_name,
        "paragraphs": [
            {
                "name": p.name,
                "section": p.section,
                "start_line": p.start_line,
                "end_line": p.end_line,
                "status": analysis.statuses[p.name].label,
                "never_called": analysis.statuses[p.name].never_called,
                "callers": analysis.statuses[p.name].callers,
                "statements": statement_outline(p.statements),
            }
            for p in analysis.program.paragraphs
        ],
        "call_sites": [s.__dict__ for s in analysis.call_sites],
        "external_calls": [c.__dict__ for c in analysis.external_calls],
        "execution_trace": [e.__dict__ for e in analysis.trace],
    }
    return json.dumps(payload, indent=2)


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")
