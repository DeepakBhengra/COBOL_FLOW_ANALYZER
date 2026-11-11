"""Read a DB2 DCLGEN copybook: the declared table, its columns, and the COBOL host fields."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Column:
    name: str
    sql_type: str
    not_null: bool


@dataclass
class HostField:
    name: str
    column: str | None
    pic: str | None
    usage: str | None
    table: str | None
    copybook: str
    label: str
    sql_type: str | None
    not_null: bool


@dataclass
class TableDecl:
    table: str
    copybook: str
    label: str
    prefix: str
    columns: dict[str, Column]
    fields: dict[str, HostField]


_DECLARE = re.compile(
    r"DECLARE\s+([A-Z0-9_]+)\s+TABLE\s*\((.*?)\)\s*END-EXEC",
    re.IGNORECASE | re.DOTALL,
)
_NAMES = re.compile(r"NAMES\s*\(\s*([A-Z0-9\-]+)\s*\)", re.IGNORECASE)
_TABLE_COMMENT = re.compile(r"COBOL\s+DECLARATION\s+FOR\s+TABLE\s+([A-Z0-9_]+)", re.IGNORECASE)
_LEVEL = re.compile(r"^(\s*)(\d{2})\s+([A-Z0-9-]+)(.*)$", re.IGNORECASE)
_COMMENT_NAME = re.compile(r"^\s*\*\s*([A-Z][A-Z0-9_]*)\s*$")
_PIC = re.compile(r"\bPIC(?:TURE)?\s+([A-Z0-9(),V\-]+)", re.IGNORECASE)
_USAGE = re.compile(r"\b(?:USAGE\s+(?:IS\s+)?)?(COMP-\d|COMP|BINARY|PACKED-DECIMAL)\b", re.IGNORECASE)


def parse_dclgen(copybook: str, label: str, text: str) -> list[TableDecl]:
    """Return every table declared in this copybook. Empty when it is not a DCLGEN."""
    tables: list[TableDecl] = []
    prefix_match = _NAMES.search(text)
    prefix = prefix_match.group(1).upper() if prefix_match else ""
    for match in _DECLARE.finditer(text):
        table = match.group(1).upper()
        columns = {}
        for part in _split_commas(match.group(2)):
            piece = " ".join(part.split())
            column_match = re.match(r"([A-Z0-9_]+)\s+(.+)", piece, re.IGNORECASE)
            if column_match is None:
                continue
            name = column_match.group(1).upper()
            sql_type = column_match.group(2).strip().rstrip(".").upper()
            columns[name] = Column(name, sql_type, "NOT NULL" in sql_type)
        tables.append(TableDecl(table, copybook.upper(), label, prefix, columns, {}))

    comment_table = _TABLE_COMMENT.search(text)
    active = tables[0] if len(tables) == 1 else None
    if comment_table is not None:
        wanted = comment_table.group(1).upper()
        active = next((table for table in tables if table.table == wanted), active)
    if active is None and tables:
        active = tables[0]
    if active is None:
        return []

    pending_column: str | None = None
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        comment = _COMMENT_NAME.match(line.rstrip())
        if comment and comment.group(1).upper() in active.columns:
            pending_column = comment.group(1).upper()
            index += 1
            continue
        level = _LEVEL.match(line.rstrip())
        if level is None or level.group(2) in {"66", "88"}:
            if not line.strip().startswith("*"):
                pending_column = None
            index += 1
            continue
        blob = line
        index += 1
        while index < len(lines) and "." not in blob:
            nxt = lines[index]
            if _LEVEL.match(nxt.rstrip()) or nxt.strip().startswith("*"):
                break
            blob += " " + nxt.strip()
            index += 1
        name = level.group(3).upper()
        pic_match = _PIC.search(blob)
        usage_match = _USAGE.search(blob)
        column = pending_column if pending_column in active.columns else _column_for(name, active)
        sql = active.columns.get(column) if column else None
        active.fields[name] = HostField(
            name=name,
            column=column,
            pic=pic_match.group(1).upper() if pic_match else None,
            usage=usage_match.group(1).upper() if usage_match else None,
            table=active.table,
            copybook=active.copybook,
            label=label,
            sql_type=sql.sql_type if sql else None,
            not_null=sql.not_null if sql else False,
        )
        pending_column = None
    return tables


def picture_capacity(pic: str | None) -> int | None:
    """How many character positions a PICTURE holds. None when there is no picture."""
    if not pic:
        return None
    total = 0
    found = False
    for match in re.finditer(r"[XA9](?:\((\d+)\))?", pic.upper()):
        found = True
        total += int(match.group(1) or "1")
    return total if found else None


def _column_for(host: str, table: TableDecl) -> str | None:
    stem = host
    if table.prefix and host.startswith(table.prefix.upper()):
        stem = host[len(table.prefix):]
    column = stem.replace("-", "_")
    return column if column in table.columns else None


def _split_commas(body: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if "".join(current).strip():
        parts.append("".join(current))
    return parts
