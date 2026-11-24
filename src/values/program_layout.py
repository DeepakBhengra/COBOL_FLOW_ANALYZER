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
    return origin.rsplit(":", 1)[0].replace(" (uploaded)", "")


def _depth(item) -> int:
    depth = 0
    parent = item.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def working_layout(analysis, library=None) -> dict:
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
