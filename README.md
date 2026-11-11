# COBOL Flow Analyzer

Upload a COBOL program and see its paragraphs, the calls between them, the
conditions that guard each call, the order execution would follow, and which
paragraphs are never called.

## Setup

```bash
pip install -r requirements.txt
```

## Run the React UI (recommended)

The React front end talks to a small FastAPI service that runs the analyzer.

```bash
# terminal 1 - API on http://127.0.0.1:8000
pip install -r requirements.txt
uvicorn api.server:app --reload --port 8000

# terminal 2 - UI on http://localhost:5173 (proxies /api to the API)
cd frontend
npm install
npm run dev
```

For a production-style build, run `npm run build` in `frontend/` and serve `frontend/dist`.

## Run the Streamlit UI (alternative)

```bash
streamlit run app.py
```

Screens (in both UIs):

1. **Program Upload** – upload a `.cbl` file or load `sample_programs/sample01.cbl`.
2. **Program Overview** – divisions, sections, paragraph/statement/call counts, exports.
3. **Paragraph Explorer** – searchable paragraph list; for a paragraph: definition, callers
   with conditions, outgoing calls, every mention in the procedure division, source.
4. **Paragraph Flow** – statement tree of one paragraph, what happens after it completes,
   incoming and outgoing transfers, local flow diagram.
5. **Program Flow Map** – whole-program graph (Graphviz), legend, and the static execution trace.

## Copybook Layout tab (meanings of fields)

The **Copybook Layout** screen lists every copybook in the library, lays out each one (level,
PICTURE, USAGE, type, offset, length, OCCURS, REDEFINES, 88-level condition names), and lets
you write what each field means. Notes are saved in `output/copybook_knowledge.db` (change the
location with `COBOL_KNOWLEDGE_DB`). When a program copies a copybook, the saved notes are attached
to its fields in the COMMAREA report. A note is flagged *changed since noted* if the copybook text
has changed since the note was written.

Layout and notes are available from `src/copybooks/layout.py`, `knowledge.py`, and `meanings.py`,
and through the `/api/copybooks` endpoints.

## COPY statements and copybooks

`src/copybooks/` expands `COPY` before analysis, so copied data definitions and copied
procedure code are analyzed as if they were typed into the program. It handles:

* `COPY name.` and `COPY name OF library.`
* `COPY name REPLACING ==old== BY ==new==` (pseudo-text) and `REPLACING word BY word`
* multi-line COPY statements, nested copybooks, and circular copies (reported, not followed)
* missing copybooks (reported; the rest of the program is still analyzed)

Copybook files may be `.cpy` or `.txt` (other file types are ignored). Text is read as UTF-8, UTF-16 (with BOM), or Windows-1252, whichever fits. If `NAME.cpy` and `NAME.txt` both exist, the `.cpy` is used. Copybooks are found in this order: text uploaded with the program, the folder of the
program, a `copybooks` folder beside it, extra folders given on the command line, and
the folders listed in the `COBOL_COPYBOOKS` environment variable. Matching ignores case
and extension (`CUSTCOMM` finds `CUSTCOMM.cpy`).

```bash
python -m src.copybooks --list --copybook-dir sample_programs/copybooks  # copybooks found
python -m src.copybooks sample_programs/cics_custcopy.cbl            # used / missing copybooks
python -m src.copybooks sample_programs/cics_custcopy.cbl --expanded # expanded text with origins
```

Every line of an expanded program records where it came from (`CUSTCOMM.cpy:3`), available
as `Program.line_origin`.

## COMMAREA analysis (CICS programs)

`src/commarea/` explains how a CICS COBOL program uses its COMMAREA:

* lays out the `DFHCOMMAREA` (or any COMMAREA variable) with offsets and lengths
  (DISPLAY, COMP, COMP-3, OCCURS and REDEFINES are handled)
* lists every `EXEC CICS LINK / XCTL / RETURN / START / READ ...` and the data it moves
* tracks which paragraphs read and write each field, and under which conditions
* describes what the program does with the area, paragraph by paragraph
* checks the standards: DFHCOMMAREA in LINKAGE, 32,767-byte limit, explicit LENGTH,
  pseudo-conversational RETURN with TRANSID, EIBCALEN test, write-back of the response,
  channels and containers for larger data

```bash
python -m src.commarea sample_programs/cics_custinq.cbl          # text report
python -m src.commarea sample_programs/cics_custinq.cbl --json   # JSON
```

## Propose a change from a requirement

`src/changes/` reads an analysis and proposes one code change. It uses the paragraph that already updates the table, the host variables moved before that SQL statement, and the DCLGEN member named by `EXEC SQL INCLUDE`. It does not modify the source file.

```bash
python -m src.changes sample_programs/INP389.cbl.txt "update SETATRK-ACOP-PROMO-FLG with 'Y'"
python -m src.changes sample_programs/INP389.cbl.txt "set ACOP_PROMO_FLG to Y" --json
```

The text report shows the field (PICTURE, column, nullability), the paragraph and line where the edit belongs, the COBOL lines to add or replace, and what the change would affect. A value that does not fit the PICTURE is still proposed, with a warning.

The architecture of the whole tool is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). How a requirement becomes an edit, including the INP389 promo-flag example, is in [docs/CHANGE_PROPOSAL.md](docs/CHANGE_PROPOSAL.md).

## Run the tests

```bash
pytest -q tests
```

## Layout

```
api/server.py               FastAPI service: analyze, paragraph detail, search, exports
frontend/                   React (Vite) UI styled after the Order Re-Build reference
app.py                      Streamlit screens (alternative UI)
src/pipeline.py             source text -> Analysis (all views)
src/parser/                 fixed-format normalisation, lexer, divisions/paragraphs, statements
src/models/                 Program, Paragraph, Statement, CallSite, ExecEvent
src/analyzer/               reference (call sites), flow (graph, status, trace), paragraph views
src/visualization/          Graphviz DOT builders
src/export/                 Excel / CSV / JSON
src/commarea/              COMMAREA layout, CICS commands, field usage, standards
src/storage.py              SQLite persistence
```

## Limits

* The parser covers the common PROCEDURE DIVISION statements and control flow
  (IF/ELSE, EVALUATE/WHEN, PERFORM in all forms, GO TO, CALL, STOP RUN/GOBACK,
  EXIT PARAGRAPH, AT END / INVALID KEY / ON SIZE ERROR / ON EXCEPTION clauses, EXEC blocks).
  It does not evaluate data values, so every branch is shown as possible.
* `ALTER` and dynamic `GO TO` (no static target) are reported, not followed.
* Calls to other programs (`CALL 'X'`) are listed as external; their code is not analysed.
* The execution trace is a static first pass: each paragraph is expanded once, and a
  GO TO inside a PERFORM range is followed only to the end of that range.
