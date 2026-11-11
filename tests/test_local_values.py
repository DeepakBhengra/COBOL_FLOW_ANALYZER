import os

from src.pipeline import analyze_source
from src.values import analyze_values

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_programs", "parse_input_demo.cbl")


def _analysis():
    with open(SAMPLE, encoding="utf-8") as handle:
        return analyze_source(handle.read(), "parse_input_demo.cbl")


def test_computed_value_is_carried_to_the_next_move():
    result = analyze_values(_analysis(), "0500-PARSE-INPUT")
    assert "line 21: WS-FUNC-LEN-N-1 = 2" in result["chain"]
    assert "line 22: WS-START-POS = 2" in result["chain"]


def test_reference_modification_keeps_the_symbolic_form():
    result = analyze_values(_analysis(), "0500-PARSE-INPUT")
    assert any("RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)" in c for c in result["chain"])
    explains = [s["explain"] for s in result["slices"]]
    assert "1 byte of RCV-DATA-BUFFER-AREA at position 3" in explains


def test_decided_condition_applies_only_one_branch_and_else_is_recorded():
    from src.values.local_values import const
    # Called from 0500-PARSE-INPUT, where WS-START-POS is 2 when this paragraph runs.
    result = analyze_values(_analysis(), "0550-FIND-NEXT-DELIMITER", initial_env={"WS-START-POS": const(2)})
    decision = next(d for d in result["decisions"] if d["line"] == 32)
    assert decision["decided"] == "false"
    assert decision["when_else"] == ["COMPUTE WS-MOVE-LEN = WS-CHAR-POS - WS-START-POS"]
    assert "line 35: WS-MOVE-LEN = 1" in result["chain"]


def test_unknown_input_stays_undecided_with_both_branches():
    result = analyze_values(_analysis(), "0500-PARSE-INPUT")
    decision = next(d for d in result["decisions"] if d["line"] == 24)
    assert decision["decided"] is None
    assert decision["when_else"] == ["MOVE SPACES TO ORRORL-LINE-REQUEST"]


def test_a_paragraph_lists_every_local_it_uses_with_how_it_uses_it():
    result = analyze_values(_analysis(), "0500-PARSE-INPUT")
    names = {v["name"]: v for v in result["used_variables"]}
    assert "WS-START-POS" in names and "WS-FUNC-LEN" in names
    assert names["WS-START-POS"]["written"]
    assert names["WS-FUNC-LEN"]["read"]


def test_the_work_budget_stops_a_long_trace_and_says_so(monkeypatch):
    import src.values.local_values as lv
    monkeypatch.setattr(lv, "MAX_STEPS", 3)
    result = analyze_values(_analysis(), "0500-PARSE-INPUT")
    assert result["exhausted"] is True
    assert any("stopped after 3 steps" in n for n in result["notes"])
