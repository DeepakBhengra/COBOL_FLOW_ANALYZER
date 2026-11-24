"""The program's own WORKING-STORAGE laid out the same way as a copybook, with the copybook each item came
from, and the copybooks and DCLGEN members the program uses.

A DCLGEN member is pulled in with EXEC SQL INCLUDE. The expander does not expand it, so it is found
here from the statement and looked up in the copybook library like a copybook.
"""
from __future__ import annotations

import re

from ..copybooks.layout import describe
from .local_values import condition_names

INCLUDE_RE = re.compile(r"EXEC\s+SQL\s+INCLUDE\s+([A-Za-z0-9_-]+)", re.IGNORECASE)


def _origin_name(origin: str | None, source_name: str) -> str:
    """'CUSTCOMM.txt:3' -> 'CUSTCOMM.txt'; the program's own lines -> the program name."""
    if not origin or origin.startswith(source_name + ":"):
        return source_name
    name = origin.rsplit(":", 1)[0].replace(" (uploaded)", "")
    stem, dot, ext = name.rpartition(".")
    return stem if dot and ext.lower() in ("txt", "cpy") else name


def _depth(item) -> int:
    depth = 0
    parent = item.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def _copybook_path(library, copy: str, local_line: int) -> str | None:
    """The declared path in a copybook of the field on a given line of that copybook."""
    from ..copybooks.layout import layout_of_copybook
    found = library.resolve(copy) if library is not None else None
    if found is None:
        return None
    return layout_of_copybook(copy, found[1]).line_to_path.get(local_line)


def item_source(analysis, line: int) -> tuple[str, int | None]:
    """(copybook name or program name, the line inside that copybook or program)."""
    origin = analysis.program.line_origin.get(line) or ""
    name = _origin_name(origin, analysis.program.source_name)
    local = origin.rsplit(":", 1)[1] if ":" in origin else None
    return name, int(local) if local and local.isdigit() else None


def working_layout(analysis, library=None, store=None) -> dict:
    program = analysis.program
    conditions = {}
    for name, (parent, values) in condition_names(analysis.data_entries).items():
        conditions.setdefault(parent, []).append({"name": name, "values": list(values)})

    items = []
    for root in analysis.data_roots or []:
        for item in root.walk():
            if "WORKING-STORAGE" not in (item.section or "").upper():
                continue
            is_group = bool(item.children)
            meta = describe(item.pic, item.usage, is_group)
            origin = program.line_origin.get(item.line)
            items.append({
                "path": item.name.upper(),
                "name": item.name.upper(),
                "level": item.level,
                "depth": _depth(item),
                "pic": item.pic,
                "usage": item.usage,
                "occurs": item.occurs,
                "redefines": item.redefines,
                "offset": item.offset,
                "length": item.total_length if is_group else item.element_length,
                "element_length": item.element_length,
                "type_label": meta["type_label"],
                "is_group": is_group,
                "line": item.line,
                "source": _origin_name(origin, program.source_name),
                "conditions": conditions.get(item.name.upper(), []),
            })

    used = [{"name": u.name.upper(), "source": u.source, "line": u.line, "kind": "copy"}
            for u in (analysis.copybooks.used if analysis.copybooks else [])]
    seen = {u["name"] for u in used}
    dclgen = []
    whole = "\n".join(program.source_lines[n] for n in sorted(program.source_lines))
    for match in INCLUDE_RE.finditer(whole):
        name = match.group(1).upper()
        if name not in seen:
            seen.add(name)
            dclgen.append({"name": name, "source": None, "line": None, "kind": "dclgen"})

    program_notes = store.get_program_notes(program.name) if store is not None else {}
    cache: dict[str, dict] = {}
    for item in items:
        if item["source"] == program.source_name or item["source"] == program.name:
            item["description"] = program_notes.get(item["name"], "")
            item["description_from"] = "program"
            continue
        item["description"], item["description_from"] = "", "copybook"
        if store is None or library is None:
            continue
        copy = item["source"]
        _, local = item_source(analysis, item["line"])
        path = _copybook_path(library, copy, local) if local else None
        if path is None:
            continue
        if copy not in cache:
            cache[copy] = store.get_fields(copy)
        note = cache[copy].get(path)
        item["description"] = note["meaning"] if note else ""

    members = used + dclgen
    for member in members:
        found = None
        if library is not None:
            found = library.resolve(member["name"])
        member["found"] = found is not None
    return {
        "program": program.name,
        "items": items,
        "copybooks": members,
        "missing": [m["name"] for m in members if not m["found"]],
    }


_COPYBOOK_LAYOUTS: dict[tuple[str, str], object] = {}


def _layout_of_member(library, name: str):
    """The parsed layout of a copybook, cached by name and text so searching does not re-parse it."""
    from ..copybooks.layout import fingerprint, layout_of_copybook
    found = library.resolve(name) if library is not None else None
    if found is None:
        return None
    key = (name, fingerprint(found[1]))
    if key not in _COPYBOOK_LAYOUTS:
        _COPYBOOK_LAYOUTS[key] = layout_of_copybook(name, found[1])
    return _COPYBOOK_LAYOUTS[key]


def search_fields(analysis, query: str, library=None, store=None, limit: int = 500) -> dict:
    """Every field whose name contains the query (case-insensitive): the program's own working storage and
    the fields of each copybook and DCLGEN member it uses."""
    needle = (query or "").strip().upper()
    if not needle:
        return {"query": query or "", "matches": [], "count": 0, "truncated": False}
    layout = working_layout(analysis, library, store)
    matches = []
    for it in layout["items"]:
        if needle in it["name"]:
            matches.append({
                "name": it["name"], "source": layout["program"], "kind": "program", "level": it["level"],
                "pic": it["pic"], "type_label": it["type_label"], "offset": it["offset"],
                "length": it["length"], "line": it["line"], "path": it["path"], "description": it["description"],
                "description_from": it["description_from"],
            })
    for member in layout["copybooks"]:
        if not member["found"]:
            continue
        cb = _layout_of_member(library, member["name"])
        if cb is None:
            continue
        notes = store.get_fields(member["name"]) if store is not None else {}
        for item in cb.items:
            if needle not in item.name.upper():
                continue
            note = notes.get(item.path)
            matches.append({
                "name": item.name.upper(), "source": member["name"], "kind": member["kind"],
                "level": item.level, "pic": item.pic, "type_label": item.type_label,
                "offset": item.offset, "length": item.length, "line": item.line, "path": item.path,
                "description": note["meaning"] if note else "", "description_from": "copybook",
            })
    return {"query": query, "matches": matches[:limit], "count": len(matches),
            "truncated": len(matches) > limit}
