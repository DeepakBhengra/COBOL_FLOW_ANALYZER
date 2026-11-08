import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.commarea import COMMAREA_LIMIT, to_dict, to_text  # noqa: E402
from src.commarea.cics_commands import parse_exec_text  # noqa: E402
from src.commarea.data_layout import picture_length  # noqa: E402
from src.commarea.usage import classify  # noqa: E402
from src.pipeline import analyze_file, analyze_source  # noqa: E402

CICS = os.path.join(ROOT, "sample_programs", "cics_custinq.cbl")
BATCH = os.path.join(ROOT, "sample_programs", "sample01.cbl")


def _base():
    with open(CICS, encoding="utf-8") as handle:
        return handle.read()


def _findings(report):
    return {f.code for f in report.findings}


# ---------------------------------------------------------------- layout sizes
def test_picture_lengths_follow_ibm_rules():
    assert picture_length("X(8)", "DISPLAY") == 8
    assert picture_length("9(2)", "DISPLAY") == 2
    assert picture_length("S9(9)V99", "COMP-3") == 6          # 11 digits -> 11 // 2 + 1
    assert picture_length("S9(4)", "COMP") == 2
    assert picture_length("S9(8)", "COMP") == 4
    assert picture_length("S9(12)", "COMP") == 8
    assert picture_length(None, "COMP-2") == 8


def test_sample_commarea_layout_and_offsets():
    a = analyze_file(CICS)
    c = a.commarea
    assert c.applicable
    assert c.area_name == "DFHCOMMAREA"
    assert c.area_location == "LINKAGE"
    assert c.area_length == 107
    offsets = {f.path: (f.offset, f.length) for f in c.fields}
    assert offsets["DFHCOMMAREA.CA-ACTION"] == (0, 1)
    assert offsets["DFHCOMMAREA.CA-CUST-ID"] == (1, 8)
    assert offsets["DFHCOMMAREA.CA-CUST-BALANCE"] == (41, 6)
    assert offsets["DFHCOMMAREA.CA-MESSAGE"] == (47, 60)


def test_occurs_multiplies_length():
    src = _base().replace("          05 CA-MESSAGE       PIC X(60).",
                          "          05 CA-TABLE OCCURS 10 TIMES PIC X(4).", 1)
    c = analyze_source(src).commarea
    table = next(f for f in c.fields if f.path.endswith("CA-TABLE"))
    assert table.length == 40
    assert c.area_length == 107 - 60 + 40


# ---------------------------------------------------------------- command flow
def test_sample_pseudo_conversational_and_link():
    c = analyze_file(CICS).commarea
    assert c.pseudo_conversational
    assert c.tests_eibcalen
    assert c.transids == ["CUST"]
    assert c.linked_programs == ["BALCALC"]
    assert "MAIN-PARA" in c.narratives
    assert any("pseudo-conversational" in s for s in c.narratives["MAIN-PARA"])
    assert any("BALCALC" in s for s in c.narratives["CALL-BALANCE"])


def test_sample_has_no_findings_and_all_standards_pass_or_do_not_apply():
    c = analyze_file(CICS).commarea
    assert not [f for f in c.findings if f.severity == "error"]
    assert all(s.status in ("met", "not applicable") for s in c.standards)


def test_field_roles_and_writers():
    c = analyze_file(CICS).commarea
    by = {f.path: f for f in c.fields}
    assert by["DFHCOMMAREA.CA-ACTION"].role == "input"
    assert by["DFHCOMMAREA.CA-CUST-NAME"].role == "input/output"
    assert "READ-CUSTOMER" in by["DFHCOMMAREA.CA-CUST-NAME"].written_in
    assert "FIRST-TIME-PARA" in by["DFHCOMMAREA.CA-MESSAGE"].written_in


def test_branch_conditions_are_reported():
    c = analyze_file(CICS).commarea
    setters = [a for a in c.accesses if a.field == "DFHCOMMAREA.CA-CUST-NAME" and a.mode == "W"]
    assert setters and any("IF WS-RESP = 0 [TRUE]" in cond for cond in setters[0].conditions)


# ---------------------------------------------------------------- findings
def test_length_mismatch_is_reported():
    src = _base().replace("LENGTH(LENGTH OF DFHCOMMAREA)\n           END-EXEC.\n       FIRST",
                          "LENGTH(80)\n           END-EXEC.\n       FIRST", 1)
    c = analyze_source(src).commarea
    assert "LENGTH_MISMATCH" in _findings(c)
    length_standard = next(s for s in c.standards if s.standard.startswith("LENGTH"))
    assert length_standard.status == "not met"


def test_oversize_commarea_is_an_error_and_fails_standards():
    src = _base().replace("          05 CA-MESSAGE       PIC X(60).",
                          "          05 CA-TABLE OCCURS 1000 TIMES PIC X(40).", 1)
    c = analyze_source(src).commarea
    assert c.area_length > COMMAREA_LIMIT
    assert "COMMAREA_TOO_LARGE" in _findings(c)
    limit = next(s for s in c.standards if "32,767" in s.standard)
    assert limit.status == "not met"


def test_dfhcommarea_outside_linkage_is_an_error():
    src = _base().replace("       LINKAGE SECTION.\n", "       LINKAGE SECTION.\n       01 OTHER-AREA PIC X(1).\n", 1)
    # Move DFHCOMMAREA into WORKING-STORAGE by removing the LINKAGE header.
    src = src.replace("       LINKAGE SECTION.\n", "", 1)
    c = analyze_source(src).commarea
    assert c.area_location == "WORKING-STORAGE"
    assert "DFHCOMMAREA_NOT_LINKAGE" in _findings(c)


def test_missing_eibcalen_test_is_flagged():
    src = _base().replace("           IF EIBCALEN = 0", "           IF WS-RESP = 0", 1)
    c = analyze_source(src).commarea
    assert not c.tests_eibcalen
    assert "NO_EIBCALEN_TEST" in _findings(c)


def test_return_without_transid_is_not_pseudo_conversational():
    src = _base().replace("TRANSID('CUST')", "", 1)
    c = analyze_source(src).commarea
    assert not c.pseudo_conversational
    assert "RETURN_WITHOUT_STATE" in _findings(c)


def test_xctl_is_reported_as_a_transfer():
    src = _base().replace("       CALL-BALANCE.\n",
                          "       CALL-BALANCE.\n           EXEC CICS XCTL PROGRAM('MENU') "
                          "COMMAREA(DFHCOMMAREA) LENGTH(LENGTH OF DFHCOMMAREA) END-EXEC.\n", 1)
    c = analyze_source(src).commarea
    assert "MENU" in c.linked_programs
    assert any("Transfers control to MENU" in s for s in c.narratives["CALL-BALANCE"])


def test_channels_are_noted():
    src = _base().replace("       CALL-BALANCE.\n",
                          "       CALL-BALANCE.\n           EXEC CICS PUT CONTAINER('X') "
                          "FROM(WS-CUST-REC) END-EXEC.\n", 1)
    c = analyze_source(src).commarea
    assert c.uses_channels
    assert "CHANNELS_IN_USE" in _findings(c)


# ---------------------------------------------------------------- not CICS
def test_batch_program_is_not_applicable():
    c = analyze_file(BATCH).commarea
    assert not c.applicable
    assert to_dict(c) == {"applicable": False}
    assert "No COMMAREA" in to_text(c)


# ---------------------------------------------------------------- helpers
def test_exec_parser_reads_options():
    command, options = parse_exec_text(
        "EXEC CICS LINK PROGRAM ( 'BALCALC' ) COMMAREA ( DFHCOMMAREA ) LENGTH ( LENGTH OF DFHCOMMAREA )")
    assert command == "LINK"
    assert options["PROGRAM"] == "'BALCALC'"
    assert options["COMMAREA"] == "DFHCOMMAREA"
    assert options["LENGTH"] == "LENGTH OF DFHCOMMAREA"


def test_classify_moves_adds_and_computes():
    assert classify("MOVE CA-X TO WS-Y")["R"] == {"CA-X"}
    assert classify("MOVE CA-X TO WS-Y")["W"] == {"WS-Y"}
    assert classify("ADD 1 TO CA-COUNT")["RW"] == {"CA-COUNT"}
    assert classify("COMPUTE CA-TOTAL = CA-A + CA-B")["W"] == {"CA-TOTAL"}
    assert classify("COMPUTE CA-TOTAL = CA-A + CA-B")["R"] == {"CA-A", "CA-B"}
    assert classify("IF CA-ACTION = 'B'")["R"] == {"CA-ACTION"}
