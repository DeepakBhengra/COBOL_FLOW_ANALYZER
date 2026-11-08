import json
import os

from fastapi.testclient import TestClient

from src.programlog import ProgramLog, source_fingerprint

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_programs", "sample01.cbl")


def _summary(name="DEMO"):
    return {
        "program": {"name": name},
        "stats": {"paragraphs": 2},
        "copybooks": {"used": [], "missing": []},
        "commarea": None,
        "paragraphs": [
            {"name": "MAIN-PARA", "status": "entry", "never_called": False, "reachable": True},
            {"name": "DEAD-PARA", "status": "never called", "never_called": True, "reachable": False},
        ],
    }


def test_runs_are_recorded_and_retrieved_by_fingerprint(tmp_path):
    log = ProgramLog(str(tmp_path / "log.db"), str(tmp_path / "log.jsonl"))
    fp = source_fingerprint("IDENTIFICATION DIVISION.")

    assert log.history(fp)["run_count"] == 0
    log.record_run(fp, "demo.cbl", _summary())
    log.record_run(fp, "renamed.cbl", _summary())

    history = log.history(fp)
    assert history["run_count"] == 2
    assert history["runs"][0]["source"] == "renamed.cbl"          # newest first
    assert history["runs"][0]["summary"]["stats"] == {"paragraphs": 2}   # summary is stored as given

    lines = (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["program"] == "DEMO"


def test_details_can_be_added_updated_and_removed(tmp_path):
    log = ProgramLog(str(tmp_path / "log.db"), str(tmp_path / "log.jsonl"))
    fp = source_fingerprint("x")
    log.add_detail(fp, "owner", "Payments team")
    log.add_detail(fp, "owner", "Billing team")                  # replaces the value
    log.add_detail(fp, "uses DB2", "yes", category="Database")   # new category and key on the fly

    details = {(d["category"], d["key"]): d["value"] for d in log.history(fp)["details"]}
    assert details == {("general", "owner"): "Billing team", ("Database", "uses DB2"): "yes"}

    assert log.delete_detail(fp, "owner")
    assert not log.delete_detail(fp, "owner")


def test_programs_lists_each_program_once(tmp_path):
    log = ProgramLog(str(tmp_path / "log.db"), str(tmp_path / "log.jsonl"))
    a, b = source_fingerprint("a"), source_fingerprint("b")
    log.record_run(a, "a.cbl", _summary("A"))
    log.record_run(a, "a.cbl", _summary("A"))
    log.record_run(b, "b.cbl", _summary("B"))

    rows = {r["fingerprint"]: r for r in log.programs()}
    assert rows[a]["run_count"] == 2 and rows[b]["run_count"] == 1
    assert len(rows) == 2


def test_analyze_endpoint_logs_run_and_returns_earlier_details(tmp_path, monkeypatch):
    monkeypatch.setenv("COBOL_PROGRAM_LOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("COBOL_PROGRAM_LOG_FILE", str(tmp_path / "log.jsonl"))
    from api import programlog_routes
    from api.server import app

    programlog_routes.program_log.cache_clear()
    client = TestClient(app)
    with open(SAMPLE, encoding="utf-8") as handle:
        source = handle.read()

    first = client.post("/api/analyze", json={"name": "sample01.cbl", "source": source}).json()
    assert first["log"]["previous_runs"] == 0

    fp = first["log"]["fingerprint"]
    added = client.put(f"/api/program-log/{fp}/details",
                       json={"category": "Notes", "key": "gotcha", "value": "check ERROR-PARA first"})
    assert added.status_code == 200

    second = client.post("/api/analyze", json={"name": "copy.cbl", "source": source}).json()
    assert second["log"]["fingerprint"] == fp
    assert second["log"]["previous_runs"] == 1
    assert second["log"]["details"][0]["value"] == "check ERROR-PARA first"

    history = client.get(f"/api/program-log/{fp}").json()
    assert history["run_count"] == 2

    assert client.get("/api/program-log").json()["programs"][0]["run_count"] == 2
    removed = client.delete(f"/api/program-log/{fp}/details", params={"key": "gotcha", "category": "Notes"})
    assert removed.status_code == 200 and removed.json()["details"] == []
    assert client.get("/api/program-log/0000").status_code == 404
    programlog_routes.program_log.cache_clear()
