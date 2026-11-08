"""Builds a sample input buffer (for example RCV-DATA-BUFFER-AREA) that satisfies the tests a paragraph makes.

The tracker in local_values records two kinds of evidence:

  * constraints: a branch is taken only when a value equals one of some literals, for example
      MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2) TO WS-FUNCTION
      EVALUATE WS-FUNCTION WHEN 'OL' OR 'CL' ...          -> RCV(WS-NEXT-POS:2) must be 'OL', 'CL', ...
      IF RCV-DATA-BUFFER-AREA(WS-START-POS:2) = 'CF'      -> RCV(WS-START-POS:2) must be 'CF'
  * group moves: a slice of the buffer moved into a group item, for example
      MOVE RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN) TO ORRCNFG-CNFG-REQUEST

The builder places the first allowed literal of each constraint at its position in the buffer, where
positions are known from the tracker (or from assumptions passed in). For each group move it builds a
sample of the whole group: each field gets the value required by a test on that field, or the first
88-level VALUE of the field, or a blank (alphanumeric) or zeros (numeric). The group sample is then
written into the buffer at the slice position.

Anything that cannot be placed (unknown positions, conflicting values) is listed rather than guessed.
"""
from __future__ import annotations

from .local_values import trace_paragraph
from ..summary.paragraph_summary import build_catalog

DEFAULT_BUFFER = "RCV-DATA-BUFFER-AREA"


def _first_literal(values_text: str) -> str | None:
    """First quoted value in an 88-level VALUE list such as "'CF'" or "'N' 'Y'"."""
    quoted = []
    inside = False
    buf = ""
    for ch in values_text:
        if ch == "'":
            if inside:
                quoted.append(buf)
                buf = ""
            inside = not inside
        elif inside:
            buf += ch
    return quoted[0] if quoted else None


def _default_for(child: dict, catalog, group_name: str) -> tuple[str, str]:
    """A value for one field of a group sample, with the reason it was chosen."""
    for name, (parent, values) in catalog.levels88.items():
        if parent == child["name"]:
            literal = _first_literal(values)
            if literal is not None:
                return literal, f"first 88-level value {name}"
    if child["type"] in ("Alphanumeric", "Alphabetic"):
        return " ", "no test on this field: blank"
    return "0", "no test on this field: zero"


def _write(buf: list, occupied: dict, start: int, value: str, source: str, conflicts: list) -> None:
    for offset, ch in enumerate(value):
        pos = start + offset
        if pos < 1:
            continue
        if pos in occupied and occupied[pos][0] != ch:
            conflicts.append({"position": pos, "existing": occupied[pos][0], "existing_source": occupied[pos][1],
                              "new": ch, "new_source": source})
        while len(buf) < pos:
            buf.append(" ")
        buf[pos - 1] = ch
        occupied[pos] = (ch, source)


def _fit(value: str, length: int) -> str:
    if len(value) >= length:
        return value[:length]
    return value + " " * (length - len(value))


def build_sample(analysis, paragraph: str, buffer_name: str = DEFAULT_BUFFER,
                 assumptions: dict | None = None, library=None) -> dict | None:
    """Build a sample of `buffer_name` for the tests made by `paragraph` and the paragraphs it PERFORMs."""
    traced = trace_paragraph(analysis, paragraph, assumptions)
    if traced is None:
        return None
    ctx, env = traced
    catalog = build_catalog(analysis, library)
    buffer_info = ctx.layouts.get(buffer_name.upper(), {})
    size = buffer_info.get("bytes") or 0

    buf: list[str] = []
    occupied: dict = {}
    conflicts: list[dict] = []
    placements: list[dict] = []
    groups: list[dict] = []
    unresolved: list[dict] = []

    # 1. What the tests on the buffer require.
    for c in ctx.constraints:
        if c["kind"] != "slice" or c["buffer"] != buffer_name.upper():
            continue
        start, length = c["start"].num, c["length"].num
        if start is None or length is None:
            unresolved.append({"text": c["text"], "line": c["line"], "reason":
                               f"position {c['start'].text} or length {c['length'].text} is not known; "
                               f"pass it in assumptions"})
            continue
        value = _fit(c["allowed"][0], length)
        source = f"line {c['line']}: {c['text']}"
        _write(buf, occupied, start, value, source, conflicts)
        placements.append({"start": start, "length": length, "value": value, "why": "test on the buffer",
                           "line": c["line"], "via": c["via"], "condition": c["text"],
                           "other_allowed_values": c["allowed"][1:]})

    # 2. Groups that receive a slice of the buffer: build a full sample of the group.
    for gm in ctx.group_moves:
        bname, start_val, length_val = gm["slice"]
        if bname != buffer_name.upper():
            continue
        group = ctx.layouts.get(gm["group"], {})
        group_bytes = group.get("bytes") or 0
        start, length = start_val.num, length_val.num
        if start is None or length is None:
            unresolved.append({"text": f"MOVE {bname}({start_val.text}:{length_val.text}) TO {gm['group']}",
                               "line": gm["line"], "reason": "slice position or length is not known"})
            continue
        fields = []
        record_parts = []
        for child in group.get("children", []):
            tests = [c for c in ctx.constraints if c["kind"] == "field" and c["field"] == child["name"]]
            if tests:
                value, reason = tests[0]["allowed"][0], f"required by line {tests[0]['line']}: {tests[0]['text']}"
            else:
                value, reason = _default_for(child, catalog, gm["group"])
            value = _fit(value, child["bytes"])
            fields.append({"name": child["name"], "offset": child["offset"], "bytes": child["bytes"],
                           "pic": child["pic"], "type": child["type"], "value": value, "reason": reason,
                           "occurs": child["occurs"]})
            record_parts.append((child["offset"], value))
        record = [" "] * group_bytes
        for offset, value in record_parts:
            for k, ch in enumerate(value):
                if 0 <= offset + k < group_bytes:
                    record[offset + k] = ch
        record_text = "".join(record)
        take = min(group_bytes, length)
        if take < group_bytes:
            unresolved.append({"text": f"MOVE {bname}({start}:{length}) TO {gm['group']}", "line": gm["line"],
                               "reason": f"the slice is {length} bytes but the group is {group_bytes}; "
                                         f"only the first {take} bytes of the group are kept"})
        if size and start + take - 1 > size:
            unresolved.append({"text": f"MOVE {bname}({start}:{length}) TO {gm['group']}", "line": gm["line"],
                               "reason": f"the move reads to position {start + take - 1}, past the end of "
                                         f"{bname} ({size} bytes)"})
        _write(buf, occupied, start, record_text[:take], f"line {gm['line']}: group {gm['group']}", conflicts)
        groups.append({"group": gm["group"], "line": gm["line"], "via": gm["via"], "bytes": group_bytes,
                       "placed_at": start, "placed_length": take, "fields": fields,
                       "sample": record_text})
        placements.append({"start": start, "length": take, "value": record_text[:take],
                           "why": f"group {gm['group']} is moved from this slice", "line": gm["line"],
                           "via": gm["via"], "condition": f"MOVE {bname}({start}:{length}) TO {gm['group']}",
                           "other_allowed_values": []})

    total = max([size, len(buf)] + [p["start"] + p["length"] - 1 for p in placements] or [0])
    sample = "".join(buf).ljust(total)
    return {
        "paragraph": paragraph,
        "buffer": buffer_name.upper(),
        "size": size,
        "sample": sample,
        "display": sample.replace(" ", "·"),
        "placements": placements,
        "groups": groups,
        "conflicts": conflicts,
        "unresolved": unresolved,
        "assumptions": dict(assumptions or {}),
        "notes": ctx.notes,
    }
