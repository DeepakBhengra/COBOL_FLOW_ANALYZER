"""Turns procedure blocks into Paragraph objects with parsed statement trees."""
from __future__ import annotations

from ..models.paragraph import Paragraph
from .division_parser import ProcedureBlock
from .statement_parser import StatementParser


def build_paragraphs(blocks: list[ProcedureBlock]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for index, block in enumerate(blocks):
        statements = StatementParser(block.tokens).parse()
        end_line = block.tokens[-1].line if block.tokens else block.start_line
        paragraphs.append(Paragraph(
            name=block.name,
            index=index,
            section=block.section,
            start_line=block.start_line,
            end_line=end_line,
            statements=statements,
        ))
    return paragraphs
