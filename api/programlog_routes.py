"""Program log endpoints: list analysed programs, read one program's history, add or remove details."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.programlog import DEFAULT_CATEGORY, ProgramLog

router = APIRouter(prefix="/api/program-log", tags=["program-log"])


@lru_cache(maxsize=1)
def program_log() -> ProgramLog:
    return ProgramLog()


class DetailBody(BaseModel):
    category: str = Field(default=DEFAULT_CATEGORY, max_length=60)
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=5000)


@router.get("/programs/{program_name}/paragraphs")
def list_paragraph_records(program_name: str) -> dict:
    rows = program_log().paragraphs_of_program(program_name)
    if not rows:
        raise HTTPException(status_code=404, detail="No paragraph records for this program.")
    return {"program": program_name, "paragraphs": [
        {"paragraph": r["paragraph"], "origin": r["origin"], "recorded_at": r["recorded_at"],
         "decisions": r["decision_count"], "changes": r["change_count"], "calls": r["call_count"],
         "summary": r["summary"]} for r in rows]}


@router.get("/programs/{program_name}/paragraphs/{paragraph}")
def get_paragraph_record(program_name: str, paragraph: str) -> dict:
    record = program_log().paragraph_record(program_name, paragraph)
    if record is None:
        raise HTTPException(status_code=404, detail="No record for this paragraph.")
    return record


@router.get("")
def list_programs(limit: int = Query(50, ge=1, le=500)) -> dict:
    return {"programs": program_log().programs(limit)}


@router.get("/{fingerprint}")
def get_history(fingerprint: str) -> dict:
    history = program_log().history(fingerprint)
    if history["run_count"] == 0 and not history["details"]:
        raise HTTPException(status_code=404, detail="This program has not been logged yet.")
    return history


@router.put("/{fingerprint}/details")
def put_detail(fingerprint: str, body: DetailBody) -> dict:
    try:
        program_log().add_detail(fingerprint, body.key, body.value, body.category)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"details": program_log().history(fingerprint)["details"]}


@router.delete("/{fingerprint}/details")
def delete_detail(fingerprint: str, key: str = Query(..., min_length=1),
                  category: str = Query(DEFAULT_CATEGORY)) -> dict:
    if not program_log().delete_detail(fingerprint, key, category):
        raise HTTPException(status_code=404, detail="No such detail.")
    return {"details": program_log().history(fingerprint)["details"]}
