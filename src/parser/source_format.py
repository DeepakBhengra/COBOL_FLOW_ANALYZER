"""Fixed-format (and free-format fallback) COBOL source normalisation.

Fixed format layout:
    columns 1-6   sequence area (ignored)
    column  7     indicator: ' ' normal, '*' or '/' comment, '-' continuation,
                  'D'/'d' debugging line (treated as comment)
    columns 8-72  program text
    columns 73+   identification area (ignored)

Lines that do not carry a valid sequence/indicator layout are treated as
free-format text and kept whole.
"""
from __future__ import annotations

from dataclasses import dataclass

COMMENT_INDICATORS = frozenset("*/dD")
CONTINUATION_INDICATOR = "-"


@dataclass
class LogicalLine:
    number: int  # line number in the (expanded) program text
    text: str
    origin: str | None = None  # e.g. 'CUSTCOMM.cpy:12' for lines that came from a copybook


def _is_fixed_layout(raw: str) -> bool:
    if len(raw) < 7:
        return False
    seq = raw[:6].strip()
    return (seq == "" or seq.isdigit()) and raw[6] in (" ",) + tuple(COMMENT_INDICATORS) + (CONTINUATION_INDICATOR,)


def normalize(source: str) -> list[LogicalLine]:
    """Return the program text with sequence numbers, comments and continuations resolved."""
    result: list[LogicalLine] = []
    for number, raw in enumerate(source.expandtabs(8).splitlines(), start=1):
        if raw.startswith("*"):
            continue  # legacy comment line with the asterisk in column 1
        if not _is_fixed_layout(raw):
            result.append(LogicalLine(number, raw))
            continue

        indicator = raw[6]
        content = raw[7:72]

        if indicator in COMMENT_INDICATORS:
            continue

        if indicator == CONTINUATION_INDICATOR and result:
            previous = result[-1]
            stripped = content.lstrip()
            # Inside a literal the continuation line restarts with a quote.
            if stripped[:1] in ("'", '"'):
                previous.text = previous.text + stripped[1:]
            else:
                previous.text = previous.text.rstrip() + " " + stripped
            continue

        result.append(LogicalLine(number, content))
    return result
