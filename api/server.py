"""FastAPI backend for the COBOL Flow Analyzer React UI.

Run from the project folder:  uvicorn api.server:app --reload --port 8000
"""
from __future__ import annotations

import os
import sys
import uuid
from collections import OrderedDict

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.analyzer.paragraph_analyzer import paragraph_detail  # noqa: E402
from src.export.report_generator import (  # noqa: E402
    call_sites_frame, paragraphs_frame, to_csv_bytes, to_excel_bytes, to_json_text,
)
from src.commarea import to_dict as commarea_to_dict  # noqa: E402
from src.copybooks import CopybookLibrary  # noqa: E402
from src.pipeline import Analysis, analyze_source  # noqa: E402
from src.programlog import source_fingerprint, summary_of  # noqa: E402
from src.summary.paragraph_summary import paragraph_summary, program_insights  # noqa: E402
from src.values import analyze_values  # noqa: E402
from src.values.buffer_builder import build_sample  # noqa: E402
from src.values.buffer_search import analyze_with_buffer, build_by_execution  # noqa: E402
from src.values.local_values import const  # noqa: E402
from src.values.working_storage import working_storage  # noqa: E402

SAMPLE_PATH = os.path.join(ROOT, "sample_programs", "sample01.cbl")
MAX_STORED = 20

app = FastAPI(title="COBOL Flow Analyzer API")

from api.copybook_routes import knowledge as _knowledge, router as copybook_router  # noqa: E402
from api.programlog_routes import program_log as _program_log, router as program_log_router  # noqa: E402
app.include_router(copybook_router)
app.include_router(program_log_router)
_analyses: "OrderedDict[str, Analysis]" = OrderedDict()


class AnalyzeRequest(BaseModel):
    name: str = "program.cbl"
    source: str
    # Copybooks uploaded with the program: {"CUSTCOMM": "...text..."}
    copybooks: dict[str, str] = {}


def _store(analysis: Analysis) -> str:
    analysis_id = uuid.uuid4().hex[:10]
    _analyses[analysis_id] = analysis
    while len(_analyses) > MAX_STORED:
        _analyses.popitem(last=False)
    return analysis_id


def _get(analysis_id: str) -> Analysis:
    analysis = _analyses.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found; upload the program again.")
    return analysis


def _origin(program, line: int) -> str:
    """Where a line really is: 'INP389.cbl.txt:60' (or a copybook file), not the expanded number."""
    return program.line_origin.get(line) or f"{program.source_name}:{line}"


def _payload(analysis_id: str, a: Analysis) -> dict:
    p = a.program
    statuses = a.statuses
    paragraphs = []
    for para in p.paragraphs:
        st = statuses[para.name]
        paragraphs.append({
            "name": para.name,
            "index": para.index,
            "section": para.section,
            "start_line": para.start_line,
            "origin": _origin(p, para.start_line),
            "end_line": para.end_line,
            "statement_count": para.statement_count,
            "status": st.label,
            "is_entry": st.is_entry,
            "call_count": st.call_count,
            "caller_count": st.caller_count,
            "callers": st.callers,
            "never_called": st.never_called,
            "reachable": st.reachable,
            "multiple_callers": st.multiple_callers,
            "falls_through": not any(s.kind in ("TERMINATE", "GOTO", "EXIT_PARA") for s in para.statements),
        })

    graph_nodes = [{"id": row["name"], **row} for row in paragraphs]
    graph_edges = [{"source": u, "target": v, "kind": d.get("kind"), "conditional": bool(d.get("conditional")),
                    "conditions": d.get("conditions", ""), "line": d.get("line")}
                   for u, v, d in a.graph.edges(data=True)]

    return {
        "id": analysis_id,
        "program": {
            "name": p.name,
            "source_name": p.source_name,
            "line_count": p.line_count,
            "data_item_count": p.data_item_count,
            "procedure_start_line": p.procedure_start_line,
            "procedure_origin": _origin(p, p.procedure_start_line),
        },
        "divisions": [{"name": d.name, "start_line": d.start_line, "origin": _origin(p, d.start_line)} for d in p.divisions],
        "sections": [{"name": s.name, "division": s.division, "start_line": s.start_line, "origin": _origin(p, s.start_line),
                      "paragraph_count": s.paragraph_count} for s in p.sections],
        "stats": {
            "paragraphs": len(p.paragraphs),
            "statements": sum(para.statement_count for para in p.paragraphs),
            "call_sites": len(a.call_sites),
            "external_calls": len(a.external_calls),
            "never_called": len(a.never_called),
            "unreachable": len(a.unreachable),
            "multiple_callers": sum(1 for st in statuses.values() if st.multiple_callers),
            "trace_events": len(a.trace),
        },
        "paragraphs": paragraphs,
        "call_sites": [{"caller": s.caller, "target": s.target, "kind": s.kind, "line": s.line,
                        "conditions": s.conditions, "statement": s.statement} for s in a.call_sites],
        "external_calls": [{"caller": c.caller, "program": c.target, "line": c.line,
                            "conditions": c.conditions} for c in a.external_calls],
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
        "commarea": commarea_to_dict(a.commarea),
        "field_meanings": a.field_meanings,
        "copybooks": {
            "expanded": bool(a.copybooks and a.copybooks.expanded),
            "used": [{"name": u.name, "source": u.source, "depth": u.depth, "line": u.line}
                     for u in (a.copybooks.used if a.copybooks else [])],
            "missing": a.copybooks.missing if a.copybooks else [],
            "problems": a.copybooks.problems if a.copybooks else [],
        },
        "trace": [{"seq": e.seq, "depth": e.depth, "kind": e.kind, "paragraph": e.paragraph,
                   "detail": e.detail, "condition_path": e.condition_path} for e in a.trace],
    }


def _analyze(name: str, source: str, copybooks: dict[str, str] | None = None) -> dict:
    try:
        library = CopybookLibrary.from_environment(extra=[os.path.join(ROOT, 'sample_programs', 'copybooks')], texts=copybooks or {})
        analysis = analyze_source(source, source_name=name, library=library, knowledge=_knowledge())
        analysis.library = library  # kept so summaries can read the 88-level names of its copybooks
    except Exception as exc:  # surface parser problems to the UI instead of a bare 500
        raise HTTPException(status_code=422, detail=f"Could not analyze {name}: {exc}") from exc
    if not analysis.program.paragraphs:
        raise HTTPException(status_code=422, detail="No PROCEDURE DIVISION paragraphs were found.")
    analysis_id = _store(analysis)
    payload = _payload(analysis_id, analysis)
    payload["log"] = _log_run(source, name, payload)
    payload["log"]["paragraphs_recorded"] = _record_paragraphs(source, analysis)
    return payload


def _record_paragraphs(source: str, analysis: Analysis) -> int:
    """Store the summary of every paragraph, indexed by the program name from the analysis."""
    try:
        library = getattr(analysis, "library", None)
        summaries = [s for s in (paragraph_summary(analysis, p.name, library=library)
                                 for p in analysis.program.paragraphs) if s]
        return _program_log().record_paragraphs(source_fingerprint(source), analysis.program.name, summaries)
    except Exception:  # a failed record must not stop the analysis from showing
        return 0


def _log_run(source: str, name: str, payload: dict) -> dict:
    """Record this run in the program log and return what was already known about the program."""
    fingerprint = source_fingerprint(source)
    try:
        log = _program_log()
        earlier = log.history(fingerprint)
        run_id = log.record_run(fingerprint, name, summary_of(payload))
    except Exception as exc:  # logging must never stop an analysis from showing
        return {"fingerprint": fingerprint, "error": f"Program log could not be updated: {exc}"}
    return {
        "fingerprint": fingerprint,
        "run_id": run_id,
        "previous_runs": earlier["run_count"],
        "previous_analysed_at": earlier["runs"][0]["analysed_at"] if earlier["runs"] else None,
        "details": earlier["details"],
    }


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    return _analyze(req.name, req.source, req.copybooks)


@app.get("/api/sample")
def sample() -> dict:
    with open(SAMPLE_PATH, encoding="utf-8") as handle:
        return {"name": "sample01.cbl", "source": handle.read()}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    return _payload(analysis_id, _get(analysis_id))


@app.get("/api/analyses/{analysis_id}/source")
def get_source(analysis_id: str) -> dict:
    analysis = _get(analysis_id)
    return {"lines": [{"number": n, "text": t} for n, t in sorted(analysis.program.source_lines.items())]}


@app.get("/api/analyses/{analysis_id}/paragraphs/{name}")
def get_paragraph(analysis_id: str, name: str) -> dict:
    detail = paragraph_detail(_get(analysis_id), name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No paragraph named {name}.")
    return detail


@app.get("/api/analyses/{analysis_id}/paragraphs/{name}/summary")
def get_paragraph_summary(analysis_id: str, name: str) -> dict:
    result = paragraph_summary(_get(analysis_id), name, library=getattr(_get(analysis_id), "library", None))
    if result is None:
        raise HTTPException(status_code=404, detail=f"No paragraph named {name}.")
    return result


@app.get("/api/analyses/{analysis_id}/paragraphs/{name}/locals")
def get_paragraph_locals(analysis_id: str, name: str) -> dict:
    result = analyze_values(_get(analysis_id), name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No paragraph named {name}.")
    return result


@app.get("/api/analyses/{analysis_id}/paragraphs/{name}/sample-buffer")
def get_sample_buffer(analysis_id: str, name: str, buffer: str = "RCV-DATA-BUFFER-AREA",
                      assume: str = "") -> dict:
    """assume: comma-separated NAME=value pairs for positions the program does not set, e.g. WS-NEXT-POS=1."""
    analysis = _get(analysis_id)
    assumptions = {}
    for pair in filter(None, (part.strip() for part in assume.split(","))):
        key, _, value = pair.partition("=")
        if key.strip() and value.strip().lstrip("-").isdigit():
            assumptions[key.strip().upper()] = const(int(value))
    result = build_sample(analysis, name, buffer, assumptions, library=getattr(analysis, "library", None))
    if result is None:
        raise HTTPException(status_code=404, detail=f"No paragraph named {name}.")
    return result


@app.get("/api/analyses/{analysis_id}/working-storage")
def get_working_storage(analysis_id: str, local_only: bool = False) -> dict:
    analysis = _get(analysis_id)
    items = [w.to_dict() for w in working_storage(analysis) if not local_only or w.is_local]
    return {"count": len(items), "items": items}


@app.get("/api/analyses/{analysis_id}/buffer-search")
def get_buffer_search(analysis_id: str, entry: str, paragraph: str = "", buffer: str = "RCV-DATA-BUFFER-AREA",
                      assume: str = "") -> dict:
    """Build the buffer by running the tests from `entry`; optionally run `paragraph` on the result."""
    analysis = _get(analysis_id)
    assumptions = {}
    for pair in filter(None, (part.strip() for part in assume.split(","))):
        key, _, value = pair.partition("=")
        if key.strip() and value.strip().lstrip("-").isdigit():
            assumptions[key.strip().upper()] = const(int(value))
    built = build_by_execution(analysis, entry, buffer, assumptions)
    if built is None:
        raise HTTPException(status_code=404, detail=f"No paragraph named {entry}.")
    result = {"built": built}
    if paragraph:
        run = analyze_with_buffer(analysis, paragraph, built["sample"], buffer, assumptions)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No paragraph named {paragraph}.")
        result["run"] = run
    return result


@app.get("/api/analyses/{analysis_id}/insights")
def get_insights(analysis_id: str) -> dict:
    analysis = _get(analysis_id)
    return program_insights(analysis, library=getattr(analysis, "library", None))


@app.get("/api/analyses/{analysis_id}/search")
def search(analysis_id: str, q: str = "") -> dict:
    analysis = _get(analysis_id)
    needle = q.strip().upper()
    hits = [p.name for p in analysis.program.paragraphs if needle in p.name.upper()] if needle else \
        [p.name for p in analysis.program.paragraphs]
    return {"matches": hits}


@app.get("/api/analyses/{analysis_id}/export/{fmt}")
def export(analysis_id: str, fmt: str) -> Response:
    analysis = _get(analysis_id)
    name = analysis.program.name
    if fmt == "xlsx":
        return Response(to_excel_bytes(analysis), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}_flow.xlsx"'})
    if fmt == "json":
        return Response(to_json_text(analysis), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}_analysis.json"'})
    if fmt == "paragraphs.csv":
        return Response(to_csv_bytes(paragraphs_frame(analysis)), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}_paragraphs.csv"'})
    if fmt == "callsites.csv":
        return Response(to_csv_bytes(call_sites_frame(analysis)), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}_call_sites.csv"'})
    raise HTTPException(status_code=404, detail="Unknown export format.")
