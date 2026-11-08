import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.copybooks import CopybookLibrary  # noqa: E402
from src.copybooks.knowledge import KnowledgeStore  # noqa: E402
from src.copybooks.layout import describe, layout_of_copybook  # noqa: E402
from src.pipeline import analyze_source  # noqa: E402

COPYBOOKS = os.path.join(ROOT, "sample_programs", "copybooks")
CUSTCOMM = open(os.path.join(COPYBOOKS, "CUSTCOMM.cpy"), encoding="utf-8").read()
PROGRAM = os.path.join(ROOT, "sample_programs", "cics_custcopy.cbl")


# ------------------------------------------------------------ type descriptions
@pytest.mark.parametrize("pic,usage,label", [
    ("X(8)", "DISPLAY", "Alphanumeric"),
    ("A(3)", "DISPLAY", "Alphabetic"),
    ("9(2)", "DISPLAY", "Zoned decimal (DISPLAY)"),
    ("S9(9)V99", "COMP-3", "Packed decimal (COMP-3)"),
    ("S9(4)", "COMP", "Binary integer (COMP)"),
    ("S9(16)", "COMP-5", "Binary integer (COMP-5)"),
    (None, "COMP-1", "Floating point, single precision (COMP-1)"),
    (None, "COMP-2", "Floating point, double precision (COMP-2)"),
])
def test_type_descriptions(pic, usage, label):
    assert describe(pic, usage, False)["type_label"] == label


def test_digits_decimals_and_sign():
    info = describe("S9(9)V99", "COMP-3", False)
    assert (info["digits"], info["decimals"], info["signed"]) == (11, 2, True)


# ------------------------------------------------------------ layout
def test_copybook_layout_matches_the_program_layout():
    layout = layout_of_copybook("CUSTCOMM", CUSTCOMM)
    assert layout.total_length == 107
    by = {i.path: i for i in layout.items}
    assert by["CUST-ID"].offset == 1 and by["CUST-ID"].length == 8
    assert by["CUST-BALANCE"].type_label == "Packed decimal (COMP-3)"
    assert by["CUST-BALANCE"].length == 6


def test_condition_names_are_attached_to_their_field():
    text = CUSTCOMM + "          05 CUST-STATUS PIC X.\n             88 CUST-ACTIVE VALUE 'A'.\n             88 CUST-CLOSED VALUE 'C' 'X'.\n"
    layout = layout_of_copybook("X", text)
    status = next(i for i in layout.items if i.path == "CUST-STATUS")
    assert [c.name for c in status.conditions] == ["CUST-ACTIVE", "CUST-CLOSED"]
    assert status.conditions[1].values == "'C' 'X'"


def test_occurs_redefines_and_filler_paths():
    text = (
        "       01 REC.\n"
        "          05 TBL OCCURS 3 TIMES PIC X(2).\n"
        "          05 RED REDEFINES TBL PIC 9(6).\n"
        "          05 FILLER PIC X(3).\n"
        "          05 FILLER PIC X(1).\n"
    )
    layout = layout_of_copybook("T", text)
    by = {i.path: i for i in layout.items}
    assert by["REC.TBL"].length == 6 and by["REC.TBL"].occurs == 3
    assert by["REC.RED"].offset == by["REC.TBL"].offset
    assert by["REC.RED"].redefines == "TBL"
    assert "REC.FILLER" in by and "REC.FILLER#2" in by
    assert layout.total_length == 6 + 3 + 1


def test_copybook_without_data_entries_is_flagged():
    layout = layout_of_copybook("CUSTMSG", "           MOVE A TO B.\n           DISPLAY 'X'.\n")
    assert not layout.has_data
    assert layout.items == []


# ------------------------------------------------------------ knowledge store
def test_store_round_trip(tmp_path):
    store = KnowledgeStore(str(tmp_path / "kb.db"))
    store.upsert_field("custcomm", "CUST-ID", "Customer number", "Identifier", ["key"], "abc")
    fields = store.get_fields("CUSTCOMM")
    assert fields["CUST-ID"]["meaning"] == "Customer number"
    assert fields["CUST-ID"]["tags"] == ["key"]
    store.upsert_field("CUSTCOMM", "CUST-ID", "Updated", "", [], "abc")
    assert store.get_fields("CUSTCOMM")["CUST-ID"]["meaning"] == "Updated"
    assert store.annotated_counts() == {"CUSTCOMM": 1}
    assert store.delete_field("CUSTCOMM", "CUST-ID")
    assert not store.delete_field("CUSTCOMM", "CUST-ID")


def test_description_round_trip(tmp_path):
    store = KnowledgeStore(str(tmp_path / "kb.db"))
    store.set_description("CUSTCOMM", "Customer area", "fp1")
    assert store.get_description("CUSTCOMM")["description"] == "Customer area"
    assert store.export_json()["copybooks"][0]["copybook"] == "CUSTCOMM"


# ------------------------------------------------------------ learning across programs
def test_note_on_copybook_field_appears_when_a_program_copies_it(tmp_path):
    store = KnowledgeStore(str(tmp_path / "kb.db"))
    library = CopybookLibrary(directories=[COPYBOOKS])
    layout = layout_of_copybook("CUSTCOMM", CUSTCOMM)
    store.upsert_field("CUSTCOMM", "CUST-ID", "Customer number keyed on the screen", "Identifier", [],
                       layout.fingerprint)

    with open(PROGRAM, encoding="utf-8") as handle:
        a = analyze_source(handle.read(), "cics_custcopy.cbl", library=library, knowledge=store)

    assert a.field_meanings["DFHCOMMAREA.CUST-ID"]["meaning"] == "Customer number keyed on the screen"
    field = next(f for f in a.commarea.fields if f.path == "DFHCOMMAREA.CUST-ID")
    assert field.meaning == "Customer number keyed on the screen"
    assert field.category == "Identifier"
    assert not field.note_stale


def test_note_still_applies_under_replacing_renames(tmp_path):
    # CUSTFLD is copied with ==:PFX:== BY ==WS==; a note on the declared name still applies.
    store = KnowledgeStore(str(tmp_path / "kb.db"))
    library = CopybookLibrary(directories=[COPYBOOKS])
    store.upsert_field("CUSTFLD", ":PFX:-RESP", "Response code from CICS", "Status", [], None)
    with open(PROGRAM, encoding="utf-8") as handle:
        a = analyze_source(handle.read(), "cics_custcopy.cbl", library=library, knowledge=store)
    assert a.field_meanings["WS-RESP"]["meaning"] == "Response code from CICS"


def test_note_is_marked_stale_when_the_copybook_changes(tmp_path):
    store = KnowledgeStore(str(tmp_path / "kb.db"))
    old_layout = layout_of_copybook("CUSTCOMM", CUSTCOMM)
    store.upsert_field("CUSTCOMM", "CUST-ID", "Customer number", "", [], old_layout.fingerprint)

    changed = CUSTCOMM + "          05 CUST-EXTRA PIC X.\n"
    library = CopybookLibrary(texts={"CUSTCOMM": changed})
    with open(PROGRAM, encoding="utf-8") as handle:
        a = analyze_source(handle.read(), "cics_custcopy.cbl", library=library, knowledge=store)
    assert a.field_meanings["DFHCOMMAREA.CUST-ID"]["stale"] is True


def test_no_store_means_no_meanings():
    with open(PROGRAM, encoding="utf-8") as handle:
        a = analyze_source(handle.read(), "cics_custcopy.cbl", library=CopybookLibrary(directories=[COPYBOOKS]))
    assert a.field_meanings == {}


# ------------------------------------------------------------ API
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COBOL_KNOWLEDGE_DB", str(tmp_path / "kb.db"))
    from fastapi.testclient import TestClient

    import api.copybook_routes as routes
    from api.server import app

    routes.knowledge.cache_clear()
    routes.library.cache_clear()
    yield TestClient(app)
    routes.knowledge.cache_clear()
    routes.library.cache_clear()


def test_api_lists_and_shows_a_layout(client):
    listing = client.get("/api/copybooks", params={"q": "CUSTCOMM"}).json()
    assert listing["total"] == 1
    layout = client.get("/api/copybooks/CUSTCOMM").json()
    assert layout["total_length"] == 107
    assert layout["items"][1]["path"] == "CUST-ID"
    assert layout["items"][1]["note"] is None


def test_api_saves_and_deletes_a_field_note(client):
    r = client.put("/api/copybooks/CUSTCOMM/fields/CUST-ID",
                   json={"meaning": "Customer number", "category": "Identifier", "tags": ["key"]})
    assert r.status_code == 200
    item = next(i for i in client.get("/api/copybooks/CUSTCOMM").json()["items"] if i["path"] == "CUST-ID")
    assert item["note"]["meaning"] == "Customer number"
    assert client.delete("/api/copybooks/CUSTCOMM/fields/CUST-ID").status_code == 200
    assert client.delete("/api/copybooks/CUSTCOMM/fields/CUST-ID").status_code == 404


def test_api_rejects_unknown_fields_and_categories(client):
    assert client.put("/api/copybooks/CUSTCOMM/fields/NOPE",
                      json={"meaning": "x"}).status_code == 404
    assert client.put("/api/copybooks/CUSTCOMM/fields/CUST-ID",
                      json={"meaning": "x", "category": "Bogus"}).status_code == 422
    assert client.put("/api/copybooks/CUSTCOMM/fields/CUST-ID",
                      json={"meaning": ""}).status_code == 422


def test_api_unknown_copybook_is_404(client):
    assert client.get("/api/copybooks/NO-SUCH-BOOK").status_code == 404
