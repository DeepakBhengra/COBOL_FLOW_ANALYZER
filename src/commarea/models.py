"""Data classes for COMMAREA analysis."""
from __future__ import annotations

from dataclasses import dataclass, field

# CICS limit for a traditional COMMAREA (bytes).
COMMAREA_LIMIT = 32767


@dataclass
class DataItem:
    """One entry of the DATA DIVISION, with its computed storage layout."""
    name: str
    level: int
    section: str
    line: int
    pic: str | None = None
    usage: str = "DISPLAY"
    occurs: int = 1
    redefines: str | None = None
    parent: "DataItem | None" = field(default=None, repr=False)
    children: list["DataItem"] = field(default_factory=list, repr=False)
    element_length: int = 0   # bytes for one occurrence
    offset: int = 0           # offset from the start of the root record
    @property
    def total_length(self) -> int:
        return self.element_length * self.occurs

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    @property
    def path(self) -> str:
        parts = []
        node: DataItem | None = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return ".".join(reversed(parts))

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class CommandUse:
    """One EXEC CICS command found in the PROCEDURE DIVISION."""
    command: str                      # LINK, XCTL, RETURN, READ, SEND, ...
    paragraph: str
    line: int
    text: str
    options: dict[str, str] = field(default_factory=dict)
    conditions: list[str] = field(default_factory=list)

    @property
    def target_program(self) -> str | None:
        value = self.options.get("PROGRAM")
        return _literal(value)

    @property
    def transid(self) -> str | None:
        return _literal(self.options.get("TRANSID"))

    @property
    def commarea(self) -> str | None:
        return self.options.get("COMMAREA")

    @property
    def length_expr(self) -> str | None:
        return self.options.get("LENGTH")


def _literal(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1]
    return value


@dataclass
class FieldAccess:
    """A read or write of a COMMAREA field (or of the whole area) by a statement."""
    field: str            # qualified path, e.g. DFHCOMMAREA.CA-CUST-ID
    mode: str             # R, W, RW, SEND, RECEIVE, PASS (LINK: sent and returned)
    paragraph: str
    line: int
    statement: str
    conditions: list[str] = field(default_factory=list)
    whole_area: bool = False


@dataclass
class Finding:
    severity: str         # error, warning, info
    code: str
    message: str
    paragraph: str | None = None
    line: int | None = None


@dataclass
class StandardCheck:
    standard: str
    status: str           # met, not met, not applicable, review
    detail: str


@dataclass
class FieldSummary:
    path: str
    pic: str | None
    usage: str
    offset: int
    length: int
    role: str             # input, output, input/output, unused
    read_in: list[str] = field(default_factory=list)
    written_in: list[str] = field(default_factory=list)
    meaning: str | None = None     # from a saved copybook note
    category: str | None = None
    note_stale: bool = False       # the copybook changed after the note was written


@dataclass
class CommareaReport:
    applicable: bool
    area_name: str | None
    area_length: int | None
    area_location: str | None             # LINKAGE SECTION, WORKING-STORAGE, ...
    fields: list[FieldSummary] = field(default_factory=list)
    commands: list[CommandUse] = field(default_factory=list)
    accesses: list[FieldAccess] = field(default_factory=list)
    narratives: dict[str, list[str]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    standards: list[StandardCheck] = field(default_factory=list)
    pseudo_conversational: bool = False
    tests_eibcalen: bool = False
    transids: list[str] = field(default_factory=list)
    linked_programs: list[str] = field(default_factory=list)
    uses_channels: bool = False
