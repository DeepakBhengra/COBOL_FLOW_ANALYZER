"""A requirement becomes a concrete edit from the analysis, not from a hardcoded program."""
import hashlib
from pathlib import Path

from src.changes import propose_change
from src.changes.propose import open_program
from src.copybooks import CopybookLibrary
from src.pipeline import analyze_source

ROOT = Path(__file__).resolve().parents[1]
INP389 = ROOT / "sample_programs" / "INP389.cbl.txt"

DCL = """
           EXEC SQL DECLARE DEMO_ROW TABLE
           ( ID         INTEGER NOT NULL,
             ACTV_FLG   CHAR(1) NOT NULL,
             PROMO_FLG  CHAR(1) NOT NULL
           ) END-EXEC.
      * COBOL DECLARATION FOR TABLE DEMO_ROW
       01  DCLDEMO-ROW.
      *                       ACTV_FLG
           10 DEMO-ACTV-FLG   PIC X(1).
      *                       PROMO_FLG
           10 DEMO-PROMO-FLG  PIC X(1).
      *                       ID
           10 DEMO-ID         PIC S9(9) COMP-5.
"""

PROGRAM = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
                INCLUDE DEMOSET
           END-EXEC.
       PROCEDURE DIVISION.
       UPDATE-ROW.
           MOVE 1              TO DEMO-ID.
           MOVE 'N'            TO DEMO-ACTV-FLG.
           EXEC SQL
              UPDATE DEMO_ROW
                 SET ACTV_FLG = :DEMO-ACTV-FLG
               WHERE ID       = :DEMO-ID
           END-EXEC.
           GOBACK.
"""


def _demo(requirement):
    library = CopybookLibrary.from_environment(texts={"DEMOSET": DCL})
    analysis = analyze_source(PROGRAM, "demo.cbl", library=library)
    return propose_change(analysis, requirement, library)


def test_inp389_promo_flag_is_added_to_the_existing_update():
    before = hashlib.sha256(INP389.read_bytes()).hexdigest()
    analysis, library = open_program(str(INP389))
    proposal = propose_change(analysis, "update SETATRK-ACOP-PROMO-FLG with 'Y'", library)

    assert proposal["ok"] is True
    assert proposal["change_required"] is True
    assert proposal["field"]["name"] == "SETATRK-ACOP-PROMO-FLG"
    assert proposal["field"]["column"] == "ACOP_PROMO_FLG"
    assert proposal["field"]["table"] == "ACOP_TRK"
    assert proposal["field"]["pic"] == "X(1)"
    assert proposal["field"]["not_null"] is True
    assert proposal["placement"]["paragraph"] == "1000-UPDATE-ACOP-TRK"
    assert "INP389.cbl.txt" in proposal["placement"]["origin"]

    texts = [edit["text"] for edit in proposal["edits"]]
    assert any("MOVE 'Y'" in text and "SETATRK-ACOP-PROMO-FLG" in text for text in texts)
    assert any("ACOP_PROMO_FLG" in text and ":SETATRK-ACOP-PROMO-FLG" in text for text in texts)
    assert proposal["proposed_paragraph"].count("ACOP_PROMO_FLG") == 1
    assert "MOVE 'N'" in proposal["proposed_paragraph"]
    assert "WHERE" in proposal["proposed_paragraph"]
    assert hashlib.sha256(INP389.read_bytes()).hexdigest() == before
    assert any("source file was not changed" in note for note in proposal["consequences"])


def test_column_name_and_move_statement_name_the_same_field():
    analysis, library = open_program(str(INP389))
    by_column = propose_change(analysis, "set ACOP_PROMO_FLG to Y", library)
    by_move = propose_change(analysis, "MOVE 'Y' TO SETATRK-ACOP-PROMO-FLG", library)
    assert by_column["field"]["name"] == "SETATRK-ACOP-PROMO-FLG"
    assert by_move["edits"][0]["text"] == by_column["edits"][0]["text"]


def test_same_literal_is_already_coded():
    analysis, library = open_program(str(INP389))
    proposal = propose_change(analysis, "set SETATRK-ACOP-ACTV-FLG to 'N'", library)
    assert proposal["ok"] is True
    assert proposal["change_required"] is False
    assert proposal["edits"] == []
    assert "No code change" in proposal["understood"]


def test_changing_an_existing_literal_does_not_add_the_column_twice():
    analysis, library = open_program(str(INP389))
    proposal = propose_change(analysis, "set SETATRK-ACOP-ACTV-FLG to 'Y'", library)
    assert proposal["change_required"] is True
    assert len(proposal["edits"]) == 1
    assert proposal["edits"][0]["kind"] == "replace_line"
    assert "MOVE 'Y'" in proposal["edits"][0]["text"]
    assert "SETATRK-ACOP-ACTV-FLG" in proposal["edits"][0]["text"]
    assert proposal["proposed_paragraph"].count("ACOP_ACTV_FLG") == 1


def test_unknown_field_explains_why_it_cannot_be_placed():
    analysis, library = open_program(str(INP389))
    proposal = propose_change(analysis, "update NO-SUCH-FLAG with 'Y'", library)
    assert proposal["ok"] is False
    assert proposal["edits"] == []
    assert "not in this analysis" in proposal["error"]


def test_a_different_program_uses_the_same_rules():
    proposal = _demo("update DEMO-PROMO-FLG with 'Y'")
    assert proposal["ok"] is True
    assert proposal["placement"]["paragraph"] == "UPDATE-ROW"
    assert proposal["placement"]["table"] == "DEMO_ROW"
    joined = "\n".join(edit["text"] for edit in proposal["edits"])
    assert "MOVE 'Y'" in joined and "DEMO-PROMO-FLG" in joined
    assert "PROMO_FLG" in joined and ":DEMO-PROMO-FLG" in joined
    assert "ACTV_FLG" in proposal["proposed_paragraph"]


def test_value_longer_than_the_picture_is_warned():
    analysis, library = open_program(str(INP389))
    proposal = propose_change(analysis, "update SETATRK-ACOP-PROMO-FLG with 'YES'", library)
    assert proposal["ok"] is True
    assert any("PIC X(1)" in note for note in proposal["warnings"])
