"""Business Logic Extraction Engine.

Reads the Python module generated from COBOL (the intermediate layer) and turns it into business
rules and plain-language explanations. It does not look at the COBOL text again: every rule comes from
the Python code, so what is explained is exactly what the converted program does.

Output per paragraph:
  rules        a tree of decisions (condition, what happens when true, what happens otherwise),
               repeats, and actions (sets, performs, SQL / CICS calls, stops)
  explanation  the same tree written as sentences

Review findings (checks on the intermediate layer):
  constant_condition  a condition compares fixed values, so one branch always runs
  undeclared          a name is used but not declared in the program's data
  decision_on_undeclared  a decision depends on an undeclared name (it is read as blank)
  not_converted       a COBOL statement the converter could not translate
  sql_missing_comma   an SQL SET list has no comma between two assignments
  sql_host_variable   an SQL host variable (:NAME) is not declared; a close name is suggested
"""
from __future__ import annotations

import ast
import re

from ..convert import cobol_runtime as rt

COMPARE_TEXT = {"eq": "is equal to", "ne": "is not equal to", "gt": "is greater than",
                "lt": "is less than", "ge": "is at least", "le": "is at most"}
PY_COMPARE_TEXT = {"Eq": "is equal to", "NotEq": "is not equal to", "Gt": "is greater than",
                   "Lt": "is less than", "GtE": "is at least", "LtE": "is at most",
                   "In": "is one of", "NotIn": "is not one of"}
BIN_TEXT = {"Add": "plus", "Sub": "minus", "Mult": "times", "Div": "divided by"}


def py_name(paragraph: str) -> str:
    return "p_" + re.sub(r"[^0-9A-Za-z]", "_", paragraph)


def _literal(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


class _Context:
    def __init__(self, tree, meanings, declared, findings):
        self.tree = tree
        self.meanings = meanings or {}
        self.declared = declared
        self.findings = findings
        self.paragraph = ""

    def label(self, name: str) -> str:
        meaning = self.meanings.get(name)
        if name not in self.declared:
            return f"{name} [not declared]"
        return f"{name} ({meaning})" if meaning else name


def _const(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in ("SPACES", "ZERO"):
        return getattr(rt, node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    raise ValueError("not a constant")


def _value(node, ctx: _Context) -> str:
    if isinstance(node, ast.Constant):
        return f"'{node.value}'" if isinstance(node.value, str) else str(node.value)
    if isinstance(node, ast.Name):
        return {"SPACES": "spaces", "ZERO": "zero"}.get(node.id, node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"minus {_value(node.operand, ctx)}"
    if isinstance(node, ast.BinOp):
        return f"({_value(node.left, ctx)} {BIN_TEXT.get(type(node.op).__name__, '?')} {_value(node.right, ctx)})"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = node.func.id
        if fn == "num":
            return _value(node.args[0], ctx)
        if fn == "div":
            return f"{_value(node.args[0], ctx)} divided by {_value(node.args[1], ctx)}"
        if fn in COMPARE_TEXT:
            return _compare(fn, node.args, ctx)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        args = node.args
        if attr == "get" and isinstance(args[0], ast.Constant):
            return ctx.label(args[0].value)
        if attr == "sub" and isinstance(args[0], ast.Constant):
            return f"{_value(args[2], ctx)} bytes of {ctx.label(args[0].value)} starting at {_value(args[1], ctx)}"
        if attr == "length" and isinstance(args[0], ast.Constant):
            return f"the length of {ctx.label(args[0].value)}"
    return ast.unparse(node)


def _compare(fn: str, args, ctx) -> str:
    return f"{_value(args[0], ctx)} {COMPARE_TEXT[fn]} {_value(args[1], ctx)}"


def _cond(node, ctx: _Context) -> str:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in COMPARE_TEXT:
        return _compare(node.func.id, node.args, ctx)
    if isinstance(node, ast.BoolOp):
        joiner = " and " if isinstance(node.op, ast.And) else " or "
        return "(" + joiner.join(_cond(v, ctx) for v in node.values) + ")"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return f"not {_cond(node.operand, ctx)}"
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op = PY_COMPARE_TEXT.get(type(node.ops[0]).__name__, "compared with")
        return f"{_value(node.left, ctx)} {op} {_value(node.comparators[0], ctx)}"
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return "always true" if node.value else "always false"
    return _value(node, ctx)


def _constant_result(node):
    """True / False when the condition only compares fixed values; None otherwise."""
    try:
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in COMPARE_TEXT:
            a, b = _const(node.args[0]), _const(node.args[1])
            return getattr(rt, node.func.id)(a, b)
        if isinstance(node, ast.BoolOp):
            values = [_constant_result(v) for v in node.values]
            if any(v is None for v in values):
                return None
            return all(values) if isinstance(node.op, ast.And) else any(values)
    except (ValueError, TypeError, AttributeError, IndexError):
        return None
    return None


def _names_in(node) -> set[str]:
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.args \
                and isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str):
            found.add(sub.args[0].value)
    return found


def _action(call: ast.Call, ctx: _Context) -> dict | None:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return {"kind": "action", "category": "other", "text": ast.unparse(call)}
    attr, args = func.attr, call.args
    if attr == "loop_check":
        return None
    if attr == "put" and isinstance(args[0], ast.Constant):
        name = args[0].value
        value = _value(args[1], ctx)
        return {"kind": "action", "category": "set", "field": name, "value": value,
                "text": f"sets {ctx.label(name)} to {value}"}
    if attr == "put_sub" and isinstance(args[0], ast.Constant):
        start = _value(args[1], ctx)
        length = _value(args[2], ctx)
        value = _value(args[3], ctx)
        return {"kind": "action", "category": "set", "field": args[0].value, "value": value,
                "text": f"sets {length} byte(s) of {ctx.label(args[0].value)} from position {start} to {value}"}
    if attr == "initialize" and isinstance(args[0], ast.Constant):
        return {"kind": "action", "category": "set", "field": args[0].value, "value": "initial value",
                "text": f"clears {ctx.label(args[0].value)} to its initial value"}
    if attr == "perform" and isinstance(args[0], ast.Constant):
        return {"kind": "action", "category": "perform", "target": args[0].value,
                "text": f"performs paragraph {args[0].value}"}
    if attr == "perform_thru" and isinstance(args[0], ast.Constant):
        return {"kind": "action", "category": "perform", "target": args[0].value,
                "text": f"performs paragraphs {args[0].value} through {args[1].value}"}
    if attr == "external" and isinstance(args[0], ast.Constant):
        raw = args[0].value
        upper = raw.upper()
        short = raw if len(raw) <= 140 else raw[:137] + "..."
        if upper.startswith("EXEC SQL"):
            category, text = "sql", f"runs an SQL statement: {short}"
        elif upper.startswith("EXEC CICS"):
            category, text = "cics", f"issues a CICS request: {short}"
        elif upper.startswith("CALL"):
            category, text = "call", f"calls a program: {short}"
        else:
            category, text = "external", short
        return {"kind": "action", "category": category, "statement": raw, "text": text}
    if attr == "stop":
        return {"kind": "action", "category": "stop", "text": "ends the program"}
    if attr == "display" and args and isinstance(args[0], ast.Constant):
        return {"kind": "action", "category": "display", "text": f"displays {args[0].value}"}
    if attr == "unsupported" and args and isinstance(args[0], ast.Constant):
        return {"kind": "action", "category": "unsupported", "statement": args[0].value,
                "text": f"NOT CONVERTED: {args[0].value}"}
    if attr == "notes":
        return None
    return {"kind": "action", "category": "other", "text": f"calls {attr}"}


def _is_origin(st) -> str | None:
    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute) \
            and st.value.func.attr == "origin" and st.value.args and isinstance(st.value.args[0], ast.Constant):
        return st.value.args[0].value
    return None


def _rules(statements, ctx: _Context) -> list[dict]:
    """Rules for a statement list. An origin marker is attached to the rule that follows it."""
    out: list[dict] = []
    pending = None
    for st in statements:
        marker = _is_origin(st)
        if marker is not None:
            pending = marker
            continue
        before = len(out)
        out.extend(_rules_one(st, ctx))
        if pending and len(out) > before:
            out[before]["origin"] = pending
            pending = None
    return out


def _rules_one(st, ctx: _Context) -> list[dict]:
    out: list[dict] = []
    for st in [st]:
        if isinstance(st, ast.If):
            constant = _constant_result(st.test)
            if constant is not None:
                ctx.findings.append({
                    "severity": "error", "kind": "constant_condition", "paragraph": ctx.paragraph,
                    "message": f"The condition {_cond(st.test, ctx)} compares fixed values, so it is always "
                               f"{'true' if constant else 'false'}: the "
                               f"{'first' if constant else 'other'} branch always runs.",
                })
            names = _names_in(st.test)
            for name in sorted(names):
                if name not in ctx.declared:
                    ctx.findings.append({
                        "severity": "error", "kind": "decision_on_undeclared", "paragraph": ctx.paragraph,
                        "message": f"A decision depends on {name}, which is not declared in this program. "
                                   "It is read as blank, so the branch taken depends on a value that is not given."})
            out.append({"kind": "decision", "condition": _cond(st.test, ctx), "constant": constant,
                        "when_true": _rules(st.body, ctx), "when_false": _rules(st.orelse, ctx)})
        elif isinstance(st, ast.While):
            test = st.test.operand if isinstance(st.test, ast.UnaryOp) and isinstance(st.test.op, ast.Not) else st.test
            out.append({"kind": "repeat", "until": _cond(test, ctx), "body": _rules(st.body, ctx)})
        elif isinstance(st, ast.For):
            times = _value(st.iter.args[0], ctx) if isinstance(st.iter, ast.Call) and st.iter.args else "?"
            out.append({"kind": "repeat", "times": times, "body": _rules(st.body, ctx)})
        elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            action = _action(st.value, ctx)
            if action is not None:
                out.append(action)
        elif isinstance(st, ast.Return):
            out.append({"kind": "action", "category": "end_paragraph", "text": "the paragraph ends here"})
    return out


def _sentence(rule: dict) -> str:
    text = _sentence_body(rule)
    if rule.get("origin"):
        return f"{text} (from copybook {rule['origin']})"
    return text


def _sentence_body(rule: dict) -> str:
    if rule["kind"] == "decision":
        text = f"if {rule['condition']}, then " + _join(rule["when_true"], "nothing")
        if rule["when_false"]:
            text += "; otherwise " + _join(rule["when_false"], "nothing")
        return text
    if rule["kind"] == "repeat":
        if "until" in rule:
            return f"repeat until {rule['until']}: " + _join(rule["body"], "nothing")
        return f"repeat {rule['times']} time(s): " + _join(rule["body"], "nothing")
    return rule["text"]


def _join(rules, empty: str) -> str:
    if not rules:
        return empty
    return "; ".join(_sentence(r) for r in rules)


def explain(rules: list[dict]) -> list[str]:
    """One sentence per top-level rule, with the decisions and their outcomes written out."""
    sentences = []
    for rule in rules:
        text = _sentence(rule)
        text = text.rstrip(". ")
        sentences.append(text[0].upper() + text[1:] + ".")
    return sentences


def _sql_findings(text: str, paragraph: str, declared: set, findings: list[dict]) -> None:
    if re.search(r"=\s*:[A-Za-z0-9-]+\s+[A-Za-z_][A-Za-z0-9_]*\s*=", text):
        findings.append({"severity": "error", "kind": "sql_missing_comma", "paragraph": paragraph,
                         "message": "The SQL SET list looks like it is missing a comma between two assignments: "
                                    + text[:160]})
    for host in sorted(set(re.findall(r":([A-Za-z][A-Za-z0-9-]*)", text))):
        if host in declared:
            continue
        close = sorted(d for d in declared if d.startswith(host + "-") or host.startswith(d + "-")
                       or (host in d and len(host) > 3))
        hint = f"; did you mean {close[0]}?" if close else ""
        findings.append({"severity": "error", "kind": "sql_host_variable", "paragraph": paragraph,
                         "message": f"The SQL host variable :{host} is not declared in this program{hint}"})


def extract(module_source: str, paragraphs: list[str], meanings: dict | None = None) -> dict:
    tree = ast.parse(module_source)
    spec = _literal(tree, "SPEC") or {}
    undeclared = _literal(tree, "UNDECLARED") or []
    conditions = _literal(tree, "CONDITIONS") or {}
    declared = set(spec) | set(conditions)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    findings: list[dict] = []

    result_paragraphs = []
    for name in paragraphs:
        fn = functions.get(py_name(name))
        if fn is None:
            continue
        ctx = _Context(tree, meanings, declared, findings)
        ctx.paragraph = name
        rules = _rules(fn.body, ctx)
        calls = sorted({r["target"] for r in _walk_rules(rules) if r.get("category") == "perform"})
        result_paragraphs.append({"name": name, "rules": rules, "explanation": explain(rules),
                                  "performs": calls, "flow": flow_of(name, rules)})

        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) and stmt.func.attr == "external" \
                    and stmt.args and isinstance(stmt.args[0], ast.Constant) and isinstance(stmt.args[0].value, str):
                text = stmt.args[0].value
                if text.upper().startswith("EXEC SQL"):
                    _sql_findings(text, name, declared, findings)
            if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) and stmt.func.attr == "unsupported":
                findings.append({"severity": "warning", "kind": "not_converted", "paragraph": name,
                                 "message": f"Not converted: {stmt.args[0].value}"})

    for name in undeclared:
        findings.append({"severity": "warning", "kind": "undeclared", "paragraph": "",
                         "message": f"{name} is used but not declared in this program's data. It is read as blank "
                                    "unless a value is supplied (for example from a copybook or a caller)."})

    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {"paragraphs": result_paragraphs, "findings": findings, "undeclared": undeclared,
            "summary": {"paragraphs": len(result_paragraphs), "findings": len(findings),
                        "by_severity": counts}}


def _walk_rules(rules):
    for r in rules:
        yield r
        if r["kind"] == "decision":
            yield from _walk_rules(r["when_true"])
            yield from _walk_rules(r["when_false"])
        elif r["kind"] == "repeat":
            yield from _walk_rules(r["body"])




def _short(text: str, limit: int = 110) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def flow_of(name: str, rules: list[dict]) -> dict:
    """The rules as a flow chart: decisions branch yes / no, repeats loop back, actions run in order."""
    nodes = [{"id": "start", "kind": "start", "label": f"Start {name}"}]
    edges: list[dict] = []
    counter = {"n": 0}

    def new(kind: str, label: str) -> str:
        counter["n"] += 1
        node_id = f"n{counter['n']}"
        nodes.append({"id": node_id, "kind": kind, "label": _short(label)})
        return node_id

    def connect(frontier, target):
        for source, label in frontier:
            edges.append({"source": source, "target": target, "label": label or ""})

    def add(items, frontier):
        for rule in items:
            if rule["kind"] == "decision":
                node = new("decision", (f"[{rule['origin']}] " if rule.get("origin") else "") + rule["condition"])
                connect(frontier, node)
                yes_end = add(rule["when_true"], [(node, "yes")])
                no_end = add(rule["when_false"], [(node, "no")]) if rule["when_false"] else [(node, "no")]
                frontier = yes_end + no_end
            elif rule["kind"] == "repeat":
                label = f"repeat until {rule['until']}" if "until" in rule else f"repeat {rule['times']} time(s)"
                node = new("repeat", label)
                connect(frontier, node)
                body_end = add(rule["body"], [(node, "loop")])
                connect(body_end, node)
                frontier = [(node, "done")]
            else:
                category = rule.get("category", "")
                kind = {"perform": "perform", "stop": "stop", "end_paragraph": "stop",
                        "sql": "data", "cics": "data", "call": "call", "unsupported": "warning"}.get(category, "action")
                label = rule.get("text", "")
                if rule.get("origin"):
                    label = f"[{rule['origin']}] {label}"
                node = new(kind, label)
                connect(frontier, node)
                frontier = [] if kind == "stop" else [(node, "")]
        return frontier

    end_frontier = add(rules, [("start", "")])
    end = {"id": "end", "kind": "end", "label": f"End of {name}"}
    nodes.append(end)
    connect(end_frontier, "end")
    return {"nodes": nodes, "edges": edges}
