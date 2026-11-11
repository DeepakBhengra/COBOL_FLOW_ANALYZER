"""The JSON bridge the COBOL analyst agent calls."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "agent_query.py")


def _query(payload):
    completed = subprocess.run(
        [sys.executable, SCRIPT],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_sample_overview_marks_unused_paragraph():
    result = _query({"command": "analyze", "sample": "sample01.cbl"})
    assert result["ok"] is True
    assert result["program"] == "ORDPROC"
    assert result["entry_paragraph"] == "MAIN-PARA"
    assert "UNUSED-PARA" in result["never_called"]
    assert "UNUSED-PARA" in result["unreachable"]
    names = [item["name"] for item in result["paragraphs"]]
    assert "ERROR-PARA" in names
    assert result["commarea"]["applicable"] is False


def test_paragraph_query_is_case_insensitive():
    result = _query({"command": "paragraph", "sample": "sample01.cbl", "paragraph": "error-para"})
    assert result["ok"] is True
    assert result["paragraph"] == "ERROR-PARA"
    assert result["reached_from"]
    assert "DISPLAY" in result["source"]
    assert result["start_line"] < result["end_line"]


def test_unknown_sample_is_an_error_object():
    result = _query({"command": "analyze", "sample": "missing.cbl"})
    assert result["ok"] is False
    assert "missing.cbl" in result["error"]
