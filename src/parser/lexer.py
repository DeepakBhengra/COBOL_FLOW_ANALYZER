"""Tokenizer for normalised COBOL text."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .source_format import LogicalLine

WORD = "WORD"
NUMBER = "NUMBER"
STRING = "STRING"
PERIOD = "PERIOD"
LPAREN = "LPAREN"
RPAREN = "RPAREN"
OP = "OP"

_TOKEN_RE = re.compile(
    r"""
    (?P<STRING>'(?:[^']|'')*'|"(?:[^"]|"")*")
    |(?P<NUMBER>[+-]?\d+(?:\.\d+)?(?![A-Za-z0-9_\-]))
    |(?P<WORD>[A-Za-z0-9:][A-Za-z0-9_\-:]*)  # ':' allows copybook placeholders such as :PFX:-RESP
    |(?P<PERIOD>\.(?=\s|$))
    |(?P<LPAREN>\()
    |(?P<RPAREN>\))
    |(?P<OP><>|<=|>=|\*\*|[=<>+\-*/&])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int

    def upper(self) -> str:
        return self.value.upper()


def tokenize(lines: list[LogicalLine]) -> list[Token]:
    tokens: list[Token] = []
    for logical in lines:
        for match in _TOKEN_RE.finditer(logical.text):
            tokens.append(Token(match.lastgroup, match.group(), logical.number))
    return tokens
