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

import re
from dataclasses import dataclass

# A paragraph header: a name with at least one hyphen, ending with a period, optionally followed by
# EXIT. (as in "1050A-EXIT. EXIT."). Level numbers such as "05 FILLER." never match.
HEADER_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)+\.(?:\s+EXIT\.)?$")
# Words after which a name is a target, not a header: "PERFORM 1100-X" split over two lines.
TARGET_WORDS = ("PERFORM", "THRU", "THROUGH", "GO TO", "GO", "TO", "UNTIL", "VARYING")

COMMENT_INDICATORS = frozenset("*/dD")
CONTINUATION_INDICATOR = "-"


@dataclass
class LogicalLine:
    number: int  # line number in the (expanded) program text
    text: str
    origin: str | None = None  # e.g. 'CUSTCOMM.cpy:12' for lines that came from a copybook
    header: bool = False       # a paragraph header written on its own line in Area A (e.g. 1100-X.)


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

        if content.lstrip().startswith("*"):
            continue  # a comment written after the indicator column
        stripped = content.strip().upper()
        leading = len(content) - len(content.lstrip())
        previous_text = result[-1].text.strip().upper() if result else ""
        is_header = (leading <= 3 and HEADER_RE.match(stripped) is not None
                     and not previous_text.endswith(TARGET_WORDS))
        result.append(LogicalLine(number, content, header=is_header))
    return result
