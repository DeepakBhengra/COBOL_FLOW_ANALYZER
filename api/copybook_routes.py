"""Copybook endpoints: browse the library, view a layout, and save what each field means."""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.copybooks import CopybookLibrary
from src.copybooks.knowledge import KnowledgeStore
from src.copybooks.layout import CATEGORIES, layout_of_copybook
from src.parser.source_format import normalize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COPYBOOK_DIR = os.path.join(ROOT, "sample_programs", "copybooks")

router = APIRouter(prefix="/api/copybooks", tags=["copybooks"])


@lru_cache(maxsize=1)
def library() -> CopybookLibrary:
    return CopybookLibrary.from_environment(extra=[DEFAULT_COPYBOOK_DIR])


@lru_cache(maxsize=1)
def knowledge() -> KnowledgeStore:
    return KnowledgeStore()


class FieldNote(BaseModel):
    meaning: str = Field(min_length=1, max_length=2000)
    category: str = ""
    tags: list[str] = []


class DescriptionBody(BaseModel):
    description: str = Field(default="", max_length=5000)


def _load(name: str):
    found = library().resolve(name)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Copybook {name} was not found.")
    label, text = found
    return label, layout_of_copybook(name.upper(), text)


@router.get("")
def list_copybooks(q: str = "", limit: int = 300) -> dict:
    names = library().available()
    needle = q.strip().upper()
    if needle:
        names = [n for n in names if needle in n]
    counts = knowledge().annotated_counts()
    return {
        "total": len(names),
        "items": [{"name": n, "annotated_fields": counts.get(n, 0)} for n in names[:max(1, min(limit, 1000))]],
    }


@router.get("/categories")
def categories() -> dict:
    return {"categories": CATEGORIES}


@router.get("/export")
def export() -> dict:
    return knowledge().export_json()


PROCEDURE_WORDS = ("DISPLAY", "CALL", "MOVE", "IF", "GOBACK", "STOP", "PERFORM", "EXEC", "COMPUTE", "GO", "ELSE")


def _looks_like_code(code: list[dict]) -> bool:
    """A copybook with statements and no data entries holds procedure code (for example an abend routine)."""
    words = {w.upper() for line in code for w in line["text"].split()}
    return any(w in words for w in PROCEDURE_WORDS)


@router.get("/{name}")
def get_copybook(name: str) -> dict:
    label, layout = _load(name)
    store = knowledge()
    notes = store.get_fields(name)
    description = store.get_description(name)
    items = []
    for item in layout.items:
        note = notes.get(item.path)
        items.append({
            "path": item.path, "name": item.name, "level": item.level, "depth": item.depth,
            "pic": item.pic, "usage": item.usage, "occurs": item.occurs, "redefines": item.redefines,
            "offset": item.offset, "length": item.length, "element_length": item.element_length,
            "line": item.line, "is_group": item.is_group, "type_label": item.type_label,
            "digits": item.digits, "decimals": item.decimals, "signed": item.signed,
            "conditions": [{"name": c.name, "values": c.values, "line": c.line} for c in item.conditions],
            "note": (
                {"meaning": note["meaning"], "category": note["category"], "tags": note["tags"],
                 "updated_at": note["updated_at"],
                 "stale": note.get("fingerprint") not in (None, layout.fingerprint)}
                if note else None
            ),
        })
    text = library().resolve(name)[1]
    code = [{"number": line.number, "text": line.text.rstrip()} for line in normalize(text)]
    kind = "data" if layout.has_data else ("procedure" if _looks_like_code(code) else "empty")
    return {
        "name": layout.name,
        "file": label,
        "kind": kind,
        "code": code if kind == "procedure" else [],
        "fingerprint": layout.fingerprint,
        "has_data": layout.has_data,
        "total_length": layout.total_length,
        "roots": layout.roots,
        "problems": layout.problems,
        "items": items,
        "annotated_fields": len(notes),
        "description": description["description"] if description else "",
        "description_stale": bool(description and description.get("fingerprint") not in (None, layout.fingerprint)),
        "updated_at": description["updated_at"] if description else None,
    }


@router.get("/{name}/procedure")
def procedure_analysis(name: str) -> dict:
    """The statements of a copybook that holds procedure code, analysed as one paragraph named after it:
    a summary, the business logic, a flow chart and the Python module. Fields the statements use that
    the copybook does not declare are reported; they belong to the program that copies it."""
    from src.analyzer.paragraph_analyzer import paragraph_detail  # noqa: F401  (keeps the analyser loaded)
    from src.business.logic_extraction import extract as extract_logic
    from src.convert.python_gen import generate as generate_python
    from src.pipeline import analyze_source
    from src.summary.paragraph_summary import paragraph_summary

    label, layout = _load(name)
    text = library().resolve(name)[1]
    body = [line.text.rstrip() for line in normalize(text)]
    if not any(line.strip() for line in body):
        raise HTTPException(status_code=404, detail=f"Copybook {name} has no statements.")
    paragraph = name.upper()
    source = "\n".join(
        ["       IDENTIFICATION DIVISION.", f"       PROGRAM-ID. {paragraph}.", "       PROCEDURE DIVISION.",
         f"       {paragraph}."] + ["       " + line for line in body]) + "\n"
    analysis = analyze_source(source, f"{paragraph}.txt", library=library())
    if paragraph not in analysis.program.paragraph_map:
        raise HTTPException(status_code=422, detail=f"Copybook {name} could not be read as statements.")
    summary = paragraph_summary(analysis, paragraph, library=library())
    generated = generate_python(analysis, [paragraph])
    logic = extract_logic(generated["module"], generated["paragraphs"], {})
    para = next((p for p in logic["paragraphs"] if p["name"] == paragraph), None)
    return {
        "name": paragraph,
        "summary": summary["summary"] if summary else "",
        "explanation": para["explanation"] if para else [],
        "flow": para["flow"] if para else {"nodes": [], "edges": []},
        "findings": logic["findings"],
        "python": generated["module"],
        "notes": generated["notes"],
    }


@router.put("/{name}/description")
def set_description(name: str, body: DescriptionBody) -> dict:
    _, layout = _load(name)
    knowledge().set_description(name, body.description, layout.fingerprint)
    return {"ok": True}


@router.put("/{name}/fields/{path:path}")
def save_field(name: str, path: str, note: FieldNote) -> dict:
    _, layout = _load(name)
    if path not in {i.path for i in layout.items}:
        raise HTTPException(status_code=404, detail=f"{path} is not a field of {name}.")
    if note.category and note.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Unknown category {note.category}.")
    knowledge().upsert_field(name, path, note.meaning.strip(), note.category,
                             [t.strip() for t in note.tags if t.strip()], layout.fingerprint)
    return {"ok": True}


@router.delete("/{name}/fields/{path:path}")
def delete_field(name: str, path: str) -> dict:
    if not knowledge().delete_field(name, path):
        raise HTTPException(status_code=404, detail="No saved note for that field.")
    return {"ok": True}
