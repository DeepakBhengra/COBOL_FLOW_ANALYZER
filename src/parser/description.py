"""The program's own description, taken from the comment block between DATE-COMPILED and REVISIONS INFO.

Many programs describe themselves in a comment box after the IDENTIFICATION DIVISION: purpose,
functions, examples, input and output. That text is the best short description of the program, so it
is kept with the analysis. Comment lines are read from the original source, because the comment
lines are dropped from the normalised text.
"""
from __future__ import annotations

import re
import textwrap

DATE_COMPILED = re.compile(r"\bDATE[- ]COMPILED\b", re.IGNORECASE)
REVISIONS = re.compile(r"REVISIONS?\s+INFO", re.IGNORECASE)
END_OF_IDENTIFICATION = re.compile(r"\b(ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.IGNORECASE)
SEPARATOR = re.compile(r"[\s*=\-+|]*")


def _body(raw: str) -> str | None:
    """The text of one comment line, or None for a line that is code."""
    line = raw.rstrip()
    if not line.strip():
        return ""
    if line.startswith("*"):
        body = line[1:]
    elif len(line) >= 7 and line[6] == "*":
        body = line[7:]
    else:
        return None
    body = re.sub(r"\s*\*+\s*$", "", body).rstrip()     # the box border on the right
    if SEPARATOR.fullmatch(body):
        return ""                                       # a ruled line or a box edge
    return body


def program_description(text: str) -> str:
    """The comment block between DATE-COMPILED and REVISIONS INFO, cleaned up. Empty if there is none."""
    lines = text.expandtabs(8).splitlines()
    start = next((i for i, line in enumerate(lines) if DATE_COMPILED.search(line)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if REVISIONS.search(lines[i])), None)
    if end is None:
        end = next((i for i in range(start + 1, len(lines)) if END_OF_IDENTIFICATION.search(lines[i])), len(lines))

    out: list[str] = []
    for raw in lines[start + 1:end]:
        body = _body(raw)
        if body is None:
            continue
        if body == "":
            if out and out[-1] != "":
                out.append("")
        else:
            out.append(body)
    while out and out[-1] == "":
        out.pop()
    return textwrap.dedent("\n".join(out)).strip("\n")
