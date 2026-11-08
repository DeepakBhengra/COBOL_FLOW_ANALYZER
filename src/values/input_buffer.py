"""Finds the input buffer a program works from (for example RCV-DATA-BUFFER-AREA), where its bytes come
from, and where the program reads it.

Sources that fill a buffer are recognised from the statements:
  * EXEC CICS RETRIEVE / RECEIVE ... INTO (buffer)
  * READ ... INTO buffer, ACCEPT buffer
  * MOVE DFHCOMMAREA TO buffer (or buffer(start:length))

Reads are reference-modified references such as buffer(WS-NEXT-POS:2), found in every paragraph.
The buffer with the most reads and loads is the primary input.
"""
from __future__ import annotations

import re

from ..analyzer.reference_analyzer import walk_statements

LOAD_PATTERNS = [
    ("EXEC CICS RETRIEVE/RECEIVE", re.compile(r"\b(?:RETRIEVE|RECEIVE)\b.*?\bINTO\s*\(?\s*([A-Z][A-Z0-9-]*)", re.I)),
    ("READ INTO", re.compile(r"^READ\b.*?\bINTO\s+([A-Z][A-Z0-9-]*)", re.I)),
    ("ACCEPT", re.compile(r"^ACCEPT\s+([A-Z][A-Z0-9-]*)", re.I)),
    ("MOVE DFHCOMMAREA", re.compile(r"^MOVE\s+DFHCOMMAREA\s+TO\s+([A-Z][A-Z0-9-]*)", re.I)),
]
READ_RE = re.compile(r"([A-Z][A-Z0-9-]*)\s*\(\s*([^()]*?)\s*:\s*([^()]*?)\s*\)")
SKIP = {"DFHCOMMAREA", "EIBCALENDAR"}


def _loads(analysis) -> list[dict]:
    out = []
    for para in analysis.program.paragraphs:
        for stmt, _ in walk_statements(para.statements):
            text = " ".join(stmt.text.split())
            for label, pattern in LOAD_PATTERNS:
                m = pattern.search(text)
                if m and m.group(1).upper() not in SKIP:
                    out.append({"buffer": m.group(1).upper(), "how": label, "line": stmt.line,
                                "paragraph": para.name, "statement": text[:160]})
                    break
    return out


def _reads(analysis) -> list[dict]:
    out = []
    for para in analysis.program.paragraphs:
        for stmt, _ in walk_statements(para.statements):
            text = " ".join(stmt.text.split())
            if text.upper().startswith(("EXEC ", "EXEC")) or " INTO " in text.upper()[:40]:
                pass
            for m in READ_RE.finditer(text):
                name = m.group(1).upper()
                if name in SKIP:
                    continue
                out.append({"buffer": name, "start": m.group(2), "length": m.group(3), "line": stmt.line,
                            "paragraph": para.name, "statement": text[:160]})
    return out


def _declared(analysis) -> dict[str, dict]:
    info = {}
    for root in analysis.data_roots or []:
        for item in root.walk():
            info[item.name.upper()] = {"bytes": item.total_length if item.children else item.element_length,
                                       "pic": item.pic, "section": item.section}
    return info


def detect_input_buffers(analysis) -> list[dict]:
    loads = _loads(analysis)
    reads = _reads(analysis)
    declared = _declared(analysis)
    names = {x["buffer"] for x in loads} | {x["buffer"] for x in reads}
    paragraphs = list(analysis.program.paragraphs)
    order = {p.name: i for i, p in enumerate(paragraphs)}
    result = []
    for name in names:
        my_loads = [x for x in loads if x["buffer"] == name]
        my_reads = [x for x in reads if x["buffer"] == name]
        if not my_loads and not my_reads:
            continue
        first_read = min(my_reads, key=lambda r: (order.get(r["paragraph"], 999), r["line"])) if my_reads else None
        entry = (first_read["paragraph"] if first_read else my_loads[0]["paragraph"])
        result.append({
            "buffer": name,
            "declared": name in declared,
            "bytes": declared.get(name, {}).get("bytes"),
            "pic": declared.get(name, {}).get("pic"),
            "loaded_by": my_loads,
            "reads": my_reads,
            "read_count": len(my_reads),
            "entry_paragraph": entry,
            "score": len(my_reads) + 5 * len(my_loads) + (3 if "BUFFER" in name else 0)
            + (2 if name.startswith("RCV-") else 0),
        })
    result.sort(key=lambda r: -r["score"])
    return result
