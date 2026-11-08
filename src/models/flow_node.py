"""Flow-level models: call sites between paragraphs and execution-trace events."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallSite:
    """A PERFORM or GO TO that transfers control from one paragraph to another."""
    caller: str
    target: str
    kind: str                      # PERFORM, PERFORM THRU, GO TO
    line: int
    statement: str
    conditions: list[str] = field(default_factory=list)
    thru: str | None = None

    @property
    def is_conditional(self) -> bool:
        return bool(self.conditions)


@dataclass
class ExternalCall:
    caller: str
    target: str
    line: int
    conditions: list[str] = field(default_factory=list)


@dataclass
class ExecEvent:
    """One step of the static execution trace."""
    seq: int
    depth: int
    kind: str          # ENTER, PERFORM, RETURN, GO TO, BRANCH, LOOP, CALL, STOP, EXIT PARAGRAPH, END, ALREADY, RECURSIVE, NOTE
    paragraph: str
    detail: str
    condition_path: str = ""
