"""Read one change requirement written in plain language.

Accepted forms:

    update SETATRK-ACOP-PROMO-FLG with 'Y'
    set ACOP_PROMO_FLG to Y
    MOVE 'Y' TO SETATRK-ACOP-PROMO-FLG
    set DEMO-PROMO-FLG from INP389-OPER-ID
"""
from __future__ import annotations

import re

_FIELD = r"[A-Z0-9][A-Z0-9_\-]*"
_VALUE = r"(?:'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\S+)"

_SET = re.compile(
    rf"(?:please\s+)?(?:updat(?:e|ing)|set(?:ting)?|chang(?:e|ing)|assign(?:ing)?)\s+"
    rf"({_FIELD})\s+(?:with|to|as|=|from)\s+({_VALUE})",
    re.IGNORECASE,
)
_MOVE = re.compile(
    rf"move\s+({_VALUE})\s+to\s+({_FIELD})",
    re.IGNORECASE,
)


class RequirementError(ValueError):
    pass


def parse_requirement(text: str, known_names: set[str] | None = None) -> dict:
    """Return the field to change and the value to give it.

    `known_names` are data names already found in the program or its copybooks.
    A bare word that matches one of them is kept as a sending field. Anything
    else short of a number is an alphanumeric literal.
    """
    raw = " ".join((text or "").strip().split())
    if not raw:
        raise RequirementError("The requirement is empty.")
    sentence = raw.rstrip(".")
    match = _MOVE.search(sentence) or _SET.search(sentence)
    if match is None:
        raise RequirementError(
            "The requirement must name one field and one value, for example "
            "\"update SETATRK-ACOP-PROMO-FLG with 'Y'\"."
        )
    if match.re is _MOVE:
        value_raw, field_raw = match.group(1), match.group(2)
    else:
        field_raw, value_raw = match.group(1), match.group(2)
    kind, source, shown = _value(value_raw, known_names or set())
    return {
        "raw": raw,
        "field": field_raw.upper().replace("_", "-") if "_" in field_raw and "-" not in field_raw else field_raw.upper(),
        "field_as_written": field_raw.upper(),
        "value_kind": kind,
        "source": source,
        "value": shown,
    }


def _value(raw: str, known_names: set[str]) -> tuple[str, str, str]:
    token = raw.strip().rstrip(".")
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        inner = token[1:-1].replace("''", "'").replace('""', '"')
        return "literal", "'" + inner.replace("'", "''") + "'", inner
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", token):
        return "literal", token, token
    upper = token.upper()
    cobol = upper.replace("_", "-")
    known = {name.upper() for name in known_names}
    if "-" in token or "_" in token or (cobol in known and len(cobol) > 1):
        return "field", cobol, cobol
    return "literal", "'" + token.replace("'", "''") + "'", token
