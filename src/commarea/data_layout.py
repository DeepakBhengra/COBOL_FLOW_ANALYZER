"""Builds the DATA DIVISION item tree and computes storage sizes and offsets.

Sizes follow the usual IBM COBOL rules:
  DISPLAY (X, A, 9, Z, edited)  one byte per character position; V and S take none
  COMP / BINARY / COMP-5        2 bytes for 1-4 digits, 4 for 5-9, 8 for 10-18
  COMP-3 / PACKED-DECIMAL       (digits // 2) + 1 bytes
  COMP-1 / COMP-2               4 / 8 bytes
A group's size is the sum of its children (REDEFINES children add nothing); OCCURS multiplies.
"""
from __future__ import annotations

from ..parser.lexer import NUMBER, PERIOD, WORD, Token
from .models import DataItem

_CLAUSE_WORDS = {
    "USAGE", "OCCURS", "REDEFINES", "VALUE", "VALUES", "SIGN", "SYNC", "SYNCHRONIZED",
    "JUST", "JUSTIFIED", "BLANK", "EXTERNAL", "GLOBAL", "INDEXED", "BASED", "TYPE",
    "COMP", "COMP-1", "COMP-2", "COMP-3", "COMP-4", "COMP-5", "COMPUTATIONAL",
    "COMPUTATIONAL-1", "COMPUTATIONAL-2", "COMPUTATIONAL-3", "COMPUTATIONAL-4",
    "COMPUTATIONAL-5", "BINARY", "PACKED-DECIMAL", "DISPLAY", "INDEX", "POINTER",
}
_USAGE_NORMAL = {
    "COMP": "COMP", "COMPUTATIONAL": "COMP", "COMP-4": "COMP", "COMPUTATIONAL-4": "COMP",
    "COMP-5": "COMP-5", "COMPUTATIONAL-5": "COMP-5", "BINARY": "COMP",
    "COMP-3": "COMP-3", "COMPUTATIONAL-3": "COMP-3", "PACKED-DECIMAL": "COMP-3",
    "COMP-1": "COMP-1", "COMPUTATIONAL-1": "COMP-1", "COMP-2": "COMP-2", "COMPUTATIONAL-2": "COMP-2",
    "DISPLAY": "DISPLAY", "INDEX": "INDEX", "POINTER": "POINTER",
}


def _expand_picture(pic: str) -> list[tuple[str, int]]:
    """'X(3)9V9' -> [('X', 3), ('9', 1), ('V', 1), ('9', 1)]"""
    result: list[tuple[str, int]] = []
    i, n = 0, len(pic)
    while i < n:
        ch = pic[i]
        if i + 1 < n and pic[i + 1] == "(":
            close = pic.find(")", i + 2)
            if close == -1:
                count = 1
                i += 1
            else:
                count = int(pic[i + 2:close]) if pic[i + 2:close].isdigit() else 1
                i = close + 1
        else:
            count = 1
            i += 1
        result.append((ch, count))
    return result


def picture_length(pic: str | None, usage: str) -> int:
    """Storage length in bytes of one elementary item."""
    if usage == "COMP-1":
        return 4
    if usage == "COMP-2":
        return 8
    if pic is None:
        return {"INDEX": 4, "POINTER": 4}.get(usage, 0)

    expanded = _expand_picture(pic.upper())
    digits = sum(c for ch, c in expanded if ch == "9")
    if usage in ("COMP", "COMP-5"):
        if digits <= 4:
            return 2
        if digits <= 9:
            return 4
        return 8
    if usage == "COMP-3":
        return digits // 2 + 1
    # DISPLAY: count every character position except V (implied point), S (sign) and P (scale).
    return sum(c for ch, c in expanded if ch not in "VSP")


def _picture_text(tokens: list[Token], start: int) -> tuple[str, int]:
    """Join the PICTURE string beginning at tokens[start]; returns (text, next index)."""
    parts: list[str] = []
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == WORD and tok.upper() in _CLAUSE_WORDS:
            break
        if tok.kind == PERIOD:
            break
        if tok.kind in (WORD, NUMBER, "LPAREN", "RPAREN", "OP"):
            parts.append(tok.value)
        i += 1
    return "".join(parts), i


def parse_entry(section: str, tokens: list[Token]) -> DataItem | None:
    """Parse one DATA DIVISION entry. Returns None for 66 and 88 level entries."""
    if len(tokens) < 2:
        return None
    try:
        level = int(tokens[0].value)
    except ValueError:
        return None
    if level in (66, 88):
        return None

    name = "FILLER"
    i = 1
    if tokens[1].kind == WORD and tokens[1].upper() != "FILLER":
        name = tokens[1].value
        i = 2
    elif tokens[1].kind == WORD:
        i = 2

    item = DataItem(name=name, level=level, section=section, line=tokens[0].line)
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        word = tok.upper() if tok.kind == WORD else ""
        if word in ("PIC", "PICTURE"):
            i += 1
            if i < n and tokens[i].kind == WORD and tokens[i].upper() == "IS":
                i += 1
            item.pic, i = _picture_text(tokens, i)
            continue
        if word == "USAGE":
            i += 1
            if i < n and tokens[i].kind == WORD and tokens[i].upper() == "IS":
                i += 1
            if i < n and tokens[i].kind == WORD:
                item.usage = _USAGE_NORMAL.get(tokens[i].upper(), tokens[i].upper())
                i += 1
            continue
        if word in _USAGE_NORMAL:
            item.usage = _USAGE_NORMAL[word]
            i += 1
            continue
        if word == "OCCURS":
            i += 1
            if i < n and tokens[i].kind == NUMBER:
                item.occurs = int(float(tokens[i].value))
                i += 1
            # OCCURS n TO m TIMES: keep the maximum, which is what storage must hold.
            if i < n and tokens[i].upper() == "TO" and i + 1 < n and tokens[i + 1].kind == NUMBER:
                item.occurs = int(float(tokens[i + 1].value))
                i += 2
            if i < n and tokens[i].upper() == "TIMES":
                i += 1
            if i < n and tokens[i].upper() == "DEPENDING":
                i += 3  # DEPENDING ON data-name
            continue
        if word == "REDEFINES":
            i += 1
            if i < n:
                item.redefines = tokens[i].value
                i += 1
            continue
        if word in ("VALUE", "VALUES"):
            break
        i += 1
    return item


def build_layout(entries: list[tuple[str, list[Token]]]) -> tuple[list[DataItem], dict[str, DataItem]]:
    """Return (root items, name index) with children, lengths and offsets filled in."""
    roots: list[DataItem] = []
    index: dict[str, DataItem] = {}
    stack: list[DataItem] = []

    for section, tokens in entries:
        item = parse_entry(section, tokens)
        if item is None:
            continue
        while stack and stack[-1].level >= item.level:
            stack.pop()
        if stack:
            item.parent = stack[-1]
            stack[-1].children.append(item)
        else:
            roots.append(item)
        stack.append(item)
        index.setdefault(item.name.upper(), item)

    for root in roots:
        _size(root)
        _place(root, 0)
    return roots, index


def _size(item: DataItem) -> None:
    """Post-order: element_length for every item."""
    for child in item.children:
        _size(child)
    if item.children:
        item.element_length = sum(
            c.total_length for c in item.children if c.redefines is None
        )
    else:
        item.element_length = picture_length(item.pic, item.usage)


def _place(item: DataItem, start: int) -> None:
    """Pre-order: offsets relative to the root record."""
    item.offset = start
    position = start
    for child in item.children:
        if child.redefines:
            target = next((c for c in item.children if c.name.upper() == child.redefines.upper()), None)
            _place(child, target.offset if target else position)
        else:
            _place(child, position)
            position += child.total_length


def find(index: dict[str, DataItem], name: str | None) -> DataItem | None:
    if not name:
        return None
    return index.get(name.upper())
