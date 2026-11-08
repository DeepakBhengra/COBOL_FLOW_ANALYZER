"""Program-level model."""
from __future__ import annotations

from dataclasses import dataclass, field

from .paragraph import Paragraph


@dataclass
class Division:
    name: str
    start_line: int


@dataclass
class Section:
    name: str
    division: str
    start_line: int
    paragraph_count: int = 0


@dataclass
class Program:
    name: str
    source_name: str
    line_count: int
    divisions: list[Division] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    data_item_count: int = 0
    procedure_start_line: int = 0
    source_lines: dict[int, str] = field(default_factory=dict)
    # expanded line number -> where it came from ('MAIN.cbl:12' or 'CUSTCOMM.cpy:3')
    line_origin: dict[int, str] = field(default_factory=dict)

    @property
    def paragraph_map(self) -> dict[str, Paragraph]:
        return {p.name: p for p in self.paragraphs}

    @property
    def entry_paragraph(self) -> Paragraph | None:
        return self.paragraphs[0] if self.paragraphs else None
