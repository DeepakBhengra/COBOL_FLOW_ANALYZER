"""Control-flow graph, paragraph status and static execution trace.

Graph model (networkx DiGraph, one node per paragraph):
  PERFORM / PERFORM THRU / GO TO   -> edge kind as recorded, conditional if guarded
  FALL-THROUGH                     -> edge from paragraph i to i+1 (source order) when
                                      paragraph i can finish without a transfer of control

Reachability is computed from the main flow: execution starts at the first paragraph
and falls through in source order until a paragraph that does not fall through. From
there, PERFORM and GO TO edges extend reachability. A PERFORM returns at the end of its
own range, so fall-through edges do not extend reachability into performed code.

The execution trace is a static, first-pass walk from the entry paragraph:
  * PERFORM runs the target range and returns to the next statement
  * GO TO transfers control; inside a PERFORM range it stays in the range
  * IF / EVALUATE explore every branch, each labelled with its condition
  * a paragraph is expanded only once; later references are reported with its result
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import networkx as nx

from ..models.flow_node import CallSite, ExecEvent
from ..models.paragraph import Paragraph, Statement
from ..models.program import Program
from .reference_analyzer import ReferenceAnalyzer

TERMINAL_KINDS = frozenset({"TERMINATE", "GOTO", "EXIT_PARA"})


def falls_through(paragraph: Paragraph) -> bool:
    """True if control reaches the next paragraph when this one finishes normally."""
    return not any(stmt.kind in TERMINAL_KINDS for stmt in paragraph.statements)


def main_flow_indices(program: Program) -> list[int]:
    """Paragraph indexes reached by falling through from the entry paragraph."""
    chain: list[int] = []
    for para in program.paragraphs:
        chain.append(para.index)
        if not falls_through(para):
            break
    return chain


def build_graph(program: Program, call_sites: list[CallSite]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for para in program.paragraphs:
        graph.add_node(para.name, index=para.index, section=para.section or "",
                       start_line=para.start_line, end_line=para.end_line,
                       statements=para.statement_count)

    for site in call_sites:
        if site.target in graph:
            graph.add_edge(site.caller, site.target, kind=site.kind,
                           conditional=site.is_conditional,
                           conditions=" AND ".join(site.conditions), line=site.line)

    paragraphs = program.paragraphs
    for prev, nxt in zip(paragraphs, paragraphs[1:]):
        if falls_through(prev):
            graph.add_edge(prev.name, nxt.name, kind="FALL-THROUGH", conditional=False,
                           conditions="", line=prev.end_line)
    return graph


@dataclass
class ParagraphStatus:
    name: str
    is_entry: bool
    call_count: int
    caller_count: int
    callers: list[str]
    reached_by_fall_through: bool
    reachable: bool
    never_called: bool
    multiple_callers: bool
    label: str


def paragraph_statuses(program: Program, graph: nx.DiGraph, call_sites: list[CallSite]) -> dict[str, ParagraphStatus]:
    names = [p.name for p in program.paragraphs]
    main_names = {names[i] for i in main_flow_indices(program)}

    # Reachability: main flow, then follow PERFORM / GO TO edges only.
    calls_from: dict[str, set[str]] = {}
    for site in call_sites:
        calls_from.setdefault(site.caller, set()).add(site.target)
    reachable = set(main_names)
    queue = deque(main_names)
    while queue:
        for nxt in calls_from.get(queue.popleft(), ()):
            if nxt in names and nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)

    entry = names[0] if names else None
    statuses: dict[str, ParagraphStatus] = {}
    for para in program.paragraphs:
        sites = [s for s in call_sites if s.target == para.name]
        callers = sorted({s.caller for s in sites})
        is_entry = para.name == entry
        in_main = para.name in main_names
        never = not sites and not is_entry and not in_main

        if is_entry:
            label = "Entry point"
        elif never:
            label = "Never called"
        elif sites:
            label = f"Called from {len(callers)} paragraphs" if len(callers) > 1 else "Called from 1 paragraph"
        else:
            label = "Reached by fall-through only"

        statuses[para.name] = ParagraphStatus(
            name=para.name,
            is_entry=is_entry,
            call_count=len(sites),
            caller_count=len(callers),
            callers=callers,
            reached_by_fall_through=in_main and not is_entry,
            reachable=para.name in reachable,
            never_called=never,
            multiple_callers=len(callers) > 1,
            label=label,
        )
    return statuses


class _TraceLimitReached(Exception):
    pass


class ExecutionTracer:
    OK, STOP, EXIT_PARA, JUMP_DONE = "NORMAL", "STOP", "EXIT_PARA", "JUMP_DONE"

    def __init__(self, program: Program, analyzer: ReferenceAnalyzer, max_events: int = 1500):
        self.program = program
        self.analyzer = analyzer
        self.paras = program.paragraphs
        self.by_name = program.paragraph_map
        self.max_events = max_events
        self.events: list[ExecEvent] = []
        self.expanded_at: dict[str, int] = {}
        self.results: dict[str, str] = {}
        self.stack: list[str] = []
        self.conditions: list[str] = []
        self.frames: list[tuple[int, int]] = []  # active PERFORM ranges (first, last index)

    # -------------------------------------------------------------- events
    def _emit(self, kind: str, paragraph: str, detail: str) -> None:
        if len(self.events) >= self.max_events:
            raise _TraceLimitReached()
        self.events.append(ExecEvent(
            seq=len(self.events) + 1,
            depth=len(self.stack),
            kind=kind,
            paragraph=paragraph,
            detail=detail,
            condition_path=" > ".join(self.conditions),
        ))

    @property
    def _current(self) -> str:
        return self.stack[-1] if self.stack else ""

    # -------------------------------------------------------------- walking
    def run(self) -> list[ExecEvent]:
        if not self.paras:
            return self.events
        try:
            if self._run_chain(self.paras[0]) == self.OK:
                self._emit("END", "", "Control falls off the last paragraph; program ends")
        except _TraceLimitReached:
            self._emit("NOTE", "", f"Trace stopped after {self.max_events} events")
        return self.events

    def _run_chain(self, start: Paragraph) -> str:
        """Main flow: run start, then fall through paragraph by paragraph."""
        saved_frames, self.frames = self.frames, []
        try:
            index = start.index
            while index < len(self.paras):
                if self._run_paragraph(self.paras[index]) == self.STOP:
                    return self.STOP
                index += 1
            return self.OK
        finally:
            self.frames = saved_frames

    def _run_range(self, first: int, last: int) -> str:
        """PERFORM semantics: run paragraphs first..last, then return to the caller."""
        index = first
        while index <= last:
            status = self._run_paragraph(self.paras[index])
            if status == self.STOP:
                return self.STOP
            if status == self.JUMP_DONE:
                return self.OK  # a GO TO inside the range already ran to its end
            index += 1
        return self.OK

    def _run_paragraph(self, para: Paragraph) -> str:
        if para.name in self.stack:
            self._emit("RECURSIVE", para.name, "Already on the call stack; not expanded again")
            return self.OK
        if para.name in self.expanded_at:
            prior = self.results.get(para.name, self.OK)
            outcome = "ends the program" if prior == self.STOP else "returns normally"
            self._emit("ALREADY", para.name,
                       f"Already traced at step {self.expanded_at[para.name]} ({outcome}); not expanded again")
            return prior

        self.expanded_at[para.name] = len(self.events) + 1
        self.stack.append(para.name)
        self._emit("ENTER", para.name, f"Section {para.section}" if para.section else "Paragraph starts")
        status = self._run_statements(para.statements)
        self.stack.pop()
        if status == self.JUMP_DONE:
            return self.JUMP_DONE
        if status == self.STOP:
            self.results[para.name] = self.STOP
            return self.STOP
        self._emit("END", para.name, "Paragraph completes")
        self.results[para.name] = self.OK
        return self.OK

    def _run_statements(self, statements: list[Statement]) -> str:
        for stmt in statements:
            if stmt.kind == "TERMINATE":
                self._emit("STOP", self._current, stmt.text)
                return self.STOP
            if stmt.kind == "EXIT_PARA":
                self._emit("EXIT PARAGRAPH", self._current, stmt.text)
                return self.EXIT_PARA
            if stmt.kind == "GOTO":
                return self._run_goto(stmt)
            if stmt.kind == "PERFORM":
                status = self._run_perform(stmt)
                if status != self.OK:
                    return status
            elif stmt.kind in ("IF", "EVALUATE"):
                outcome = self._run_branches(stmt)
                if outcome != self.OK:
                    return outcome
            elif stmt.kind == "SIMPLE":
                if stmt.external_call:
                    self._emit("CALL", self._current, f"External program {stmt.external_call}")
                # Optional clauses (AT END, INVALID KEY, ...) are shown; the main path continues.
                self._run_optional_branches(stmt)
        return self.OK

    def _run_goto(self, stmt: Statement) -> str:
        if not stmt.targets:
            self._emit("NOTE", self._current, "GO TO with no static target (ALTER or dynamic)")
            return self.STOP
        target = stmt.targets[0]
        self._emit("GO TO", self._current, f"Transfers control to {target}")
        if target not in self.by_name:
            return self.STOP
        target_index = self.by_name[target].index
        if self.frames and self.frames[-1][0] <= target_index <= self.frames[-1][1]:
            # Still inside the active PERFORM range: run to the end of the range, then return.
            self._run_range(target_index, self.frames[-1][1])
            return self.JUMP_DONE
        self._run_chain(self.by_name[target])
        return self.STOP

    def _run_perform(self, stmt: Statement) -> str:
        if stmt.target is None and stmt.branches:  # inline PERFORM ... END-PERFORM
            loop = f"LOOP {stmt.condition}" if stmt.condition else "LOOP"
            self.conditions.append(loop)
            self._emit("LOOP", self._current, stmt.text)
            status = self._run_statements(stmt.branches[0].body)
            self.conditions.pop()
            return status

        names = self.analyzer.resolve_range(stmt.target, stmt.thru)
        if not names:
            self._emit("NOTE", self._current, f"PERFORM {stmt.target}: target not found in program")
            return self.OK
        first, last = self.by_name[names[0]].index, self.by_name[names[-1]].index
        target_text = f"PERFORM {stmt.target}" + (f" THRU {stmt.thru}" if stmt.thru else "")
        loop = f" {stmt.condition}" if stmt.condition else ""
        self._emit("PERFORM", self._current, target_text + loop)

        pushed = bool(loop)
        if pushed:
            self.conditions.append(f"LOOP{loop}")
        self.frames.append((first, last))
        try:
            status = self._run_range(first, last)
        finally:
            self.frames.pop()
            if pushed:
                self.conditions.pop()
        if status == self.STOP:
            return self.STOP
        self._emit("RETURN", self._current, f"Returns from {stmt.target}")
        return self.OK

    def _run_branches(self, stmt: Statement) -> str:
        outcomes: list[str] = []
        for branch in stmt.branches:
            if stmt.kind == "IF":
                label = f"IF {stmt.condition} is {branch.label.lower()}"
            else:
                label = f"EVALUATE {stmt.condition} WHEN {branch.label}"
            self.conditions.append(label)
            self._emit("BRANCH", self._current, label)
            outcomes.append(self._run_statements(branch.body))
            self.conditions.pop()
        if not outcomes or self.OK in outcomes:
            return self.OK
        if self.JUMP_DONE in outcomes:
            return self.JUMP_DONE
        if self.STOP in outcomes:
            return self.STOP
        return self.EXIT_PARA

    def _run_optional_branches(self, stmt: Statement) -> None:
        for branch in stmt.branches:
            label = f"{stmt.verb} {branch.label}"
            self.conditions.append(label)
            self._emit("BRANCH", self._current, label)
            self._run_statements(branch.body)
            self.conditions.pop()


def trace_execution(program: Program, analyzer: ReferenceAnalyzer, max_events: int = 1500) -> list[ExecEvent]:
    return ExecutionTracer(program, analyzer, max_events).run()
