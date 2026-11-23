# COBOL Flow Analyzer

Upload a COBOL program (with its copybooks) and see how it works: its paragraphs and the calls
between them, the conditions behind each call, the values of its local variables, the input record
it reads from CICS, a plain-language summary and business logic for each paragraph, a flow chart,
and a Python module that runs the same logic. Every analysis is logged, so the next run of the same
program is easy to find.

The full design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). How a requirement becomes a code
change is in [docs/CHANGE_PROPOSAL.md](docs/CHANGE_PROPOSAL.md).

## Setup

```bash
pip install -r requirements.txt
```

Node.js is needed for the React UI (`npm` in `frontend/`).

## Run the React UI (recommended)

The React front end talks to a FastAPI service that runs the analyzer.

```bash
# terminal 1 - API on http://127.0.0.1:8000
uvicorn api.server:app --reload --port 8000

# terminal 2 - UI on http://localhost:5173 (proxies /api to the API)
cd frontend
npm install
npm run dev
```

If the API runs on another port, set `API_PROXY` (for example `API_PROXY=http://127.0.0.1:8001`)
before `npm run dev`.

For a production-style build, run `npm run build` in `frontend/` and serve `frontend/dist`.

The API keeps analyses in memory. After you change the backend, restart it and analyse the program again.

## Run the Streamlit UI (older alternative)

```bash
streamlit run app.py
```

The Streamlit screens cover the first version of the analyzer only.

## Screens

1. **Program Upload** - upload a `.cbl` file or load a sample (sample01, INP389, and others).
   Shows divisions, sections, and the source.
2. **Program Overview** - divisions, sections, paragraph, statement and call counts, and exports
   (Excel, JSON, paragraph and call-site CSV).
3. **Paragraph Explorer** - a searchable paragraph list. For the selected paragraph:
   - definition, callers with their conditions, outgoing calls, and every mention in the procedure division;
   - **Summary** - each IF with its true and else actions, every PERFORM made inside it, and the
     fields it changes, in program order. The copybook a line came from is named where it applies;
   - **Simulated input** - when the paragraph receives an input record (for example
     `INP389-TRANSACTION-AREA` from `EXEC CICS RETRIEVE`), the record built field by field at its
     offsets, including COMP-3 packed fields, and the logic run on it;
   - **Convert to Python** - the paragraph and the paragraphs it PERFORMs as a Python module, with
     `cobol_runtime.py`, and a download button for each;
   - **Business logic** - rules and plain-language explanations, review findings, and a flow chart
     per paragraph (zoom with the buttons or Ctrl + mouse wheel; scroll up, down and sideways).
4. **Paragraph Flow** - the statement tree of one paragraph, what happens after it completes,
   incoming and outgoing transfers, and a local flow diagram.
5. **Program Flow Map** - the whole-program call graph, a legend, and the static execution trace.
6. **Copybook Layout** - every copybook in the library, with its fields (level, PICTURE, USAGE,
   type, offset, length, OCCURS, REDEFINES, 88-level names) and the meaning of each field. A
   copybook that holds procedure code (for example an abend routine) shows its statements, plus
   its own summary, logic and flow chart.
7. **Program Log** - every analysed program, its runs, and the details you add about it.
8. **Program Values** - the input buffer a program reads (for example `RCV-DATA-BUFFER-AREA`), where
   it is set and read, a sample built by running the program's own tests (with an assumptions box
   such as `WS-NEXT-POS=1`), the local variables a paragraph uses with their values, the logic
   chain, and the decisions.

## Analysis features

- **Structure:** paragraphs (including headers in Area A that follow a statement with no period),
  sections, PERFORM / GO TO call graph, reachability, never-called paragraphs, and a static trace.
- **Copybooks:** `COPY` is expanded before analysis, including `REPLACING`, nested and missing
  copybooks. A copybook is treated as data or as procedure code. Field meanings are saved and reused.
- **Local values:** the tracer follows WS- variables through IF, EVALUATE, PERFORM and COMPUTE,
  keeps the value of each computed result for the statements after it, and shows
  reference-modified slices such as `RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)`.
- **Input records:** EXEC CICS RETRIEVE and MOVE DFHCOMMAREA are recognised as the program's input.
  The record is built from its declared layout, with COMP-3 packed decimal stored as real bytes.
- **Python conversion:** IF / ELSE, EVALUATE, PERFORM (THRU, inline UNTIL, VARYING), MOVE with
  reference modification, COMPUTE, ADD, SUBTRACT, SET, INITIALIZE, and external statements
  (kept as text). The generated code is checked against COBOL rules by tests that run it.
- **Business logic:** read from the generated Python: decisions with their outcomes, repeats,
  actions, and findings such as constant conditions, undeclared names, SQL host variables that are
  not declared, and statements that are not converted.
- **Program log:** every analysis is recorded with its paragraph summaries, decisions and changes,
  indexed by program name (PROGRAM-ID) and paragraph.
- **COMMAREA:** the CICS COMMAREA layout, the CICS commands that move data, field usage, and
  standards checks (see below).
- **Change proposals:** a requirement in plain words is turned into one proposed code change (see below).

## Copybook Layout tab (meanings of fields)

The **Copybook Layout** screen lists every copybook in the library, lays out each one (level,
PICTURE, USAGE, type, offset, length, OCCURS, REDEFINES, 88-level condition names), and lets
you write what each field means. Notes are saved in `output/copybook_knowledge.db` (change the
location with `COBOL_KNOWLEDGE_DB`). When a program copies a copybook, the saved notes are attached
to its fields. A note is flagged *changed since noted* if the copybook text has changed since the
note was written.

Notes can also be added from a TBX table document (for the `TBIxxxx` copybooks) and copied from one
copybook to its twin (`CORORx` to `ORRORx`) by field name.

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

To use a copybook folder such as the COPYBOOK folder of your project, set `COBOL_COPYBOOKS` before
starting the API (folders are separated by `;` on Windows):

```bash
set COBOL_COPYBOOKS=C:\path\to\COPYBOOK
uvicorn api.server:app --port 8000
```

```bash
python -m src.copybooks --list --copybook-dir sample_programs/copybooks  # copybooks found
python -m src.copybooks sample_programs/cics_custcopy.cbl            # used / missing copybooks
python -m src.copybooks sample_programs/cics_custcopy.cbl --expanded # expanded text with origins
```

Every line of an expanded program records where it came from (`CUSTCOMM.cpy:3`), available
as `Program.line_origin`. Statements copied in from a copybook are labelled with it in the summary,
the Python module, the business logic and the flow charts.

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

## API

The API is documented in section 8 of [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The main endpoints:

| Path | Purpose |
|---|---|
| `POST /api/analyze` | analyse a program (source, optional copybooks) |
| `GET /api/analyses/{id}` | the analysis payload |
| `GET /api/analyses/{id}/paragraphs/{name}` | one paragraph: callers, calls, source |
| `GET /api/analyses/{id}/paragraphs/{name}/summary` | summary, decisions, changes, simulated input |
| `GET /api/analyses/{id}/paragraphs/{name}/locals` | local variable values and the logic chain |
| `GET /api/analyses/{id}/paragraphs/{name}/python` | Python module and runtime for a paragraph |
| `GET /api/analyses/{id}/paragraphs/{name}/business-logic` | business rules, explanations, findings, flow |
| `GET /api/analyses/{id}/input-buffer` | input buffers and a sample built from the tests |
| `GET /api/analyses/{id}/simulate` | the input record built and the logic run on it |
| `GET /api/copybooks/{name}` | a copybook's layout, or its code if it holds procedure code |
| `GET /api/copybooks/{name}/procedure` | summary, logic and flow of a procedure copybook |
| `GET /api/program-log/...` | the program log and paragraph records |

## Run the tests

```bash
py -m pytest -q
```

The suite has 118 tests covering the parser, COMMAREA, copybooks, the program log, summaries, the
tracer, the buffer and record builders, the Python conversion (the generated code is run and
checked), the business logic, flow charts, and change proposals.

## Layout

```
api/server.py               FastAPI service: analysis, paragraph, values, simulation, conversion endpoints
api/copybook_routes.py      copybook library, layouts, procedure copybooks, field notes
api/programlog_routes.py    program log and paragraph records
frontend/                   React (Vite) UI styled after the Order Re-Build reference
app.py                      Streamlit screens (older alternative UI)
src/pipeline.py             source text -> Analysis (all views)
src/parser/                 fixed-format normalisation, lexer, divisions/paragraphs, statements
src/models/                 Program, Paragraph, Statement, CallSite, ExecEvent
src/analyzer/               reference (call sites), flow (graph, status, trace), paragraph views
src/copybooks/              COPY expansion, library, layouts, field notes, meanings
src/summary/                paragraph summaries and program insights
src/values/                 local variable tracer, WORKING-STORAGE, input buffers and records, buffer search
src/convert/                COBOL paragraph -> Python module, and its runtime
src/business/               business logic, explanations, findings and flow from the Python module
src/programlog/             program log store (SQLite)
src/commarea/               COMMAREA layout, CICS commands, field usage, standards
src/changes/                change proposals from a requirement
src/visualization/          Graphviz DOT builders
src/export/                 Excel / CSV / JSON
src/storage.py              SQLite persistence for the older Streamlit app
docs/                       architecture and change-proposal documents
```

## Limits

* The analyzer does not evaluate data values in the static analysis, so every branch is shown as
  possible. The buffer, record and simulation features use the values you give (or a sample) and
  report the decisions that depend on values they do not have.
* Loops are followed once in the tracer and the buffer search. The generated Python runs loops for real.
* `ALTER` and dynamic `GO TO` (no static target) are reported, not followed.
* Calls to other programs (`CALL 'X'`) are listed as external; their code is not analysed, and SQL
  return codes must be supplied to follow a success path.
* The Python conversion covers the common statements. A GO TO to another paragraph, EVALUATE ranges
  and some verbs are reported as not converted.
* `EXEC SQL INCLUDE` is not expanded, so host variables from an SQL copybook appear as undeclared.
* The execution trace is a static first pass: each paragraph is expanded once, and a GO TO inside a
  PERFORM range is followed only to the end of that range.
* The API keeps analyses in memory, so they are lost when the server restarts.
