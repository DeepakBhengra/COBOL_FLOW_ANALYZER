"""End-to-end analysis: source text in, every derived view out."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import networkx as nx

from .analyzer.flow_analyzer import ParagraphStatus, build_graph, paragraph_statuses, trace_execution
from .analyzer.reference_analyzer import ReferenceAnalyzer
from .commarea import CommareaReport, analyze_commarea
from .commarea.data_layout import build_layout
from .copybooks import CopybookLibrary, ExpansionResult, expand_copybooks
from .copybooks.knowledge import KnowledgeStore
from .copybooks.meanings import field_meanings
from .models.flow_node import CallSite, ExecEvent, ExternalCall
from .models.program import Program
from .parser import build_paragraphs, normalize, parse_structure, tokenize


@dataclass
class Analysis:
    program: Program
    analyzer: ReferenceAnalyzer
    call_sites: list[CallSite] = field(default_factory=list)
    external_calls: list[ExternalCall] = field(default_factory=list)
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)
    statuses: dict[str, ParagraphStatus] = field(default_factory=dict)
    trace: list[ExecEvent] = field(default_factory=list)
    commarea: CommareaReport | None = None
    copybooks: ExpansionResult | None = None
    field_meanings: dict = field(default_factory=dict)   # expanded field path -> saved note
    data_roots: list = field(default_factory=list)       # DATA DIVISION items with sizes and offsets
    data_entries: list = field(default_factory=list)     # raw DATA DIVISION entries (for VALUE clauses)

    @property
    def never_called(self) -> list[str]:
        return [n for n, s in self.statuses.items() if s.never_called]

    @property
    def unreachable(self) -> list[str]:
        return [n for n, s in self.statuses.items() if not s.reachable]


def analyze_source(text: str, source_name: str = "program.cbl",
                   library: CopybookLibrary | None = None,
                   knowledge: KnowledgeStore | None = None) -> Analysis:
    """Analyse program text. COPY statements are expanded from `library`
    (default: the COBOL_COPYBOOKS folders)."""
    if library is None:
        library = CopybookLibrary.from_environment()

    expansion = expand_copybooks(normalize(text), library, source_name)
    lines = expansion.lines

    if expansion.expanded:
        # Line numbers now refer to the expanded text; show that text, with origins.
        source_map = {line.number: line.text for line in lines}
        origins = {line.number: line.origin or "" for line in lines}
        line_count = len(lines)
    else:
        physical = text.expandtabs(8).splitlines()
        source_map = {i: line for i, line in enumerate(physical, start=1)}
        origins = {}
        line_count = len(physical)

    tokens = tokenize(lines)
    structure = parse_structure(tokens)
    paragraphs = build_paragraphs(structure.procedure_blocks)

    for para in paragraphs:
        para.source_text = "\n".join(
            source_map[n] for n in range(para.start_line, para.end_line + 1) if n in source_map)

    program = Program(
        name=structure.program_id,
        source_name=source_name,
        line_count=line_count,
        divisions=structure.divisions,
        sections=structure.sections,
        paragraphs=paragraphs,
        data_item_count=structure.data_item_count,
        procedure_start_line=structure.procedure_start_line,
        source_lines=source_map,
        line_origin=origins,
    )

    roots, _ = build_layout(structure.data_entries)
    meanings: dict = {}
    if knowledge is not None and expansion.expanded:
        items = [item for root in roots for item in root.walk()]
        meanings = field_meanings(items, program.line_origin, source_name, library, knowledge)

    analyzer = ReferenceAnalyzer(program)
    call_sites = analyzer.call_sites()
    graph = build_graph(program, call_sites)
    return Analysis(
        program=program,
        analyzer=analyzer,
        commarea=analyze_commarea(program, analyzer, structure.data_entries, meanings),
        call_sites=call_sites,
        external_calls=analyzer.external_calls(),
        graph=graph,
        statuses=paragraph_statuses(program, graph, call_sites),
        trace=trace_execution(program, analyzer),
        copybooks=expansion,
        field_meanings=meanings,
        data_roots=roots,
        data_entries=structure.data_entries,
    )


def analyze_file(path: str, copybook_dirs: list[str] | None = None) -> Analysis:
    """Analyse a file. Copybooks are looked up next to the program, in a 'copybooks'
    folder beside it, in `copybook_dirs`, and in the COBOL_COPYBOOKS folders."""
    folder = os.path.dirname(os.path.abspath(path))
    search = [folder, os.path.join(folder, "copybooks")] + list(copybook_dirs or [])
    library = CopybookLibrary.from_environment(extra=search)
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    return analyze_source(text, source_name=os.path.basename(path), library=library)
