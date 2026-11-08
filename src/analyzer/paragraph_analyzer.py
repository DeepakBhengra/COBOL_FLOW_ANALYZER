"""Per-paragraph answers: definition, callers, outgoing calls, outline and what happens next."""
from __future__ import annotations

from ..models.paragraph import Statement
from .flow_analyzer import falls_through


def statement_outline(statements: list[Statement], depth: int = 0) -> list[dict]:
    """Flatten the statement tree into indented rows for display."""
    rows: list[dict] = []
    for stmt in statements:
        rows.append({"depth": depth, "line": stmt.line, "kind": stmt.kind, "text": stmt.text})
        for branch in stmt.branches:
            rows.append({"depth": depth + 1, "line": stmt.line, "kind": "BRANCH",
                         "text": f"[{branch.label}]"})
            rows.extend(statement_outline(branch.body, depth + 2))
    return rows


def _terminal_summary(statements: list[Statement]) -> str | None:
    for stmt in statements:
        if stmt.kind == "TERMINATE":
            return f"ends the program ({stmt.text})"
        if stmt.kind == "GOTO":
            return "transfers control with " + stmt.text
        if stmt.kind == "EXIT_PARA":
            return "exits the paragraph early (EXIT PARAGRAPH)"
    return None


def paragraph_detail(analysis, name: str) -> dict | None:
    program = analysis.program
    para = program.paragraph_map.get(name)
    if para is None:
        return None
    status = analysis.statuses[name]
    sites = analysis.call_sites
    callers = [s for s in sites if s.target == name]
    outgoing = [s for s in sites if s.caller == name]

    next_para = program.paragraphs[para.index + 1].name if para.index + 1 < len(program.paragraphs) else None
    performed_by = [s for s in callers if s.kind != "GO TO"]
    if falls_through(para):
        if next_para:
            after = (f"Finishing this paragraph hands control to {next_para} (source order) "
                     "if it was reached in the main flow.")
        else:
            after = "This is the last paragraph; finishing it ends the program if reached in the main flow."
    else:
        summary = _terminal_summary(para.statements)
        after = f"It {summary}." if summary else "It does not fall through."

    if performed_by:
        resume = "; ".join(f"{s.caller} resumes after its PERFORM at line {s.line}" for s in performed_by)
        after += f" When PERFORMed, control returns to the caller: {resume}."

    return {
        "name": name,
        "section": para.section,
        "index": para.index,
        "start_line": para.start_line,
        "end_line": para.end_line,
        "origin": program.line_origin.get(para.start_line) or f"{program.source_name}:{para.start_line}",
        "source": para.source_text,
        "statement_count": para.statement_count,
        "status": status.label,
        "is_entry": status.is_entry,
        "never_called": status.never_called,
        "reachable": status.reachable,
        "callers": [
            {"caller": s.caller, "kind": s.kind, "line": s.line, "statement": s.statement,
             "conditions": s.conditions}
            for s in callers
        ],
        "outgoing": [
            {"target": s.target, "kind": s.kind, "line": s.line, "statement": s.statement,
             "conditions": s.conditions}
            for s in outgoing
        ],
        "external_calls": [
            {"program": c.target, "line": c.line, "conditions": c.conditions}
            for c in analysis.external_calls if c.caller == name
        ],
        "falls_through_to": next_para if falls_through(para) else None,
        "after_completion": after,
        "outline": statement_outline(para.statements),
        "occurrences": analysis.analyzer.occurrences(name),
    }


def search_paragraphs(analysis, text: str) -> list[str]:
    needle = text.strip().upper()
    if not needle:
        return [p.name for p in analysis.program.paragraphs]
    return [p.name for p in analysis.program.paragraphs if needle in p.name.upper()]
