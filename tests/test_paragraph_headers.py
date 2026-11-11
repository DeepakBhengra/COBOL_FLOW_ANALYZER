from src.pipeline import analyze_source

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HDRTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMM-LEN          PIC 9(04).
       01  WS-A                 PIC X(01).
       PROCEDURE DIVISION.
       0000-INITIAL.
           INITIALIZE WS-COMM-LEN.
           IF EIBCALEN = ZERO
              MOVE LENGTH OF WS-A TO WS-COMM-LEN
           ELSE
              MOVE EIBCALEN TO WS-COMM-LEN
           END-IF
           PERFORM 1100-FORMAT-ORDER-HEADER
              THRU 1100-EXIT
           PERFORM 2000-LINK-TO-TRAN THRU 2000-EXIT
           GOBACK.
      *SE8712-ALLOW SPECIAL CHARACTERS
           IF WS-A = 'X'
              CONTINUE
           END-IF
       1100-FORMAT-ORDER-HEADER.
           MOVE 'X' TO WS-A
       1100-EXIT.
           EXIT.
       2000-LINK-TO-TRAN.
           CONTINUE.
       2000-EXIT. EXIT.
"""


def test_area_a_names_are_paragraphs_even_without_a_period_before_them():
    a = analyze_source(PROGRAM, "hdr.cbl")
    assert [p.name for p in a.program.paragraphs] == [
        "0000-INITIAL", "1100-FORMAT-ORDER-HEADER", "1100-EXIT", "2000-LINK-TO-TRAN", "2000-EXIT"]


def test_perform_targets_are_not_paragraphs_and_comment_text_is_ignored():
    a = analyze_source(PROGRAM, "hdr.cbl")
    initial = a.program.paragraph_map["0000-INITIAL"]
    assert initial.statement_count == 9          # includes the IF after the comment line
    assert all("SE8712" not in s.text for s in initial.statements)  # comment is not a statement
