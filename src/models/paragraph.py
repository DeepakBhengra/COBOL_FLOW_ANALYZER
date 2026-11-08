"""Paragraph and statement tree models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Branch:
    """One alternative of a conditional construct (IF TRUE, WHEN x, AT END, ...)."""
    label: str
    body: list["Statement"] = field(default_factory=list)


@dataclass
class Statement:
    """A statement in a paragraph.

    kind values:
      SIMPLE     - any ordinary statement (MOVE, DISPLAY, READ ... with optional clauses)
      IF         - IF / ELSE with branches TRUE and FALSE
      EVALUATE   - EVALUATE with one branch per WHEN
      PERFORM    - out-of-line PERFORM (target set) or inline PERFORM (branches[0] is the body)
      GOTO       - GO TO (targets set)
      TERMINATE  - STOP RUN, GOBACK, EXIT PROGRAM
      EXIT_PARA  - EXIT PARAGRAPH / EXIT SECTION (ends the paragraph)
      NOOP       - CONTINUE, EXIT
    """
    kind: str
    verb: str
    text: str
    line: int
    condition: str | None = None
    target: str | None = None
    thru: str | None = None
    targets: list[str] = field(default_factory=list)
    external_call: str | None = None
    branches: list[Branch] = field(default_factory=list)


@dataclass
class Paragraph:
    name: str
    index: int
    section: str | None
    start_line: int
    end_line: int
    statements: list[Statement] = field(default_factory=list)
    source_text: str = ""

    @property
    def statement_count(self) -> int:
        return count_statements(self.statements)


def count_statements(statements: list[Statement]) -> int:
    total = 0
    for stmt in statements:
        total += 1
        for branch in stmt.branches:
            total += count_statements(branch.body)
    return total
