from src.copybooks import CopybookLibrary
from src.pipeline import analyze_source
from src.values.buffer_builder import build_sample

COPY = """       01  CNF-REQUEST.
           05  CNF-FUNCTION      PIC X(02).
               88  CNF-CREATE    VALUE 'CF'.
           05  CNF-NAME          PIC X(12).
           05  CNF-QTY           PIC 9(03).
"""

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BUFTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARSE-AREA.
           05  WS-FUNCTION       PIC X(02).
           05  WS-NEXT-POS       PIC 9(03).
           05  WS-START-POS      PIC 9(03).
           05  WS-MOVE-LEN       PIC 9(03).
       01  RCV-DATA-BUFFER-AREA  PIC X(200).
       COPY CNFCPY.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 0500-PARSE-INPUT
           STOP RUN.
       0500-PARSE-INPUT.
           MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2) TO WS-FUNCTION
           EVALUATE WS-FUNCTION
              WHEN 'OL' OR 'CL'
                 PERFORM 0570-MOVE-CONFIG-LINE
              WHEN OTHER
                 CONTINUE
           END-EVALUATE.
       0570-MOVE-CONFIG-LINE.
           MOVE LENGTH OF CNF-REQUEST TO WS-MOVE-LEN
           MOVE 3 TO WS-START-POS
           IF RCV-DATA-BUFFER-AREA(WS-START-POS:2) = 'CF'
              MOVE RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)
                   TO CNF-REQUEST
           END-IF.
"""


def _analysis():
    library = CopybookLibrary.from_environment(texts={"CNFCPY": COPY})
    analysis = analyze_source(PROGRAM, "buftest.cbl", library=library)
    analysis.library = library
    return analysis


def test_each_test_on_the_buffer_is_placed_at_its_position():
    from src.values.local_values import const
    result = build_sample(_analysis(), "0500-PARSE-INPUT", assumptions={"WS-NEXT-POS": const(1)},
                          library=_analysis().library)
    placed = {(p["start"], p["value"]) for p in result["placements"]}
    assert (1, "OL") in placed
    assert (3, "CF") in placed


def test_group_sample_gets_its_88_value_and_fits_the_buffer():
    result = build_sample(_analysis(), "0570-MOVE-CONFIG-LINE", library=_analysis().library)
    group = result["groups"][0]
    assert group["group"] == "CNF-REQUEST"
    fields = {f["name"]: f["value"] for f in group["fields"]}
    assert fields["CNF-FUNCTION"] == "CF"
    assert result["sample"][2:4] == "CF"
    assert result["conflicts"] == []
    assert result["unresolved"] == []


def test_missing_position_is_listed_not_guessed():
    result = build_sample(_analysis(), "0500-PARSE-INPUT", library=_analysis().library)
    assert any("WS-NEXT-POS" in u["reason"] or "position" in u["reason"] for u in result["unresolved"])
