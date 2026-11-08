"""Rendering of a CommareaReport as a dictionary (for the API) or as text (for the console)."""
from __future__ import annotations

from dataclasses import asdict

from .models import COMMAREA_LIMIT, CommareaReport


def to_dict(report: CommareaReport) -> dict:
    if not report.applicable:
        return {"applicable": False}
    return {
        "applicable": True,
        "area_name": report.area_name,
        "area_location": report.area_location,
        "area_length": report.area_length,
        "limit": COMMAREA_LIMIT,
        "pseudo_conversational": report.pseudo_conversational,
        "tests_eibcalen": report.tests_eibcalen,
        "transids": report.transids,
        "linked_programs": report.linked_programs,
        "uses_channels": report.uses_channels,
        "fields": [asdict(f) for f in report.fields],
        "commands": [
            {"command": c.command, "paragraph": c.paragraph, "line": c.line,
             "target": c.target_program or c.transid, "commarea": c.commarea,
             "length": c.length_expr, "conditions": c.conditions}
            for c in report.commands
        ],
        "accesses": [asdict(a) for a in report.accesses],
        "narratives": report.narratives,
        "findings": [asdict(f) for f in report.findings],
        "standards": [asdict(s) for s in report.standards],
    }


def to_text(report: CommareaReport) -> str:
    if not report.applicable:
        return "No COMMAREA: the program has no EXEC CICS commands and no DFHCOMMAREA."

    out: list[str] = []
    out.append(f"COMMAREA: {report.area_name or '(none)'}"
               f"  location: {report.area_location or '(not declared)'}"
               f"  length: {report.area_length if report.area_length is not None else '?'} bytes"
               f" (limit {COMMAREA_LIMIT:,})")
    out.append(f"Pseudo-conversational: {'yes' if report.pseudo_conversational else 'no'}"
               f"   EIBCALEN tested: {'yes' if report.tests_eibcalen else 'no'}")
    if report.transids:
        out.append("Transactions returned to: " + ", ".join(report.transids))
    if report.linked_programs:
        out.append("Programs called with the area: " + ", ".join(report.linked_programs))

    out.append("")
    out.append("Standards")
    for s in report.standards:
        out.append(f"  [{s.status:>14}] {s.standard}: {s.detail}")

    out.append("")
    out.append("Fields")
    for f in report.fields:
        out.append(f"  {f.offset:>5} {f.length:>5}  {f.path:<40} {f.pic or '':<14} {f.usage:<8} {f.role}")
        if f.read_in:
            out.append(f"        read in:    {', '.join(f.read_in)}")
        if f.written_in:
            out.append(f"        written in: {', '.join(f.written_in)}")

    out.append("")
    out.append("What the program does with the area")
    for para, sentences in report.narratives.items():
        out.append(f"  {para}")
        for s in sentences:
            out.append(f"    - {s}")

    if report.findings:
        out.append("")
        out.append("Findings")
        for f in report.findings:
            where = f" [{f.paragraph}]" if f.paragraph else ""
            out.append(f"  {f.severity.upper():<7} {f.code}{where}: {f.message}")
    return "\n".join(out)
