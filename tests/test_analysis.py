import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.analyzer.paragraph_analyzer import paragraph_detail  # noqa: E402
from src.parser import normalize  # noqa: E402
from src.pipeline import analyze_file, analyze_source  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_programs", "sample01.cbl")


def _fixed(code_lines):
    """Build fixed-format source: 7 leading columns, then the code."""
    body = ["       PROCEDURE DIVISION."] + ["       " + line for line in code_lines]
    return "\n".join(body) + "\n"


def test_source_format_strips_comments_and_sequence_area():
    text = "000100* a comment\n000200       MOVE 1 TO X.\n      *   another\n"
    lines = normalize(text)
    assert [l.text.strip() for l in lines] == ["MOVE 1 TO X."]


def test_sample_program_structure():
    a = analyze_file(SAMPLE)
    names = [p.name for p in a.program.paragraphs]
    assert a.program.name == "ORDPROC"
    assert names[0] == "MAIN-PARA"
    assert len(names) == 11
    assert [d.name for d in a.program.divisions] == [
        "IDENTIFICATION DIVISION", "ENVIRONMENT DIVISION", "DATA DIVISION", "PROCEDURE DIVISION"]
    assert a.program.data_item_count == 4
    assert "WORKING-STORAGE" in [s.name for s in a.program.sections]


def test_error_para_callers_and_conditions():
    a = analyze_file(SAMPLE)
    detail = paragraph_detail(a, "ERROR-PARA")
    callers = {(c["caller"], tuple(c["conditions"])) for c in detail["callers"]}
    assert ("VALIDATE-AMOUNT", ("IF WS-AMOUNT > 100000 [TRUE]",)) in callers
    assert ("PROCESS-RECORD", ("IF WS-AMOUNT > 0 [FALSE]",)) in callers
    assert ("WRITE-OUTPUT", ("WRITE INVALID KEY",)) in callers
    assert a.statuses["ERROR-PARA"].multiple_callers
    assert "ERROR-PARA" in " ".join(detail["after_completion"].split()) or detail["after_completion"]


def test_never_called_and_unreachable_paragraphs():
    a = analyze_file(SAMPLE)
    assert "UNUSED-PARA" in a.never_called
    assert "UNUSED-PARA" in a.unreachable
    assert a.statuses["VALIDATE-EXIT"].call_count == 2


def test_perform_thru_expands_range():
    src = _fixed([
        "P-ONE.", "    PERFORM A-PARA THRU C-PARA.", "    STOP RUN.",
        "A-PARA.", "    CONTINUE.", "B-PARA.", "    CONTINUE.", "C-PARA.", "    CONTINUE.",
    ])
    a = analyze_source(src)
    targets = {s.target for s in a.call_sites if s.caller == "P-ONE"}
    assert targets == {"A-PARA", "B-PARA", "C-PARA"}


def test_goto_is_a_transfer_and_not_a_fall_through():
    src = _fixed([
        "MAIN-PARA.", "    GO TO END-PARA.", "MIDDLE-PARA.", "    DISPLAY 'X'.",
        "END-PARA.", "    STOP RUN.",
    ])
    a = analyze_source(src)
    edges = {(u, v, d["kind"]) for u, v, d in a.graph.edges(data=True)}
    assert ("MAIN-PARA", "END-PARA", "GO TO") in edges
    assert ("MAIN-PARA", "MIDDLE-PARA", "FALL-THROUGH") not in edges
    assert a.statuses["MIDDLE-PARA"].never_called


def test_inline_perform_and_evaluate_are_parsed():
    src = _fixed([
        "MAIN-PARA.",
        "    PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3",
        "        DISPLAY I",
        "    END-PERFORM.",
        "    EVALUATE CODE-X",
        "        WHEN 1 PERFORM ONE-PARA",
        "        WHEN OTHER PERFORM TWO-PARA",
        "    END-EVALUATE.",
        "    STOP RUN.",
        "ONE-PARA.", "    CONTINUE.",
        "TWO-PARA.", "    CONTINUE.",
    ])
    a = analyze_source(src)
    main = a.program.paragraph_map["MAIN-PARA"]
    kinds = [s.kind for s in main.statements]
    assert kinds == ["PERFORM", "EVALUATE", "TERMINATE"]
    callers = {(s.target, s.conditions[0]) for s in a.call_sites if s.caller == "MAIN-PARA"}
    assert ("ONE-PARA", "EVALUATE CODE-X WHEN 1") in callers
    assert ("TWO-PARA", "EVALUATE CODE-X WHEN OTHER") in callers


def test_read_at_end_branch_is_recorded():
    a = analyze_file(SAMPLE)
    read_para = a.program.paragraph_map["READ-INPUT"]
    read = read_para.statements[0]
    assert read.verb == "READ"
    assert [b.label for b in read.branches] == ["AT END", "NOT AT END"]


def test_execution_trace_stops_at_stop_run_and_skips_unused_paragraph():
    a = analyze_file(SAMPLE)
    entered = [e.paragraph for e in a.trace if e.kind == "ENTER"]
    assert entered[0] == "MAIN-PARA"
    assert "UNUSED-PARA" not in entered
    assert any(e.kind == "STOP" for e in a.trace)
    assert any(e.kind == "GO TO" and e.detail.endswith("VALIDATE-EXIT") for e in a.trace)
