"""Builds the COMMAREA report: layout, command flow, field usage, findings and standards."""
from __future__ import annotations

import re

from ..analyzer.reference_analyzer import walk_statements
from .cics_commands import extract_commands
from .data_layout import build_layout, find
from .models import (
    COMMAREA_LIMIT, CommandUse, CommareaReport, DataItem, FieldAccess, FieldSummary,
    Finding, StandardCheck,
)
from .usage import classify

READ_MODES = {"R", "RW", "SEND", "PASS"}
WRITE_MODES = {"W", "RW", "RECEIVE"}
NARRATED_ONLY_MODES = {"SEND", "PASS", "RECEIVE"}  # described by the command sentence instead
_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*")


def _root(item: DataItem) -> DataItem:
    while item.parent is not None:
        item = item.parent
    return item


def _identifier(value: str | None) -> str | None:
    if value and _IDENT.fullmatch(value.strip()):
        return value.strip()
    return None


def _length_of(expr: str | None, index: dict[str, DataItem]) -> int | None:
    """Byte length given by a LENGTH() option: a literal, LENGTH OF x, or a data name."""
    if not expr:
        return None
    text = expr.strip()
    match = re.fullmatch(r"LENGTH\s+OF\s+(\S+)", text, re.IGNORECASE)
    if match:
        item = find(index, match.group(1))
        return item.total_length if item else None
    if text.isdigit():
        return int(text)
    item = find(index, _identifier(text))
    return item.total_length if item else None


def _role(reads: bool, writes: bool) -> str:
    if reads and writes:
        return "input/output"
    if reads:
        return "input"
    if writes:
        return "output"
    return "unused"


def _command_sentence(c: CommandUse, area: str | None) -> str | None:
    cmd = c.command
    if cmd == "LINK":
        prog = c.target_program or "another program"
        return (f"Calls {prog} with {area or 'no commarea'} (LINK); "
                "the response comes back in the same area.")
    if cmd == "XCTL":
        prog = c.target_program or "another program"
        return f"Transfers control to {prog} with {area or 'no commarea'} (XCTL); this program does not get control back."
    if cmd == "RETURN":
        if c.transid and area:
            return (f"Returns to transaction {c.transid} passing {area}; "
                    "the area is kept for the next task (pseudo-conversational).")
        if c.transid:
            return f"Returns to transaction {c.transid} without a commarea; no state is kept."
        if area:
            return f"Ends the task with {area}, but no TRANSID is given, so the next task is not defined."
        return "Ends the task (RETURN with no transaction and no commarea)."
    if cmd == "START":
        return f"Starts transaction {c.options.get('TRANSID', '?')}" + (f" with {area}." if area else ".")
    return None


def analyze_commarea(program, analyzer, data_entries, meanings: dict | None = None) -> CommareaReport:
    roots, index = build_layout(data_entries)
    commands = extract_commands(program, analyzer)

    dfh = find(index, "DFHCOMMAREA")
    scope_roots: list[DataItem] = []
    if dfh is not None and _root(dfh) not in scope_roots:
        scope_roots.append(_root(dfh))
    for c in commands:
        arg = find(index, _identifier(c.commarea))
        if arg is not None and _root(arg) not in scope_roots:
            scope_roots.append(_root(arg))

    if not commands and dfh is None:
        return CommareaReport(applicable=False, area_name=None, area_length=None, area_location=None)

    area_root = _root(dfh) if dfh is not None else (scope_roots[0] if scope_roots else None)
    report = CommareaReport(
        applicable=True,
        area_name=area_root.name if area_root else None,
        area_length=area_root.total_length if area_root else None,
        area_location=dfh.section if dfh is not None else None,
        commands=commands,
    )

    # Names that refer to commarea storage.
    scope_index: dict[str, DataItem] = {}
    for root in scope_roots:
        for item in root.walk():
            scope_index.setdefault(item.name.upper(), item)

    accesses: list[FieldAccess] = []

    # 1. Plain statements (MOVE, ADD, IF, ...).
    for para in program.paragraphs:
        for stmt, conds in walk_statements(para.statements):
            if stmt.kind == "SIMPLE" and stmt.verb == "EXEC":
                continue
            for mode, names in classify(stmt.text).items():
                for name in names:
                    item = scope_index.get(name)
                    if item is None:
                        continue
                    accesses.append(FieldAccess(
                        field=item.path, mode=mode, paragraph=para.name, line=stmt.line,
                        statement=stmt.text, conditions=list(conds), whole_area=item.parent is None,
                    ))

    # 2. EXEC CICS options that move data in or out of storage.
    for c in commands:
        arg_name = _identifier(c.commarea)
        if arg_name:
            item = scope_index.get(arg_name.upper())
            if item is not None:
                mode = {"LINK": "PASS", "XCTL": "SEND", "RETURN": "SEND", "START": "SEND",
                        "RECEIVE": "RECEIVE", "RETRIEVE": "RECEIVE"}.get(c.command, "R")
                accesses.append(FieldAccess(field=item.path, mode=mode, paragraph=c.paragraph,
                                            line=c.line, statement=c.text, conditions=c.conditions,
                                            whole_area=item.parent is None))
        for option, mode in (("INTO", "W"), ("FROM", "R"), ("RIDFLD", "R")):
            name = _identifier(c.options.get(option))
            item = scope_index.get(name.upper()) if name else None
            if item is not None:
                accesses.append(FieldAccess(field=item.path, mode=mode, paragraph=c.paragraph,
                                            line=c.line, statement=c.text, conditions=c.conditions,
                                            whole_area=item.parent is None))

    accesses.sort(key=lambda a: (a.line, a.paragraph))
    report.accesses = accesses

    # 3. Per-field summary: which paragraphs read and write each leaf.
    for root in scope_roots:
        for leaf in (x for x in root.walk() if not x.children):
            reads = [a for a in accesses if a.mode in READ_MODES and _covers(a.field, leaf.path)]
            writes = [a for a in accesses if a.mode in WRITE_MODES and _covers(a.field, leaf.path)]
            report.fields.append(FieldSummary(
                path=leaf.path, pic=leaf.pic, usage=leaf.usage, offset=leaf.offset,
                length=leaf.total_length, role=_role(bool(reads), bool(writes)),
                read_in=sorted({a.paragraph for a in reads}),
                written_in=sorted({a.paragraph for a in writes}),
                meaning=(meanings or {}).get(leaf.path, {}).get("meaning"),
                category=(meanings or {}).get(leaf.path, {}).get("category") or None,
                note_stale=bool((meanings or {}).get(leaf.path, {}).get("stale")),
            ))

    # 4. Narrative per paragraph.
    report.narratives = _narratives(program, commands, accesses, report.area_name)

    # 5. Facts used by findings and standards.
    report.transids = sorted({c.transid for c in commands if c.command in ("RETURN", "START") and c.transid})
    report.linked_programs = sorted({c.target_program for c in commands
                                     if c.command in ("LINK", "XCTL") and c.target_program})
    report.uses_channels = any(("CONTAINER" in c.options or "CHANNEL" in c.options) for c in commands)
    report.tests_eibcalen = any("EIBCALEN" in (cond or "").upper()
                                for para in program.paragraphs
                                for stmt, conds in walk_statements(para.statements)
                                for cond in list(conds) + [stmt.condition or ""])
    report.pseudo_conversational = any(
        c.command == "RETURN" and c.transid and c.commarea for c in commands)

    report.findings = _findings(report, commands, index, scope_index, dfh, area_root)
    report.standards = _standards(report, commands, dfh, area_root)
    return report


def _covers(access_path: str, leaf_path: str) -> bool:
    return leaf_path == access_path or leaf_path.startswith(access_path + ".")


def _narratives(program, commands, accesses, area_name) -> dict[str, list[str]]:
    lines: dict[str, list[tuple[int, str]]] = {}

    def describe(condition: str) -> str:
        return condition.replace(" [TRUE]", " is true").replace(" [FALSE]", " is false")

    def add(paragraph: str, line: int, text: str, conditions: list[str]) -> None:
        if conditions:
            text = f"{text} (only when {' and '.join(describe(c) for c in conditions)})"
        lines.setdefault(paragraph, []).append((line, text))

    verbs = {"R": "Reads", "W": "Sets", "RW": "Updates"}
    for a in accesses:
        if a.mode in NARRATED_ONLY_MODES:
            continue
        if a.whole_area:
            text = f"{verbs.get(a.mode, 'Uses')} the whole area {a.field}"
        else:
            text = f"{verbs.get(a.mode, 'Uses')} {a.field}"
        add(a.paragraph, a.line, text, a.conditions)

    for c in commands:
        if c.command in ("LINK", "XCTL", "RETURN", "START"):
            area = c.commarea
            sentence = _command_sentence(c, area)
            if sentence:
                add(c.paragraph, c.line, sentence, c.conditions)

    result: dict[str, list[str]] = {}
    for para, items in lines.items():
        seen: list[str] = []
        for _, text in sorted(items):
            if text not in seen:
                seen.append(text)
        result[para] = seen
    return {p.name: result[p.name] for p in program.paragraphs if p.name in result}


def _findings(report, commands, index, scope_index, dfh, area_root) -> list[Finding]:
    out: list[Finding] = []

    if dfh is not None and dfh.section.upper() != "LINKAGE":
        out.append(Finding("error", "DFHCOMMAREA_NOT_LINKAGE",
                           f"DFHCOMMAREA is declared in {dfh.section or 'an unknown section'}; "
                           "CICS passes the commarea through the LINKAGE SECTION."))

    if area_root is not None and area_root.total_length > COMMAREA_LIMIT:
        out.append(Finding("error", "COMMAREA_TOO_LARGE",
                           f"{area_root.name} is {area_root.total_length} bytes, above the "
                           f"{COMMAREA_LIMIT:,}-byte COMMAREA limit. Use channels and containers instead."))

    for c in commands:
        if not c.commarea or c.command not in ("LINK", "XCTL", "RETURN", "START"):
            if c.command in ("LINK", "XCTL") and not c.commarea:
                out.append(Finding("info", "NO_COMMAREA_PASSED",
                                   f"{c.command} at line {c.line} passes no COMMAREA.",
                                   c.paragraph, c.line))
            continue
        arg_name = _identifier(c.commarea)
        arg = find(index, arg_name)
        if arg is None:
            out.append(Finding("warning", "COMMAREA_UNDECLARED",
                               f"{c.command} at line {c.line} uses COMMAREA({c.commarea}), "
                               "which is not declared in the DATA DIVISION.", c.paragraph, c.line))
            continue
        declared = _root(arg).total_length
        if c.length_expr is None:
            out.append(Finding("info", "NO_LENGTH_OPTION",
                               f"{c.command} at line {c.line} gives no LENGTH; CICS uses the full "
                               f"length of {c.commarea} ({declared} bytes).", c.paragraph, c.line))
        else:
            given = _length_of(c.length_expr, index)
            if given is None:
                out.append(Finding("info", "LENGTH_NOT_CHECKED",
                                   f"Could not work out LENGTH({c.length_expr}) at line {c.line}.",
                                   c.paragraph, c.line))
            elif given != declared:
                out.append(Finding("warning", "LENGTH_MISMATCH",
                                   f"{c.command} at line {c.line} passes {given} bytes, but "
                                   f"{_root(arg).name} is {declared} bytes.", c.paragraph, c.line))

    if report.applicable and dfh is not None:
        touched = any(a.field.split(".")[0] == dfh.name for a in report.accesses)
        if touched and not report.tests_eibcalen:
            out.append(Finding("warning", "NO_EIBCALEN_TEST",
                               "The program uses DFHCOMMAREA but never tests EIBCALEN, so it cannot "
                               "tell a first call from a continuation."))
        reads = any(a.field.split(".")[0] == dfh.name and a.mode in READ_MODES for a in report.accesses)
        writes = any(a.field.split(".")[0] == dfh.name and a.mode in WRITE_MODES for a in report.accesses)
        if reads and not writes:
            out.append(Finding("warning", "NO_RESPONSE_WRITTEN",
                               "DFHCOMMAREA is read but never written back, so the caller gets its input unchanged."))
        if not touched:
            out.append(Finding("info", "AREA_NOT_USED",
                               "DFHCOMMAREA is declared but the procedure division never uses it."))

    if any(c.command == "RETURN" for c in report.commands) and not report.pseudo_conversational:
        out.append(Finding("info", "RETURN_WITHOUT_STATE",
                           "A RETURN passes no TRANSID and COMMAREA, so the conversation state is not kept."))

    if report.uses_channels:
        out.append(Finding("info", "CHANNELS_IN_USE",
                           "The program uses channels and containers, the modern alternative to COMMAREA."))

    for f in report.fields:
        if f.role == "output" and f.path.startswith((report.area_name or "") + "."):
            out.append(Finding("info", "FIELD_SET_NOT_READ",
                               f"{f.path} is set by the program but never read by it (output only)."))
    return out


def _standards(report, commands, dfh, area_root) -> list[StandardCheck]:
    checks: list[StandardCheck] = []

    if dfh is not None and dfh.section.upper() == "LINKAGE":
        checks.append(StandardCheck("Receive area named DFHCOMMAREA in the LINKAGE SECTION", "met",
                                    "DFHCOMMAREA is declared in the LINKAGE SECTION."))
    elif dfh is not None:
        checks.append(StandardCheck("Receive area named DFHCOMMAREA in the LINKAGE SECTION", "not met",
                                    f"DFHCOMMAREA is declared in {dfh.section or 'an unknown section'}."))
    else:
        checks.append(StandardCheck("Receive area named DFHCOMMAREA in the LINKAGE SECTION", "review",
                                    "No DFHCOMMAREA is declared; the program passes its own commarea variables."))

    if area_root is None:
        checks.append(StandardCheck("Total length within 32,767 bytes", "not applicable", "No commarea found."))
    elif area_root.total_length <= COMMAREA_LIMIT:
        checks.append(StandardCheck("Total length within 32,767 bytes", "met",
                                    f"{area_root.name} is {area_root.total_length} bytes."))
    else:
        checks.append(StandardCheck("Total length within 32,767 bytes", "not met",
                                    f"{area_root.name} is {area_root.total_length} bytes; use channels and containers."))

    with_area = [c for c in commands if c.commarea]
    if not with_area:
        checks.append(StandardCheck("LENGTH passed explicitly and matches the declared size",
                                    "not applicable", "No command passes a commarea."))
    else:
        missing = [c for c in with_area if c.length_expr is None]
        problems = [f for f in report.findings if f.code in ("LENGTH_MISMATCH",)]
        if problems:
            checks.append(StandardCheck("LENGTH passed explicitly and matches the declared size", "not met",
                                        "; ".join(f.message for f in problems)))
        elif missing:
            checks.append(StandardCheck("LENGTH passed explicitly and matches the declared size", "review",
                                        f"{len(missing)} command(s) rely on the default length."))
        else:
            checks.append(StandardCheck("LENGTH passed explicitly and matches the declared size", "met",
                                        "Every commarea command passes a LENGTH that matches."))

    returns = [c for c in commands if c.command == "RETURN"]
    if not returns:
        checks.append(StandardCheck("Pseudoconversational RETURN with TRANSID and COMMAREA",
                                    "not applicable", "The program never issues RETURN."))
    elif report.pseudo_conversational:
        checks.append(StandardCheck("Pseudoconversational RETURN with TRANSID and COMMAREA", "met",
                                    f"Returns to {', '.join(report.transids)} with a commarea."))
    else:
        checks.append(StandardCheck("Pseudoconversational RETURN with TRANSID and COMMAREA", "review",
                                    "RETURN is used, but not with both TRANSID and COMMAREA."))

    if report.area_name and dfh is not None:
        if report.tests_eibcalen:
            checks.append(StandardCheck("Tests EIBCALEN to tell first entry from a continuation", "met",
                                        "The program tests EIBCALEN."))
        else:
            checks.append(StandardCheck("Tests EIBCALEN to tell first entry from a continuation", "not met",
                                        "No condition tests EIBCALEN."))
    else:
        checks.append(StandardCheck("Tests EIBCALEN to tell first entry from a continuation",
                                    "not applicable", "No DFHCOMMAREA receive area."))

    if dfh is None:
        checks.append(StandardCheck("Bidirectional: writes the response back into the area",
                                    "not applicable", "No DFHCOMMAREA receive area."))
    else:
        written = any(f.role in ("output", "input/output") and f.path.startswith(dfh.name + ".")
                      for f in report.fields)
        if written:
            checks.append(StandardCheck("Bidirectional: writes the response back into the area", "met",
                                        "DFHCOMMAREA fields are set for the caller."))
        else:
            checks.append(StandardCheck("Bidirectional: writes the response back into the area", "not met",
                                        "No DFHCOMMAREA field is set, so the caller gets no response."))

    if area_root is None or area_root.total_length <= COMMAREA_LIMIT:
        checks.append(StandardCheck("Channels and containers for data above 32 KB", "not applicable",
                                    "The area is within the COMMAREA limit."))
    elif report.uses_channels:
        checks.append(StandardCheck("Channels and containers for data above 32 KB", "met",
                                    "Containers are used."))
    else:
        checks.append(StandardCheck("Channels and containers for data above 32 KB", "not met",
                                    "The area is over 32 KB and no containers are used."))
    return checks
