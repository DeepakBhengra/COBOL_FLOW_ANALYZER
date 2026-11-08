"""Builds RCV-DATA-BUFFER-AREA by running the program's own tests on a candidate buffer.

Method (the "slowly build the buffer" loop):
  1. Start from a blank buffer.
  2. Run the tracer over the entry paragraph (and the paragraphs it PERFORMs) with the buffer's real
     bytes. Every test on the buffer that is not satisfied by the bytes now present is noted with the
     value it needs.
  3. Write the first needed value of each unsatisfied test into the buffer, and go back to step 2.
  4. Stop when every test that the run reaches is satisfied, or after a fixed number of rounds.

Each round can reach more of the program: a test inside a branch that was not taken becomes visible
once the earlier tests are satisfied. The result is the buffer, the log of every value placed (with the
line that needed it), the path the run takes, and anything that could not be satisfied.
"""
from __future__ import annotations

from .buffer_builder import DEFAULT_BUFFER, _fit
from .local_values import trace_paragraph
from ..summary.paragraph_summary import build_catalog  # noqa: F401  (kept for callers that label fields)

MAX_ROUNDS = 25


def _buffer_size(analysis, name: str) -> int:
    for root in analysis.data_roots or []:
        for item in root.walk():
            if item.name.upper() == name.upper() and not item.children:
                return item.element_length or 0
    return 0


def build_by_execution(analysis, entry: str, buffer_name: str = DEFAULT_BUFFER,
                       assumptions: dict | None = None, rounds: int = MAX_ROUNDS) -> dict | None:
    if entry.upper() not in analysis.program.paragraph_map:
        return None
    name = buffer_name.upper()
    size = _buffer_size(analysis, name) or 2000
    buf = [" "] * size
    placed: dict[int, dict] = {}          # position -> the value written there and why
    log: list[dict] = []
    conflicts: list[dict] = []
    traced = None
    done_round = 0

    for rnd in range(1, rounds + 1):
        traced = trace_paragraph(analysis, entry, assumptions, buffer=(name, "".join(buf)))
        ctx, _env = traced
        writes = 0
        for c in ctx.constraints:
            if c["kind"] != "slice" or c["buffer"] != name:
                continue
            start, length = c["start"].num, c["length"].num
            if start is None or length is None or start < 1:
                continue
            current = "".join(buf[start - 1:start - 1 + length]).ljust(length)
            if any(current.rstrip(" ") == a.rstrip(" ") for a in c["allowed"]):
                continue
            value = _fit(c["allowed"][0], length)
            clash = [p for p in range(start, start + length) if p in placed]
            if clash:
                previous = placed[clash[0]]
                conflicts.append({"position": start, "length": length, "needed": value,
                                  "needed_by": f"line {c['line']}: {c['text']}",
                                  "already_placed": previous["value"], "placed_for": previous["why"]})
                continue
            for k, ch in enumerate(value):
                buf[start - 1 + k] = ch
                placed[start + k] = {"value": value, "why": f"line {c['line']}: {c['text']}"}
            log.append({"round": rnd, "position": start, "length": length, "value": value,
                        "line": c["line"], "via": c["via"], "condition": c["text"],
                        "other_allowed_values": c["allowed"][1:]})
            writes += 1
        done_round = rnd
        if writes == 0:
            break

    ctx, _env = trace_paragraph(analysis, entry, assumptions, buffer=(name, "".join(buf)))
    sample = "".join(buf).rstrip(" ")
    unsatisfied = []
    for c in ctx.constraints:
        if c["kind"] != "slice" or c["buffer"] != name or c["start"].num is None or c["length"].num is None:
            continue
        current = "".join(buf[c["start"].num - 1:c["start"].num - 1 + c["length"].num])
        if not any(current.rstrip(" ") == a.rstrip(" ") for a in c["allowed"]):
            unsatisfied.append({"line": c["line"], "condition": c["text"]})
    return {
        "entry": entry.upper(),
        "buffer": name,
        "size": size,
        "rounds": done_round,
        "sample": sample,
        "display": sample.replace(" ", "·"),
        "placements": log,
        "conflicts": conflicts,
        "unsatisfied": unsatisfied,
        "decisions": [{"line": d.line, "condition": d.condition,
                       "decided": None if d.decided is None else ("true" if d.decided else "false"),
                       "via": d.via} for d in ctx.decisions],
        "unresolved_positions": [n for n in ctx.notes if "not followed" in n or "unknown" in n],
        "notes": ctx.notes,
    }


def analyze_with_buffer(analysis, paragraph: str, buffer_text: str, buffer_name: str = DEFAULT_BUFFER,
                        assumptions: dict | None = None) -> dict | None:
    """Run one paragraph (and what it PERFORMs) on a given buffer and report what it does."""
    from .local_values import analyze_values
    if paragraph.upper() not in analysis.program.paragraph_map:
        return None
    traced = trace_paragraph(analysis, paragraph, assumptions, buffer=(buffer_name.upper(), buffer_text))
    result = analyze_values(analysis, paragraph, assumptions)
    ctx, _env = traced
    result["buffer_run"] = {
        "buffer": buffer_name.upper(),
        "decisions": [{"line": d.line, "condition": d.condition,
                       "decided": None if d.decided is None else ("true" if d.decided else "false"),
                       "when_true": d.when_true, "when_else": d.when_else, "via": d.via}
                      for d in ctx.decisions],
        "slices": [{"text": s["text"], "explain": s["explain"]} for s in ctx.slices],
        "group_moves": [{"line": g["line"], "group": g["group"], "via": g["via"]} for g in ctx.group_moves],
    }
    return result
