"""Tracks the values of local variables (names starting with WS-) through a paragraph.

Each variable holds either a known value (a number or a text literal) or a symbolic expression
that is written out in full, for example:

  COMPUTE WS-FUNC-LEN-N-1 = WS-FUNC-LEN + 1      WS-FUNC-LEN-N-1 = WS-FUNC-LEN + 1
  MOVE WS-FUNC-LEN-N-1 TO WS-START-POS           WS-START-POS    = WS-FUNC-LEN + 1

A variable that comes from outside the program (a file, a caller, the CICS input) stays as its own
name, because its value is not known here.

Reference modification is read as a slice: RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN) is the
WS-MOVE-LEN bytes of RCV-DATA-BUFFER-AREA beginning at position WS-START-POS.

IF and EVALUATE are followed on both sides. When the condition can be decided from the known values,
only the branch taken is applied. Otherwise both branches are applied and a variable that differs
between them is shown as "(X or Y)".
PERFORMed paragraphs are followed with the values they see, up to a fixed depth.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..copybooks.layout import describe
from ..models.paragraph import Statement

LOCAL_PREFIX = "WS-"
MAX_PERFORM_DEPTH = 3
MAX_STEPS = 20000          # statements the tracer may apply for one request; the result says when reached
REFMOD_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)\s*\(\s*(.+?)\s*:\s*(.*?)\s*\)$")
COMPARE_RE = re.compile(r"^(.+?)\s+(NOT\s*=|NOT\s*<|NOT\s*>|>=|<=|=|<|>)\s+(.+)$")
TOKEN_RE = re.compile(r"'[^']*'|\d+|[A-Za-z][A-Za-z0-9-]*|[+\-*/()]")
OP_TEXT = {"=": "equal to", "NOT =": "not equal to", "NOT=": "not equal to", ">": "greater than",
           "<": "less than", ">=": "at least", "<=": "at most", "NOT >": "not greater than",
           "NOT <": "not less than", "NOT>": "not greater than", "NOT<": "not less than"}
SPECIAL = {"SPACE": " ", "SPACES": " ", "ZERO": 0, "ZEROS": 0, "ZEROES": 0,
           "LOW-VALUE": "\x00", "LOW-VALUES": "\x00", "HIGH-VALUE": "\xff", "HIGH-VALUES": "\xff"}
KEYWORDS = {"IF", "THEN", "ELSE", "END-IF", "AND", "OR", "NOT", "MOVE", "TO", "FROM", "COMPUTE", "ADD",
            "SUBTRACT", "SET", "TRUE", "PERFORM", "GIVING", "ROUNDED"}


@dataclass
class Val:
    text: str                   # how the value reads, e.g. "3", "' '", "WS-FUNC-LEN + 1"
    num: int | None = None
    lit: str | None = None
    slice: tuple | None = None  # (buffer name, start Val, length Val) for a reference-modified slice
    origin: str | None = None   # the data name this value was read from (its identity, not its text)

    @property
    def known(self) -> bool:
        return self.num is not None or self.lit is not None


def const(n: int) -> Val:
    return Val(str(n), num=n)


def text_lit(s: str) -> Val:
    if s and set(s) == {" "}:
        shown = "SPACES"
    elif any(ord(ch) < 32 or ord(ch) > 126 for ch in s):
        shown = "X'" + s.encode("latin-1", "replace").hex().upper() + "'"
    else:
        shown = f"'{s}'"
    return Val(shown, lit=s)


def sym(text: str) -> Val:
    return Val(text)


@dataclass
class Change:
    line: int
    name: str
    value: str
    how: str
    via: str


@dataclass
class Decision:
    line: int
    condition: str
    decided: bool | None
    when_true: list[str]
    when_else: list[str]
    via: str


@dataclass
class Context:
    analysis: object
    layouts: dict
    initial: dict
    buffer: tuple | None = None      # (buffer name, its contents) when the tracer reads real bytes
    changes: list[Change] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    slices: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    child_of: dict = field(default_factory=dict)
    cond88: dict = field(default_factory=dict)
    cond_used: set = field(default_factory=set)
    steps: int = 0
    exhausted: bool = False
    constraints: list[dict] = field(default_factory=list)   # what a value must equal for a branch to be taken
    group_moves: list[dict] = field(default_factory=list)   # a slice moved into a group item


# ------------------------------------------------------------------ data layout
def _layouts(analysis) -> dict:
    info = {}
    for root in analysis.data_roots or []:
        for item in root.walk():
            if item.children:          # a group: its length is the total of its children
                info[item.name.upper()] = {
                    "type": "Group", "bytes": item.total_length, "pic": None, "occurs": item.occurs,
                    "offset": item.offset,
                    "children": [_leaf_info(c, item) for c in _leaves(item)],
                }
                continue
            meta = describe(item.pic, item.usage, False)
            info[item.name.upper()] = {
                "type": meta["type_label"],
                "bytes": item.element_length,
                "pic": item.pic,
                "digits": meta["digits"],
                "signed": meta["signed"],
                "occurs": item.occurs,
                "offset": item.offset,
            }
    return info


def _leaves(group) -> list:
    out = []
    for child in group.children:
        out.extend([child] if not child.children else _leaves(child))
    return out


def _leaf_info(item, group) -> dict:
    meta = describe(item.pic, item.usage, False)
    return {"name": item.name.upper(), "offset": item.offset - group.offset, "bytes": item.element_length,
            "pic": item.pic, "type": meta["type_label"], "occurs": item.occurs, "usage": item.usage,
            "digits": meta["digits"] or item.element_length, "signed": bool(meta["signed"])}


def condition_names(entries) -> dict[str, tuple[str, list[str]]]:
    """88-level condition names: name -> (parent item, the values that make it true)."""
    out: dict[str, tuple[str, list[str]]] = {}
    parent = None
    for _section, tokens in entries or []:
        if len(tokens) < 2 or tokens[0].kind != "NUMBER":
            continue
        level = tokens[0].value.lstrip("0") or "0"
        if level == "88":
            values = []
            for t in tokens[2:]:
                if t.kind == "STRING":
                    values.append(t.value[1:-1])
                elif t.kind == "NUMBER":
                    values.append(t.value)
                elif t.kind == "WORD" and t.value.upper() in ("VALUE", "VALUES", "THRU", "THROUGH"):
                    continue
            if parent is not None:
                out[tokens[1].value.upper()] = (parent, values)
        elif tokens[1].kind == "WORD":
            parent = tokens[1].value.upper()
    return out


def _initial_values(entries) -> dict[str, Val]:
    initial: dict[str, Val] = {}
    for _section, tokens in entries or []:
        if len(tokens) < 2 or tokens[0].kind != "NUMBER" or tokens[1].kind != "WORD":
            continue
        if tokens[0].value.lstrip("0") == "88":      # a condition name's VALUE is not the item's value
            continue
        name = tokens[1].value.upper()
        for i, tok in enumerate(tokens):
            if tok.kind == "WORD" and tok.value.upper() in ("VALUE", "VALUES") and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if nxt.kind == "NUMBER":
                    initial[name] = const(int(nxt.value))
                elif nxt.kind == "STRING":
                    initial[name] = text_lit(nxt.value[1:-1])
                elif nxt.value.upper() == "X" and i + 2 < len(tokens) and tokens[i + 2].kind == "STRING":
                    initial[name] = text_lit(chr(int(tokens[i + 2].value.strip("'\""), 16)))
                elif nxt.value.upper() in SPECIAL:
                    value = SPECIAL[nxt.value.upper()]
                    initial[name] = const(value) if isinstance(value, int) else text_lit(value)
                break
    return initial


# ------------------------------------------------------------------ operands
def _clean(text: str) -> str:
    text = re.sub(r"\s*\(\s*", "(", text.strip())
    return re.sub(r"\s*\)", ")", text)


def _refmod(text: str):
    m = REFMOD_RE.match(_clean(text))
    if not m:
        return None
    return m.group(1).upper(), m.group(2), m.group(3)


def _operand(text: str, env: dict, ctx: Context) -> Val:
    text = _clean(text)
    upper = text.upper()
    m = re.match(r"^LENGTH\s+OF\s+([A-Za-z0-9-]+)$", text, re.IGNORECASE)
    if m:
        info = ctx.layouts.get(m.group(1).upper())
        return const(info["bytes"]) if info else sym(f"LENGTH OF {m.group(1).upper()}")
    if upper in SPECIAL:
        value = SPECIAL[upper]
        return const(value) if isinstance(value, int) else text_lit(value)
    if re.fullmatch(r"-?\d+", text):
        return const(int(text))
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text_lit(text[1:-1])
    ref = _refmod(text)
    if ref:
        name, start, length = ref
        start_val = _operand(start, env, ctx)
        len_val = _operand(length, env, ctx)
        symbolic = f"{name}({_clean(start)}:{_clean(length)})"
        resolved = f"{name}({start_val.text}:{len_val.text})"
        shown = symbolic if symbolic == resolved else f"{symbolic} = {resolved}"
        ctx.slices.append({"text": shown, "field": name, "start": start_val.text, "length": len_val.text,
                           "bytes": len_val.num, "explain": _explain_slice(name, start_val, len_val)})
        if (ctx.buffer and name == ctx.buffer[0] and start_val.num is not None
                and len_val.num is not None and start_val.num >= 1):
            piece = ctx.buffer[1][start_val.num - 1:start_val.num - 1 + len_val.num].ljust(len_val.num)
            return Val(shown, lit=piece, slice=(name, start_val, len_val))
        return Val(shown, slice=(name, start_val, len_val))
    if upper in env:
        v = env[upper]
        return Val(v.text, v.num, v.lit, v.slice, origin=upper)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", text):
        v = env.setdefault(upper, sym(upper))
        return Val(v.text, v.num, v.lit, v.slice, origin=upper)
    return _expression(text, env, ctx)


def _explain_slice(name: str, start: Val, length: Val) -> str:
    if length.num == 1:
        return f"1 byte of {name} at position {start.text}"
    return f"{length.text} bytes of {name} starting at position {start.text}"


def _expression(text: str, env: dict, ctx: Context) -> Val:
    tokens = TOKEN_RE.findall(text)
    if not tokens:
        return sym(_clean(text))
    py_parts, sym_parts, all_known = [], [], True
    for tok in tokens:
        if tok in "+-*/()":
            py_parts.append("//" if tok == "/" else tok)
            sym_parts.append(tok)
            continue
        if tok.isdigit():
            py_parts.append(tok)
            sym_parts.append(tok)
            continue
        val = _operand(tok, env, ctx) if not tok.startswith("'") else text_lit(tok[1:-1])
        if val.num is None:
            all_known = False
        py_parts.append(str(val.num) if val.num is not None else "0")
        sym_parts.append(val.text if " " not in val.text else f"({val.text})")
    shown = " ".join(sym_parts).replace("( ", "(").replace(" )", ")")
    if all_known:
        try:
            return const(int(eval("".join(py_parts), {"__builtins__": {}}, {})))
        except Exception:  # noqa: BLE001 - odd text stays symbolic
            pass
    return sym(shown)


# ------------------------------------------------------------------ conditions
def _condition(text: str, env: dict, ctx: Context):
    """Return (decided, plain text). decided is True, False, or None when it cannot be known."""
    raw = _clean(text)
    if raw.upper() in ctx.cond88:
        parent, values = ctx.cond88[raw.upper()]
        current = env.get(parent)
        plain = f"{raw.upper()} is true when {parent} is " + " or ".join(f"'{v}'" for v in values)
        ctx.cond_used.add(raw.upper())
        if current is not None and current.lit is not None:
            return current.lit.rstrip(" ") in [v.rstrip(" ") for v in values], plain
        return None, plain
    if re.search(r"\s(AND|OR)\s", raw, re.IGNORECASE):
        return None, _plain_logic(raw)
    m = COMPARE_RE.match(raw)
    if not m:
        val = _operand(raw, env, ctx)
        return (bool(val.num) if val.num is not None else None), raw
    left = _operand(m.group(1), env, ctx)
    op = re.sub(r"\s+", " ", m.group(2).upper())
    right = _operand(m.group(3), env, ctx)
    lname = left.origin or left.text
    rname = right.origin or right.text
    plain = f"{lname} is {OP_TEXT.get(op, op.lower())} {rname}"
    if left.num is not None and right.num is not None:
        ops = {"=": left.num == right.num, "NOT =": left.num != right.num, "NOT=": left.num != right.num,
               ">": left.num > right.num, "<": left.num < right.num, ">=": left.num >= right.num,
               "<=": left.num <= right.num, "NOT >": not left.num > right.num, "NOT <": not left.num < right.num,
               "NOT>": not left.num > right.num, "NOT<": not left.num < right.num}
        return ops.get(op), plain
    if left.lit is not None and right.lit is not None:
        a, b = left.lit.rstrip(" "), right.lit.rstrip(" ")
        ops = {"=": a == b, "NOT =": a != b, "NOT=": a != b, ">": a > b, "<": a < b,
               ">=": a >= b, "<=": a <= b}
        return ops.get(op), plain
    return None, plain


def _plain_logic(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace(" AND ", " and ").replace(" OR ", " or ")


# ------------------------------------------------------------------ statements
def _assign(name: str, value: Val, env: dict, ctx: Context, line: int, how: str, via: str) -> None:
    env[name.upper()] = value
    ctx.changes.append(Change(line, name.upper(), value.text, how, via))


def _names_used(ctx: Context) -> set[str]:
    return set(ctx.cond_used)


def _names_in(text: str) -> list[str]:
    return [w.upper() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]*", text or "") if w.upper() not in KEYWORDS]


def _apply(stmt: Statement, env: dict, ctx: Context, via: str, depth: int, stack: tuple) -> bool:
    """Apply one statement. Returns False when control leaves the paragraph (GO TO, STOP)."""
    ctx.steps += 1
    if ctx.steps > MAX_STEPS:
        if not ctx.exhausted:
            ctx.exhausted = True
            ctx.notes.append(f"analysis stopped after {MAX_STEPS} steps: the result below is partial")
        return False
    text = _clean(stmt.text)
    upper = text.upper()
    if stmt.kind == "IF":
        _if(stmt, env, ctx, via, depth, stack)
        return True
    if stmt.kind == "EVALUATE":
        ctx.decisions.append(Decision(stmt.line, f"EVALUATE {stmt.condition}", None,
                                      [b.label for b in stmt.branches], [], via))
        subject = _operand(stmt.condition, env, ctx)
        branch_envs = []
        for branch in stmt.branches:
            if stmt.condition.strip().upper() == "TRUE":      # EVALUATE TRUE: each WHEN is a condition
                _record_constraints(branch.label, env, ctx, stmt.line, via)
            else:
                add_constraint(subject, _literals(branch.label), ctx, stmt.line, via,
                               f"{stmt.condition} = {branch.label}")
            branch_env = dict(env)
            _run_list(branch.body, branch_env, ctx, via, depth, stack)
            branch_envs.append(branch_env)
        if branch_envs:
            _merge(env, branch_envs)
        return True
    if stmt.kind == "PERFORM":
        if stmt.branches:
            for inner in stmt.branches[0].body:
                if not _apply(inner, env, ctx, via, depth, stack):
                    return False
            return True
        target = (stmt.target or "").upper()
        ctx.calls.append({"target": target, "line": stmt.line, "via": via})
        program = ctx.analysis.program
        if target in program.paragraph_map and depth < MAX_PERFORM_DEPTH and target not in stack:
            _run_paragraph(target, env, ctx, depth + 1, stack + (target,))
        else:
            if target not in program.paragraph_map:
                ctx.notes.append(f"line {stmt.line}: PERFORM {target}: that paragraph is not in this program, "
                                 "so its effect is unknown")
            else:
                ctx.notes.append(f"line {stmt.line}: PERFORM {target} not followed (depth or recursion limit)")
        return True
    if stmt.kind == "GOTO":
        ctx.notes.append(f"line {stmt.line}: {stmt.text} leaves the paragraph")
        return False
    if stmt.kind in ("TERMINATE", "EXIT_PARA"):
        ctx.notes.append(f"line {stmt.line}: {stmt.kind.replace('_', ' ').lower()}")
        return False

    m = re.match(r"^MOVE\s+(.+?)\s+TO\s+(.+)$", text, re.IGNORECASE)
    if m:
        value = _operand(m.group(1), env, ctx)
        for dst in _split_targets(m.group(2)):
            ref = _refmod(dst)
            if ref:
                name = ref[0]
                ctx.changes.append(Change(stmt.line, f"{name}({ref[1]}:{ref[2]})", value.text, "MOVE part", via))
            elif dst.upper() not in KEYWORDS:
                if value.slice and ctx.layouts.get(dst.upper(), {}).get("children"):
                    ctx.group_moves.append({"line": stmt.line, "group": dst.upper(), "slice": value.slice,
                                            "via": via})
                _assign(dst, value, env, ctx, stmt.line, "MOVE", via)
        return True
    m = re.match(r"^COMPUTE\s+(.+?)\s*=\s*(.+)$", text, re.IGNORECASE)
    if m:
        target = m.group(1).strip()
        value = _operand(m.group(2), env, ctx)
        _assign(target, value, env, ctx, stmt.line, "COMPUTE", via)
        return True
    m = re.match(r"^ADD\s+(.+?)\s+TO\s+(.+)$", text, re.IGNORECASE)
    if m:
        for target in _split_targets(m.group(2)):
            cur = _operand(target, env, ctx)
            add = _operand(m.group(1), env, ctx)
            _assign(target, _combine(cur, "+", add), env, ctx, stmt.line, "ADD", via)
        return True
    m = re.match(r"^SUBTRACT\s+(.+?)\s+FROM\s+(.+)$", text, re.IGNORECASE)
    if m:
        for target in _split_targets(m.group(2)):
            cur = _operand(target, env, ctx)
            sub = _operand(m.group(1), env, ctx)
            _assign(target, _combine(cur, "-", sub), env, ctx, stmt.line, "SUBTRACT", via)
        return True
    m = re.match(r"^SET\s+(.+?)\s+TO\s+TRUE$", text, re.IGNORECASE)
    if m:
        name = m.group(1).upper()
        if name in ctx.cond88:
            parent, values = ctx.cond88[name]
            if values:
                _assign(parent, text_lit(values[0]), env, ctx, stmt.line, f"SET {name} TO TRUE", via)
        else:
            ctx.notes.append(f"line {stmt.line}: SET {name} TO TRUE (condition name is not declared here)")
        return True
    if upper.startswith(("DISPLAY", "CONTINUE", "INITIALIZE", "EXEC", "CALL")):
        return True
    return True


def _split_targets(text: str) -> list[str]:
    parts = []
    for word in re.split(r"\s+", _clean(text).strip()):
        if word and word.upper() not in KEYWORDS and word not in ("GIVING", "ROUNDED"):
            parts.append(word)
    return parts


def _combine(a: Val, op: str, b: Val) -> Val:
    if a.num is not None and b.num is not None:
        return const(a.num + b.num if op == "+" else a.num - b.num)
    return sym(f"{a.text} {op} {b.text}")


OR_SPLIT_RE = re.compile(r"\s+OR\s+|\s*,\s*", re.IGNORECASE)


def _literals(text: str) -> list[str]:
    out = []
    for alt in OR_SPLIT_RE.split(text):
        alt = alt.strip().strip("()").strip()
        if alt.startswith("'") and alt.endswith("'") and len(alt) >= 2:
            out.append(alt[1:-1])
        elif re.fullmatch(r"-?\d+", alt):
            out.append(str(int(alt)))
    return out


def add_constraint(left: Val, allowed: list[str], ctx: Context, line: int, via: str, shown: str) -> None:
    """Note that a branch is taken only when the left side equals one of the allowed values."""
    if not allowed:
        return
    if left.slice:
        name, start, length = left.slice
        ctx.constraints.append({"kind": "slice", "buffer": name, "start": start, "length": length,
                                "allowed": allowed, "line": line, "via": via, "text": shown})
    elif (left.origin or left.text.upper()) in ctx.child_of:
        name = left.origin or left.text.upper()
        ctx.constraints.append({"kind": "field", "field": name,
                                "group": ctx.child_of[name],
                                "allowed": allowed, "line": line, "via": via, "text": shown})


def _record_constraints(compare: str, env: dict, ctx: Context, line: int, via: str) -> None:
    m = re.match(r"^(.+?)\s*=\s*(.+)$", _clean(compare))
    if not m or re.search(r"\bNOT\b", m.group(1), re.IGNORECASE):
        return
    left = _operand(m.group(1), env, ctx)
    allowed = _literals(m.group(2))
    if not allowed:
        right = _operand(m.group(2), env, ctx)          # e.g. IF RCV(...) = WS-TAB-CHAR
        if right.lit is not None:
            allowed = [right.lit]
        elif right.num is not None:
            allowed = [str(right.num)]
    add_constraint(left, allowed, ctx, line, via, _clean(compare))


def _if(stmt: Statement, env: dict, ctx: Context, via: str, depth: int, stack: tuple) -> None:
    _record_constraints(stmt.condition, env, ctx, stmt.line, via)
    decided, plain = _condition(stmt.condition, env, ctx)
    true_body = next((b.body for b in stmt.branches if b.label == "TRUE"), [])
    false_body = next((b.body for b in stmt.branches if b.label == "FALSE"), [])
    when_true = [_shallow(s) for s in true_body]
    when_else = [_shallow(s) for s in false_body]
    ctx.decisions.append(Decision(stmt.line, plain, decided, when_true, when_else, via))

    if decided is True:
        _run_list(true_body, env, ctx, via, depth, stack)
    elif decided is False:
        _run_list(false_body, env, ctx, via, depth, stack)
    else:
        env_true, env_else = dict(env), dict(env)
        _run_list(true_body, env_true, ctx, via, depth, stack)
        _run_list(false_body, env_else, ctx, via, depth, stack)
        for name in set(env_true) | set(env_else):
            a = env_true.get(name)
            b = env_else.get(name)
            if a is None or b is None:
                env[name] = a or b
            elif a.text == b.text:
                env[name] = a
            else:
                env[name] = sym(f"({a.text} or {b.text})")


def _merge(env: dict, envs: list[dict]) -> None:
    """Values after a choice: a name keeps its value only if every branch leaves it the same."""
    for name in set().union(*envs):
        values = [e[name] for e in envs if name in e]
        texts = []
        for v in values:
            if v.text not in texts:
                texts.append(v.text)
        if len(values) == len(envs) and len(texts) == 1:
            env[name] = values[0]
        else:
            env[name] = sym("(" + " or ".join(texts) + ")")


def _shallow(stmt: Statement) -> str:
    if stmt.kind == "IF":
        return f"IF {stmt.condition}"
    if stmt.kind == "PERFORM" and stmt.target:
        return f"PERFORM {stmt.target}"
    return _clean(stmt.text)


def _run_list(statements: list[Statement], env: dict, ctx: Context, via: str, depth: int, stack: tuple) -> bool:
    for stmt in statements:
        if not _apply(stmt, env, ctx, via, depth, stack):
            return False
    return True


def _run_paragraph(name: str, env: dict, ctx: Context, depth: int, stack: tuple) -> None:
    para = ctx.analysis.program.paragraph_map[name]
    _run_list(para.statements, env, ctx, name, depth, stack)


# ------------------------------------------------------------------ public
def trace_paragraph(analysis, paragraph: str, initial_env: dict | None = None,
                    buffer: tuple[str, str] | None = None):
    """Run the tracker over one paragraph. Returns (context, final values) or None.
    buffer: (name, contents) when the reference-modified reads should use real bytes."""
    if paragraph not in analysis.program.paragraph_map:
        return None
    layouts = _layouts(analysis)
    initial = _initial_values(analysis.data_entries)
    child_of = {}
    for name, info in layouts.items():
        for child in info.get("children", []):
            child_of[child["name"]] = name
    ctx = Context(analysis=analysis, layouts=layouts, initial=initial, child_of=child_of,
                  cond88=condition_names(analysis.data_entries),
                  buffer=(buffer[0].upper(), buffer[1]) if buffer else None)
    env = dict(initial)
    for name, val in (initial_env or {}).items():
        env[name.upper()] = val
    _run_paragraph(paragraph, env, ctx, 0, (paragraph,))
    return ctx, env


def _roles(statements) -> dict[str, dict]:
    """Each WS- name in these statements: read, written, and the lines it appears on."""
    from ..analyzer.reference_analyzer import walk_statements
    roles: dict[str, dict] = {}

    def note(name, role, line):
        entry = roles.setdefault(name, {"read": False, "written": False, "lines": []})
        entry[role] = True
        if line not in entry["lines"]:
            entry["lines"].append(line)

    for stmt, _ in walk_statements(statements):
        text = _clean(stmt.text)
        if stmt.kind == "IF" or stmt.kind == "EVALUATE":
            for n in _names_in(stmt.condition):
                note(n, "read", stmt.line)
            continue
        if stmt.kind == "PERFORM" or stmt.kind == "GOTO":
            continue
        m = re.match(r"^MOVE\s+(.+?)\s+TO\s+(.+)$", text, re.IGNORECASE)
        if m:
            for n in _names_in(m.group(1)):
                note(n, "read", stmt.line)
            for n in _split_targets(m.group(2)):
                note(n.upper(), "written", stmt.line)
            continue
        m = re.match(r"^COMPUTE\s+(.+?)\s*=\s*(.+)$", text, re.IGNORECASE)
        if m:
            note(m.group(1).strip().upper(), "written", stmt.line)
            for n in _names_in(m.group(2)):
                note(n, "read", stmt.line)
            continue
        m = re.match(r"^(ADD|SUBTRACT)\s+(.+?)\s+(TO|FROM)\s+(.+)$", text, re.IGNORECASE)
        if m:
            for n in _names_in(m.group(2)):
                note(n, "read", stmt.line)
            for n in _split_targets(m.group(4)):
                note(n.upper(), "written", stmt.line)
            continue
        m = re.match(r"^SET\s+(.+?)\s+TO\s+(.+)$", text, re.IGNORECASE)
        if m:
            for n in _names_in(m.group(1)):
                note(n, "written", stmt.line)
            for n in _names_in(m.group(2)):
                note(n, "read", stmt.line)
            continue
        for n in _names_in(text):
            note(n, "read", stmt.line)
    return roles


def used_variables(analysis, paragraph: str, env: dict, layouts: dict, initial: dict) -> list[dict]:
    """Every WS- data item the paragraph names, with its type, length, start value, end value and roles."""
    from ..values.working_storage import names_in_code
    para = analysis.program.paragraph_map[paragraph]
    roles = _roles(para.statements)
    out = []
    for name in names_in_code(para.source_text):
        if not name.startswith(LOCAL_PREFIX) or name not in layouts or layouts[name].get("children"):
            continue
        info = layouts[name]
        role = roles.get(name, {"read": False, "written": False, "lines": []})
        out.append({
            "name": name,
            "type": info.get("type"),
            "bytes": info.get("bytes"),
            "pic": info.get("pic"),
            "initial": initial[name].text if name in initial else None,
            "final": env[name].text if name in env else None,
            "read": bool(role["read"]),
            "written": bool(role["written"]),
            "lines": role["lines"],
        })
    return out


def analyze_values(analysis, paragraph: str, initial_env: dict | None = None) -> dict | None:
    """Follow the local variables through one paragraph and the paragraphs it PERFORMs."""
    traced = trace_paragraph(analysis, paragraph, initial_env)
    if traced is None:
        return None
    ctx, env = traced
    layouts = ctx.layouts
    initial = ctx.initial

    local_names = sorted({c.name for c in ctx.changes if c.name.startswith(LOCAL_PREFIX)}
                         | {n for n in env if n.startswith(LOCAL_PREFIX) and n not in ctx.cond88})
    condition_out = [{"name": n, "parent": p, "values": v, "parent_value": (env[p].text if p in env else None)}
                     for n, (p, v) in sorted(ctx.cond88.items())
                     if n in {c.name for c in ctx.changes} or n in _names_used(ctx)]
    locals_out = []
    for name in local_names:
        info = layouts.get(name, {})
        history = [{"line": c.line, "value": c.value, "how": c.how, "via": c.via}
                   for c in ctx.changes if c.name == name]
        locals_out.append({
            "name": name,
            "type": info.get("type"),
            "bytes": info.get("bytes"),
            "pic": info.get("pic"),
            "initial": initial[name].text if name in initial else None,
            "final": env[name].text if name in env else None,
            "history": history,
        })

    chain = [f"line {c.line}: {c.name} = {c.value}" + (f" (via {c.via})" if c.via != paragraph else "")
             for c in ctx.changes]
    decisions = []
    for d in ctx.decisions:
        decisions.append({
            "line": d.line,
            "condition": d.condition,
            "decided": None if d.decided is None else ("true" if d.decided else "false"),
            "when_true": d.when_true,
            "when_else": d.when_else,
            "via": d.via,
        })
    return {
        "paragraph": paragraph,
        "used_variables": used_variables(analysis, paragraph, env, layouts, initial),
        "exhausted": ctx.exhausted,
        "locals": locals_out,
        "chain": chain,
        "decisions": decisions,
        "slices": ctx.slices,
        "calls": ctx.calls,
        "condition_names": condition_out,
        "notes": ctx.notes,
    }
