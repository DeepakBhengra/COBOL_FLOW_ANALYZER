"""Splits a token stream into divisions, sections, data items and procedure paragraphs."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models.program import Division, Section
from .keywords import RESERVED_FOR_HEADERS
from .lexer import PERIOD, WORD, Token

_DIVISION_WORDS = {"IDENTIFICATION": "IDENTIFICATION", "ID": "IDENTIFICATION",
                   "ENVIRONMENT": "ENVIRONMENT", "DATA": "DATA", "PROCEDURE": "PROCEDURE"}


@dataclass
class ProcedureBlock:
    """Tokens belonging to one paragraph, including the period after each sentence."""
    name: str
    section: str | None
    start_line: int
    tokens: list[Token] = field(default_factory=list)


@dataclass
class Structure:
    divisions: list[Division] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    data_item_count: int = 0
    procedure_start_line: int = 0
    procedure_blocks: list[ProcedureBlock] = field(default_factory=list)
    program_id: str = "UNKNOWN"
    # (section name, tokens) for every DATA DIVISION entry that starts with a level number.
    data_entries: list[tuple[str, list[Token]]] = field(default_factory=list)


def _split_sentences(tokens: list[Token]) -> list[list[Token]]:
    sentences: list[list[Token]] = []
    current: list[Token] = []
    for tok in tokens:
        if tok.kind == PERIOD:
            if current:
                sentences.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        sentences.append(current)
    return sentences


def parse_structure(tokens: list[Token]) -> Structure:
    structure = Structure()
    n = len(tokens)

    # ---- divisions -------------------------------------------------------
    division_at: list[tuple[int, str]] = []
    for i, tok in enumerate(tokens):
        if tok.kind == WORD and tok.upper() in _DIVISION_WORDS and i + 1 < n \
                and tokens[i + 1].upper() == "DIVISION":
            name = _DIVISION_WORDS[tok.upper()]
            division_at.append((i, name))
            structure.divisions.append(Division(f"{name} DIVISION", tok.line))

    def division_for(index: int) -> str | None:
        current = None
        for pos, name in division_at:
            if pos <= index:
                current = name
        return current

    # ---- PROGRAM-ID -------------------------------------------------------
    for i, tok in enumerate(tokens):
        if tok.upper() == "PROGRAM-ID" and i + 2 < n:
            structure.program_id = tokens[i + 2].value
            break

    # ---- data items (level 01 / 77 entries) ------------------------------
    procedure_index = next((i for i, name in division_at if name == "PROCEDURE"), n)
    data_end = procedure_index
    data_tokens = [t for t in tokens[:data_end]]
    for sentence in _split_sentences(data_tokens):
        if sentence and sentence[0].kind == "NUMBER" and sentence[0].value.lstrip("0") in ("1", "77"):
            structure.data_item_count += 1

    data_start = next((i for i, name in division_at if name == "DATA"), None)
    if data_start is not None:
        current_section = ""
        for sentence in _split_sentences(tokens[data_start:procedure_index]):
            if len(sentence) == 2 and sentence[1].upper() == "SECTION":
                current_section = sentence[0].value.upper()
            elif sentence and sentence[0].kind == "NUMBER":
                structure.data_entries.append((current_section, sentence))

    # ---- sections outside the PROCEDURE DIVISION (ENVIRONMENT, DATA, ...) ----
    for i in range(procedure_index):
        if tokens[i].kind == WORD and i + 1 < n and tokens[i + 1].kind == WORD \
                and tokens[i + 1].upper() == "SECTION" and tokens[i].upper() not in _DIVISION_WORDS:
            structure.sections.append(Section(tokens[i].value, division_for(i) or "", tokens[i].line))

    # ---- procedure division ----------------------------------------------
    if procedure_index >= n:
        return structure
    structure.procedure_start_line = tokens[procedure_index].line

    # Skip the PROCEDURE DIVISION header sentence (may carry USING clauses).
    body_start = procedure_index
    while body_start < n and tokens[body_start].kind != PERIOD:
        body_start += 1
    body_start += 1

    current: ProcedureBlock | None = None
    current_section: str | None = None
    skipping_declaratives = False

    def start_block(name: str, line: int) -> ProcedureBlock:
        block = ProcedureBlock(name=name, section=current_section, start_line=line)
        structure.procedure_blocks.append(block)
        return block

    for sentence in _split_sentences(tokens[body_start:]):
        first = sentence[0]
        words = [t.upper() for t in sentence]

        if words == ["DECLARATIVES"]:
            skipping_declaratives = True
            continue
        if words == ["END", "DECLARATIVES"]:
            skipping_declaratives = False
            continue
        if skipping_declaratives:
            continue

        period = Token(PERIOD, ".", sentence[-1].line)

        if len(sentence) == 2 and first.kind == WORD and words[1] == "SECTION":
            current_section = first.value
            structure.sections.append(Section(first.value, division_for(procedure_index) or "PROCEDURE DIVISION",
                                              first.line))
            current = None
            continue

        if len(sentence) == 1 and first.kind == WORD and words[0] not in RESERVED_FOR_HEADERS:
            current = start_block(first.value, first.line)
            continue

        if current is None:
            current = start_block("(UNNAMED)", first.line)
        current.tokens.extend(sentence)
        current.tokens.append(period)

    # Attach paragraph counts to sections.
    for section in structure.sections:
        section.paragraph_count = sum(1 for b in structure.procedure_blocks if b.section == section.name)
    return structure
