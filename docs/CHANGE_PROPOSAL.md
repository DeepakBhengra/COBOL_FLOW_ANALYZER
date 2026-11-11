# Change proposal: architecture

This document describes one feature: given a program the analyzer has already read, and a
requirement that names one field and one value, `src/changes` proposes the COBOL edit that
would make the program do that. It does not modify the source file, and it does not invent a
new SQL statement.

The worked example is INP389 and the requirement
`update SETATRK-ACOP-PROMO-FLG with 'Y'`. The same path is used for any other field.

The rest of the analyzer is described in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. What the feature does

The analyzer explains a program as it is. This feature takes that explanation and answers a
different question: where would a requested assignment go, and what would the lines look like.

For one requirement it returns:

- the host variable, its PICTURE, and, when the name comes from a DCLGEN, the DB2 column and table;
- the paragraph and source line of the `UPDATE` or `INSERT` that already writes that table;
- the COBOL lines to insert or replace, aligned with the surrounding source;
- the paragraph as it would read after the edit;
- consequences taken from the call graph (who calls the paragraph, how SQL codes are handled);
- warnings when the value does not fit the picture, and a refusal when the program has nowhere
  to put the change.

A refusal is a result. If the field is not in the program, or the program never writes that
table, the report says so and returns no edit.

---

## 2. Where it sits

```
 requirement text
        |
        v
 +------------------+     +---------------------------+
 | src/changes      |---->| Analysis from src.pipeline |
 |  requirement.py  |     |  paragraphs, statements    |
 |  dclgen.py       |     |  call sites, reachability  |
 |  propose.py      |     |  source lines and origins  |
 +--------+---------+     +-------------+-------------+
          |                             |
          |                             v
          |               +---------------------------+
          +-------------->| CopybookLibrary           |
                          |  EXEC SQL INCLUDE members |
                          +---------------------------+
          |
          v
   proposal dict  (text report or JSON)
   source file is left unchanged
```

Nothing in `api/` or `frontend/` calls this module. It is a Python entry point:

```bash
python -m src.changes sample_programs/INP389.cbl.txt "update SETATRK-ACOP-PROMO-FLG with 'Y'"
```

`open_program` analyses the file with the same copybook search as `analyze_file`: the program's
folder, a `copybooks` folder beside it, any `--copybook-dir`, and `COBOL_COPYBOOKS`.
`propose_change(analysis, requirement, library)` does the rest, so a caller that already holds
an `Analysis` does not analyse the program twice.

---

## 3. Modules

| Module | Responsibility |
| --- | --- |
| `src/changes/requirement.py` | Turn one sentence into a field name and a value. It does not know which program is being changed. |
| `src/changes/dclgen.py` | Read a DB2 DCLGEN member: `DECLARE table`, column types, and the COBOL host fields under it. |
| `src/changes/propose.py` | Join the requirement to the analysis, choose the SQL statement, and build the edit. |
| `src/changes/__main__.py` | Command line. Exit 0 when a proposal is produced, 2 when the requirement cannot be placed. |

`requirement.py` accepts any field, not a fixed list. These are the same request:

- `update SETATRK-ACOP-PROMO-FLG with 'Y'`
- `set ACOP_PROMO_FLG to Y`
- `MOVE 'Y' TO SETATRK-ACOP-PROMO-FLG`
- `set DEMO-PROMO-FLG from INP389-OPER-ID`

A quoted token or a number is a literal. A hyphenated name, or a name that already exists in the
expanded DATA DIVISION, is a sending field (`MOVE INP389-OPER-ID TO ...`). A sentence with no
field and no value is rejected before any program fact is read.

`dclgen.py` is separate because the analyzer does not expand `EXEC SQL INCLUDE`. The host
variables of `SETATRK` are not in the expanded DATA DIVISION of INP389. This module reads the
included member from the copybook library and pairs each COBOL name with the column named in
the comment above it (`ACOP_PROMO_FLG` above `SETATRK-ACOP-PROMO-FLG`). The `NAMES(SETATRK-)`
prefix is used when that comment is missing. `picture_capacity` reads `PIC X(1)` as one
character so a longer value can be warned about.

---

## 4. How a requirement becomes an edit

`propose_change` runs these steps in order. Each step adds a sentence to `evidence` so the
report can show which facts were used.

1. **Parse the sentence.** `parse_requirement` returns the field as written, a COBOL source
   token (`'Y'`, `100`, or another data name), and whether that token is a literal or a field.
2. **Find included DCLGEN members.** Walk the program source, ignoring comment lines. Inside
   each `EXEC SQL` ... `END-EXEC`, record `INCLUDE name`. INP389 yields `SQLCA` and `SETATRK`.
   A member that is not in the library is reported and skipped. `SQLCA` is skipped that way.
3. **Resolve the field.** Match the requested name to a host variable or a column, treating
   hyphens and underscores as the same. `ACOP_PROMO_FLG` and `SETATRK-ACOP-PROMO-FLG` resolve
   to the same host field. If several DCLGEN members declare it, the one whose table this
   program already updates is kept. If it is not in a DCLGEN, an elementary item of the same
   name in the expanded DATA DIVISION is used, with no table.
4. **Find SQL writes.** Walk every paragraph's statement tree. An `EXEC SQL` whose source block
   contains `UPDATE table` or `INSERT INTO table` becomes a write. The block is the original
   source lines from `EXEC` through `END-EXEC`, not the flattened statement text: the lexer
   drops commas, and the SET layout is read from the source. Assignments between `SET` and
   `WHERE` are the columns. Host variables are the `:NAME` tokens.
5. **Choose one write.** Keep writes of the field's table. A requirement whose first word is
   "update" prefers `UPDATE` over `INSERT` when both exist. The remaining candidates are ranked:
   the statement already sets this column, then it already uses this host variable, then the
   paragraph is reachable from the entry, then it uses more host variables, then it appears
   earlier in the source. Other writes of the same table are left unchanged and named in a
   warning.
6. **Build the edit** from the shape of that statement. See the next section.
7. **Describe the effect** from facts already on the analysis: reachability, callers and their
   conditions, whether `SQLCODE-NOT-FOUND` is continued, whether the paragraph abends, and
   whether any copied input field has a similar name. A literal is used when no copied field
   carries the value.

If step 3 or step 5 fails, the function returns `ok: false` and no edit. The source file is
never opened for writing.

---

## 5. Three shapes of edit

The statement that was chosen decides the shape. The new lines copy the indentation and the
column of `=` from a neighbouring line, so the proposal matches the program's layout.

**The column is not in the SET yet.** This is the INP389 promo-flag case. Insert
`MOVE 'Y' TO host` after the last `MOVE` that feeds this SQL, and insert
`,COLUMN = :host` before `WHERE`. The `WHERE` clause is not rewritten.

**The column is already set, and a MOVE already fills the host variable.** If that MOVE already
has the requested value, `change_required` is false and there is no edit. If the value differs,
only that MOVE line is replaced. The column is not added a second time. Setting
`SETATRK-ACOP-ACTV-FLG` to `'N'` is the first case, because INP389 already moves `'N'`. Setting
it to `'Y'` is the second.

**The write is an INSERT.** A MOVE is proposed before the statement. The column list and the
`VALUES` list are not rewritten; the report says that part still has to be done by hand.

A value longer than the PICTURE, or a non-numeric value moved to a numeric picture, is still
proposed. The warning names the picture and the length. `NOT NULL` is noted when the column
was declared that way, because a literal satisfies it.

---

## 6. What the proposal contains

`propose_change` returns one dictionary. The command prints it as a text report, or as JSON
with `--json`.

| Field | Meaning |
| --- | --- |
| `ok` | The requirement was understood and a place was found, or the program already does it. False when there is nowhere to put the change. |
| `change_required` | True when `edits` is not empty. |
| `requirement` | Field, value, and whether the value is a literal or another field. |
| `understood` | One sentence: what would change, and in which paragraph. |
| `field` | Host name, column, table, PICTURE, USAGE, SQL type, nullability, copybook. |
| `placement` | Paragraph, expanded line, origin such as `INP389.cbl.txt:91`, callers, and why this statement was chosen. |
| `edits` | `insert_after`, `insert_before`, or `replace_line`, each with the origin, the anchor line, the new text, and the reason. |
| `proposed_paragraph` | The paragraph source with those edits applied. |
| `diff` | The same paragraph, with added lines marked `+`. |
| `consequences` | What a normal run would do, from the call graph and the SQL checks already in the paragraph. |
| `warnings` | Picture overflow, a second write left untouched, a sending field that is not declared. |
| `evidence` | The facts that were read: included members, the declaration, and each SQL write. |

Line numbers in `edits` are expanded-program lines. `origin` is `Program.line_origin`, so a
line that came from the program file is reported as `INP389.cbl.txt:89` rather than the
expanded number.

---

## 7. Worked example: INP389

INP389 is a CICS subroutine. `000-MAINLINE` receives `INP389-TRANSACTION-AREA` and performs
`1000-UPDATE-ACOP-TRK`. That paragraph updates `ACOP_TRK` and sets `ACOP_ACTV_FLG` from a
literal `'N'`.

The requirement `update SETATRK-ACOP-PROMO-FLG with 'Y'` is not a special case in the code.
The steps above produce it as follows.

- `INCLUDE SETATRK` is in the program. The library file `SETATRK.txt` declares table `ACOP_TRK`
  and host field `SETATRK-ACOP-PROMO-FLG`, `PIC X(1)`, column `ACOP_PROMO_FLG CHAR(1) NOT NULL`.
- The only SQL write is `UPDATE ACOP_TRK` in `1000-UPDATE-ACOP-TRK`, called from `000-MAINLINE`
  by `PERFORM THRU` with no condition. The paragraph is reachable.
- `ACOP_PROMO_FLG` is not in the SET list. The other host variables are filled by MOVE
  statements immediately before the SQL. The new MOVE is inserted after
  `MOVE 'N' TO SETATRK-ACOP-ACTV-FLG`, and the new column is inserted before `WHERE`, with `=`
  in the same column as the existing SET lines.

```cobol
           MOVE 'Y'                    TO SETATRK-ACOP-PROMO-FLG.
                    ,ACOP_PROMO_FLG    =  :SETATRK-ACOP-PROMO-FLG
```

The company and tracking number in the `WHERE` clause stay as they are. SQL code 0 and +100
still continue, because those tests are in the same paragraph and the edit does not touch them.
Any other SQL code still performs `999-ABEND`. No copied input field contains `PROMO`, so the
value is the literal `'Y'`.

A different column of the same table, such as `SETATRK-ACOP-RVS-FLG`, follows this same path
and is added to the same `UPDATE`.

A field of another table does not. `WWCO-CO-NAM` is a real column of `WW_COMPANY` in
`WWTCMPNY.txt`, but INP389 does not `INCLUDE` that member and has no `UPDATE` of `WW_COMPANY`.
The report stops at step 3: the only table read from this program is `ACOP_TRK`. The feature
will add a column to an `UPDATE` the program already has. It will not create a new `UPDATE`
for a table the program does not write.

---

## 8. Facts it uses, and facts it does not

It uses:

- paragraph statements, so it can see `MOVE` and `EXEC SQL`;
- the original source lines of the SQL block, so commas and alignment survive;
- `line_origin`, so the report names the program file and line;
- call sites and paragraph status, so it can say the paragraph is reached from the entry and
  under which condition;
- the copybook library, for members named by `EXEC SQL INCLUDE`;
- COPY members already expanded into the DATA DIVISION, when the requirement names one of
  those fields as the value to move.

It does not use the saved copybook notes in `copybook_knowledge.db`, the program log, or the
paragraph-summary sentences. Those notes are empty for the INP389 copybooks, and the summary
sentences drop branches. The edit is built from the statement tree and the DCLGEN instead.

It does not search the whole copybook library. A DCLGEN that the program does not `INCLUDE`
is invisible, even when the file is on disk.

---

## 9. Limits

- One field and one value per requirement. A sentence such as "deactivate the ACOP" is rejected
  by the parser. Two fields in one sentence are not split.
- The table is discovered from the field's DCLGEN, not from a table name in the sentence.
- The program must already `UPDATE` or `INSERT` that table. A new statement, a new paragraph,
  and a new `INCLUDE` are not generated.
- `INSERT` column lists and `VALUES` lists are not rewritten.
- `EXEC SQL INCLUDE` is still not expanded by the analyzer. This feature reads those members
  itself, and only the DCLGEN shape it knows: `DECLARE table` plus a COBOL declaration.
- The `WHERE` clause is kept. The proposal does not decide which rows should change.
- The edit is a proposal. Nothing writes it back into the `.cbl` file, and the UI does not
  show it yet.

Tests for the INP389 promo flag, an already-coded literal, a changed literal, an unknown field,
a short synthetic program, and a picture-length warning are in `tests/test_change_proposal.py`.
