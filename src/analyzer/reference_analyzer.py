"""Finds every place where one paragraph transfers control to another.

Each call site records the chain of conditions that must hold for it to execute.
"""
from __future__ import annotations

import re
from typing import Iterator

from ..models.flow_node import CallSite, ExternalCall
from ..models.paragraph import Statement
from ..models.program import Program


def walk_statements(statements: list[Statement],
                    conditions: tuple[str, ...] = ()) -> Iterator[tuple[Statement, tuple[str, ...]]]:
    """Yield (statement, enclosing_conditions) for every statement, depth first."""
    for stmt in statements:
        yield stmt, conditions
        for branch in stmt.branches:
            if stmt.kind == "IF":
                label = f"IF {stmt.condition} [{branch.label}]"
            elif stmt.kind == "EVALUATE":
                label = f"EVALUATE {stmt.condition} WHEN {branch.label}"
            elif stmt.kind == "PERFORM":
                label = f"LOOP {stmt.condition or ''}".strip()
            else:
                label = f"{stmt.verb} {branch.label}"
            yield from walk_statements(branch.body, conditions + (label,))


class ReferenceAnalyzer:
    def __init__(self, program: Program):
        self.program = program
        self.paragraphs = program.paragraphs
        self.names = [p.name for p in self.paragraphs]
        self.name_index = {name: i for i, name in enumerate(self.names)}
        self.section_ranges = self._section_ranges()

    def _section_ranges(self) -> dict[str, tuple[str, str]]:
        ranges: dict[str, tuple[str, str]] = {}
        for para in self.paragraphs:
            if para.section:
                first, _ = ranges.get(para.section, (para.name, para.name))
                ranges[para.section] = (first, para.name)
        return ranges

    def resolve_range(self, start: str, end: str | None = None) -> list[str]:
        """Return the paragraph names a PERFORM covers, in source order."""
        if end is None and start in self.section_ranges:
            first, last = self.section_ranges[start]
            return self.names[self.name_index[first]:self.name_index[last] + 1]
        if start not in self.name_index:
            return []
        s = self.name_index[start]
        if end and end in self.name_index:
            e = self.name_index[end]
            if e >= s:
                return self.names[s:e + 1]
        return [start]

    def call_sites(self) -> list[CallSite]:
        sites: list[CallSite] = []
        for para in self.paragraphs:
            for stmt, conds in walk_statements(para.statements):
                if stmt.kind == "PERFORM" and stmt.target:
                    loop = (f"LOOP {stmt.condition}",) if stmt.condition else ()
                    kind = "PERFORM THRU" if stmt.thru else "PERFORM"
                    for target in self.resolve_range(stmt.target, stmt.thru) or [stmt.target]:
                        sites.append(CallSite(
                            caller=para.name, target=target, kind=kind, line=stmt.line,
                            statement=stmt.text, conditions=list(conds + loop), thru=stmt.thru,
                        ))
                elif stmt.kind == "GOTO":
                    for target in stmt.targets:
                        sites.append(CallSite(
                            caller=para.name, target=target, kind="GO TO", line=stmt.line,
                            statement=stmt.text, conditions=list(conds),
                        ))
        return sites

    def external_calls(self) -> list[ExternalCall]:
        found: list[ExternalCall] = []
        for para in self.paragraphs:
            for stmt, conds in walk_statements(para.statements):
                if stmt.external_call:
                    found.append(ExternalCall(para.name, stmt.external_call, stmt.line, list(conds)))
        return found

    def occurrences(self, name: str) -> list[dict]:
        """Every line in the PROCEDURE DIVISION that mentions the name."""
        pattern = re.compile(r"(?<![A-Za-z0-9_\-])" + re.escape(name) + r"(?![A-Za-z0-9_\-])", re.IGNORECASE)
        owner_by_line = self._owner_by_line()
        results = []
        for number in sorted(self.program.source_lines):
            if number < self.program.procedure_start_line:
                continue
            text = self.program.source_lines[number]
            if pattern.search(text):
                results.append({"line": number, "paragraph": owner_by_line.get(number, ""),
                                "text": text.strip()})
        return results

    def _owner_by_line(self) -> dict[int, str]:
        owner: dict[int, str] = {}
        for para in self.paragraphs:
            for line in range(para.start_line, para.end_line + 1):
                owner[line] = para.name
        return owner
