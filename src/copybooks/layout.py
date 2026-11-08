"""Lays out one copybook: every field with its level, path, PICTURE, USAGE, type, offset,
length, OCCURS, REDEFINES and 88-level condition names.

Works on a copybook on its own (no DATA DIVISION header needed), so it can be shown in the UI
before any program uses it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..commarea.data_layout import _expand_picture, build_layout
from ..parser.lexer import NUMBER, PERIOD, WORD, tokenize
from ..parser.source_format import normalize

CATEGORIES = [
    "Identifier", "Amount", "Date / time", "Code / flag", "Status", "Counter",
    "Message / text", "Filler / reserved", "Group / record", "Other",
]


@dataclass
class ConditionName:
    name: str
    values: str
    line: int


@dataclass
class LayoutItem:
    path: str                 # unique, dotted, e.g. CUSTCOMM.CUST-NAME
    name: str
    level: int
    depth: int
    pic: str | None
    usage: str
    occurs: int
    redefines: str | None
    offset: int
    length: int               # bytes for the item including OCCURS
    element_length: int
    line: int                 # line in the copybook file
    is_group: bool
    type_label: str
    digits: int | None
    decimals: int | None
    signed: bool | None
    conditions: list[ConditionName] = field(default_factory=list)


@dataclass
class CopybookLayout:
    name: str
    fingerprint: str
    items: list[LayoutItem] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    has_data: bool = False

    @property
    def total_length(self) -> int:
        return sum(i.length for i in self.items if i.depth == 0 and not i.redefines)

    @property
    def line_to_path(self) -> dict[int, str]:
        return {i.line: i.path for i in self.items}


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def describe(pic: str | None, usage: str, is_group: bool) -> dict:
    """Plain-language type for a field: what the PICTURE and USAGE mean."""
    if is_group:
        return {"type_label": "Group", "digits": None, "decimals": None, "signed": None}
    if usage == "COMP-1":
        return {"type_label": "Floating point, single precision (COMP-1)", "digits": None,
                "decimals": None, "signed": True}
    if usage == "COMP-2":
        return {"type_label": "Floating point, double precision (COMP-2)", "digits": None,
                "decimals": None, "signed": True}
    if usage in ("INDEX", "POINTER"):
        return {"type_label": usage.title(), "digits": None, "decimals": None, "signed": None}

    p = (pic or "").upper()
    expanded = _expand_picture(p) if p else []
    digits = decimals = 0
    after_point = False
    for ch, count in expanded:
        if ch == "V":
            after_point = True
        elif ch == "9":
            digits += count
            if after_point:
                decimals += count
    signed = p.startswith("S") if p else None
    chars = {ch for ch, _ in expanded}

    if usage == "COMP-3":
        label = "Packed decimal (COMP-3)"
    elif usage in ("COMP", "COMP-5", "COMP-4"):
        label = f"Binary integer ({usage})"
    elif chars and chars <= {"X"}:
        label = "Alphanumeric"
    elif chars and chars <= {"A"}:
        label = "Alphabetic"
    elif chars and chars <= {"9", "V", "S", "P"}:
        label = "Zoned decimal (DISPLAY)"
    elif chars:
        label = "Edited (DISPLAY)"
    else:
        label = "No PICTURE"
    return {"type_label": label, "digits": digits or None, "decimals": decimals or None, "signed": signed}


def _split_sentences(tokens):
    sentences, current = [], []
    for tok in tokens:
        if tok.kind == PERIOD:
            if current:
                sentences.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        sentences.append(current)
    return sentences


def layout_of_copybook(name: str, text: str) -> CopybookLayout:
    layout = CopybookLayout(name=name, fingerprint=fingerprint(text))
    sentences = _split_sentences(tokenize(normalize(text)))

    entries = []
    condition_sentences = []
    for sentence in sentences:
        if not sentence or sentence[0].kind != NUMBER:
            continue
        level = sentence[0].value.lstrip("0") or "0"
        if level == "88":
            condition_sentences.append(sentence)
        elif level == "66":
            continue
        else:
            entries.append(("", sentence))
    layout.has_data = bool(entries)
    if not entries:
        return layout

    roots, _ = build_layout(entries)
    layout.roots = [r.name for r in roots]

    # Top-level entries in a copybook are laid out one after another from its start.
    def shift(item, delta):
        item.offset += delta
        for child in item.children:
            shift(child, delta)

    position = 0
    for root in roots:
        if root.redefines:
            # A record that REDEFINES another starts where that record starts.
            target = next((r for r in roots if r.name.upper() == root.redefines.upper()), None)
            start = target.offset if target is not None else position
            shift(root, start - root.offset)
        else:
            shift(root, position - root.offset)
            position += root.total_length

    # Flatten the tree in declaration order with unique paths.
    flat = []

    def visit(item, parent_path, depth):
        if parent_path is None:
            path = item.name
        else:
            base = f"{parent_path}.{item.name}"
            path = base
        flat.append((item, path, depth))
        for child in item.children:
            visit(child, path, depth + 1)

    for root in roots:
        visit(root, None, 0)

    seen: dict[str, int] = {}
    unique_paths = {}
    for item, path, depth in flat:
        count = seen.get(path, 0) + 1
        seen[path] = count
        unique_paths[id(item)] = path if count == 1 else f"{path}#{count}"

    items: list[LayoutItem] = []
    for item, _, depth in flat:
        meta = describe(item.pic, item.usage, item.is_group)
        if item.pic is None and not item.children and item.usage == "DISPLAY":
            layout.problems.append(f"line {item.line}: {item.name} has no PICTURE clause")
        items.append(LayoutItem(
            path=unique_paths[id(item)],
            name=item.name,
            level=item.level,
            depth=depth,
            pic=item.pic,
            usage=item.usage,
            occurs=item.occurs,
            redefines=item.redefines,
            offset=item.offset,
            length=item.total_length,
            element_length=item.element_length,
            line=item.line,
            is_group=item.is_group,
            type_label=meta["type_label"],
            digits=meta["digits"],
            decimals=meta["decimals"],
            signed=meta["signed"],
        ))

    # Attach each 88-level condition name to the nearest item above it.
    by_line = sorted(items, key=lambda i: i.line)
    for sentence in condition_sentences:
        line = sentence[0].line
        owners = [i for i in by_line if i.line < line]
        if not owners or len(sentence) < 2:
            layout.problems.append(f"line {line}: condition name has no parent field")
            continue
        values = []
        tokens = sentence[2:]
        if tokens and tokens[0].kind == WORD and tokens[0].upper() in ("VALUE", "VALUES"):
            tokens = tokens[1:]
        values = " ".join(t.value for t in tokens)
        owners[-1].conditions.append(ConditionName(name=sentence[1].value, values=values, line=line))

    layout.items = items
    return layout
