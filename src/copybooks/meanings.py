"""Connects saved field notes to the fields of an analysed program.

For every data item that came from a copybook, the expansion tells us which copybook file
and line it came from (Program.line_origin). The copybook's own layout tells us the declared
path of the field at that line, and the knowledge store is asked for a note on that path.
"""
from __future__ import annotations

from ..commarea.models import DataItem
from .knowledge import KnowledgeStore
from .layout import layout_of_copybook


def _copybook_name(label: str) -> tuple[str, int] | None:
    """'CUSTCOMM.txt:12' -> ('CUSTCOMM', 12); 'CUSTCOMM (uploaded):3' -> ('CUSTCOMM', 3)."""
    if ":" not in label:
        return None
    file_part, _, line_part = label.rpartition(":")
    if not line_part.isdigit():
        return None
    base = file_part.replace(" (uploaded)", "")
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return stem.upper(), int(line_part)


def field_meanings(items: list[DataItem], line_origin: dict[int, str], source_name: str,
                   library, store: KnowledgeStore) -> dict[str, dict]:
    """Return {expanded field path: note} for fields that have a saved note."""
    layouts: dict[str, object] = {}
    notes_cache: dict[str, dict] = {}
    result: dict[str, dict] = {}

    for item in items:
        origin = line_origin.get(item.line, "")
        if not origin or origin.rpartition(":")[0] == source_name:
            continue  # written in the program itself
        parsed = _copybook_name(origin)
        if parsed is None:
            continue
        name, local_line = parsed

        if name not in layouts:
            found = library.resolve(name)
            if found is None:
                layouts[name] = None
            else:
                layouts[name] = layout_of_copybook(name, found[1])
            notes_cache[name] = store.get_fields(name)
        layout = layouts[name]
        if layout is None:
            continue

        declared = layout.line_to_path.get(local_line)
        note = notes_cache[name].get(declared) if declared else None
        if note is None:
            continue
        result[item.path] = {
            "meaning": note["meaning"],
            "category": note.get("category", ""),
            "tags": note.get("tags", []),
            "copybook": name,
            "declared_path": declared,
            "stale": note.get("fingerprint") not in (None, layout.fingerprint),
        }
    return result
