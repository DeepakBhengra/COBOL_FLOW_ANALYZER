"""Converts COBOL paragraphs into a Python module that behaves like them.

The module has one function per paragraph, a data table of the working storage (from the same data
layout the analysis uses), and the condition-name table. It imports cobol_runtime.py, which holds the
COBOL rules for MOVE, comparisons, reference modification and PERFORM.

Converted: IF / ELSE, EVALUATE (subject and TRUE forms, with WHEN lists), PERFORM (paragraph, THRU
range, inline with UNTIL), GO TO a paragraph-exit, EXIT PARAGRAPH, STOP RUN / GOBACK, CONTINUE,
MOVE (including reference modification and LENGTH OF), COMPUTE, ADD, SUBTRACT, SET ... TO TRUE, SET,
INITIALIZE, and external statements (EXEC CICS / EXEC SQL / CALL), which are recorded, not run.

Not converted (written as a comment and recorded in the notes): other verbs, GO TO to a paragraph that
is not an exit of the paragraph before it, and EVALUATE forms with ranges.
"""
from __future__ import annotations

import re

from ..analyzer.reference_analyzer import walk_statements
from ..values.local_values import condition_names
from ..values.working_storage import working_storage

RUNTIME_NAMES = "Program, SPACES, ZERO, eq, ne, gt, lt, ge, le, cmp, num, div, ProgramStop, LoopLimit"
TOKEN_RE = re.compile(
    r"'[^']*'|\"[^\"]*\"|[+-]?\d+(?:\.\d+)?(?![A-Za-z0-9-])|[A-Za-z][A-Za-z0-9-]*|<>|>=|<=|[=<>()+\-*/:,]")
FIGURATIVE = {"SPACE": "SPACES", "SPACES": "SPACES", "ZERO": "ZERO", "ZEROS": "ZERO", "ZEROES": "ZERO"}
COMPARE_WORDS = {"=", "<>", ">", "<", ">=", "<="}


class Unsupported(Exception):
    pass


def py_name(paragraph: str) -> str:
    return "p_" + re.sub(r"[^0-9A-Za-z]", "_", paragraph)


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.replace(" = ", " = "))


def _normalise_compare(tokens: list[str]) -> list[str]:
    """Turn COBOL comparison words into symbols: IS, EQUAL TO, NOT EQUAL, GREATER THAN ..."""
    out = []
    i = 0
    upper = [t.upper() if not t.startswith(("'", '"')) else t for t in tokens]
    while i < len(upper):
        t = upper[i]
        seq = upper[i:i + 6]
        if t == "IS":
            i += 1
            continue
        if seq[:4] == ["GREATER", "THAN", "OR", "EQUAL"] and len(seq) >= 4:
            out.append(">=")
            i += 4
            if upper[i:i + 1] == ["TO"]:
                i += 1
            continue
        if seq[:3] == ["LESS", "THAN", "OR"] and seq[3:4] == ["EQUAL"]:
            out.append("<=")
            i += 4
            if upper[i:i + 1] == ["TO"]:
                i += 1
            continue
        if seq[:2] == ["EQUAL", "TO"] or (t == "EQUAL" and upper[i + 1:i + 2] != ["TO"]):
            out.append("=")
            i += 2 if upper[i + 1:i + 2] == ["TO"] else 1
            continue
        if seq[:2] == ["NOT", "EQUAL"]:
            out.append("<>")
            i += 2
            if upper[i:i + 1] == ["TO"]:
                i += 1
            continue
        if seq[:3] == ["NOT", "GREATER", "THAN"]:
            out.append("<=")
            i += 3
            continue
        if seq[:3] == ["NOT", "LESS", "THAN"]:
            out.append(">=")
            i += 3
            continue
        if seq[:2] == ["GREATER", "THAN"]:
            out.append(">")
            i += 2
            continue
        if seq[:2] == ["LESS", "THAN"]:
            out.append("<")
            i += 2
            continue
        if seq[:1] == ["GREATER"]:
            out.append(">")
            i += 1
            continue
        if seq[:1] == ["LESS"]:
            out.append("<")
            i += 1
            continue
        out.append(tokens[i])
        i += 1
    return out


class Expr:
    """Parses operands and arithmetic over a token list."""

    def __init__(self, tokens: list[str], conditions: dict):
        self.t = tokens
        self.i = 0
        self.conditions = conditions

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def operand(self) -> str:
        tok = self.take()
        if tok is None:
            raise Unsupported("missing operand")
        if tok.startswith(("'", '"')):
            return repr(tok[1:-1])
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", tok):
            return repr(int(float(tok))) if "." not in tok else repr(float(tok))
        up = tok.upper()
        if up in FIGURATIVE:
            return FIGURATIVE[up]
        if up == "LENGTH" and self.peek() and self.peek().upper() == "OF":
            self.take()
            name = self.take().upper()
            return f"p.length({name!r})"
        if up == "(":
            inner = self.arith()
            self.expect(")")
            return inner
        if up in ("+", "-"):
            return f"({up}{self.operand()})"
        name = up
        if self.peek() == "(":
            self.take()
            start = self.arith()
            if self.peek() == ":":
                self.take()
                length = self.arith()
                self.expect(")")
                return f"p.sub({name!r}, {start}, {length})"
            self.expect(")")
            return f"p.sub({name!r}, {start}, 1)"
        return f"p.get({name!r})"

    def expect(self, tok):
        if self.peek() is None or self.peek().upper() != tok:
            raise Unsupported(f"expected {tok}")
        self.take()

    def term(self) -> str:
        left = self.factor()
        while self.peek() in ("*", "/"):
            op = self.take()
            right = self.factor()
            left = f"num({left}) * num({right})" if op == "*" else f"div({left}, {right})"
        return left

    def factor(self) -> str:
        return self.operand()

    def arith(self) -> str:
        left = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.term()
            left = f"(num({left}) {op} num({right}))"
        return left


class Conditions:
    """Parses IF / WHEN conditions into a Python boolean expression."""

    def __init__(self, conditions: dict):
        self.conditions = conditions

    def parse(self, text: str) -> str:
        tokens = _normalise_compare(_tokens(text))
        parser = _CondParser(tokens, self.conditions)
        expr = parser.cond()
        if parser.i != len(tokens):
            raise Unsupported(f"could not read the condition: {text}")
        return expr


class _CondParser:
    def __init__(self, tokens, conditions):
        self.t = tokens
        self.i = 0
        self.conditions = conditions

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def cond(self) -> str:
        left = self.and_()
        while (self.peek() or "").upper() == "OR":
            self.take()
            left = f"({left} or {self.and_()})"
        return left

    def and_(self) -> str:
        left = self.unary()
        while (self.peek() or "").upper() == "AND":
            self.take()
            left = f"({left} and {self.unary()})"
        return left

    def unary(self) -> str:
        if (self.peek() or "").upper() == "NOT":
            self.take()
            return f"(not {self.unary()})"
        if self.peek() == "(":
            self.take()
            inner = self.cond()
            if self.take() != ")":
                raise Unsupported("missing )")
            return inner
        return self.relation()

    def relation(self) -> str:
        first = self.peek()
        if first is None:
            raise Unsupported("empty condition")
        up = first.upper()
        if up in self.conditions and not (self.peek(1) in COMPARE_WORDS or (self.peek(1) or "").upper() == "NOT"):
            self.take()
            parent, values = self.conditions[up]
            options = [f"eq(p.get({parent!r}), {v!r})" for v in values] or ["False"]
            return "(" + " or ".join(options) + ")"
        left = self._operand()
        op = self.peek()
        negate = False
        if (op or "").upper() == "NOT":
            self.take()
            negate = True
            op = self.peek()
        if op not in COMPARE_WORDS:
            # A bare operand is true when it is not blank or zero.
            return f"(num({left}) != 0 or {left} not in (SPACES, ' '))"
        self.take()
        compare = {"=": "eq", "<>": "ne", ">": "gt", "<": "lt", ">=": "ge", "<=": "le"}[op]
        if self.peek() == "(" and op == "=" and self._or_list_ahead():
            self.take()
            items = [self._operand()]
            while (self.peek() or "").upper() == "OR":
                self.take()
                items.append(self._operand())
            if self.take() != ")":
                raise Unsupported("missing ) after the list")
            expr = "(" + " or ".join(f"eq({left}, {item})" for item in items) + ")"
            return f"(not {expr})" if negate else expr
        right = self._operand()
        expr = f"{compare}({left}, {right})"
        alternatives = [expr]
        # Abbreviated relation: X = 'A' OR 'B' OR 'C'
        while op == "=" and (self.peek() or "").upper() == "OR" and self._literal_at(1):
            self.take()
            alternatives.append(f"eq({left}, {self._operand()})")
        if len(alternatives) > 1:
            expr = "(" + " or ".join(alternatives) + ")"
        return f"(not {expr})" if negate else expr

    def _or_list_ahead(self) -> bool:
        """True when the parenthesis at the cursor holds an OR list at its top level."""
        depth = 0
        for k in range(len(self.t) - self.i):
            tok = self.t[self.i + k]
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
                if depth == 0:
                    return False
            elif tok.upper() == "OR" and depth == 1:
                return True
        return False

    def _literal_at(self, k: int) -> bool:
        tok = self.peek(k)
        return tok is not None and (tok.startswith(("'", '"')) or bool(re.fullmatch(r"[+-]?\d+", tok)))

    def _operand(self) -> str:
        expr = Expr(self.t[self.i:], self.conditions)
        text = expr.operand()
        self.i += expr.i
        return text


def _split_names(text: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z0-9-]*", text)]


class Generator:
    def __init__(self, analysis, conditions: dict):
        self.analysis = analysis
        self.conditions = conditions
        self.cond = Conditions(conditions)
        self.notes: list[str] = []
        self.exit_after: dict[str, str] = {}
        paragraphs = analysis.program.paragraphs
        for i, para in enumerate(paragraphs[:-1]):
            nxt = paragraphs[i + 1].name
            self.exit_after[para.name] = nxt

    # ----------------------------------------------------------- statements
    def _copybook_origin(self, line: int) -> str | None:
        """'ERXBATCH.txt:3' when a statement came from a copybook, None when it is in the program itself."""
        program = self.analysis.program
        origin = program.line_origin.get(line)
        if origin and not origin.startswith(program.source_name + ":"):
            return origin
        return None

    def block(self, statements, paragraph: str, indent: int) -> list[str]:
        self.current = paragraph
        lines = []
        for stmt in statements:
            origin = self._copybook_origin(stmt.line)
            if origin:
                lines.append(" " * indent + f"p.origin({origin!r})")
            lines.extend(self.statement(stmt, paragraph, indent))
        return lines or [" " * indent + "pass"]

    def statement(self, stmt, paragraph: str, indent: int) -> list[str]:
        pad = " " * indent
        try:
            if stmt.kind == "IF":
                return self._if(stmt, paragraph, indent)
            if stmt.kind == "EVALUATE":
                return self._evaluate(stmt, paragraph, indent)
            if stmt.kind == "PERFORM":
                return self._perform(stmt, paragraph, indent)
            if stmt.kind == "GOTO":
                target = (stmt.targets or [stmt.target or ""])[0].upper()
                if self.exit_after.get(paragraph) == target or target.endswith("-EXIT") and self._is_exit_of(paragraph, target):
                    return [pad + "return  # GO TO the exit of this paragraph"]
                raise Unsupported(f"GO TO {target}")
            if stmt.kind == "TERMINATE":
                return [pad + "p.stop()"]
            if stmt.kind == "EXIT_PARA":
                return [pad + "return"]
            if stmt.kind == "NOOP":
                return [pad + "pass"]
            return self._simple(stmt, pad)
        except Unsupported as exc:
            self.notes.append(f"{paragraph} line {stmt.line}: {exc}")
            return [pad + f"p.unsupported({stmt.text[:80]!r})"]

    def _is_exit_of(self, paragraph: str, target: str) -> bool:
        names = [p.name for p in self.analysis.program.paragraphs]
        if paragraph not in names or target not in names:
            return False
        return names.index(target) == names.index(paragraph) + 1

    def _if(self, stmt, paragraph, indent):
        pad = " " * indent
        cond = self.cond.parse(stmt.condition)
        true_body = next((b.body for b in stmt.branches if b.label == "TRUE"), [])
        false_body = next((b.body for b in stmt.branches if b.label == "FALSE"), [])
        lines = [f"{pad}if {cond}:"] + self.block(true_body, paragraph, indent + 4)
        if false_body:
            lines += [f"{pad}else:"] + self.block(false_body, paragraph, indent + 4)
        return lines

    def _evaluate(self, stmt, paragraph, indent):
        pad = " " * indent
        subject_text = stmt.condition
        lines: list[str] = []
        if subject_text.strip().upper() == "TRUE":
            subject = None
        else:
            subject = Expr(_tokens(subject_text), self.conditions).operand()
            lines.append(f"{pad}_subject = {subject}")
        first = True
        otherwise = None
        for branch in stmt.branches:
            body = branch.body
            label = branch.label.strip()
            if label.upper() == "OTHER":
                otherwise = body
                continue
            if subject is None:
                test = self.cond.parse(label)
            else:
                alternatives = []
                for alt in re.split(r"\s+OR\s+", label, flags=re.IGNORECASE):
                    alt = alt.strip().strip("()").strip()
                    if alt:
                        alternatives.append(f"eq(_subject, {Expr(_tokens(alt), self.conditions).operand()})")
                if not alternatives:
                    raise Unsupported(f"WHEN {label}")
                test = "(" + " or ".join(alternatives) + ")"
            lines.append(f"{pad}{'if' if first else 'elif'} {test}:")
            lines += self.block(body, paragraph, indent + 4)
            first = False
        if otherwise is not None:
            if first:
                lines += self.block(otherwise, paragraph, indent)
            else:
                lines += [f"{pad}else:"] + self.block(otherwise, paragraph, indent + 4)
        return lines

    def _perform(self, stmt, paragraph, indent):
        pad = " " * indent
        if stmt.branches:      # inline PERFORM ... END-PERFORM
            header = (stmt.condition or "").strip()
            body = stmt.branches[0].body
            varying = re.match(r"^VARYING\s+(\S+)\s+FROM\s+(.+?)\s+BY\s+(.+?)\s+UNTIL\s+(.+)$",
                               header, re.IGNORECASE)
            if varying:
                index = varying.group(1).upper()
                start = Expr(_tokens(varying.group(2)), self.conditions).arith()
                step = Expr(_tokens(varying.group(3)), self.conditions).arith()
                test = self.cond.parse(varying.group(4))
                lines = [f"{pad}p.put({index!r}, {start})", f"{pad}_count = 0",
                         f"{pad}while not ({test}):", f"{pad}    _count += 1", f"{pad}    p.loop_check(_count)"]
                return lines + self.block(body, paragraph, indent + 4) + [
                    f"{pad}    p.put({index!r}, num(p.get({index!r})) + num({step}))"]
            if header.upper().startswith("UNTIL "):
                test = self.cond.parse(header[6:])
                lines = [f"{pad}_count = 0", f"{pad}while not ({test}):",
                         f"{pad}    _count += 1", f"{pad}    p.loop_check(_count)"]
                return lines + self.block(body, paragraph, indent + 4)
            if header.upper().endswith("TIMES") or header == "":
                count = Expr(_tokens(header[:-5]), self.conditions).operand() if header.upper().endswith("TIMES") else "1"
                return [f"{pad}for _i in range(num({count})):"] + self.block(body, paragraph, indent + 4)
            raise Unsupported(f"PERFORM {header}")
        if stmt.thru:
            return [f"{pad}p.perform_thru({stmt.target.upper()!r}, {stmt.thru.upper()!r})"]
        return [f"{pad}p.perform({stmt.target.upper()!r})"]

    def _simple(self, stmt, pad):
        verb = stmt.verb.upper()
        text = " ".join(stmt.text.split())
        if verb == "MOVE":
            m = re.match(r"^MOVE (.+?) TO (.+)$", text, re.IGNORECASE)
            if not m:
                raise Unsupported(text)
            src = Expr(_tokens(m.group(1)), self.conditions).operand()
            return [pad + line for line in self._store_all(m.group(2), src)]
        if verb == "COMPUTE":
            m = re.match(r"^COMPUTE (.+?) = (.+)$", text, re.IGNORECASE)
            if not m:
                raise Unsupported(text)
            value = Expr(_tokens(m.group(2)), self.conditions).arith()
            return [pad + line for line in self._store_all(m.group(1), value, numeric=True)]
        if verb == "ADD":
            m = re.match(r"^ADD (.+?) TO (.+)$", text, re.IGNORECASE)
            if not m:
                raise Unsupported(text)
            amount = Expr(_tokens(m.group(1)), self.conditions).arith()
            out = []
            for target in _split_names(m.group(2)):
                out.append(f"{pad}p.put({target!r}, num(p.get({target!r})) + num({amount}))")
            return out
        if verb == "SUBTRACT":
            m = re.match(r"^SUBTRACT (.+?) FROM (.+)$", text, re.IGNORECASE)
            if not m:
                raise Unsupported(text)
            amount = Expr(_tokens(m.group(1)), self.conditions).arith()
            return [f"{pad}p.put({t!r}, num(p.get({t!r})) - num({amount}))" for t in _split_names(m.group(2))]
        if verb == "SET":
            m = re.match(r"^SET (.+?) TO (TRUE|.+)$", text, re.IGNORECASE)
            if not m:
                raise Unsupported(text)
            name = m.group(1).strip().upper()
            if m.group(2).upper() == "TRUE":
                if name not in self.conditions:
                    raise Unsupported(text)
                parent, values = self.conditions[name]
                return [f"{pad}p.put({parent!r}, {values[0]!r})"] if values else [pad + "pass"]
            value = Expr(_tokens(m.group(2)), self.conditions).operand()
            return [f"{pad}p.put({name!r}, {value})"]
        if verb == "INITIALIZE":
            return [f"{pad}p.initialize({t!r})" for t in _split_names(text[len("INITIALIZE"):])]
        if verb in ("CONTINUE", "EXIT"):
            return [pad + "pass"]
        if verb == "COPY":
            name = (text.split()[1] if len(text.split()) > 1 else "?").rstrip(".")
            raise Unsupported(f"copybook {name} was not found in the copybook library, so its statements are missing")
        if verb == "NEXT" or text.upper().startswith("NEXT SENTENCE"):
            self.notes.append(f"NEXT SENTENCE treated as CONTINUE: {text[:60]}")
            return [pad + "pass"]
        if verb == "EXEC" or verb in ("CALL",):
            return [f"{pad}p.external({self._raw_text(stmt)!r})"]
        if verb == "DISPLAY":
            return [f"{pad}p.display({text[len('DISPLAY'):].strip()[:200]!r})"]
        raise Unsupported(text)

    def _raw_text(self, stmt) -> str:
        """The statement as written in the source (commas and full host variable names kept)."""
        para = self.analysis.program.paragraph_map.get(self.current or "")
        if para is None or not para.source_text:
            return " ".join(stmt.text.split())
        lines = para.source_text.split("\n")
        start = stmt.line - para.start_line
        if start < 0 or start >= len(lines):
            return " ".join(stmt.text.split())
        collected = []
        for line in lines[start:]:
            collected.append(line.strip())
            if re.search(r"\bEND-(EXEC|CALL)\b", line, re.IGNORECASE) or line.rstrip().endswith("."):
                break
        return " ".join(part for part in collected if part)

    def _store_all(self, targets_text: str, value: str, numeric: bool = False) -> list[str]:
        lines = []
        for target in re.split(r"\s+(?=[A-Za-z])", targets_text.strip()):
            t = target.strip()
            if not t or t.upper() in ("ROUNDED", "GIVING"):
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9-]*)\s*\((.*)\)$", t)
            if m:
                start = Expr(_tokens(m.group(2).split(":")[0]), self.conditions).arith()
                length = Expr(_tokens(m.group(2).split(":")[1]), self.conditions).arith() \
                    if ":" in m.group(2) else "1"
                lines.append(f"p.put_sub({m.group(1).upper()!r}, {start}, {length}, {value})")
            else:
                lines.append(f"p.put({t.upper()!r}, {value})")
        return lines


def generate(analysis, paragraphs: list[str]) -> dict:
    """The module text for the named paragraphs (and the paragraphs they PERFORM)."""
    conditions = condition_names(analysis.data_entries)
    conditions = {k.upper(): (v[0].upper(), list(v[1])) for k, v in conditions.items()}
    gen = Generator(analysis, conditions)
    program = analysis.program
    by_name = program.paragraph_map

    # Collect the paragraphs reached from the selected ones.
    wanted: list[str] = []
    queue = [p.upper() for p in paragraphs]
    while queue:
        name = queue.pop(0)
        if name in wanted:
            continue
        wanted.append(name)
        if name in by_name:
            for stmt, _ in walk_statements(by_name[name].statements):
                if stmt.kind == "PERFORM" and stmt.target:
                    queue.append(stmt.target.upper())
                    if stmt.thru:
                        queue.append(stmt.thru.upper())
    order = [p.name for p in program.paragraphs if p.name in wanted]
    order += [n for n in wanted if n not in order]

    functions = []
    for name in order:
        if name not in by_name:
            functions.append(f"def {py_name(name)}(p):\n"
                             f"    p.notes.append({'paragraph ' + name + ' is not in the program'!r})\n")
            continue
        body = gen.block(by_name[name].statements, name, 4)
        functions.append(f"def {py_name(name)}(p):\n" + "\n".join(body) + "\n")

    spec, initial = _data(analysis)
    notes = gen.notes
    module = []
    module.append('"""Python equivalent of the COBOL paragraphs ' + ", ".join(paragraphs) + '.\n\n'
                  'Generated from the COBOL analysis. It needs cobol_runtime.py in the same folder.\n'
                  'Set the input in the storage first, for example:\n'
                  '    p = new_program()\n'
                  '    p.put("RCV-DATA-BUFFER-AREA", "OL...")\n'
                  '    run(p, "' + paragraphs[0] + '")\n'
                  '"""')
    module.append("from cobol_runtime import " + RUNTIME_NAMES)
    module.append("")
    module.append("SPEC = " + repr(spec))
    module.append("CONDITIONS = " + repr(conditions))
    module.append("INITIAL = {" + ", ".join(f"{k!r}: {v}" for k, v in initial.items()) + "}")
    module.append("")
    module.extend(functions)
    module.append("REGISTRY = {" + ", ".join(f"{n!r}: {py_name(n)}" for n in order) + "}")
    module.append("ORDER = " + repr(order))
    declared = set(spec) | set(conditions)
    used = set(re.findall(r"p\.(?:get|put|sub|put_sub|initialize|length)\('([A-Za-z0-9-]+)'", "\n".join(functions)))
    undeclared = sorted(n for n in used if n not in declared and not n.startswith("__"))
    module.append("UNDECLARED = " + repr(undeclared))
    module.append("")
    module.append("def new_program():")
    module.append("    return Program(SPEC, INITIAL, REGISTRY, ORDER, CONDITIONS)")
    module.append("")
    module.append("def run(p, paragraph):")
    module.append("    try:")
    module.append("        p.perform(paragraph)")
    module.append("    except ProgramStop:")
    module.append("        pass")
    module.append("    return p")
    module.append("")
    return {
        "module": "\n".join(module) + "\n",
        "runtime": _runtime_text(),
        "paragraphs": order,
        "notes": notes,
    }


def _runtime_text() -> str:
    from pathlib import Path
    return (Path(__file__).with_name("cobol_runtime.py")).read_text(encoding="utf-8")


def _data(analysis):
    """The storage table: spec per item, and the starting value as Python source text."""
    from ..copybooks.layout import describe
    spec, initial = {}, {}
    for item in working_storage(analysis):
        if item.is_group or item.level == 88:
            continue
        numeric = item.type.startswith(("Zoned", "Binary", "Packed"))
        if numeric:
            meta = describe(item.pic, item.usage, False)
            spec[item.name] = {"kind": "number", "digits": meta["digits"] or item.bytes,
                               "signed": bool(meta["signed"])}
        else:
            spec[item.name] = {"kind": "text", "size": item.bytes}
        init = item.initial
        if init is None:
            initial[item.name] = "ZERO" if numeric else "SPACES"
        elif init.startswith("'") and init.endswith("'"):
            initial[item.name] = repr(init[1:-1])
        elif re.fullmatch(r"[Xx]'[0-9A-Fa-f]+'", init):
            initial[item.name] = repr("".join(chr(int(init[2:-1][i:i + 2], 16))
                                              for i in range(0, len(init) - 3, 2)))
        elif init.upper() in ("SPACES", "SPACE"):
            initial[item.name] = "SPACES"
        elif init.upper() in ("ZERO", "ZEROS", "ZEROES"):
            initial[item.name] = "ZERO"
        elif init.lstrip("+-").isdigit():
            initial[item.name] = repr(int(init))
        else:
            initial[item.name] = "SPACES" if not numeric else "ZERO"
    return spec, initial
