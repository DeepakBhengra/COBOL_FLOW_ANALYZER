import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.copybooks import CopybookLibrary, expand_copybooks, parse_copy_statement  # noqa: E402
from src.parser.source_format import LogicalLine, normalize  # noqa: E402
from src.pipeline import analyze_file, analyze_source  # noqa: E402

PROGRAM = os.path.join(ROOT, "sample_programs", "cics_custcopy.cbl")
COPYBOOKS = os.path.join(ROOT, "sample_programs", "copybooks")
ORIGINAL = os.path.join(ROOT, "sample_programs", "cics_custinq.cbl")


def _lines(text):
    return [LogicalLine(i, t) for i, t in enumerate(text.splitlines(), start=1)]


def _expand(source, texts, name="main.cbl"):
    library = CopybookLibrary(texts=texts)
    return expand_copybooks(normalize(source), library, name)


# ------------------------------------------------------------ the sample program
def test_copybook_program_gives_the_same_commarea_as_the_hand_written_one():
    copied = analyze_file(PROGRAM).commarea
    manual = analyze_file(ORIGINAL).commarea
    assert copied.area_length == manual.area_length == 107
    assert [(f.offset, f.length) for f in copied.fields] == [(f.offset, f.length) for f in manual.fields]


def test_copybook_program_analyses_copied_procedure_code():
    a = analyze_file(PROGRAM)
    statements = [s.text for s in a.program.paragraph_map["READ-CUSTOMER"].statements]
    assert "MOVE CUST-MESSAGE TO WS-LAST-MESSAGE" in statements
    assert any(s.startswith("DISPLAY 'CUSTINQ") for s in statements)


def test_copybook_program_reports_what_was_used():
    a = analyze_file(PROGRAM)
    assert a.copybooks.expanded
    assert [u.name for u in a.copybooks.used] == ["CUSTFLD", "CUSTCOMM", "CUSTMSG"]
    assert a.copybooks.missing == []
    assert a.copybooks.problems == []


def test_line_origins_point_back_to_the_copybook_file():
    a = analyze_file(PROGRAM)
    origins = set(a.program.line_origin.values())
    assert "CUSTCOMM.cpy:1" in origins
    assert "CUSTMSG.cpy:2" in origins
    assert any(o.startswith("cics_custcopy.cbl:") for o in origins)


def test_replacing_renames_the_copied_items():
    a = analyze_file(PROGRAM)
    text = "\n".join(a.program.source_lines.values())
    assert "WS-RESP" in text and ":PFX:" not in text
    assert "WS-REC" in text


# ------------------------------------------------------------ expansion rules
def test_plain_copy_in_data_division():
    result = _expand("       01 A.\n       COPY NUM.\n", {"NUM": "          05 B PIC X(2).\n"})
    text = [line.text.strip() for line in result.lines]
    assert text == ["01 A.", "05 B PIC X(2)."]
    assert result.used[0].name == "NUM"


def test_copy_statement_spanning_lines_with_replacing():
    src = "       COPY FLD\n           REPLACING ==:P:== BY ==WS==.\n"
    result = _expand(src, {"FLD": "       01 :P:-X PIC X.\n"})
    assert result.lines[0].text.strip() == "01 WS-X PIC X."


def test_word_replacing_matches_whole_words_only():
    src = "       COPY FLD REPLACING ABC BY XYZ.\n"
    result = _expand(src, {"FLD": "       MOVE ABC TO ABCD.\n"})
    assert result.lines[0].text.strip() == "MOVE XYZ TO ABCD."


def test_nested_copybooks_are_expanded():
    result = _expand("       COPY OUTER.\n", {
        "OUTER": "       COPY INNER.\n       05 OUTER-X PIC X.\n",
        "INNER": "       05 INNER-X PIC X.\n",
    })
    assert [l.text.strip() for l in result.lines] == ["05 INNER-X PIC X.", "05 OUTER-X PIC X."]
    assert [u.depth for u in result.used] == [0, 1]


def test_circular_copy_is_reported_not_followed():
    result = _expand("       COPY A.\n", {"A": "       COPY B.\n", "B": "       COPY A.\n"})
    assert any("circular" in p for p in result.problems)
    assert len(result.lines) == 0


def test_missing_copybook_is_reported_and_analysis_continues():
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T1.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "       COPY NOPE.\n"
        "           STOP RUN.\n"
    )
    a = analyze_source(src, "t1.cbl", library=CopybookLibrary())
    assert a.copybooks.missing == ["NOPE"]
    assert a.program.paragraphs[0].name == "MAIN-PARA"
    assert a.program.paragraphs[0].statements[0].kind == "TERMINATE"


def test_program_without_copy_is_unchanged():
    result = _expand("       MAIN-PARA.\n           STOP RUN.\n", {})
    assert not result.expanded
    assert [l.number for l in result.lines] == [1, 2]


def test_parse_copy_statement_forms():
    assert parse_copy_statement("COPY CUSTCOMM.").name == "CUSTCOMM"
    assert parse_copy_statement("COPY CUSTCOMM OF MYLIB.").name == "CUSTCOMM"
    copy = parse_copy_statement("COPY X REPLACING ==:P:== BY ==WS-== ABC BY XYZ.")
    assert copy.replacements == [(":P:", "WS-", True), ("ABC", "XYZ", False)]


def test_directory_lookup_matches_extensions(tmp_path):
    (tmp_path / "CUSTCOMM.cpy").write_text("       05 X PIC X.\n", encoding="utf-8")
    library = CopybookLibrary(directories=[str(tmp_path)])
    label, text = library.resolve("custcomm")
    assert label == "CUSTCOMM.cpy"
    assert "05 X" in text
    assert library.resolve("MISSING") is None
