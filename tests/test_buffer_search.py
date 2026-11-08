from src.pipeline import analyze_source
from src.values.buffer_search import analyze_with_buffer, build_by_execution

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEARCHT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FUNCTION          PIC X(02).
           05  WS-NEXT-POS          PIC 9(03) VALUE 1.
           05  WS-START-POS         PIC 9(03) VALUE 1.
           05  WS-CHAR-POS          PIC 9(03) VALUE 1.
           05  WS-TAB-CHAR          PIC X(01) VALUE X'09'.
           05  WS-DELIM-SW          PIC X(01) VALUE 'N'.
               88  WS-DELIM-FOUND             VALUE 'Y'.
       01  RCV-DATA-BUFFER-AREA     PIC X(100).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 0500-PARSE-INPUT
           STOP RUN.
       0500-PARSE-INPUT.
           MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2) TO WS-FUNCTION
           EVALUATE TRUE
              WHEN WS-FUNCTION = ('OL' OR 'CL')
                 PERFORM 0550-FIND-NEXT-DELIMITER
              WHEN OTHER
                 CONTINUE
           END-EVALUATE.
       0550-FIND-NEXT-DELIMITER.
           COMPUTE WS-CHAR-POS = WS-START-POS + 3
           IF RCV-DATA-BUFFER-AREA(WS-CHAR-POS:1) = WS-TAB-CHAR
              MOVE 'Y' TO WS-DELIM-SW
           ELSE
              MOVE 'N' TO WS-DELIM-SW
           END-IF.
"""


def _analysis():
    return analyze_source(PROGRAM, "searcht.cbl")


def test_buffer_is_built_by_running_the_tests():
    result = build_by_execution(_analysis(), "0500-PARSE-INPUT")
    assert result["sample"][:2] == "OL"                    # the EVALUATE test on the first two bytes
    assert result["sample"][3] == "\t"                     # the delimiter test found at WS-CHAR-POS = 4
    assert result["conflicts"] == []
    assert result["unsatisfied"] == []
    decisions = {d["line"]: d["decided"] for d in result["decisions"]}
    assert decisions[28] == "true"                         # the delimiter test is now satisfied


def test_the_built_buffer_runs_the_chosen_paragraph():
    analysis = _analysis()
    built = build_by_execution(analysis, "0500-PARSE-INPUT")
    run = analyze_with_buffer(analysis, "0550-FIND-NEXT-DELIMITER", built["sample"].ljust(10))
    decision = next(d for d in run["buffer_run"]["decisions"] if d["line"] == 28)
    assert decision["decided"] == "true"
