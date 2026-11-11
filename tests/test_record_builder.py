from src.pipeline import analyze_source
from src.values.local_values import const
from src.values.record_builder import build_record

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. RECTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMM-AREA-LENGTH     PIC 9(03).
       01  WS-OK                   PIC X(01).
       01  REC-AREA.
           05  REC-COMPANY         PIC X(02).
           05  REC-TYPE            PIC X(01).
               88  REC-NEW                     VALUE 'N'.
           05  REC-QTY             PIC 9(03).
       PROCEDURE DIVISION.
       000-MAINLINE.
           IF EIBCALEN = ZERO
              MOVE LENGTH OF REC-AREA TO WS-COMM-AREA-LENGTH
              EXEC CICS RETRIEVE
                   INTO (REC-AREA)
                   LENGTH (WS-COMM-AREA-LENGTH)
              END-EXEC
           END-IF
           PERFORM 100-CHECK
           GOBACK.
       100-CHECK.
           IF REC-COMPANY = 'XY'
              MOVE 'Y' TO WS-OK
           ELSE
              MOVE 'N' TO WS-OK
           END-IF.
"""


def _analysis():
    return analyze_source(PROGRAM, "rectest.cbl")


def test_record_field_is_set_to_the_value_a_test_needs():
    result = build_record(_analysis(), "REC-AREA", "000-MAINLINE", {"EIBCALEN": const(0)})
    fields = {f["name"]: f for f in result["record"]}
    assert fields["REC-COMPANY"]["value"] == "XY"
    assert result["patches"][0]["field"] == "REC-COMPANY"
    assert result["text"][:2] == "XY"


def test_record_fields_sit_at_their_offsets_and_show_possible_values():
    result = build_record(_analysis(), "REC-AREA", "000-MAINLINE", {"EIBCALEN": const(0)})
    fields = {f["name"]: f for f in result["record"]}
    assert fields["REC-TYPE"]["offset"] == 2
    assert fields["REC-QTY"]["offset"] == 3
    assert fields["REC-TYPE"]["possible_values"] == [{"condition": "REC-NEW", "value": "N"}]
    assert len(result["text"]) == result["bytes"] == 6


def test_downstream_decision_is_taken_on_the_built_record():
    result = build_record(_analysis(), "REC-AREA", "000-MAINLINE", {"EIBCALEN": const(0)})
    decision = next(d for d in result["decisions"] if d["condition"].startswith("REC-COMPANY"))
    assert decision["decided"] == "true"
    assert decision["taken"] == ["MOVE 'Y' TO WS-OK"]


def test_packed_decimal_bytes_match_the_ibm_layout():
    from src.values.record_builder import pack_comp3
    assert pack_comp3(12345, 5, True).hex().upper() == "12345C"      # +12345 in S9(5) COMP-3
    assert pack_comp3(-12345, 5, True).hex().upper() == "12345D"     # -12345
    assert pack_comp3(1234, 4, True).hex().upper() == "01234C"       # even digits get a leading zero nibble


def test_given_values_and_packed_sample_are_placed_by_offset():
    from src.pipeline import analyze_source as analyse
    from src.values.record_builder import build_record as build
    program = PROGRAM.replace("05  REC-QTY             PIC 9(03).",
                              "05  REC-QTY             PIC S9(05) COMP-3.")
    a = analyse(program, "rectest.cbl")
    result = build(a, "REC-AREA", "000-MAINLINE", {"EIBCALEN": const(0)},
                   values={"REC-QTY": "12345"}, sample=False)
    qty = next(f for f in result["record"] if f["name"] == "REC-QTY")
    assert qty["packed"] and qty["shown"] == "12 34 5C" and qty["offset"] == 3
    assert result["text"][3:6] == "\x12\x34\x5c"
