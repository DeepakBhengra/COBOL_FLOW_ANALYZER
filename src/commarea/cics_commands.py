"""Finds EXEC CICS commands in the PROCEDURE DIVISION and parses their options."""
from __future__ import annotations

import re

from ..analyzer.reference_analyzer import walk_statements
from .models import CommandUse

_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|[A-Za-z0-9][A-Za-z0-9_\-]*|[()=<>+\-*/]")


def parse_exec_text(text: str) -> tuple[str, dict[str, str]] | None:
    """Parse 'EXEC CICS LINK PROGRAM ( 'X' ) COMMAREA ( A ) ...' into (command, options)."""
    tokens = _TOKEN.findall(text)
    if len(tokens) < 3 or tokens[0].upper() != "EXEC" or tokens[1].upper() != "CICS":
        return None
    command = tokens[2].upper()

    options: dict[str, str] = {}
    i = 3
    while i < len(tokens):
        tok = tokens[i]
        if tok.upper() not in ("(", ")") and i + 1 < len(tokens) and tokens[i + 1] == "(":
            name = tok.upper()
            depth = 0
            value: list[str] = []
            i += 1  # at '('
            while i < len(tokens):
                t = tokens[i]
                if t == "(":
                    depth += 1
                    if depth > 1:
                        value.append(t)
                elif t == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                    value.append(t)
                else:
                    value.append(t)
                i += 1
            options[name] = " ".join(value).replace(" ( ", "(").replace(" )", ")")
            continue
        i += 1  # flag or sub-command word, e.g. CONDITION, MAP
    return command, options


def extract_commands(program, analyzer) -> list[CommandUse]:
    """Every EXEC CICS command, with its paragraph, line and the conditions guarding it."""
    commands: list[CommandUse] = []
    for para in program.paragraphs:
        for stmt, conditions in walk_statements(para.statements):
            if stmt.kind != "SIMPLE" or stmt.verb != "EXEC":
                continue
            parsed = parse_exec_text(stmt.text)
            if parsed is None:
                continue
            command, options = parsed
            commands.append(CommandUse(
                command=command,
                paragraph=para.name,
                line=stmt.line,
                text=stmt.text,
                options=options,
                conditions=list(conditions),
            ))
    return commands
