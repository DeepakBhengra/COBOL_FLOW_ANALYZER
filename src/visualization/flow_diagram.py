"""Graphviz DOT builders for the program map and paragraph neighbourhood views."""
from __future__ import annotations

import networkx as nx

EDGE_STYLE = {
    "PERFORM": ("#1565c0", "solid"),
    "PERFORM THRU": ("#1565c0", "bold"),
    "GO TO": ("#c62828", "dashed"),
    "FALL-THROUGH": ("#9e9e9e", "dotted"),
}

NODE_FILL = {
    "entry": "#c8e6c9",
    "never": "#ffcdd2",
    "called": "#bbdefb",
    "fallthrough": "#eeeeee",
}


def _q(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _short(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _node_attrs(name: str, status) -> str:
    if status.is_entry:
        fill = NODE_FILL["entry"]
    elif status.never_called:
        fill = NODE_FILL["never"]
    elif status.call_count:
        fill = NODE_FILL["called"]
    else:
        fill = NODE_FILL["fallthrough"]
    style = "filled,rounded" if status.reachable else "filled,rounded,dashed"
    return f'[label={_q(name)}, fillcolor={_q(fill)}, style={_q(style)}]'


def _edge_attrs(data: dict) -> str:
    color, style = EDGE_STYLE.get(data.get("kind", ""), ("#424242", "solid"))
    parts = [f"color={_q(color)}", f"style={_q(style)}"]
    if data.get("conditional"):
        parts.append(f"label={_q('? ' + _short(data.get('conditions', '')))}")
        parts.append("fontsize=9")
    return "[" + ", ".join(parts) + "]"


def program_map_dot(graph: nx.DiGraph, statuses: dict, show_fall_through: bool = True) -> str:
    lines = [
        "digraph program_map {",
        '  rankdir=LR;',
        '  node [shape=box, fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=9];',
    ]
    for name in graph.nodes:
        lines.append(f"  {_q(name)} {_node_attrs(name, statuses[name])};")
    for u, v, data in graph.edges(data=True):
        if data.get("kind") == "FALL-THROUGH" and not show_fall_through:
            continue
        lines.append(f"  {_q(u)} -> {_q(v)} {_edge_attrs(data)};")
    lines.append("}")
    return "\n".join(lines)


def neighbourhood_dot(graph: nx.DiGraph, statuses: dict, name: str) -> str:
    """Focus paragraph plus its direct callers and callees."""
    if name not in graph:
        return "digraph empty {}"
    keep = {name} | set(graph.predecessors(name)) | set(graph.successors(name))
    sub = graph.subgraph(keep)
    lines = [
        "digraph neighbourhood {",
        '  rankdir=LR;',
        '  node [shape=box, fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=9];',
    ]
    for node in sub.nodes:
        attrs = _node_attrs(node, statuses[node])
        if node == name:
            attrs = attrs[:-1] + ', penwidth=3]'
        lines.append(f"  {_q(node)} {attrs};")
    for u, v, data in sub.edges(data=True):
        lines.append(f"  {_q(u)} -> {_q(v)} {_edge_attrs(data)};")
    lines.append("}")
    return "\n".join(lines)
