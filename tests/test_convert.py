import importlib.util
import sys

from src.pipeline import analyze_source
from src.convert.python_gen import generate

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONVT.
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
           05  WS-COUNT             PIC S9(03) COMP-3 VALUE +0.
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
           END-IF
           ADD 1 TO WS-COUNT.
"""


def _load(tmp_path, paragraphs):
    analysis = analyze_source(PROGRAM, "convt.cbl")
    result = generate(analysis, paragraphs)
    (tmp_path / "cobol_runtime.py").write_text(result["runtime"], encoding="utf-8")
    (tmp_path / "converted.py").write_text(result["module"], encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        spec = importlib.util.spec_from_file_location("converted", tmp_path / "converted.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(tmp_path))
    return module, result


def test_converted_paragraphs_run_like_the_cobol(tmp_path):
    module, result = _load(tmp_path, ["0500-PARSE-INPUT"])
    assert "0550-FIND-NEXT-DELIMITER" in result["paragraphs"]
    p = module.new_program()
    p.put("RCV-DATA-BUFFER-AREA", "OL \t")
    module.run(p, "0500-PARSE-INPUT")
    assert p.get("WS-FUNCTION") == "OL"
    assert p.get("WS-DELIM-SW") == "Y"          # the tab at position 4 was found
    assert p.get("WS-COUNT") == 1               # ADD 1 TO WS-COUNT ran


def test_the_other_branch_is_taken_when_the_byte_differs(tmp_path):
    module, _ = _load(tmp_path, ["0500-PARSE-INPUT"])
    p = module.new_program()
    p.put("RCV-DATA-BUFFER-AREA", "OL  X")
    module.run(p, "0500-PARSE-INPUT")
    assert p.get("WS-DELIM-SW") == "N"


def test_packed_and_numeric_storage_follow_cobol_rules(tmp_path):
    module, _ = _load(tmp_path, ["0500-PARSE-INPUT"])
    p = module.new_program()
    p.put("WS-START-POS", 12345)
    assert p.get("WS-START-POS") == 345          # 3 digits: the leading digits are dropped
    p.put("WS-COUNT", -7)
    assert p.get("WS-COUNT") == -7
