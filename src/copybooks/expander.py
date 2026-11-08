"""Expands COPY statements in normalised COBOL lines.

Supported forms:
    COPY name.
    COPY name OF library.            (library part is ignored)
    COPY name REPLACING ==old== BY ==new== ...  .
    COPY name REPLACING word BY word ...        .
    COPY statements that span several lines.

Expansion is recursive (a copybook may COPY others). A cycle, or nesting deeper than
MAX_DEPTH, is reported and the COPY is skipped. A missing copybook is reported and the
rest of the program is still analysed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parser.source_format import LogicalLine, normalize
from .library import CopybookLibrary

MAX_DEPTH = 10
_COPY_START = re.compile(r"^\s*COPY\s+\S", re.IGNORECASE)
_ENDS_WITH_PERIOD = re.compile(r"\.\s*$")
_PAIR = re.compile(r"(==.*?==|\S+)\s+BY\s+(==.*?==|\S+)", re.IGNORECASE)


@dataclass
class CopybookUse:
    name: str
    source: str          # file name, or 'name (uploaded)'
    depth: int
    line: int            # line of the COPY statement in the file that contains it


@dataclass
class ExpansionResult:
    lines: list[LogicalLine]
    expanded: bool = False                       # True if any COPY statement was found
    used: list[CopybookUse] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class _Copy:
    name: str
    replacements: list[tuple[str, str, bool]]    # (old, new, old_is_pseudo_text)


def parse_copy_statement(text: str) -> _Copy | None:
    body = text.strip().rstrip(".").strip()
    match = re.match(r"COPY\s+(\S+)(.*)$", body, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    name = match.group(1).rstrip(".")
    rest = match.group(2).strip()
    rest = re.sub(r"^(IN|OF)\s+\S+\s*", "", rest, flags=re.IGNORECASE)

    replacements: list[tuple[str, str, bool]] = []
    replacing = re.match(r"REPLACING\s+(.*)$", rest, re.IGNORECASE | re.DOTALL)
    if replacing:
        for old, new in _PAIR.findall(replacing.group(1)):
            old_pseudo = old.startswith("==")
            new_text = new[2:-2] if new.startswith("==") else new
            old_text = old[2:-2] if old_pseudo else old
            replacements.append((old_text, new_text, old_pseudo))
    return _Copy(name=name, replacements=replacements)


def _apply_replacing(lines: list[LogicalLine], replacements: list[tuple[str, str, bool]]) -> None:
    if not replacements:
        return
    compiled = []
    for old, new, pseudo in replacements:
        if pseudo:
            compiled.append((re.compile(re.escape(old)), new))
        else:
            compiled.append((re.compile(r"(?<![A-Za-z0-9_\-])" + re.escape(old) + r"(?![A-Za-z0-9_\-])",
                                        re.IGNORECASE), new))
    for line in lines:
        for pattern, new in compiled:
            line.text = pattern.sub(lambda _m, rep=new: rep, line.text)


def expand_copybooks(lines: list[LogicalLine], library: CopybookLibrary, source_name: str) -> ExpansionResult:
    """Return the program with every COPY replaced by the copybook text."""
    if not any(_COPY_START.match(line.text) for line in lines):
        return ExpansionResult(lines=lines)

    result = ExpansionResult(lines=[], expanded=True)
    for line in lines:
        if line.origin is None:
            line.origin = f"{source_name}:{line.number}"

    def process(source: list[LogicalLine], depth: int, stack: tuple[str, ...]) -> list[LogicalLine]:
        out: list[LogicalLine] = []
        i = 0
        while i < len(source):
            current = source[i]
            if not _COPY_START.match(current.text):
                out.append(current)
                i += 1
                continue

            # A COPY statement may run over several lines until its period.
            statement = current.text
            j = i
            while not _ENDS_WITH_PERIOD.search(statement) and j + 1 < len(source):
                j += 1
                statement += " " + source[j].text.strip()
            i = j + 1

            copy = parse_copy_statement(statement)
            if copy is None:
                result.problems.append(f"{current.origin}: could not read COPY statement")
                continue

            key = copy.name.upper()
            if depth >= MAX_DEPTH:
                result.problems.append(f"{current.origin}: COPY {copy.name} is nested deeper than {MAX_DEPTH}")
                continue
            if key in stack:
                result.problems.append(f"{current.origin}: COPY {copy.name} is circular, skipped")
                continue

            found = library.resolve(copy.name)
            if found is None:
                result.missing.append(copy.name)
                result.problems.append(f"{current.origin}: copybook {copy.name} was not found")
                continue

            label, text = found
            result.used.append(CopybookUse(name=copy.name, source=label, depth=depth,
                                           line=current.number))
            body = normalize(text)
            for line in body:
                line.origin = f"{label}:{line.number}"
            body = process(body, depth + 1, stack + (key,))
            _apply_replacing(body, copy.replacements)
            out.extend(body)
        return out

    expanded = process(lines, 0, ())
    for index, line in enumerate(expanded, start=1):
        line.number = index
    result.lines = expanded
    return result
