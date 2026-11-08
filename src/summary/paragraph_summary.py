"""Plain-language summaries of paragraphs and program-wide logic, using the saved field notes.

Inputs:
  analysis      the result of analyze_source / analyze_file (it carries field_meanings: the
                saved copybook notes for every field the program gets from a copybook)
  library       the copybook library, used to read the 88-level condition names of those copybooks

Outputs (plain dicts, ready for JSON):
  paragraph_summary(analysis, name)   what one paragraph does, which fields it tests and changes,
                                      and what happens next
  program_insights(analysis)          the decision fields of the whole program, where each one is
                                      set, and which ones the program never sets
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..analyzer.paragraph_analyzer import paragraph_detail
from ..analyzer.reference_analyzer import walk_statements
from ..copybooks import CopybookLibrary
from ..copybooks.layout import layout_of_copybook

KEYWORDS = {
    "IF", "THEN", "ELSE", "END-IF", "AND", "OR", "NOT", "MOVE", "TO", "FROM", "BY", "GIVING", "COMPUTE",
    "ADD", "SUBTRACT", "SET", "TRUE", "FALSE", "PERFORM", "CALL", "USING", "EVALUATE", "WHEN", "OTHER",
    "END-EVALUATE", "GO", "EXEC", "CICS", "SQL", "END-EXEC", "SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES",
    "HIGH-VALUE", "LOW-VALUE", "EQUAL", "GREATER", "LESS", "THAN", "NUMERIC", "ALPHABETIC",
}
COMPARE_RE = re.compile(
    r"^\s*(?P<left>[A-Z0-9][A-Z0-9-]*)\s+(?P<op>NOT\s+=|NOT\s+>|NOT\s+<|=|>=|<=|>|<|EQUAL TO|NOT EQUAL TO)\s*"
    r"(?P<right>.+?)\s*$",
    re.IGNORECASE,
)
OP_TEXT = {"=": "is", "EQUAL TO": "is", "NOT =": "is not", "NOT EQUAL TO": "is not", "NOT >": "is not greater than",
            "NOT <": "is not less than", ">": "is greater than", "<": "is less than",
            ">=": "is at least", "<=": "is at most"}


@dataclass
class FieldInfo:
    name: str
    meaning: str
    category: str = ""
    stale: bool = False


@dataclass
class Catalog:
    fields: dict[str, FieldInfo] = field(default_factory=dict)     # field name -> saved meaning
    levels88: dict[str, tuple[str, str]] = field(default_factory=dict)  # 88 name -> (parent, values)

    def meaning(self, name: str) -> str | None:
        info = self.fields.get(name.upper())
        return info.meaning if info else None


def _clean(meaning: str) -> str:
    """The note's description without the 'Values: ...' list that was appended to it."""
    return re.split(r"\s*Values:", meaning)[0].strip().rstrip(".")


def _strip_quotes(value: str) -> str:
    return value.strip().strip("'\"“”‘’").strip()


def build_catalog(analysis, library: CopybookLibrary | None = None) -> Catalog:
    """Field names with saved notes, plus the 88-level condition names of the copybooks used."""
    catalog = Catalog()
    for path, note in (analysis.field_meanings or {}).items():
        leaf = path.split(".")[-1].upper()
        catalog.fields[leaf] = FieldInfo(leaf, _clean(note["meaning"]), note.get("category", ""),
                                         bool(note.get("stale")))

    library = library or CopybookLibrary.from_environment()
    used = {u.name for u in (analysis.copybooks.used if analysis.copybooks else [])}
    for copy in used:
        found = library.resolve(copy)
        if found is None:
            continue
        layout = layout_of_copybook(copy, found[1])
        for item in layout.items:
            for cond in item.conditions:
                catalog.levels88[cond.name.upper()] = (item.name.upper(), cond.values)
    return catalog


def _plain_comparison(text: str, catalog: Catalog) -> str:
    m = COMPARE_RE.match(text)
    if not m:
        return text
    left = m.group("left").upper()
    op = re.sub(r"\s+", " ", m.group("op").upper())
    right = _strip_quotes(m.group("right"))
    meaning = catalog.meaning(left)
    subject = f"{left} ({meaning})" if meaning else left
    return f"{subject} {OP_TEXT.get(op, op.lower())} {right}"


def plain_condition(condition: str, catalog: Catalog) -> str:
    """'TB-IL-PASSWORD-VALIDATION-SW = 'Y'' -> 'TB-IL-PASSWORD-VALIDATION-SW (Term ID needs password validation) is Y'."""
    if not condition:
        return ""
    parts = re.split(r"\s+(AND|OR)\s+", condition.strip(), flags=re.IGNORECASE)
    rendered = []
    for part in parts:
        if part.upper() in ("AND", "OR"):
            rendered.append(part.lower())
            continue
        token = part.strip().upper()
        if token in catalog.levels88:
            parent, values = catalog.levels88[token]
            meaning = catalog.meaning(parent)
            label = f"{parent} ({meaning})" if meaning else parent
            rendered.append(f"{token} is true when {label} is {values}")
        else:
            rendered.append(_plain_comparison(part, catalog))
    return " ".join(rendered)


def _names_in(text: str, catalog: Catalog) -> list[str]:
    found = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9-]*", text or ""):
        upper = word.upper()
        if upper in KEYWORDS:
            continue
        if upper in catalog.fields or upper in catalog.levels88:
            if upper not in found:
                found.append(upper)
    return found


def _writes(statement, catalog: Catalog) -> list[dict]:
    """Fields a statement changes, with the value it gives them where that is visible."""
    text = statement.text.strip()
    upper = text.upper()
    out = []
    if upper.startswith("MOVE "):
        m = re.match(r"MOVE\s+(?P<src>.+?)\s+TO\s+(?P<dst>.+)$", text, re.IGNORECASE)
        if m:
            value = _strip_quotes(m.group("src"))
            for target in _names_in(m.group("dst"), catalog):
                out.append({"field": target, "value": value, "line": statement.line, "by": "MOVE"})
    elif upper.startswith("SET "):
        m = re.match(r"SET\s+(?P<dst>.+?)\s+TO\s+(?P<val>.+)$", text, re.IGNORECASE)
        if m:
            for target in _names_in(m.group("dst"), catalog):
                if target in catalog.levels88:
                    parent, values = catalog.levels88[target]
                    out.append({"field": parent, "value": values, "line": statement.line, "by": f"SET {target}"})
                else:
                    out.append({"field": target, "value": _strip_quotes(m.group("val")), "line": statement.line,
                                "by": "SET"})
    elif upper.startswith("COMPUTE "):
        m = re.match(r"COMPUTE\s+(?P<dst>[A-Za-z0-9-]+)", text, re.IGNORECASE)
        if m and m.group("dst").upper() in catalog.fields:
            out.append({"field": m.group("dst").upper(), "value": "(computed)", "line": statement.line,
                        "by": "COMPUTE"})
    elif upper.startswith(("ADD ", "SUBTRACT ")):
        m = re.search(r"\b(?:TO|FROM)\s+(?P<dst>[A-Za-z0-9-]+)", text, re.IGNORECASE)
        if m and m.group("dst").upper() in catalog.fields:
            out.append({"field": m.group("dst").upper(), "value": "(arithmetic)", "line": statement.line,
                        "by": text.split()[0].upper()})
    return out


def paragraph_summary(analysis, name: str, library: CopybookLibrary | None = None,
                      catalog: Catalog | None = None) -> dict | None:
    detail = paragraph_detail(analysis, name)
    if detail is None:
        return None
    catalog = catalog or build_catalog(analysis, library)
    para = analysis.program.paragraph_map[name]

    decisions, writes, reads = [], [], []
    for stmt, enclosing in walk_statements(para.statements):
        if stmt.kind == "IF":
            plain = plain_condition(stmt.condition, catalog)
            names = _names_in(stmt.condition, catalog)
            reads.extend(n for n in names if n not in reads)
            true_actions = [s.text for s in (stmt.branches[0].body if stmt.branches else [])][:4]
            decisions.append({
                "line": stmt.line, "condition": stmt.condition, "plain": plain, "fields": names,
                "enclosing": list(enclosing), "when_true": true_actions,
            })
        else:
            writes.extend(_writes(stmt, catalog))

    written = {}
    for w in writes:
        written.setdefault(w["field"], []).append(w)
    changed = [
        {"field": f, "meaning": catalog.meaning(f), "values": sorted({w["value"] for w in ws}),
         "lines": [w["line"] for w in ws]}
        for f, ws in written.items()
    ]
    tested = [
        {"field": f, "meaning": catalog.meaning(f)} for f in reads
    ]

    sentences = []
    for d in decisions:
        action = f" If so: {d['when_true'][0]}." if d["when_true"] else ""
        sentences.append(f"Line {d['line']}: if {d['plain']}.{action}")
    for c in changed:
        values = ", ".join(f"'{v}'" for v in c["values"])
        sentences.append(f"It sets {c['field']} to {values}" + (f" ({c['meaning']})." if c["meaning"] else "."))
    if not decisions and not changed:
        sentences.append("It has no decisions on noted fields and changes no noted fields.")
    sentences.append(detail["after_completion"])

    return {
        "paragraph": name,
        "origin": detail["origin"],
        "reached_from": [
            {"caller": c["caller"], "kind": c["kind"], "line": c["line"]} for c in detail["callers"]
        ],
        "decisions": decisions,
        "changes": changed,
        "fields_tested": tested,
        "calls": [{"target": o["target"], "kind": o["kind"], "line": o["line"]} for o in detail["outgoing"]],
        "after_completion": detail["after_completion"],
        "summary": " ".join(sentences),
    }


def program_insights(analysis, library: CopybookLibrary | None = None) -> dict:
    """Which noted fields drive the program's decisions, and where they are set."""
    catalog = build_catalog(analysis, library)
    tested: dict[str, list[dict]] = {}
    writes: dict[str, list[dict]] = {}

    for para in analysis.program.paragraphs:
        for stmt, _ in walk_statements(para.statements):
            if stmt.kind == "IF":
                for name in _names_in(stmt.condition, catalog):
                    # An 88-level name is tested through its parent field, so group it there.
                    key = catalog.levels88[name][0] if name in catalog.levels88 else name
                    tested.setdefault(key, []).append({"paragraph": para.name, "line": stmt.line,
                                                       "condition": plain_condition(stmt.condition, catalog)})
            for w in _writes(stmt, catalog):
                writes.setdefault(w["field"], []).append({"paragraph": para.name, **w})

    insights = []
    for name, uses in sorted(tested.items()):
        sets = writes.get(name, [])
        insights.append({
            "field": name,
            "meaning": catalog.meaning(name),
            "tested_in": uses,
            "set_in": sets,
            "note": ("set in this program" if sets else
                     "never set in this program: its value comes from a file, a table, or the caller"),
        })
    return {
        "decision_fields": insights,
        "fields_with_notes": len(catalog.fields),
        "conditions_88": len(catalog.levels88),
    }
