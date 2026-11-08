"""Builds a statement tree from the tokens of one paragraph.

Scope rules followed (COBOL semantics):
  * A period ends the sentence and closes every open IF/EVALUATE/PERFORM scope.
  * ELSE, WHEN and END-xxx terminate the block they belong to.
  * Optional clauses (AT END, INVALID KEY, ON SIZE ERROR, ON EXCEPTION, ON OVERFLOW,
    and their NOT forms) open a conditional branch inside a simple statement.
"""
from __future__ import annotations

from ..models.paragraph import Branch, Statement
from .keywords import BRANCH_CLAUSES, CLAUSE_VERBS, END_KEYWORDS, PERFORM_KEYWORDS, STATEMENT_VERBS
from .lexer import PERIOD, STRING, WORD, Token


class StatementParser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.i = 0
        self.n = len(tokens)

    # ------------------------------------------------------------------ helpers
    def _word(self, index: int) -> str | None:
        if 0 <= index < self.n and self.toks[index].kind == WORD:
            return self.toks[index].upper()
        return None

    def _is_verb_start(self, index: int) -> bool:
        return self._word(index) in STATEMENT_VERBS

    def _clause_at(self, index: int) -> tuple[str, int] | None:
        """Return (label, token_count) if a branch clause opens at index."""
        negated = self._word(index) == "NOT"
        offset = 1 if negated else 0
        for clause in BRANCH_CLAUSES:
            words = [self._word(index + offset + k) for k in range(len(clause))]
            if tuple(words) == clause:
                label = " ".join(clause)
                if negated:
                    label = "NOT " + label
                return label, offset + len(clause)
        return None

    def _is_ender(self, index: int) -> bool:
        """True if the token closes the current block (not consumed here)."""
        if index >= self.n:
            return True
        tok = self.toks[index]
        if tok.kind == PERIOD:
            return True
        word = self._word(index)
        if word is None:
            return False
        if word in ("ELSE", "WHEN") or word in END_KEYWORDS:
            return True
        return self._clause_at(index) is not None

    def _block(self) -> list[Statement]:
        body: list[Statement] = []
        while self.i < self.n and not self._is_ender(self.i):
            body.append(self._statement())
        return body

    # ------------------------------------------------------------------ entry
    def parse(self) -> list[Statement]:
        statements: list[Statement] = []
        while self.i < self.n:
            if self.toks[self.i].kind == PERIOD or self._is_ender(self.i):
                # Stray terminator at the top level: skip it.
                self.i += 1
                continue
            statements.append(self._statement())
        return statements

    def _statement(self) -> Statement:
        word = self._word(self.i)
        if word == "IF":
            return self._if()
        if word == "EVALUATE":
            return self._evaluate()
        if word == "PERFORM":
            return self._perform()
        if word == "GO":
            return self._goto()
        if word == "EXEC":
            return self._exec()
        return self._simple()

    # ------------------------------------------------------------------ IF
    def _if(self) -> Statement:
        line = self.toks[self.i].line
        self.i += 1
        cond: list[str] = []
        while self.i < self.n and not self._is_ender(self.i) and self._word(self.i) != "THEN" \
                and not self._is_verb_start(self.i):
            cond.append(self.toks[self.i].value)
            self.i += 1
        if self._word(self.i) == "THEN":
            self.i += 1

        condition = " ".join(cond)
        true_body = self._block()
        branches = [Branch("TRUE", true_body)]
        if self._word(self.i) == "ELSE":
            self.i += 1
            branches.append(Branch("FALSE", self._block()))
        if self._word(self.i) == "END-IF":
            self.i += 1
        return Statement(kind="IF", verb="IF", text=f"IF {condition}", line=line,
                         condition=condition, branches=branches)

    # ------------------------------------------------------------------ EVALUATE
    def _evaluate(self) -> Statement:
        line = self.toks[self.i].line
        self.i += 1
        subject: list[str] = []
        while self.i < self.n and self._word(self.i) != "WHEN" and not self._is_ender(self.i):
            subject.append(self.toks[self.i].value)
            self.i += 1

        branches: list[Branch] = []
        while self._word(self.i) == "WHEN":
            self.i += 1
            cond: list[str] = []
            while self.i < self.n and not self._is_ender(self.i) and not self._is_verb_start(self.i):
                cond.append(self.toks[self.i].value)
                self.i += 1
            label = " ".join(cond) or "(no condition)"
            branches.append(Branch(label, self._block()))

        if self._word(self.i) == "END-EVALUATE":
            self.i += 1
        subj = " ".join(subject)
        return Statement(kind="EVALUATE", verb="EVALUATE", text=f"EVALUATE {subj}", line=line,
                         condition=subj, branches=branches)

    # ------------------------------------------------------------------ PERFORM
    def _perform(self) -> Statement:
        line = self.toks[self.i].line
        self.i += 1
        word = self._word(self.i)
        is_out_of_line = (
            word is not None
            and word not in PERFORM_KEYWORDS
            and not self._is_verb_start(self.i)
            and self._word(self.i + 1) != "TIMES"
            and self.toks[self.i].kind == WORD
        )
        if is_out_of_line:
            target = self.toks[self.i].value
            self.i += 1
            thru = None
            if self._word(self.i) in ("THRU", "THROUGH") and self.i + 1 < self.n:
                thru = self.toks[self.i + 1].value
                self.i += 2
            cond: list[str] = []
            while self.i < self.n and not self._is_ender(self.i) and not self._is_verb_start(self.i):
                cond.append(self.toks[self.i].value)
                self.i += 1
            text = f"PERFORM {target}" + (f" THRU {thru}" if thru else "")
            if cond:
                text += " " + " ".join(cond)
            return Statement(kind="PERFORM", verb="PERFORM", text=text, line=line,
                             target=target, thru=thru,
                             condition=" ".join(cond) or None)

        # Inline PERFORM: header (TIMES / UNTIL / VARYING ...) followed by statements.
        header: list[str] = []
        while self.i < self.n and not self._is_ender(self.i) and not self._is_verb_start(self.i):
            header.append(self.toks[self.i].value)
            self.i += 1
        body = self._block()
        if self._word(self.i) == "END-PERFORM":
            self.i += 1
        head = " ".join(header)
        return Statement(kind="PERFORM", verb="PERFORM", text=f"PERFORM {head} (inline)".strip(),
                         line=line, condition=head or None,
                         branches=[Branch("INLINE", body)])

    # ------------------------------------------------------------------ GO TO
    def _goto(self) -> Statement:
        line = self.toks[self.i].line
        self.i += 1
        if self._word(self.i) == "TO":
            self.i += 1
        targets: list[str] = []
        while self.i < self.n and not self._is_ender(self.i) and not self._is_verb_start(self.i):
            if self._word(self.i) == "DEPENDING":
                # GO TO a OR b DEPENDING ON x: skip the selector expression.
                self.i += 1
                while self.i < self.n and not self._is_ender(self.i) and not self._is_verb_start(self.i):
                    self.i += 1
                break
            if self.toks[self.i].kind == WORD:
                targets.append(self.toks[self.i].value)
            self.i += 1
        text = "GO TO " + " ".join(targets) if targets else "GO TO (dynamic)"
        return Statement(kind="GOTO", verb="GO TO", text=text, line=line,
                         target=targets[0] if targets else None, targets=targets)

    # ------------------------------------------------------------------ EXEC SQL / CICS
    def _exec(self) -> Statement:
        line = self.toks[self.i].line
        self.i += 1
        words: list[str] = []
        while self.i < self.n and self.toks[self.i].kind != PERIOD and self._word(self.i) != "END-EXEC":
            words.append(self.toks[self.i].value)
            self.i += 1
        if self._word(self.i) == "END-EXEC":
            self.i += 1
        return Statement(kind="SIMPLE", verb="EXEC", text="EXEC " + " ".join(words), line=line)

    # ------------------------------------------------------------------ simple statements
    def _simple(self) -> Statement:
        first = self.toks[self.i]
        verb = first.upper()
        line = first.line
        self.i += 1
        end_marker = "END-" + verb
        words: list[str] = []
        branches: list[Branch] = []

        while self.i < self.n:
            tok = self.toks[self.i]
            if tok.kind == PERIOD or self._is_verb_start(self.i):
                break
            if self._word(self.i) == end_marker:
                self.i += 1
                break
            if self._is_ender(self.i):
                clause = self._clause_at(self.i) if verb in CLAUSE_VERBS else None
                if clause is None:
                    break  # ELSE, WHEN, END-xxx or a clause that belongs to an outer statement
                label, count = clause
                self.i += count
                branches.append(Branch(label, self._block()))
                continue
            words.append(tok.value)
            self.i += 1

        return self._classify(verb, words, line, branches)

    def _classify(self, verb: str, words: list[str], line: int, branches: list[Branch]) -> Statement:
        text = " ".join([verb] + words)
        upper_words = [w.upper() for w in words]
        external = None
        if verb == "CALL" and words:
            external = words[0].strip("'\"")

        kind = "SIMPLE"
        if verb in ("STOP", "GOBACK"):
            kind = "TERMINATE"
        elif verb == "EXIT":
            if upper_words[:1] == ["PROGRAM"]:
                kind = "TERMINATE"
            elif upper_words[:1] in (["PARAGRAPH"], ["SECTION"]):
                kind = "EXIT_PARA"
            else:
                kind = "NOOP"
        elif verb == "CONTINUE":
            kind = "NOOP"

        return Statement(kind=kind, verb=verb, text=text, line=line,
                         external_call=external, branches=branches)
