"""Works out which data names a COBOL statement reads and writes.

This is a verb-by-verb heuristic over the statement text. It is accurate for the common
forms (MOVE, ADD, SUBTRACT, COMPUTE, IF conditions, STRING/UNSTRING INTO, CALL USING, ...).
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|[A-Za-z0-9][A-Za-z0-9_\-]*|[=<>+\-*/()]")
_STOP = {"TO", "FROM", "GIVING", "INTO", "BY", "USING", "OF", "IN", "ROUNDED", "ON", "SIZE",
         "ERROR", "NOT", "END-IF", "END-EVALUATE", "AND", "OR", "THEN", "ELSE", "SPACES",
         "ZEROS", "ZERO", "LOW-VALUES", "HIGH-VALUES", "SPACE", "ZEROES", "CORRESPONDING"}


def words(text: str | None) -> list[str]:
    """Upper-cased tokens with literals removed."""
    if not text:
        return []
    return [t.upper() for t in _TOKEN.findall(text) if not t[0] in "'\""]


def _names(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _STOP and t[0].isalpha()]


def classify(statement_text: str, condition: str | None = None) -> dict[str, set[str]]:
    """Return {'R': names read, 'W': names written, 'RW': names read and written}."""
    result = {"R": set(), "W": set(), "RW": set()}
    toks = words(statement_text)
    if not toks:
        return result
    verb, args = toks[0], toks[1:]

    def add(mode: str, names: list[str]) -> None:
        for name in _names(names):
            result[mode].add(name)

    if verb == "MOVE":
        if "TO" in args:
            t = args.index("TO")
            add("R", args[:t])
            add("W", args[t + 1:])
        else:
            add("R", args)

    elif verb == "ADD":
        if "TO" in args:
            t = args.index("TO")
            add("R", args[:t])
            after = args[t + 1:]
            if "GIVING" in after:
                g = after.index("GIVING")
                add("R", after[:g])
                add("W", after[g + 1:])
            else:
                add("RW", after)
        else:
            add("R", args)

    elif verb in ("SUBTRACT", "MULTIPLY"):
        marker = "FROM" if verb == "SUBTRACT" else "BY"
        if marker in args:
            m = args.index(marker)
            add("R", args[:m])
            after = args[m + 1:]
            if "GIVING" in after:
                g = after.index("GIVING")
                add("R", after[:g])
                add("W", after[g + 1:])
            else:
                add("RW", after)
        else:
            add("R", args)

    elif verb == "DIVIDE":
        if "INTO" in args:
            i = args.index("INTO")
            add("R", args[:i])
            after = args[i + 1:]
            if "GIVING" in after:
                g = after.index("GIVING")
                add("R", after[:g])
                add("W", after[g + 1:])
            else:
                add("RW", after)
        else:
            if "GIVING" in args:
                g = args.index("GIVING")
                add("R", args[:g])
                add("W", args[g + 1:])
            else:
                add("R", args)

    elif verb == "COMPUTE":
        target = args[0] if args else None
        rest = args[1:]
        if "=" in rest:
            rest = rest[rest.index("=") + 1:]
        if target and target[0].isalpha():
            add("W", [target])
        add("R", rest)

    elif verb == "STRING":
        if "INTO" in args:
            i = args.index("INTO")
            add("R", args[:i])
            add("W", args[i + 1:i + 2])
        else:
            add("R", args)

    elif verb == "UNSTRING":
        if "INTO" in args:
            i = args.index("INTO")
            add("R", args[:i])
            add("W", args[i + 1:])
        else:
            add("R", args)

    elif verb == "INITIALIZE":
        add("W", args)

    elif verb == "SET":
        if "TO" in args:
            t = args.index("TO")
            add("W", args[:t])
            add("R", args[t + 1:])
        else:
            add("RW", args[:1])
            add("R", args[1:])

    elif verb == "ACCEPT":
        add("W", args[:1])

    elif verb in ("READ", "RETURN"):
        if "INTO" in args:
            i = args.index("INTO")
            add("R", args[:i])
            add("W", args[i + 1:i + 2])
        else:
            add("R", args)

    elif verb in ("WRITE", "REWRITE", "DISPLAY"):
        if "FROM" in args:
            i = args.index("FROM")
            add("R", args[:i] + args[i + 1:i + 2])
        else:
            add("R", args)

    elif verb == "CALL":
        if "USING" in args:
            u = args.index("USING")
            mode = "R"
            for tok in args[u + 1:]:
                if tok in ("CONTENT", "VALUE"):
                    mode = "R"
                elif tok == "REFERENCE":
                    mode = "RW"
                elif tok[0].isalpha():
                    add(mode, [tok])
                    mode = "RW"
        return _with_condition(result, condition)

    else:
        add("R", args)

    return _with_condition(result, condition)


def _with_condition(result: dict[str, set[str]], condition: str | None) -> dict[str, set[str]]:
    if condition:
        for name in _names(words(condition)):
            result["R"].add(name)
    return result
