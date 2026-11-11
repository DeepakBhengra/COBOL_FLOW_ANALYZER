"""Builds a group record (for example INP389-TRANSACTION-AREA) that an EXEC CICS RETRIEVE or a MOVE
from DFHCOMMAREA fills at run time, and runs the program's logic on it.

Method:
  1. Start each field at a value: a sample value (the demo sample, or values you give), otherwise blank
     (text) or zero (numeric). Every field sits at its declared offset and length (INR389 layout).
  2. Run the tracer over the entry paragraph (and the paragraphs it PERFORMs) with the record's fields
     as their values. Every test on a record field that the current value does not meet is noted with
     the value it needs.
  3. Set that field to the first needed value and run again. Stop when no test needs a change.
  4. Report the record by field and position (packed COMP-3 fields as their real bytes), the decisions
     taken on the way, the logic chain of changes and calculations, and the inputs the run could not
     determine (they stay unknown).

Assumptions (for example EIBCALEN=0 for a first-time CICS entry) are given as NAME=value and are used
as known values for the whole run.

Numeric fields: DISPLAY numeric is stored as its digits. COMP-3 (packed decimal) is stored in the
record as its bytes: two digits per byte, and the last nibble holds the sign (C positive, D negative,
F unsigned). A field with an even number of digits gets a leading zero nibble.
"""
from __future__ import annotations

from datetime import date

from .local_values import _layouts, condition_names, const, text_lit, trace_paragraph

MAX_ROUNDS = 25
NUMERIC_TYPES = ("Zoned decimal", "Binary", "Packed")

# Sample values for the INP389 demo: a 10-character date, the 2-letter company code, and a tracking
# number sized to its field ("auto" = digits of the field's length).
DEMO_SAMPLE = {
    "INP389-DATE-RECEIVED": "DATE_TODAY",
    "INP389-COMPANY": "FR",
    "INP389-SAV-TRACKING-NBR": "auto",
}


def _is_numeric(child: dict) -> bool:
    return any(child["type"].startswith(t) for t in NUMERIC_TYPES)


def _is_packed(child: dict) -> bool:
    return child.get("usage", "").upper() == "COMP-3" or child["type"].startswith("Packed")


def pack_comp3(value: int, digits: int, signed: bool) -> bytes:
    """Packed decimal bytes for `value` in a field of `digits` digits (the sign nibble is the last one)."""
    negative = value < 0
    body = str(abs(value)).zfill(digits)
    sign = ("d" if negative else "c") if signed else "f"
    nibbles = body + sign
    if len(nibbles) % 2:
        nibbles = "0" + nibbles
    return bytes.fromhex(nibbles)


def _as_int(text: str) -> int:
    t = text.strip()
    if t.startswith("+"):
        t = t[1:]
    return int(t) if t.lstrip("-").isdigit() else 0


def _value_of(child: dict, text: str):
    """The tracer value of a record field."""
    if _is_numeric(child):
        return const(_as_int(text))
    return text_lit(text.rstrip(" "))


def _fit(child: dict, text: str) -> str:
    """The value kept for a field: digits for numeric fields, text padded to its length otherwise."""
    if _is_numeric(child):
        return str(_as_int(text))
    width = child["bytes"] or len(text)
    return text[:width].ljust(width)


def encode(child: dict, value: str) -> str:
    """The bytes a field occupies in the record, as characters (packed bytes map to chr(0-255))."""
    width = child["bytes"]
    if _is_numeric(child):
        number = _as_int(value)
        digits = child.get("digits") or width
        if _is_packed(child):
            return "".join(chr(b) for b in pack_comp3(number, digits, child.get("signed", False)))
        body = str(abs(number)).zfill(digits)
        return body[-width:] if width else body
    return value[:width].ljust(width)


def encoded_text(child: dict, value: str) -> str:
    """The field as it appears in the record (for display): packed fields as hex."""
    raw = encode(child, value)
    if _is_numeric(child) and _is_packed(child):
        return " ".join(f"{ord(c):02X}" for c in raw)
    return raw


def _matches(child: dict, current: str, allowed: str) -> bool:
    if _is_numeric(child):
        return _as_int(current) == _as_int(allowed)
    return current.rstrip(" ") == allowed.rstrip(" ")


def _possible(child: dict, conditions: dict) -> list[dict]:
    """The 88-level values the field can take, from its condition names (for example 'Y' = YES)."""
    out = []
    for name, (parent, values) in conditions.items():
        if parent == child["name"]:
            out.append({"condition": name, "value": values[0] if values else ""})
    return out


def _sample(child: dict, today: date) -> str | None:
    """The demo sample value for a field, if the demo has one."""
    if child["name"] not in DEMO_SAMPLE:
        return None
    rule = DEMO_SAMPLE[child["name"]]
    if rule == "DATE_TODAY":
        return today.strftime("%m/%d/%Y")[: child["bytes"]]
    if rule == "auto":
        digits = child.get("digits") or child["bytes"]
        return ("1234567890" * (digits // 10 + 1))[:digits]
    return rule


def build_record(analysis, group: str, entry: str, assumptions: dict | None = None, library=None,
                 rounds: int = MAX_ROUNDS, values: dict | None = None, sample: bool = True,
                 today: date | None = None) -> dict | None:
    group = group.upper()
    entry = entry.upper()
    layouts = _layouts(analysis)
    info = layouts.get(group)
    if not info or not info.get("children"):
        return None
    today = today or date.today()
    conditions = condition_names(analysis.data_entries)
    children = info["children"]
    by_name = {c["name"]: c for c in children}

    record: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for c in children:
        if c["name"] in record:
            continue
        given = {k.upper(): v for k, v in (values or {}).items()}
        if c["name"] in given:
            record[c["name"]] = _fit(c, given[c["name"]])
            reasons[c["name"]] = "value you gave"
            continue
        sample_value = _sample(c, today) if sample else None
        if sample_value is not None:
            record[c["name"]] = _fit(c, sample_value)
            reasons[c["name"]] = "sample value for the demo"
            continue
        record[c["name"]] = _fit(c, "0" if _is_numeric(c) else " ")
        reasons[c["name"]] = "no test on this field yet: " + ("zero" if _is_numeric(c) else "blank")

    assumed = assumptions or {}
    patches: list[dict] = []
    ctx = env = None
    rnd = 0
    for rnd in range(1, rounds + 1):
        initial = dict(assumed)
        for name, text in record.items():
            initial[name] = _value_of(by_name[name], text)
        traced = trace_paragraph(analysis, entry, initial)
        if traced is None:
            return None
        ctx, env = traced
        changed = False
        for con in ctx.constraints:
            if con["kind"] != "field" or con["field"] not in by_name:
                continue
            child = by_name[con["field"]]
            current = record[child["name"]]
            if any(_matches(child, current, a) for a in con["allowed"]):
                continue
            new = _fit(child, con["allowed"][0])
            record[child["name"]] = new
            reasons[child["name"]] = f"required by line {con['line']}: {con['text']}"
            patches.append({"round": rnd, "field": child["name"], "offset": child["offset"],
                            "length": child["bytes"], "value": new, "line": con["line"], "via": con["via"],
                            "condition": con["text"]})
            changed = True
        if not changed:
            break

    fields = []
    for c in children:
        raw = encode(c, record[c["name"]])
        fields.append({"name": c["name"], "offset": c["offset"], "bytes": c["bytes"], "pic": c["pic"],
                       "type": c["type"], "value": record[c["name"]],
                       "shown": encoded_text(c, record[c["name"]]),
                       "packed": _is_numeric(c) and _is_packed(c),
                       "raw": raw, "reason": reasons.get(c["name"], ""),
                       "possible_values": _possible(c, conditions)})
    width = info["bytes"]
    text = [" "] * width
    for f in fields:
        for k, ch in enumerate(f["raw"]):
            if f["offset"] + k < width:
                text[f["offset"] + k] = ch
    for f in fields:
        f.pop("raw", None)

    decisions = []
    unknown = []
    for d in ctx.decisions:
        decided = None if d.decided is None else ("true" if d.decided else "false")
        taken = d.when_true if d.decided is not False else d.when_else
        decisions.append({"line": d.line, "condition": d.condition, "decided": decided,
                          "via": d.via, "when_true": d.when_true, "when_else": d.when_else,
                          "taken": taken if decided is not None else []})
        if decided is None:
            unknown.append({"line": d.line, "condition": d.condition, "via": d.via})

    by_paragraph: dict[str, list] = {}
    for d in decisions:
        by_paragraph.setdefault(d["via"], []).append(d)

    return {
        "group": group,
        "entry": entry,
        "bytes": width,
        "record": fields,
        "text": "".join(text),
        "patches": patches,
        "rounds": rnd,
        "assumptions": {k: v.text for k, v in assumed.items()},
        "decisions": decisions,
        "downstream": [{"paragraph": p, "decisions": ds} for p, ds in by_paragraph.items()],
        "chain": [f"line {c.line}: {c.name} = {c.value}" + (f" (in {c.via})" if c.via != entry else "")
                  for c in ctx.changes],
        "unknown_inputs": unknown,
        "notes": ctx.notes,
    }
