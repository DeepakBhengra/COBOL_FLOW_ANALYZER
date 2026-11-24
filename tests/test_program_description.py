from src.parser.description import program_description
from src.pipeline import analyze_source

HEADER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID.             DEMO01.
       AUTHOR.                 SOMEONE.
       DATE-WRITTEN.           26-AUG-2026.
       DATE-COMPILED.
      *
      ******************************************************************
      *                         COBOL II                               *
      ******************************************************************
      * PURPOSE: This is a demo utility that trims order lines.        *
      *                                                                *
      * EXAMPLE 1: Trim the first line.                                *
      *            QMGR=MQP1,                                          *
      ******************************************************************
      * REVISIONS INFO:                                                *
      * XX/XX/26  MKA  INITIAL VERSION                                 *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(01).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def test_description_is_the_comment_block_between_date_compiled_and_revisions():
    text = program_description(HEADER)
    assert "COBOL II" in text
    assert "PURPOSE: This is a demo utility that trims order lines." in text
    assert "EXAMPLE 1: Trim the first line." in text
    assert "QMGR=MQP1," in text
    assert "REVISIONS" not in text and "DATE-COMPILED" not in text
    assert "*" not in text


def test_the_analysis_carries_the_description():
    analysis = analyze_source(HEADER, "demo01.cbl")
    assert "PURPOSE: This is a demo utility" in analysis.program.description


def test_no_date_compiled_means_no_description():
    assert program_description("       PROGRAM-ID. X.\n") == ""
