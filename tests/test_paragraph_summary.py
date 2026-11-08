from src.copybooks import CopybookLibrary
from src.copybooks.knowledge import KnowledgeStore
from src.pipeline import analyze_source
from src.summary.paragraph_summary import build_catalog, paragraph_summary, program_insights, plain_condition

COPY = """       01  DEMO-REC.
           05  DEMO-FLAG-SW      PIC X(01) VALUE SPACE.
               88  DEMO-ON              VALUE 'Y'.
           05  DEMO-LIMIT        PIC 9(03).
"""

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG                PIC X(20).
       COPY DEMOCPY.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SET-FLAG
           PERFORM CHECK-FLAG
           STOP RUN.
       SET-FLAG.
           MOVE 'Y' TO DEMO-FLAG-SW.
       CHECK-FLAG.
           IF DEMO-ON
               MOVE 'FLAG ON' TO WS-MSG
           END-IF.
"""


def _analysis(tmp_path):
    library = CopybookLibrary.from_environment(texts={"DEMOCPY": COPY})
    store = KnowledgeStore(str(tmp_path / "kb.db"))
    store.upsert_field("DEMOCPY", "DEMO-REC.DEMO-FLAG-SW", "Flag that turns the demo on. Values: Y = Yes",
                       "", [], None)
    analysis = analyze_source(PROGRAM, "demo.cbl", library=library, knowledge=store)
    analysis.library = library
    return analysis


def test_88_condition_is_explained_through_its_parent_note(tmp_path):
    analysis = _analysis(tmp_path)
    catalog = build_catalog(analysis, analysis.library)
    text = plain_condition("DEMO-ON", catalog)
    assert "DEMO-ON is true when DEMO-FLAG-SW (Flag that turns the demo on) is 'Y'" in text


def test_paragraph_summary_reports_decision_and_change(tmp_path):
    analysis = _analysis(tmp_path)
    check = paragraph_summary(analysis, "CHECK-FLAG", library=analysis.library)
    assert check["decisions"][0]["line"] > 0
    assert "if DEMO-ON" in check["summary"]

    set_flag = paragraph_summary(analysis, "SET-FLAG", library=analysis.library)
    assert set_flag["changes"][0]["field"] == "DEMO-FLAG-SW"
    assert "sets DEMO-FLAG-SW to 'Y'" in set_flag["summary"]


def test_insights_group_88_tests_under_parent_field(tmp_path):
    analysis = _analysis(tmp_path)
    insights = program_insights(analysis, analysis.library)
    fields = {f["field"]: f for f in insights["decision_fields"]}
    assert "DEMO-FLAG-SW" in fields
    assert fields["DEMO-FLAG-SW"]["set_in"][0]["paragraph"] == "SET-FLAG"
