from src.pipeline import analyze_source
from src.convert.python_gen import generate
from src.business.logic_extraction import extract

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-SQLCODE-STATUS    PIC S9(04) COMP-3 VALUE +0.
               88  WS-NORESP                   VALUE 0.
               88  WS-NOT-FOUND                VALUE +100.
           05  WS-INDEX             PIC 9(02) VALUE 0.
           05  WS-TEXT              PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 1000-CHECK
           STOP RUN.
       1000-CHECK.
           EVALUATE TRUE
              WHEN WS-NORESP
                 CONTINUE
              WHEN WS-NOT-FOUND
                 CONTINUE
              WHEN OTHER
                 MOVE 'X' TO WS-TEXT
           END-EVALUATE
           PERFORM VARYING WS-INDEX FROM 1 BY 1
                   UNTIL WS-INDEX > 3
              MOVE 'Y' TO WS-TEXT
           END-PERFORM.
"""


def _generated():
    analysis = analyze_source(PROGRAM, "bltest.cbl")
    return generate(analysis, ["1000-CHECK"])


def test_numeric_88_values_are_tested_not_always_false():
    module = _generated()["module"]
    assert "eq(p.get('WS-SQLCODE-STATUS'), '0')" in module
    assert "if (False)" not in module


def test_perform_varying_becomes_a_loop_that_steps_the_index():
    module = _generated()["module"]
    assert "p.put('WS-INDEX', 1)" in module
    assert "p.put('WS-INDEX', num(p.get('WS-INDEX')) + num(1))" in module


def test_business_logic_explains_the_rules_and_flags_the_issues():
    gen = _generated()
    result = extract(gen["module"], gen["paragraphs"], {"WS-TEXT": "text shown on the screen"})
    para = next(p for p in result["paragraphs"] if p["name"] == "1000-CHECK")
    assert any(s.startswith("Repeat until") for s in para["explanation"])
    assert any("text shown on the screen" in s for s in para["explanation"])
    kinds = {f["kind"] for f in result["findings"]}
    assert "constant_condition" not in kinds


def test_sql_text_keeps_its_commas_and_host_variables():
    source = PROGRAM.replace("           PERFORM 1000-CHECK\n",
                             "           PERFORM 1000-CHECK\n           PERFORM 2000-SQL.\n")
    source = source.replace("       1000-CHECK.\n",
                            "       2000-SQL.\n"
                            "           EXEC SQL UPDATE T SET A = :WS-INDEX ,B = :WS-TEXT\n"
                            "           END-EXEC.\n"
                            "       1000-CHECK.\n")
    analysis = analyze_source(source, "bltest.cbl")
    gen = generate(analysis, ["2000-SQL"])
    result = extract(gen["module"], gen["paragraphs"])
    kinds = [f["kind"] for f in result["findings"]]
    assert "sql_missing_comma" not in kinds
    assert "sql_host_variable" not in kinds
    assert ",B = :WS-TEXT" in gen["module"]
