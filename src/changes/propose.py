"""Build a possible COBOL change from a requirement and an analysis.

The module does not modify the program. It reads the paragraph flow, the SQL
statements, and the DCLGEN copybooks the program includes, then places the
change on the statement that already writes that table.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ..copybooks import CopybookLibrary
from ..models.paragraph import Paragraph, Statement
from ..pipeline import Analysis, analyze_file
from .dclgen import HostField, TableDecl, parse_dclgen, picture_capacity
from .requirement import RequirementError, parse_requirement


def open_program(path: str, copybook_dirs: list[str] | None = None) -> tuple[Analysis, CopybookLibrary]:
    """Analyse a file with the same copybook search the rest of the tool uses."""
    folder = os.path.dirname(os.path.abspath(path))
    search = [folder, os.path.join(folder, "copybooks")] + list(copybook_dirs or [])
    library = CopybookLibrary.from_environment(extra=search)
    return analyze_file(path, copybook_dirs=copybook_dirs), library


def propose_change(analysis: Analysis, requirement: str, library: CopybookLibrary) -> dict:
    """Return a proposal for `requirement`. `ok` is false when no safe place exists."""
    evidence: list[str] = []
    warnings: list[str] = []
    try:
        request = parse_requirement(requirement, _known_names(analysis))
    except RequirementError as exc:
        return _failure(str(exc), evidence)

    includes = _sql_includes(analysis)
    tables, missing_includes = _load_includes(includes, library)
    for name in missing_includes:
        evidence.append(f"EXEC SQL INCLUDE {name} is in the program, and that member is not in the copybook library.")
    if not tables and includes:
        evidence.append("None of the included members could be read as a DCLGEN table.")

    host = _resolve_field(request, tables, analysis)
    if host is None:
        evidence.append(
            f"No host variable or table column named {request['field_as_written']} "
            "was found in the included DCLGEN members or the expanded DATA DIVISION."
        )
        if tables:
            evidence.append("Tables read from included copybooks: " + ", ".join(table.table for table in tables) + ".")
        return _failure(
            f"Cannot place a change for {request['field_as_written']}: the field is not in this analysis.",
            evidence,
            request,
        )

    evidence.append(_field_evidence(host))
    if not _declared_in_program(analysis, host.name):
        evidence.append(
            f"{host.name} is not in the expanded DATA DIVISION. "
            f"EXEC SQL INCLUDE {host.copybook} is not expanded by the analyzer, "
            "so the field was read from the copybook library."
        )

    writes = _sql_writes(analysis)
    for write in writes:
        evidence.append(
            f"{write.paragraph.name} {write.kind.lower()}s {write.table} at {_origin(analysis, write.statement.line)}."
        )
    chosen = _choose_write(writes, host, request, analysis)
    if chosen is None and host.table is None:
        return _failure(
            f"{host.name} is in the program, and it is not a column of a table this program updates. "
            "A column change is placed on an existing UPDATE or INSERT.",
            evidence,
            request,
            host,
        )
    if chosen is None:
        return _failure(
            f"{host.name} belongs to {host.table}, and this program has no UPDATE or INSERT of {host.table} "
            "on which to place the change.",
            evidence,
            request,
            host,
        )

    others = [write for write in writes if write is not chosen and write.table == chosen.table and write.kind == chosen.kind]
    if others:
        warnings.append(
            "Other "
            + chosen.kind
            + " statements of "
            + chosen.table
            + " were left unchanged: "
            + ", ".join(f"{write.paragraph.name} line {write.statement.line}" for write in others)
            + "."
        )

    warnings.extend(_value_warnings(request, host))
    if request["value_kind"] == "field" and not _name_exists(analysis, library, request["source"]):
        warnings.append(f"{request['source']} is not declared in the expanded program or its COPY members.")

    built = _build(analysis, chosen, host, request)
    consequences = _consequences(analysis, library, chosen, host, request, built["change_required"])
    understood = _understood(host, request, chosen, built["change_required"])
    return {
        "ok": True,
        "change_required": built["change_required"],
        "error": None,
        "requirement": request,
        "understood": understood,
        "field": _field_dict(host),
        "placement": built["placement"],
        "edits": built["edits"],
        "proposed_paragraph": built["proposed_paragraph"],
        "diff": built["diff"],
        "consequences": consequences,
        "warnings": warnings,
        "evidence": evidence,
    }


# ---------------------------------------------------------------- program facts
def _known_names(analysis: Analysis) -> set[str]:
    names = set()
    for root in analysis.data_roots:
        for item in root.walk():
            names.add(item.name.upper())
    return names


def _declared_in_program(analysis: Analysis, name: str) -> bool:
    return name.upper() in _known_names(analysis)


def _sql_includes(analysis: Analysis) -> list[str]:
    """Members named by EXEC SQL INCLUDE. Comments and the word INCLUDE elsewhere are ignored."""
    names: list[str] = []
    seen: set[str] = set()
    inside = False
    for number in sorted(analysis.program.source_lines):
        raw = analysis.program.source_lines[number]
        if raw.lstrip().startswith("*"):
            continue
        upper = raw.upper()
        if re.search(r"\bEXEC\s+SQL\b", upper):
            inside = True
        if inside:
            match = re.search(r"\bINCLUDE\s+([A-Z0-9-]+)\b", upper)
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                names.append(match.group(1))
        if "END-EXEC" in upper:
            inside = False
    return names


def _load_includes(names: list[str], library: CopybookLibrary) -> tuple[list[TableDecl], list[str]]:
    tables: list[TableDecl] = []
    missing: list[str] = []
    for name in names:
        resolved = library.resolve(name)
        if resolved is None:
            missing.append(name)
            continue
        label, text = resolved
        tables.extend(parse_dclgen(name, label, text))
    return tables, missing


def _resolve_field(request: dict, tables: list[TableDecl], analysis: Analysis) -> HostField | None:
    written = request["field_as_written"].upper()
    hyphen = written.replace("_", "-")
    compact = re.sub(r"[-_]", "", written)
    fields = [host for table in tables for host in table.fields.values()]

    def same(host: HostField) -> bool:
        column = host.column or ""
        return written in {host.name, column} or hyphen == host.name or compact == re.sub(r"[-_]", "", column)

    matches = [host for host in fields if same(host)]
    if not matches:
        for root in analysis.data_roots:
            for item in root.walk():
                if item.name.upper() == hyphen and not item.is_group:
                    return HostField(
                        name=item.name.upper(),
                        column=None,
                        pic=item.pic,
                        usage=item.usage,
                        table=None,
                        copybook="",
                        label="",
                        sql_type=None,
                        not_null=False,
                    )
        return None
    if len(matches) == 1:
        return matches[0]
    updated = {write.table for write in _sql_writes(analysis)}
    on_updated = [host for host in matches if host.table in updated]
    return on_updated[0] if len(on_updated) == 1 else matches[0]


def _name_exists(analysis: Analysis, library: CopybookLibrary, name: str) -> bool:
    if name.upper() in _known_names(analysis):
        return True
    if analysis.copybooks is None:
        return False
    for use in analysis.copybooks.used:
        resolved = library.resolve(use.name)
        if resolved and re.search(rf"\b{re.escape(name)}\b", resolved[1], re.IGNORECASE):
            return True
    return False


@dataclass
class SetItem:
    column: str
    expression: str
    line: int
    hosts: list[str] = field(default_factory=list)


@dataclass
class SqlWrite:
    paragraph: Paragraph
    statement: Statement
    conditions: list[str]
    kind: str
    table: str
    items: list[SetItem]
    lines: list[tuple[int, str]]
    where_line: int | None


def _sql_writes(analysis: Analysis) -> list[SqlWrite]:
    found: list[SqlWrite] = []
    for paragraph in analysis.program.paragraphs:
        for statement, conditions in _walk(paragraph.statements):
            if statement.verb != "EXEC" or not statement.text.upper().startswith("EXEC SQL"):
                continue
            block = _statement_lines(analysis, statement.line)
            text = "\n".join(line for _, line in block)
            update = re.search(r"\bUPDATE\s+([A-Z0-9_]+)", text, re.IGNORECASE)
            insert = re.search(r"\bINSERT\s+INTO\s+([A-Z0-9_]+)", text, re.IGNORECASE)
            if update:
                kind, table = "UPDATE", update.group(1).upper()
            elif insert:
                kind, table = "INSERT", insert.group(1).upper()
            else:
                continue
            items, where_line = _set_items(block)
            found.append(SqlWrite(paragraph, statement, conditions, kind, table, items, block, where_line))
    return found


def _walk(statements: list[Statement], conditions: list[str] | None = None):
    conditions = list(conditions or [])
    for statement in statements:
        yield statement, conditions
        for branch in statement.branches:
            label = branch.label
            if statement.kind == "IF":
                label = f"IF {statement.condition} [{branch.label}]"
            elif statement.kind == "EVALUATE":
                label = f"EVALUATE {label}"
            yield from _walk(branch.body, conditions + [label])


def _statement_lines(analysis: Analysis, start: int) -> list[tuple[int, str]]:
    lines = analysis.program.source_lines
    block = []
    for number in range(start, start + 80):
        if number not in lines:
            break
        block.append((number, lines[number]))
        if "END-EXEC" in lines[number].upper():
            break
    return block


def _set_items(block: list[tuple[int, str]]) -> tuple[list[SetItem], int | None]:
    items: list[SetItem] = []
    seen_set = False
    where_line = None
    for number, raw in block:
        if raw.lstrip().startswith("*"):
            continue
        upper = raw.upper()
        if not seen_set:
            if re.search(r"\bSET\b", upper):
                seen_set = True
            else:
                continue
        if re.search(r"\bWHERE\b", upper):
            where_line = number
            break
        match = re.search(r"(?:SET\s+|,)\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", raw, re.IGNORECASE)
        if match is None:
            continue
        expression = match.group(2).rstrip().rstrip(",")
        items.append(SetItem(
            column=match.group(1).upper(),
            expression=expression,
            line=number,
            hosts=re.findall(r":([A-Z0-9-]+)", expression, re.IGNORECASE),
        ))
    return items, where_line


def _choose_write(writes: list[SqlWrite], host: HostField, request: dict, analysis: Analysis) -> SqlWrite | None:
    if host.table is None:
        return None
    candidates = [write for write in writes if write.table == host.table]
    if not candidates:
        return None
    verb = request["raw"].split()[0].lower()
    updates = [write for write in candidates if write.kind == "UPDATE"]
    if verb.startswith("updat") and updates:
        candidates = updates
    reachable = {name for name, status in analysis.statuses.items() if status.reachable}

    def rank(write: SqlWrite) -> tuple:
        hosts = {name.upper() for item in write.items for name in item.hosts}
        return (
            int(bool(host.column) and host.column in {item.column for item in write.items}),
            int(host.name in hosts),
            int(write.paragraph.name in reachable),
            len(hosts),
            -write.statement.line,
        )

    return max(candidates, key=rank)


# ---------------------------------------------------------------- placement
def _build(analysis: Analysis, write: SqlWrite, host: HostField, request: dict) -> dict:
    moves = _feeding_moves(write)
    existing = _existing_assignment(write, host, moves)
    placement = _placement(analysis, write, existing)
    if write.kind == "INSERT":
        return _insert_proposal(analysis, write, host, request, moves, placement)
    if existing["column_item"] is not None and existing["move"] is not None:
        return _replace_move(analysis, write, host, request, existing, placement)
    return _extend_update(analysis, write, host, request, moves, existing, placement)


def _feeding_moves(write: SqlWrite) -> list[dict]:
    hosts: set[str] = set()
    for _, raw in write.lines:
        hosts.update(name.upper() for name in re.findall(r":([A-Z0-9-]+)", raw))
    moves = []
    for statement, conditions in _walk(write.paragraph.statements):
        if statement.verb != "MOVE" or statement.line >= write.statement.line:
            continue
        if conditions != write.conditions:
            continue
        parsed = _parse_move(statement.text)
        if parsed is None:
            continue
        source, targets = parsed
        for target in targets:
            moves.append({
                "line": statement.line,
                "source": source,
                "target": target,
                "text": statement.text,
                "feeds_sql": target in hosts,
            })
    return moves


def _parse_move(text: str) -> tuple[str, list[str]] | None:
    match = re.match(r"MOVE\s+(.+?)\s+TO\s+(.+)$", text.strip(), re.IGNORECASE)
    if match is None:
        return None
    targets = re.findall(r"[A-Z0-9-]+", match.group(2), re.IGNORECASE)
    return match.group(1).strip(), [target.upper() for target in targets]


def _existing_assignment(write: SqlWrite, host: HostField, moves: list[dict]) -> dict:
    column_item = next((item for item in write.items if host.column and item.column == host.column), None)
    host_moves = [move for move in moves if move["target"] == host.name and move["line"] < write.statement.line]
    move = host_moves[-1] if host_moves else None
    return {"column_item": column_item, "move": move}


def _placement(analysis: Analysis, write: SqlWrite, existing: dict) -> dict:
    status = analysis.statuses.get(write.paragraph.name)
    callers = []
    for site in analysis.call_sites:
        if site.target == write.paragraph.name:
            condition = f" when {' and '.join(site.conditions)}" if site.conditions else " with no condition"
            callers.append(f"{site.caller} {site.kind}{condition}")
    why = (
        f"This is the {write.kind} of {write.table} reached from the analyzed flow. "
        "The host variables it uses are moved in this paragraph before the SQL statement."
    )
    if callers:
        why += " Called from " + "; ".join(callers) + "."
    return {
        "paragraph": write.paragraph.name,
        "kind": write.kind,
        "table": write.table,
        "line": write.statement.line,
        "origin": _origin(analysis, write.statement.line),
        "reachable": bool(status and status.reachable),
        "conditions": write.conditions,
        "why": why,
        "existing_move": existing["move"]["text"] if existing["move"] else None,
        "existing_column": existing["column_item"].column if existing["column_item"] else None,
    }


def _extend_update(analysis, write, host, request, moves, existing, placement) -> dict:
    anchor = _anchor_move(moves, write)
    set_template, set_anchor = _set_template(write)
    move_text = _render_move(analysis, anchor, request["source"], host.name) if anchor else _plain_move(request, host)
    set_text = None
    edits = []
    if existing["column_item"] is None:
        if set_template is None or host.column is None:
            return _unplaced(placement, "The UPDATE was found, but its SET clause could not be read from the source lines.")
        set_text = _render_set(set_template, host.column, host.name)
    if existing["move"] is None:
        edits.append({
            "kind": "insert_after" if anchor else "insert_before",
            "line": anchor["line"] if anchor else write.statement.line,
            "origin": _origin(analysis, anchor["line"] if anchor else write.statement.line),
            "anchor": anchor["text"] if anchor else write.statement.text,
            "text": move_text,
            "reason": "The other values used by this SQL statement are moved immediately before it.",
        })
    elif not _values_match(existing["move"]["source"], request):
        edits.append(_replace_edit(analysis, existing["move"], move_text, "A move into this host variable is already here."))
    if set_text is not None:
        edits.append({
            "kind": "insert_before",
            "line": write.where_line or write.lines[-1][0],
            "origin": _origin(analysis, write.where_line or write.lines[-1][0]),
            "anchor": analysis.program.source_lines.get(write.where_line or write.lines[-1][0], "").strip(),
            "text": set_text,
            "reason": f"Add {host.column} to the same SET list. The WHERE clause stays as it is.",
        })
    proposed, diff = _apply(analysis, write.paragraph, edits)
    return {
        "change_required": bool(edits),
        "placement": placement,
        "edits": edits,
        "proposed_paragraph": proposed,
        "diff": diff,
    }


def _replace_move(analysis, write, host, request, existing, placement) -> dict:
    if _values_match(existing["move"]["source"], request):
        return {"change_required": False, "placement": placement, "edits": [], "proposed_paragraph": None, "diff": []}
    move_text = _render_move(analysis, existing["move"], request["source"], host.name)
    edits = [_replace_edit(
        analysis,
        existing["move"],
        move_text,
        f"{host.column} is already set from {host.name}. Only the value moved into that host variable changes.",
    )]
    proposed, diff = _apply(analysis, write.paragraph, edits)
    return {"change_required": True, "placement": placement, "edits": edits, "proposed_paragraph": proposed, "diff": diff}


def _insert_proposal(analysis, write, host, request, moves, placement) -> dict:
    anchor = _anchor_move(moves, write)
    move_text = _render_move(analysis, anchor, request["source"], host.name) if anchor else _plain_move(request, host)
    edits = [{
        "kind": "insert_after" if anchor else "insert_before",
        "line": anchor["line"] if anchor else write.statement.line,
        "origin": _origin(analysis, anchor["line"] if anchor else write.statement.line),
        "anchor": anchor["text"] if anchor else write.statement.text,
        "text": move_text,
        "reason": "Move the new value before the INSERT. The column list itself was not rewritten.",
    }]
    proposed, diff = _apply(analysis, write.paragraph, edits)
    placement["why"] += " The INSERT column list still has to name this column; that layout was not rewritten automatically."
    return {"change_required": True, "placement": placement, "edits": edits, "proposed_paragraph": proposed, "diff": diff}


def _unplaced(placement, message) -> dict:
    placement["why"] = message
    return {"change_required": False, "placement": placement, "edits": [], "proposed_paragraph": None, "diff": []}


def _anchor_move(moves: list[dict], write: SqlWrite) -> dict | None:
    feeding = [move for move in moves if move["feeds_sql"]]
    pool = feeding or moves
    return pool[-1] if pool else None


def _set_template(write: SqlWrite) -> tuple[str | None, int | None]:
    comma = None
    first = None
    for number, raw in write.lines:
        if write.where_line is not None and number >= write.where_line:
            break
        if re.search(r"^\s*,\s*[A-Z0-9_]+\s*=", raw, re.IGNORECASE):
            comma = (raw.rstrip(), number)
        elif re.search(r"\bSET\s+[A-Z0-9_]+\s*=", raw, re.IGNORECASE):
            first = (raw.rstrip(), number)
    chosen = comma or first
    return (chosen[0], chosen[1]) if chosen else (None, None)


def _render_move(analysis: Analysis, anchor: dict, source: str, target: str) -> str:
    raw = analysis.program.source_lines.get(anchor["line"], "")
    match = re.match(r"^(\s*)MOVE(\s+)(\S+)(\s+)TO(\s+)\S+\.?\s*$", raw, re.IGNORECASE)
    if match is None:
        return _plain_move({"source": source}, type("H", (), {"name": target})())
    indent, gap, _old, between, after_to = match.groups()
    prefix = f"{indent}MOVE{gap}{source}"
    to_at = len(f"{indent}MOVE{gap}{_old}{between}")
    if len(prefix) + 1 < to_at:
        prefix += " " * (to_at - len(prefix))
    else:
        prefix += " "
    return f"{prefix}TO{after_to}{target}."


def _plain_move(request, host) -> str:
    return f"           MOVE {request['source']} TO {host.name}."


def _render_set(template: str, column: str, host: str) -> str:
    equals = template.find("=")
    stripped = template.lstrip()
    if stripped.upper().startswith("SET "):
        name = re.search(r"SET\s+([A-Z0-9_]+)", template, re.IGNORECASE)
        name_at = name.start(1) if name else len(template) - len(stripped)
        prefix = " " * name_at + ","
    else:
        comma = re.match(r"^(\s*,\s*)", template)
        prefix = comma.group(1) if comma else " " * (len(template) - len(stripped)) + ","
    expression = ":" + host
    head = prefix + column
    if equals > len(head) + 1:
        head += " " * (equals - len(head))
    else:
        head += " "
    # Keep a single space after '=' when the template has one, otherwise the template's gap.
    after = template[equals + 1:] if equals >= 0 else " "
    gap = re.match(r"\s*", after).group(0) or " "
    return head + "=" + gap + expression


def _replace_edit(analysis, move, text, reason) -> dict:
    return {
        "kind": "replace_line",
        "line": move["line"],
        "origin": _origin(analysis, move["line"]),
        "anchor": move["text"],
        "text": text,
        "reason": reason,
    }


def _values_match(source: str, request: dict) -> bool:
    return source.upper().replace(" ", "") == request["source"].upper().replace(" ", "")


def _apply(analysis: Analysis, paragraph: Paragraph, edits: list[dict]) -> tuple[str | None, list[str]]:
    if not edits:
        return None, []
    by_line: dict[int, list[dict]] = {}
    for edit in edits:
        by_line.setdefault(edit["line"], []).append(edit)
    output: list[str] = []
    diff: list[str] = []
    for number in range(paragraph.start_line, paragraph.end_line + 1):
        raw = analysis.program.source_lines.get(number)
        if raw is None:
            continue
        for edit in by_line.get(number, []):
            if edit["kind"] == "insert_before":
                output.append(edit["text"])
                diff.append("+ " + edit["text"])
        replaced = next((edit for edit in by_line.get(number, []) if edit["kind"] == "replace_line"), None)
        if replaced:
            output.append(replaced["text"])
            diff.append("- " + raw.rstrip())
            diff.append("+ " + replaced["text"])
        else:
            output.append(raw.rstrip())
            diff.append("  " + raw.rstrip())
        for edit in by_line.get(number, []):
            if edit["kind"] == "insert_after":
                output.append(edit["text"])
                diff.append("+ " + edit["text"])
    return "\n".join(output), diff


# ---------------------------------------------------------------- wording
def _understood(host: HostField, request: dict, write: SqlWrite, change_required: bool) -> str:
    value = request["source"]
    if not change_required:
        return (
            f"{host.name} is already given {value} on the {write.kind} of {write.table} "
            f"in {write.paragraph.name}. No code change is required."
        )
    column = f" column {host.column}" if host.column else ""
    return (
        f"Give {host.name} the value {value} and write it to {write.table}{column} "
        f"in {write.paragraph.name}, which already updates that table."
    )


def _consequences(analysis, library, write, host, request, change_required) -> list[str]:
    if not change_required:
        return ["The current statement already does what the requirement asks."]
    notes = []
    status = analysis.statuses.get(write.paragraph.name)
    entry = analysis.program.entry_paragraph
    if status and status.reachable and entry is not None:
        notes.append(
            f"{write.paragraph.name} is on the path from {entry.name}, "
            f"so a normal run of {analysis.program.name} applies this change."
        )
    notes.append(
        f"The WHERE clause is unchanged. The row is still selected exactly as {write.paragraph.name} selects it today."
    )
    upper = write.paragraph.source_text.upper()
    if "SQLCODE-NOT-FOUND" in upper and "CONTINUE" in upper:
        notes.append("SQL code +100 is still treated as success. A missing row is not updated, so the new value is not written in that case.")
    if "ABEND" in upper or "999-ABEND" in upper:
        notes.append("Any other SQL code still follows the existing error path in this paragraph.")
    if request["value_kind"] == "literal":
        token = _stem(host.column or host.name)
        similar = _similar_fields(analysis, library, token, host.name)
        if similar:
            notes.append("A copied field could have supplied this value, and this proposal uses the literal instead: " + "; ".join(similar) + ".")
        else:
            notes.append("No copied input field carries this value, so the proposal uses a literal.")
    if host.not_null:
        notes.append(f"{host.column} is NOT NULL. {request['source']} is a value, so the column is not left empty.")
    notes.append("This is a proposal. The source file was not changed.")
    return notes


def _value_warnings(request: dict, host: HostField) -> list[str]:
    if request["value_kind"] != "literal":
        return []
    warnings = []
    capacity = picture_capacity(host.pic)
    if capacity is not None and len(request["value"]) > capacity:
        warnings.append(
            f"{request['source']} is {len(request['value'])} characters and {host.name} is PIC {host.pic} ({capacity})."
        )
    if host.pic and re.search(r"[9S]", host.pic.upper()) and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", request["value"]):
        warnings.append(f"{host.name} is numeric (PIC {host.pic}) and {request['source']} is not a number.")
    char = re.search(r"CHAR\s*\(\s*(\d+)\s*\)", host.sql_type or "", re.IGNORECASE)
    if char and len(request["value"]) > int(char.group(1)):
        warnings.append(f"{host.column} is {host.sql_type}, which is shorter than {request['source']}.")
    return warnings


def _similar_fields(analysis, library, token: str, host_name: str) -> list[str]:
    if not token or len(token) < 4 or analysis.copybooks is None:
        return []
    found = []
    for use in analysis.copybooks.used:
        resolved = library.resolve(use.name)
        if resolved is None:
            continue
        for match in re.finditer(r"\b([A-Z0-9-]*" + re.escape(token) + r"[A-Z0-9-]*)\b", resolved[1].upper()):
            name = match.group(1)
            if name != host_name and name not in found:
                found.append(f"{use.name}.{name}")
    return found[:6]


def _stem(name: str) -> str:
    parts = re.split(r"[-_]", name.upper())
    skip = {"SETATRK", "ACOP", "FLG", "FLAG", "CD", "NBR", "ID", "SW"}
    meaningful = [part for part in parts if part not in skip and len(part) >= 4]
    return meaningful[-1] if meaningful else ""


def _field_dict(host: HostField) -> dict:
    return {
        "name": host.name,
        "column": host.column,
        "table": host.table,
        "pic": host.pic,
        "usage": host.usage,
        "sql_type": host.sql_type,
        "not_null": host.not_null,
        "copybook": host.copybook,
        "copybook_label": host.label,
    }


def _field_evidence(host: HostField) -> str:
    pic = f" PIC {host.pic}" if host.pic else ""
    usage = f" {host.usage}" if host.usage else ""
    column = f", column {host.column} {host.sql_type}" if host.column else ", with no DB2 column"
    return f"{host.name}{pic}{usage} is declared in {host.label or host.copybook}{column}."


def _origin(analysis: Analysis, line: int) -> str:
    return analysis.program.line_origin.get(line) or f"{analysis.program.source_name}:{line}"


def _failure(error: str, evidence: list[str], request: dict | None = None, host: HostField | None = None) -> dict:
    return {
        "ok": False,
        "change_required": False,
        "error": error,
        "requirement": request,
        "understood": error,
        "field": _field_dict(host) if host else None,
        "placement": None,
        "edits": [],
        "proposed_paragraph": None,
        "diff": [],
        "consequences": [],
        "warnings": [],
        "evidence": evidence,
    }
