"""Lists the WORKING-STORAGE variables of a program: where each is declared, its type, its length in
bytes, its VALUE clause, and the group it belongs to.

A local variable is a WORKING-STORAGE item whose name starts with WS-. The list also covers the
other working-storage items (for example RCV-DATA-BUFFER-AREA, or the copybook records) so that the
analysis can tell a local variable apart from a field that came in from outside.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..copybooks.layout import describe
from .local_values import _initial_values, condition_names

LOCAL_PREFIX = "WS-"
WORKING_STORAGE = "WORKING-STORAGE"


@dataclass
class WorkingItem:
    name: str
    level: int
    pic: str | None
    usage: str
    type: str
    bytes: int
    occurs: int
    offset: int
    group: str | None
    initial: str | None
    is_local: bool
    is_group: bool

    def to_dict(self) -> dict:
        return asdict(self)


KEYWORDS = {
    "ADD", "ALLOW", "CALL", "COMPUTE", "CONTINUE", "ELSE", "END-EVALUATE", "END-IF", "END-PERFORM",
    "EVALUATE", "EXIT", "FROM", "GO", "IF", "INITIALIZE", "LENGTH", "MOVE", "NOT", "OF", "OR", "AND", "TO",
    "PERFORM", "SET", "SUBTRACT", "TRUE", "FALSE", "UNTIL", "WHEN", "OTHER", "THRU", "THROUGH", "USING",
    "SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "LOW-VALUE", "LOW-VALUES", "HIGH-VALUE", "HIGH-VALUES",
    "STOP", "RUN", "GOBACK", "DISPLAY", "EXEC", "CICS", "END-EXEC", "THEN", "GIVING", "ROUNDED",
}


def working_storage(analysis) -> list[WorkingItem]:
    """Every item declared in WORKING-STORAGE, in declaration order. 88-level condition names are
    included as items of kind 'Condition name' with their parent and the values that make them true."""
    initial = _initial_values(analysis.data_entries)
    items: list[WorkingItem] = []
    conditions = condition_names(analysis.data_entries)
    for root in analysis.data_roots or []:
        for item in root.walk():
            if WORKING_STORAGE not in (item.section or "").upper():
                continue
            is_group = bool(item.children)
            meta = describe(item.pic, item.usage, is_group)
            name = item.name.upper()
            value = initial.get(name)
            items.append(WorkingItem(
                name=name,
                level=item.level,
                pic=item.pic,
                usage=item.usage,
                type=meta["type_label"],
                bytes=item.total_length if is_group else item.element_length,
                occurs=item.occurs,
                offset=item.offset,
                group=item.parent.name.upper() if item.parent is not None else None,
                initial=value.text if value is not None else None,
                is_local=name.startswith(LOCAL_PREFIX),
                is_group=is_group,
            ))
    for name, (parent, values) in conditions.items():
        items.append(WorkingItem(
            name=name, level=88, pic=None, usage="", type="Condition name (88)", bytes=0, occurs=1,
            offset=0, group=parent, initial=" or ".join(f"'{v}'" for v in values) or None,
            is_local=name.startswith(LOCAL_PREFIX), is_group=False,
        ))
    return items


def condition_items(analysis) -> list[dict]:
    return [{"name": n, "parent": p, "values": v} for n, (p, v) in condition_names(analysis.data_entries).items()]


def local_variables(analysis) -> dict[str, WorkingItem]:
    """The WS- elementary items, keyed by name."""
    return {w.name: w for w in working_storage(analysis) if w.is_local and not w.is_group}


def names_in_code(text: str) -> list[str]:
    """Data-name-like words in a paragraph, ignoring string literals."""
    text = re.sub(r"'[^']*'|\"[^\"]*\"", " ", text.upper())
    return sorted({w for w in re.findall(r"[A-Z][A-Z0-9-]*[A-Z0-9]", text)})


def undeclared(analysis, names: list[str]) -> list[str]:
    """Names a paragraph uses that are not declared (paragraph names and COBOL words are skipped)."""
    declared = {w.name for w in working_storage(analysis)}
    paragraphs = set(analysis.program.paragraph_map)
    return sorted({n.upper() for n in names} - declared - paragraphs - KEYWORDS)
