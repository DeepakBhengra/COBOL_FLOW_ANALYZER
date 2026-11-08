"""COBOL keyword sets used by the parser."""

# Verbs that start a statement in the PROCEDURE DIVISION.
STATEMENT_VERBS = frozenset({
    "ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE",
    "DELETE", "DISPLAY", "DIVIDE", "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK",
    "IF", "INITIALIZE", "INSPECT", "INVOKE", "MERGE", "MOVE", "MULTIPLY", "NEXT",
    "OPEN", "PERFORM", "READ", "RELEASE", "RETURN", "REWRITE", "SEARCH", "SET",
    "SORT", "START", "STOP", "STRING", "SUBTRACT", "UNSTRING", "WRITE", "ENTER",
})

# Explicit scope terminators. Matched exactly, so a paragraph such as END-PARA is not one.
END_KEYWORDS = frozenset({
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ", "END-WRITE", "END-REWRITE",
    "END-DELETE", "END-START", "END-CALL", "END-STRING", "END-UNSTRING", "END-ADD",
    "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE", "END-RETURN",
    "END-SEARCH", "END-ACCEPT", "END-DISPLAY", "END-EXEC", "END-INVOKE", "END-SORT",
    "END-MERGE", "END-JSON", "END-XML",
})

# Words that close or continue a statement block.
BLOCK_KEYWORDS = frozenset({"ELSE", "WHEN", "THEN"})

# Words that can never be the name of a paragraph.
RESERVED_FOR_HEADERS = STATEMENT_VERBS | BLOCK_KEYWORDS | frozenset({
    "END", "USE", "DECLARATIVES", "SECTION", "DIVISION", "NOT", "AT", "ON",
    "INVALID", "TO", "BY", "FROM", "UNTIL", "VARYING", "TIMES", "WITH", "TEST",
    "THRU", "THROUGH", "OTHER", "ALSO", "RUN", "PROGRAM", "PARAGRAPH",
})

# Optional clauses that introduce a conditional branch inside a simple statement.
# Each entry is the word sequence that opens the clause (NOT may prefix any of them).
BRANCH_CLAUSES = (
    ("AT", "END"),
    ("INVALID", "KEY"),
    ("ON", "SIZE", "ERROR"),
    ("ON", "EXCEPTION"),
    ("ON", "OVERFLOW"),
)

PERFORM_KEYWORDS = frozenset({"VARYING", "UNTIL", "WITH", "TEST", "TIMES", "FOREVER"})

# Verbs that may carry AT END / INVALID KEY / ON SIZE ERROR / ON EXCEPTION clauses.
CLAUSE_VERBS = frozenset({
    "READ", "WRITE", "REWRITE", "DELETE", "START", "RETURN", "CALL", "SEARCH", "ADD",
    "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE", "STRING", "UNSTRING", "ACCEPT", "INVOKE",
})
