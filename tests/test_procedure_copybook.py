from src.copybooks import CopybookLibrary
from src.pipeline import analyze_source
from src.summary.paragraph_summary import paragraph_summary
from src.convert.python_gen import generate
from src.business.logic_extraction import extract
from api.copybook_routes import _looks_like_code
from src.parser.source_format import normalize

ERXBATCH = """      *** STANDARD ABEND ROUTINE
           DISPLAY 'WS-ERROR-INTERFACE = ', WS-ERROR-INTERFACE.
           CALL 'ERU100' USING WS-ERROR-INTERFACE.
           IF WS-ERROR-NO-RESPONSE
              NEXT SENTENCE
           ELSE
              IF WS-ERROR-CONTINUE
                 NEXT SENTENCE
              ELSE
                 MOVE WS-ERROR-RETURN-CODE TO RETURN-CODE
                 GOBACK.
"""

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ABNDTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ERROR-INTERFACE   PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 9999-ABEND
           STOP RUN.
       9999-ABEND.
           COPY ERXBATCH.
"""


def _analysis():
    library = CopybookLibrary.from_environment(texts={"ERXBATCH": ERXBATCH})
    return analyze_source(PROGRAM, "abndtest.cbl", library=library)


def test_a_code_copybook_is_recognised_as_procedure_not_data():
    assert _looks_like_code([{"number": n, "text": t} for n, t in enumerate(ERXBATCH.splitlines(), 1)])


def test_summary_and_python_say_the_code_comes_from_the_copybook():
    analysis = _analysis()
    summary = paragraph_summary(analysis, "9999-ABEND")
    assert "(in copybook ERXBATCH" in summary["summary"]
    gen = generate(analysis, ["9999-ABEND"])
    assert "p.origin('ERXBATCH" in gen["module"]
    result = extract(gen["module"], gen["paragraphs"], {})
    para = next(p for p in result["paragraphs"] if p["name"] == "9999-ABEND")
    assert any("from copybook ERXBATCH" in s for s in para["explanation"])
    labels = [n["label"] for n in para["flow"]["nodes"]]
    assert any(label.startswith("[ERXBATCH") for label in labels)
