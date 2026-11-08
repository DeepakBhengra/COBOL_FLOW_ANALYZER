import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.copybooks import CopybookLibrary, decode_bytes, expand_copybooks  # noqa: E402
from src.copybooks.reader import index_directory, read_copybook  # noqa: E402
from src.parser.source_format import normalize  # noqa: E402

BODY = "          05 CUST-NAME PIC X(30).\n"


def _write(path, data: bytes):
    path.write_bytes(data)
    return str(path)


def test_reads_plain_cpy_and_txt(tmp_path):
    _write(tmp_path / "A.cpy", BODY.encode("utf-8"))
    _write(tmp_path / "B.txt", BODY.encode("utf-8"))
    lib = CopybookLibrary(directories=[str(tmp_path)])
    assert lib.resolve("A")[1] == BODY
    assert lib.resolve("b")[1] == BODY
    assert lib.resolve("B")[0] == "B.txt"


def test_other_file_types_are_ignored(tmp_path):
    _write(tmp_path / "NOTES.md", b"not a copybook\n")
    _write(tmp_path / "DATA.csv", b"1,2,3\n")
    lib = CopybookLibrary(directories=[str(tmp_path)])
    assert lib.available() == []
    assert lib.resolve("NOTES") is None


def test_utf16_with_bom_is_read(tmp_path):
    path = _write(tmp_path / "U16.txt", BODY.encode("utf-16"))  # Python writes a BOM
    assert read_copybook(path) == BODY


def test_utf8_with_bom_is_read(tmp_path):
    path = _write(tmp_path / "U8.txt", b"\xef\xbb\xbf" + BODY.encode("utf-8"))
    assert read_copybook(path) == BODY


def test_windows_1252_text_is_read(tmp_path):
    text = "          05 CUST-NAME PIC X(30).  * café €\n"
    path = _write(tmp_path / "W.txt", text.encode("cp1252"))
    assert read_copybook(path) == text


def test_undecodable_bytes_still_read():
    assert decode_bytes(b"\x81\x8d\x8f\x90\x9d") != ""


def test_cpy_wins_over_txt_and_the_other_is_reported(tmp_path):
    _write(tmp_path / "DUP.txt", b"05 FROM-TXT PIC X.\n")
    _write(tmp_path / "DUP.cpy", b"05 FROM-CPY PIC X.\n")
    lib = CopybookLibrary(directories=[str(tmp_path)])
    assert "FROM-CPY" in lib.resolve("DUP")[1]
    assert any(name == "DUP" and path.endswith("DUP.txt") for name, path in lib.shadowed)


def test_first_folder_wins_across_folders(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    _write(first / "X.txt", b"05 FIRST PIC X.\n")
    _write(second / "X.txt", b"05 SECOND PIC X.\n")
    lib = CopybookLibrary(directories=[str(first), str(second)])
    assert "FIRST" in lib.resolve("X")[1]


def test_uploaded_text_takes_priority_over_folder(tmp_path):
    _write(tmp_path / "X.cpy", b"05 FROM-DISK PIC X.\n")
    lib = CopybookLibrary(directories=[str(tmp_path)], texts={"X": "05 UPLOADED PIC X.\n"})
    assert "UPLOADED" in lib.resolve("X")[1]


def test_txt_copybook_expands_into_a_program(tmp_path):
    _write(tmp_path / "CUSTCOMM.txt", BODY.encode("utf-16"))
    lib = CopybookLibrary(directories=[str(tmp_path)])
    result = expand_copybooks(normalize("       01 REC.\n       COPY CUSTCOMM.\n"), lib, "main.cbl")
    assert [l.text.strip() for l in result.lines] == ["01 REC.", "05 CUST-NAME PIC X(30)."]
    assert result.used[0].source == "CUSTCOMM.txt"
    assert result.lines[1].origin == "CUSTCOMM.txt:1"


def test_index_directory_on_missing_folder_is_empty():
    assert index_directory(os.path.join(ROOT, "no-such-folder")).files == {}
