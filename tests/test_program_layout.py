from src.copybooks import CopybookLibrary
from src.pipeline import analyze_source
from src.values.program_layout import working_layout

CUST = """       01  CUST-REC.
           05  CUST-ID          PIC 9(05).
           05  CUST-STATUS      PIC X(01).
               88  CUST-ACTIVE            VALUE 'A'.
"""

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LAYTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG              PIC X(01) VALUE 'N'.
           88  WS-ON                      VALUE 'Y'.
       COPY CUSTREC.
       01  WS-AMOUNT            PIC S9(05) COMP-3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
              INCLUDE SYTAJDLG
           END-EXEC
           STOP RUN.
"""


def test_working_storage_is_laid_out_with_its_copybook_and_dclgen_members():
    library = CopybookLibrary.from_environment(texts={"CUSTREC": CUST})
    analysis = analyze_source(PROGRAM, "laytest.cbl", library=library)
    analysis.library = library
    layout = working_layout(analysis, library)
    names = {i["name"]: i for i in layout["items"]}
    assert names["CUST-ID"]["source"] == "CUSTREC"
    assert names["WS-FLAG"]["source"] == "laytest.cbl"
    assert names["WS-FLAG"]["conditions"][0]["name"] == "WS-ON"
    assert names["CUST-ID"]["depth"] == 1
    kinds = {m["name"]: m["kind"] for m in layout["copybooks"]}
    assert kinds["CUSTREC"] == "copy"
    assert kinds["SYTAJDLG"] == "dclgen"
    assert "SYTAJDLG" in layout["missing"]
