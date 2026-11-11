"""Support code for the Python modules generated from COBOL paragraphs.

A generated module imports this file. It holds the working storage of the program in a Program
object, with COBOL rules for:
  * MOVE and storage: alphanumeric values are left-justified and padded with spaces, or truncated;
    numeric values are right-justified, truncated to their digits, and keep their sign;
  * comparisons: alphanumeric values are compared after padding the shorter with spaces;
  * reference modification: NAME(start:length) is 1-based, and writing it changes only those bytes;
  * PERFORM of a paragraph and PERFORM ... THRU a range, in program order;
  * external statements (EXEC CICS / EXEC SQL / CALL) are recorded, not run.
"""
from __future__ import annotations


class _Figurative:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name


SPACES = _Figurative("SPACES")
ZERO = _Figurative("ZERO")


class ProgramStop(Exception):
    """STOP RUN, GOBACK or EXIT PROGRAM was run."""


class LoopLimit(Exception):
    """A PERFORM UNTIL loop ran more times than the limit."""


LOOP_LIMIT = 10000


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def num(value) -> int:
    """A COBOL numeric value as a Python int (text of digits, blanks and signs allowed)."""
    if value is ZERO or value is SPACES or value is None:
        return 0
    if _is_number(value):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    sign = -1 if text.startswith("-") else 1
    digits = "".join(ch for ch in text if ch.isdigit())
    return sign * int(digits) if digits else 0


def text(value) -> str:
    """A COBOL alphanumeric value as text (figurative constants become their characters)."""
    if value is SPACES:
        return " "
    if value is ZERO:
        return "0"
    if _is_number(value):
        return str(value)
    return str(value)


def _pad_pair(a, b):
    a, b = text(a), text(b)
    width = max(len(a), len(b))
    return a.ljust(width), b.ljust(width)


def cmp(a, b) -> int:
    """-1, 0 or 1, comparing as COBOL does (numbers by value, text padded with spaces)."""
    if (a is ZERO or b is ZERO) or (_is_number(a) and _is_number(b)):
        x, y = num(a), num(b)
        return (x > y) - (x < y)
    if a is SPACES or b is SPACES:
        x, y = _pad_pair(a, b)
        return (x > y) - (x < y)
    if _is_number(a) or _is_number(b):
        x, y = num(a), num(b)
        return (x > y) - (x < y)
    x, y = _pad_pair(a, b)
    return (x > y) - (x < y)


def eq(a, b) -> bool:
    return cmp(a, b) == 0


def ne(a, b) -> bool:
    return cmp(a, b) != 0


def gt(a, b) -> bool:
    return cmp(a, b) > 0


def lt(a, b) -> bool:
    return cmp(a, b) < 0


def ge(a, b) -> bool:
    return cmp(a, b) >= 0


def le(a, b) -> bool:
    return cmp(a, b) <= 0


def div(a, b) -> int:
    """Division that truncates toward zero, as COBOL does when no ROUNDED phrase is given."""
    x, y = num(a), num(b)
    if y == 0:
        raise ZeroDivisionError("COBOL division by zero")
    q = abs(x) // abs(y)
    return q if (x >= 0) == (y >= 0) else -q


class Program:
    """Working storage and the paragraphs of one generated program."""

    def __init__(self, spec: dict, initial: dict, registry: dict, order: list[str], conditions: dict | None = None):
        self.spec = spec              # name -> {"kind": "text"|"number", "size": n, "digits": d, "signed": bool}
        self.registry = registry      # paragraph name -> function(program)
        self.order = order            # paragraph names in program order (for PERFORM THRU)
        self.conditions = conditions or {}   # 88 name -> (parent, [values])
        self.storage: dict = {}
        self.externals: list[str] = []
        self.displays: list[str] = []
        self.notes: list[str] = []
        self.paragraph_calls: list[str] = []
        self.missing: set[str] = set()
        for name, value in initial.items():
            self.storage[name] = self._coerce(name, value)

    # ------------------------------------------------------------ storage
    def _coerce(self, name: str, value):
        info = self.spec.get(name, {"kind": "text", "size": None})
        if info["kind"] == "number":
            if value is ZERO or value is SPACES:
                return 0
            n = num(value)
            digits = info.get("digits") or 0
            if digits:
                n = int(str(abs(n))[-digits:] or "0") * (-1 if n < 0 else 1)
            return n
        size = info.get("size")
        if value is SPACES:
            s = " "
        elif value is ZERO:
            s = "0"
        else:
            s = text(value)
        if size:
            s = s[:size].ljust(size)
        return s

    def get(self, name: str):
        if name not in self.storage and name not in self.spec:
            self.missing.add(name)
        return self.storage.get(name, SPACES)

    def put(self, name: str, value) -> None:
        if name in self.conditions:
            parent, values = self.conditions[name]
            if values:
                self.put(parent, values[0])
            return
        self.storage[name] = self._coerce(name, value)

    def sub(self, name: str, start, length) -> str:
        """NAME(start:length): the bytes beginning at 1-based position start."""
        s = text(self.get(name))
        a, n = num(start), num(length)
        return s[a - 1:a - 1 + n].ljust(n)

    def put_sub(self, name: str, start, length, value) -> None:
        """MOVE value TO NAME(start:length): only those bytes change."""
        s = text(self.get(name))
        a, n = num(start), num(length)
        s = s.ljust(a - 1 + n)
        piece = text(value).ljust(n)[:n]
        self.storage[name] = s[:a - 1] + piece + s[a - 1 + n:]

    def length(self, name: str) -> int:
        info = self.spec.get(name, {})
        if info.get("size"):
            return info["size"]
        return len(text(self.get(name)))

    def initialize(self, name: str) -> None:
        info = self.spec.get(name, {"kind": "text"})
        self.put(name, ZERO if info["kind"] == "number" else SPACES)

    def cond88(self, name: str) -> bool:
        parent, values = self.conditions[name]
        current = self.get(parent)
        return any(eq(current, v) for v in values)

    # ------------------------------------------------------------ control
    def perform(self, paragraph: str) -> None:
        self.paragraph_calls.append(paragraph)
        fn = self.registry.get(paragraph)
        if fn is None:
            self.notes.append(f"PERFORM {paragraph}: paragraph not in this module")
            return
        fn(self)

    def perform_thru(self, first: str, last: str) -> None:
        if first not in self.order or last not in self.order:
            self.notes.append(f"PERFORM {first} THRU {last}: range not in this module")
            return
        for name in self.order[self.order.index(first):self.order.index(last) + 1]:
            self.perform(name)

    def loop_check(self, count: int) -> None:
        if count > LOOP_LIMIT:
            raise LoopLimit(f"loop ran more than {LOOP_LIMIT} times")

    def external(self, statement: str) -> None:
        self.externals.append(statement)

    def display(self, *items) -> None:
        self.displays.append(" ".join(text(i) for i in items))

    def stop(self) -> None:
        raise ProgramStop()

    def origin(self, where: str) -> None:
        """Marks the statements that follow as coming from `where` (a copybook line). Nothing is run."""
        self.current_origin = where

    def unsupported(self, statement: str) -> None:
        self.notes.append(f"not converted: {statement}")
