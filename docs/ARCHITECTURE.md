# COBOL Flow Analyzer: Architecture

This document describes how the COBOL Flow Analyzer is built: the layers, the modules in each,
the data it stores, the API it exposes, how a program moves through the system, and what is
still missing. It is kept up to date with the code; the change log at the end lists what changed
and when. Last updated: 2026-11-10.

---

## 1. Purpose

The tool reads a COBOL program (fixed or free format) with its copybooks and produces:

- the paragraph structure, PERFORM / GO TO call graph, and execution trace;
- which paragraphs are never called or unreachable;
- the CICS COMMAREA layout and standards checks;
- the layout of every copybook field, with the meaning written by people, and copybooks that hold
  procedure code rather than data;
- plain-language summaries of paragraphs and of the program's decision logic, including every
  PERFORM made inside an IF;
- the values of local (WS-) variables along a paragraph's path, and a sample input buffer
  (for example `RCV-DATA-BUFFER-AREA`) built by running the program's own tests;
- the input record an EXEC CICS RETRIEVE fills (for example `INP389-TRANSACTION-AREA`), built field
  by field, including COMP-3 packed decimal, and the logic run on it;
- a Python module equivalent to a paragraph, with a runtime, and business rules, review findings
  and flow charts read from that module;
- a log of every analysis, with each paragraph's summary, decisions and changes, indexed by
  program name and paragraph.

---

## 2. Layers

```
 +-----------------------------------------------------------------------+
 | React UI (frontend/)           Streamlit UI (app.py, earlier version) |
 +----------------------------------+------------------------------------+
                                    | JSON over HTTP  (/api/...)
 +----------------------------------v------------------------------------+
 | FastAPI backend (api/)                                                |
 |   server.py            analysis, paragraph, values, simulation,        |
 |                        Python, business-logic endpoints               |
 |   copybook_routes.py   copybook library, layouts, procedure code, notes|
 |   programlog_routes.py program log, paragraph records                 |
 +----------------------------------+------------------------------------+
                                    |
 +----------------------------------v------------------------------------+
 | Analysis core (src/)                                                  |
 |   pipeline.py     one call: source text -> Analysis                    |
 |   parser/         tokens -> divisions, sections, paragraphs, statements|
 |   copybooks/      COPY expansion, library, layouts, field notes        |
 |   analyzer/       references, call graph, reachability, trace, detail  |
 |   commarea/       CICS COMMAREA layout and checks                      |
 |   summary/        paragraph summaries and program insights             |
 |   values/         local variables, WORKING-STORAGE, buffers, records,  |
 |                   input detection                                      |
 |   convert/        COBOL paragraph -> Python module, and its runtime    |
 |   business/       business-logic extraction from the Python module     |
 |   programlog/     SQLite log of runs and paragraph records             |
 |   export/         Excel, CSV, JSON export                              |
 +----------------------------------+------------------------------------+
                                    |
 +----------------------------------v------------------------------------+
 | Storage (output/ and the copybook folders)                            |
 |   copybook_knowledge.db   copybook descriptions and field notes        |
 |   program_log.db          analysis runs, details, paragraph records    |
 |   program_log.jsonl       one line per analysis run                    |
 |   COBOL_COPYBOOKS folders the copybook library (.cpy and .txt files)   |
 +-----------------------------------------------------------------------+
```

The analysis core has no web code. The API and the UI only call into it, so every feature can be
tested directly from Python.

The Python conversion is an intermediate layer: COBOL paragraph -> generated Python module ->
business logic, explanations and flow charts. The business layer reads only the Python module.

---

## 3. Repository layout

```
COBOL_FLOW_ANALYZER/
  api/                     FastAPI routes
    server.py              main app: analysis and paragraph endpoints
    copybook_routes.py     /api/copybooks
    programlog_routes.py   /api/program-log
  src/
    pipeline.py            analyze_source / analyze_file -> Analysis
    storage.py             older per-analysis SQLite table (used by app.py)
    parser/                lexer, source format, statement tree, divisions, paragraphs
    analyzer/              reference analysis, flow graph, trace, paragraph detail
    commarea/              COMMAREA data layout, CICS commands, usage, checks, report
    copybooks/             expander, library, reader, layout, knowledge store, meanings
    summary/               paragraph summary and program insights
    values/                local_values (tracer), working_storage, buffer_builder,
                           buffer_search, input_buffer, record_builder
    convert/               cobol_runtime (runtime), python_gen (generator)
    business/              logic_extraction (rules, explanations, findings, flow)
    programlog/            program log store
    export/                report generator (xlsx, csv, json)
    models/                Program, Paragraph, Statement, CallSite, ExecEvent, ...
    visualization/         DOT flow diagram
  frontend/                Vite + React UI
    src/pages/             Upload, Overview, Explorer, Flow, Flow Map, Copybook,
                           Program Log, Program Values
    src/components/        ui, FlowGraph, FlowDiagram, ParagraphSummary, SimulatedInput,
                           ConvertToPython, BusinessLogic, Sidebar, Header, Icon
  sample_programs/         sample COBOL programs, INP389, and the copybook sample folder
  tests/                   pytest suite (108 tests)
  output/                  runtime databases and exports (created on demand)
  docs/ARCHITECTURE.md     this file
```

---

## 4. Analysis pipeline

Entry points: `src.pipeline.analyze_source(text, source_name, library, knowledge)` and
`analyze_file(path, copybook_dirs)`.

Steps in `analyze_source`:

1. **Normalise** (`parser/source_format.py`): fixed-format layout. Columns 1–6 (sequence) and
   73 onward (identification) are ignored. A `*` or `/` in column 7 makes the line a comment, and
   so does a `*` written after column 7. A `-` in column 7 continues the previous line. Lines
   without a valid layout are kept as free format.
2. **Expand copybooks** (`copybooks/expander.py`): every `COPY name [REPLACING ...]` is replaced
   by the copybook text, recursively, with cycle detection (depth limit 10). Each expanded line
   records its origin (`file:line`). A copybook may hold procedure code as well as data. `EXEC SQL
   INCLUDE` is not expanded yet.
3. **Tokenise** (`parser/lexer.py`): words (including `:PFX:` placeholders), numbers, strings,
   periods, parentheses and operators. Commas are not tokens; the converter keeps SQL and CICS
   text from the source instead of from the tokens.
4. **Parse structure** (`parser/division_parser.py`): divisions, sections, PROGRAM-ID, the raw
   DATA DIVISION entries, and the PROCEDURE DIVISION blocks. A name in Area A that ends with a
   period, and is not preceded by PERFORM, THRU, GO TO or similar, starts a paragraph even when the
   statement above it has no period (`normalize` marks these lines as headers).
5. **Build paragraphs** (`parser/paragraph_parser.py`) and parse each paragraph's statements into
   a tree (`parser/statement_parser.py`): IF / ELSE, EVALUATE / WHEN, PERFORM (out-of-line,
   inline, THRU, TIMES, UNTIL, VARYING), GO TO, EXEC CICS/SQL, and simple statements.
6. **Reference analysis** (`analyzer/reference_analyzer.py`): call sites (PERFORM, GO TO) with
   the conditions around them; external CALLs.
7. **Flow analysis** (`analyzer/flow_analyzer.py`): the call graph (networkx), reachability from
   the entry paragraph, never-called paragraphs, and a static execution trace.
8. **COMMAREA** (`commarea/`): the DATA DIVISION layout, CICS commands that move data, field
   usage (read / write / both), findings and standards checks.
9. **Copybook meanings** (`copybooks/meanings.py`): saved field notes are attached to the
   program's fields by their origin.
10. **Data layout** (`commarea/data_layout.py`): `data_roots` (every DATA DIVISION item with
    offsets and byte lengths) and `data_entries` (raw entries, kept for VALUE clauses and 88s).

The result is an `Analysis` object (`pipeline.py`) with: `program`, `analyzer`, `call_sites`,
`external_calls`, `graph`, `statuses`, `trace`, `commarea`, `copybooks`, `field_meanings`,
`data_roots`, `data_entries`. The API adds `analysis.library` so later calls can read the
copybooks again.

After analysis the API also writes the paragraph records to the program log (section 7).

### Data model (`models/`)

- `Program`: name, source name, line count, divisions, sections, paragraphs, data item count,
  procedure start line, source lines by number, line origins.
- `Paragraph`: name, index, section, start and end lines, statements, source text.
- `Statement`: kind (SIMPLE, IF, EVALUATE, PERFORM, GOTO, TERMINATE, EXIT_PARA, NOOP), verb,
  text, line, condition, target, thru, targets, branches (labelled bodies).
- `CallSite`, `ExternalCall`, `ExecEvent`: flow records.

---

## 5. Copybooks

- **Library** (`copybooks/library.py`): `CopybookLibrary` resolves a name to text. It searches
  folders from the `COBOL_COPYBOOKS` environment variable, the folder of the program, a
  `copybooks` subfolder, and extra folders passed by the caller. Texts can also be given
  directly (for uploads and tests).
- **Reader** (`copybooks/reader.py`): reads `.cpy` and `.txt` files, detects BOM, handles
  UTF-16, falls back to cp1252. `.cpy` wins over `.txt` with the same name.
- **Layout** (`copybooks/layout.py`): `layout_of_copybook(name, text)` returns every field with
  its path (for example `CUSTCOMM.CUST-NAME`), level, PICTURE, USAGE, type, offset, length,
  OCCURS, REDEFINES, and 88-level condition names, plus a fingerprint of the text. A copybook with
  no data entries is not an error: see procedure copybooks below.
- **Procedure copybooks:** a copybook with statements and no data entries (for example an abend
  routine such as `ERXBATCH`) holds code. The copybook API returns `kind`: `data`, `procedure` or
  `empty`, and for procedure copybooks the code lines by number. The Copybook page shows those lines
  instead of an empty field table. When such a copybook is copied into a PROCEDURE DIVISION, its
  statements run in the paragraph they are copied into, and the analysis tags them with their
  origin (section 6.7).
- **Expander** (`copybooks/expander.py`): `COPY ... REPLACING ==x== BY ==y==` and word
  replacement.
- **Knowledge store** (`copybooks/knowledge.py`, SQLite `output/copybook_knowledge.db`):
  - `copybook_notes`: a description per copybook, with the fingerprint of the text it describes;
  - `field_notes`: a meaning, category and tags per field, keyed by copybook and the declared
    field path, with the fingerprint at the time it was written. A note whose fingerprint no
    longer matches is marked stale.
- **Meanings** (`copybooks/meanings.py`): attaches field notes to a program's expanded fields
  by copybook name and line.

Notes are written in three ways: by hand in the Copybook Layout page, from TBX table documents
(`TBIxxxx` copybooks), and by copying notes from one copybook to its twin (`CORORx` to
`ORRORx`) by field name. Copied notes are tagged with where they came from.

---

## 6. Analyses

### 6.1 Paragraph summary (`summary/paragraph_summary.py`)

- `build_catalog(analysis, library)`: the field names with notes, and the 88-level condition
  names of the copybooks in use (with their parent fields and values). Meanings are cleaned of
  the appended "Values:" list.
- `plain_condition(text, catalog)`: turns `X = 'Y'` into "X (meaning) is Y", and an 88 name into
  "NAME is true when PARENT (meaning) is 'Y'".
- `paragraph_summary(analysis, name)`: a summary of sentences in program order: each IF with all
  of its true and else actions, every PERFORM made inside it, each PERFORM that is not inside an IF
  (with its THRU range), fields changed with their values, the after-completion note, and any
  copybook the line came from. Also returns decisions, changes, fields tested, calls out, and
  `simulation` when the paragraph receives an input record (section 6.8).
- `program_insights(analysis)`: for each field that drives a decision: its meaning, every test,
  every place it is set, and whether the program sets it. 88-level tests are grouped under the
  parent field.

### 6.2 Local variable tracer (`values/local_values.py`)

A symbolic and partly concrete walk over a paragraph and the paragraphs it PERFORMs.

- **Values:** each name holds a `Val`: a known number, a known text literal, or a symbolic
  expression written in full (for example `WS-FUNC-LEN + 1`). `origin` keeps the data name a value
  was read from, so tests on fields work with initial values. A name with no value stays as its
  own name, meaning "comes from outside this program".
- **Initial values:** from VALUE clauses (numbers, strings, SPACES, ZEROS, HIGH/LOW-VALUE, and
  X'hh' hex). A condition name's VALUE is not the item's value.
- **Condition names:** 88 values may be text or numbers (`VALUE 0`, `VALUE +100`). `SET name TO
  TRUE` sets the parent field to the first value.
- **Statements:** MOVE (including MOVE LENGTH OF), COMPUTE, ADD, SUBTRACT, SET, INITIALIZE, and
  the IF / EVALUATE / PERFORM / GO TO statement kinds.
- **Decisions:** when a condition can be decided from known values, only the branch taken is
  applied. Otherwise both branches run and a value that differs is shown as "(X or Y)". Each
  decision records its true and else actions. EVALUATE TRUE treats each WHEN as a condition.
- **Reference modification:** `NAME(start:len)` is a slice. Its symbolic form is kept
  (`RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)`), and when the positions are known the
  resolved form is shown too. With a real buffer, reads return the bytes present.
- **Tests on slices and fields:** each comparison of a slice (or a value holding one) or a record
  field to literals is recorded as a constraint with its allowed values, line and paragraph.
- **Group moves:** a slice moved into a group item is recorded with the group name.
- **Used variables:** `used_variables` lists every WS- item the selected paragraph names, with its
  type, bytes, starting value, final value and whether it is read or set there.
- **Depth and budget:** PERFORMs are followed up to 3 levels deep, not recursively. The tracer
  stops after 20,000 statements per request (`MAX_STEPS`) and reports that the result is partial.

### 6.3 WORKING-STORAGE (`values/working_storage.py`)

- `working_storage(analysis)`: every WORKING-STORAGE item with level, PICTURE, USAGE, type,
  bytes, OCCURS, offset, group, VALUE, and whether it is a local (WS- prefix). 88-level
  condition names are included with their parent and the values that make them true.
- `undeclared(analysis, names)`: names a paragraph uses that are not declared, ignoring COBOL
  words, paragraph names and string literals.
- `names_in_code(text)`: data-name-like words in a paragraph, without string literals.

### 6.4 Input buffer detection (`values/input_buffer.py`)

- `detect_input_buffers(analysis)`: finds the input a program starts from by its statements, not
  its name. Loads are `EXEC CICS RETRIEVE/RECEIVE ... INTO`, `READ INTO`, `ACCEPT`, and
  `MOVE DFHCOMMAREA TO`. Reads are reference-modified references in every paragraph. Each buffer
  lists where it is loaded, where it is read, its declared size, and the entry paragraph (the
  first paragraph that reads it).

### 6.5 Sample buffer builder, one round (`values/buffer_builder.py`)

- `build_sample(analysis, paragraph, buffer_name, assumptions)`: places the first allowed value
  of each test on the buffer at its position, and builds a full sample of each group that is
  moved from the buffer. Conflicts and unresolved positions are listed, not guessed.

### 6.6 Sample buffer search (`values/buffer_search.py`)

- `build_by_execution(analysis, entry, buffer_name, assumptions, rounds)`: starts from a blank
  buffer and repeatedly runs the tracer with the real bytes. Each test the current bytes do not
  meet gets its first allowed value written in. Stops when no test needs a change, or after 25
  rounds. Returns the buffer, the placement log, the decision path, conflicts, unsatisfied tests
  and notes. Comparisons keep tabs and other control characters (only spaces are trimmed).
- `analyze_with_buffer(analysis, paragraph, buffer_text)`: runs one paragraph (and what it
  PERFORMs) on a given buffer and reports the decisions taken and the slices read.

### 6.7 Copybook code and origins

Statements copied in from a copybook carry their origin (`file:line`). The summary names the
copybook ("in copybook ERXBATCH.txt:3"), the Python module marks them with `p.origin(...)`, the
business logic says "(from copybook …)", and the flow chart shows the copybook name in the box.

### 6.8 Input record simulation (`values/record_builder.py`)

- `build_record(analysis, group, entry, assumptions, values, sample)`: builds a group record that an
  EXEC CICS RETRIEVE (or a MOVE from DFHCOMMAREA) fills at run time. Each field sits at its declared
  offset. Values come from, in order: values you give, a demo sample (`DEMO_SAMPLE`: a 10-character
  date, `FR` for INP389-COMPANY, and a tracking number sized to its field), and otherwise blank or
  zero. Tests on the path then set a field to the value they need. Runs the tracer on the entry
  paragraph and returns the record, the packed bytes, patches, decisions, downstream results,
  logic chain and unknown inputs.
- **COMP-3 (packed decimal):** `pack_comp3` writes two digits per byte with the sign in the last
  nibble (C positive, D negative, F unsigned), with a leading zero nibble when the digit count is
  even. `+12345` in `S9(5) COMP-3` is `12 34 5C`.
- The paragraph summary includes this simulation when the paragraph receives an input record.

### 6.9 Python conversion (`convert/`)

- **Runtime** (`convert/cobol_runtime.py`, written out with each module): `Program` holds the
  working storage. MOVE and storage follow COBOL rules (text padded or truncated, numbers
  truncated to their digits with sign). Comparisons pad text with spaces. Reference modification is
  1-based. PERFORM and PERFORM THRU run in program order. External statements are recorded. Names
  the program never declares are recorded in `missing`. A PERFORM UNTIL loop stops after 10,000
  iterations.
- **Generator** (`convert/python_gen.py`): `generate(analysis, paragraphs)` writes one function per
  paragraph, plus the paragraphs they PERFORM, a `SPEC` table of storage, the `CONDITIONS` table of
  88 names, the `INITIAL` values, `UNDECLARED` names, and a `run` helper. It converts IF / ELSE,
  EVALUATE (subject and TRUE forms, WHEN lists, abbreviated `X = 'A' OR 'B'`), PERFORM (including
  THRU, inline UNTIL, and VARYING), GO TO to the paragraph's own exit (as a return), STOP RUN and
  GOBACK, MOVE (with reference modification and LENGTH OF), COMPUTE, ADD, SUBTRACT, SET, INITIALIZE,
  CONTINUE, and EXEC / CALL / DISPLAY (kept as text). Other statements are written as
  `p.unsupported(...)` and listed in the notes.
- Conditions are parsed by a small recursive-descent parser over the tokens: AND, OR, NOT,
  parentheses, COBOL comparison words, and bare names.
- Tests run the generated code (`tests/test_convert.py`) and check the results against COBOL rules.

### 6.10 Business logic extraction (`business/logic_extraction.py`)

This layer reads the generated Python module with Python's `ast` module. It never reads the COBOL
again, so what it explains is what the converted program does.

- `extract(module_source, paragraphs, meanings)` returns, per paragraph:
  - `rules`: a tree of decisions (condition, true and false rules, constant result), repeats
    (until or times), and actions (set, perform, sql, cics, call, stop, display, unsupported,
    end of paragraph). An origin marker from a copybook is attached to the rule that follows it;
  - `explanation`: the rules as sentences, with field meanings where notes exist;
  - `performs`: the paragraphs it PERFORMs;
  - `flow`: nodes and edges for a flow chart. Decisions are diamonds with yes and no branches,
    repeats loop back, and each action or call is a box with its own colour.
- Review findings: `constant_condition` (a condition compares fixed values, so one branch always
  runs), `undeclared` (a name is used but not declared), `decision_on_undeclared`, `not_converted`,
  `sql_missing_comma`, and `sql_host_variable` (undeclared host variable, with a close name
  suggested).

---

## 7. Program log (`programlog/store.py`, SQLite `output/program_log.db`)

| Table | Holds | Key |
|---|---|---|
| `program_runs` | each analysis: program name, source name, time, summary JSON | source fingerprint |
| `program_details` | user notes about a program: category, key, value | fingerprint + category + key |
| `paragraph_records` | one row per paragraph: summary, after-completion, counts, changes and calls as JSON | fingerprint + paragraph; index on (program_name, paragraph) |
| `paragraph_decisions` | one row per IF / EVALUATE decision of a paragraph | fingerprint + paragraph + sequence; index on (program_name, paragraph) |
| `paragraph_changes` | one row per field changed by a paragraph | fingerprint + paragraph + sequence; index on (program_name, paragraph) |

- The fingerprint is the SHA-256 of the source text. Re-analysing the same source replaces its
  paragraph records.
- `program_name` is the PROGRAM-ID, not the file name. Two versions with the same PROGRAM-ID share
  the name; the record lookup returns the most recent.
- Every run is also appended to `output/program_log.jsonl`.

---

## 8. API

Base path `/api`. All analysis endpoints take an `analysis_id` returned by `POST /analyze`.
Analyses are kept in memory (the 20 most recent), so they are lost when the server restarts.

### 8.1 Analysis

| Method | Path | Purpose |
|---|---|---|
| POST | `/analyze` | analyse `{name, source, copybooks}`; stores the analysis, the program log entry and the paragraph records |
| GET | `/sample` | the bundled sample program |
| GET | `/analyses/{id}` | the analysis payload (divisions, sections, paragraphs, graph, COMMAREA, copybooks, trace, log) |
| GET | `/analyses/{id}/source` | numbered source lines |
| GET | `/analyses/{id}/paragraphs/{name}` | one paragraph: callers, outgoing calls, occurrences, source |
| GET | `/analyses/{id}/paragraphs/{name}/summary` | plain-language summary; includes `simulation` for an input-receiving paragraph |
| GET | `/analyses/{id}/paragraphs/{name}/locals` | local variable values, used variables, chain, decisions, slices, `exhausted` flag |
| GET | `/analyses/{id}/paragraphs/{name}/sample-buffer?assume=` | one-round buffer for a paragraph |
| GET | `/analyses/{id}/paragraphs/{name}/python` | the paragraph and the paragraphs it PERFORMs as a Python module, runtime, notes |
| GET | `/analyses/{id}/paragraphs/{name}/business-logic` | rules, explanations, flow charts and findings read from the Python module |
| GET | `/analyses/{id}/buffer-search?entry=&paragraph=&assume=` | buffer built by running the tests, optionally with a paragraph run on it |
| GET | `/analyses/{id}/input-buffer?buffer=&assume=` | detected input buffers, where they are loaded and read, and a built sample |
| GET | `/analyses/{id}/simulate?entry=&group=&assume=&values=&sample=` | input record built field by field and the logic run on it |
| GET | `/analyses/{id}/working-storage?local_only=` | WORKING-STORAGE items |
| GET | `/analyses/{id}/insights` | decision fields of the program and where they are set |
| GET | `/analyses/{id}/search?q=` | paragraph name search |
| GET | `/analyses/{id}/export/{fmt}` | xlsx, json, paragraphs.csv, callsites.csv |

`assume` takes comma-separated `NAME=value` pairs for positions or codes the program does not set,
for example `WS-NEXT-POS=1` or `SQLCODE-STATUS=0`. `values` takes `FIELD=value` pairs for the
input record, for example `INP389-COMPANY=FR`.

### 8.2 Copybooks (`/api/copybooks`)

| Method | Path | Purpose |
|---|---|---|
| GET | `` | list copybooks (search with `q`, limit) |
| GET | `/categories` | the allowed field categories |
| GET | `/export` | all descriptions and field notes as JSON |
| GET | `/{name}` | the layout with saved notes and description; `kind` (data, procedure, empty) and `code` for procedure copybooks |
| PUT | `/{name}/description` | save the copybook description |
| PUT | `/{name}/fields/{path}` | save a field note |
| DELETE | `/{name}/fields/{path}` | remove a field note |

### 8.3 Program log (`/api/program-log`)

| Method | Path | Purpose |
|---|---|---|
| GET | `` | programs logged, most recent first |
| GET | `/{fingerprint}` | run history and details of one program |
| PUT | `/{fingerprint}/details` | add or update a detail |
| DELETE | `/{fingerprint}/details?key=&category=` | remove a detail |
| GET | `/programs/{program_name}/paragraphs` | paragraph records of a program |
| GET | `/programs/{program_name}/paragraphs/{paragraph}` | one paragraph record with decisions and fields changed |

---

## 9. Frontend (`frontend/`)

- **Stack:** React 18, React Router, Vite (dev proxy to the API through `API_PROXY`, default
  `http://127.0.0.1:8000`), `@dagrejs/dagre` for the flow graphs.
- **State:** `state.jsx` holds the current analysis and the error message. The last analysis id
  is kept in `sessionStorage` (if the browser allows it).
- **Pages:**
  - *Program Upload:* choose or load a sample, analyse, see divisions and sections, source.
  - *Program Overview:* statistics, divisions, sections, export.
  - *Paragraph Explorer:* search and filter paragraphs; detail with callers, calls, occurrences
    and source, then the Summary panel (`ParagraphSummary`, with the simulated input record when
    the paragraph receives one), the Convert to Python panel (`ConvertToPython`) and, under it, the
    business logic (`BusinessLogic`) with a flow diagram per paragraph (`FlowDiagram`).
  - *Paragraph Flow* and *Program Flow Map:* the call graph and execution trace (`FlowGraph`).
  - *Copybook Layout:* browse copybooks, edit descriptions and field notes inline. A procedure
    copybook shows its code lines instead of a field table.
  - *Program Log:* programs logged, run history, details with add / edit / remove.
  - *Program Values:* the detected input buffer, where it is set and read, a sample built by
    running the tests (with an assumptions field), the local variables a paragraph uses with
    their values, the logic chain, the decisions, and the parts of the input read.
- **Styling:** `styles.css` (base), `summary.css` (summary, simulation, conversion, business logic,
  flow diagram), `programlog.css`, `values.css`; design follows the "Order Re-Build" reference
  screen.
- **Flow diagram controls:** − and + buttons, 100%, Fit width, and Ctrl + mouse wheel for zoom. The
  frame scrolls up, down and sideways.

Not yet in the UI: the working-storage list as its own view, and the paragraph records and
decisions from the program log.

---

## 10. Tests

`tests/` (pytest), 108 tests. Test files:

- `test_analysis.py`: parser, paragraphs, flow, statements.
- `test_commarea.py`: COMMAREA layout and checks.
- `test_copybooks.py`, `test_copybook_reader.py`, `test_copybook_layout.py`: expansion, reader,
  layout, knowledge store, API.
- `test_programlog.py`: runs, details, paragraph records, the analyze endpoint.
- `test_paragraph_summary.py`: summary, insights, 88-level explanations.
- `test_paragraph_headers.py`: Area A paragraph headers and comment lines.
- `test_local_values.py`: value tracking, slices, decisions, else branches, used variables, the
  step budget.
- `test_buffer_builder.py`: one-round sample buffer and group samples.
- `test_buffer_search.py`: buffer built by running the tests, and a paragraph run on it.
- `test_record_builder.py`: input records, packed decimal bytes, given values.
- `test_convert.py`: generated Python run against COBOL rules (EVALUATE, tabs, packed storage).
- `test_business_logic.py`: numeric 88 values, PERFORM VARYING, explanations, SQL text.
- `test_procedure_copybook.py`: a procedure copybook is recognised and its origin is shown.

Run from the project folder: `py -m pytest -q`.

---

## 11. Running it

- **Backend:** from the project folder, `uvicorn api.server:app --port 8000`.
- **Frontend:** `frontend/`, `npm install`, then `npx vite` (or `npm run dev`). Point it at the
  backend with `API_PROXY` if the port differs.
- **Environment variables:**
  - `COBOL_COPYBOOKS`: folders to search for copybooks (separated by the OS path separator).
  - `COBOL_KNOWLEDGE_DB`: path of the copybook knowledge database.
  - `COBOL_PROGRAM_LOG_DB` and `COBOL_PROGRAM_LOG_FILE`: paths of the program log database and
    JSON-lines file.
  - `API_PROXY`: backend address used by the Vite dev server.
- **Restarts:** the API keeps analyses in memory, and a server started before a change keeps
  running the old code. After changing the backend, restart it and analyse again.

---

## 12. Known limits

- **Loops are followed once** in the tracer and the buffer search. A character-by-character
  delimiter scan only yields its first step. The Python module, however, runs loops for real (up to
  10,000 iterations).
- **Conditions with AND / OR** are not split into separate constraints in the tracer; they are
  shown as text and are not decided.
- **Only the first allowed value** of a test is placed in a buffer; the others are listed.
- **Only the first occurrence** of an OCCURS table is built.
- **Partial MOVE** into a reference-modified target is recorded but does not change the variable
  in the tracer.
- **Undeclared names** (for example `SQLCODE`, `SETATRK-*` in INP389 when their copybook is not
  included) are reported; their values are unknown, and the runtime records them when read.
- **Conversion gaps:** GO TO to a paragraph other than the exit that follows is not converted;
  EVALUATE ranges (THRU) are not converted; NEXT SENTENCE is treated as CONTINUE.
- **PERFORMs** are followed up to three levels deep in the tracer and not recursively. A PERFORM of
  a paragraph that is not in the program is noted, and its effect is unknown.
- **EXEC SQL INCLUDE** is not expanded.
- **External CALL and SQL effects** are not modelled; SQL return codes must be supplied (for example
  `SQLCODE-STATUS=0`) to follow a success path.
- **Input record:** only the first occurrence of each OCCURS item is built, and numeric fields are
  zero or digit-filled without the sign except for packed fields.
- **Analyses are in memory** in the API; they are lost on restart.
- **The Streamlit app** (`app.py`) and `src/storage.py` are older and use an earlier format.
- **Browser checks:** the most recent screens (flow diagram zoom, copybook procedure view, simulation
  panel) have been built but not yet checked in a browser.

---

## 13. Roadmap

1. **Loop model in the tracer:** bounded iteration for `PERFORM UNTIL` and `PERFORM VARYING`, so
   the buffer builder can produce several records and delimiters.
2. **UI for the remaining analyses:** a working-storage list, and the paragraph records and
   decisions from the program log.
3. **Assumptions in the Summary panel:** a field to supply values such as `SQLCODE-STATUS=0` and
   see the branches that depend on them.
4. **Persistence of analyses:** store analyses (or rebuild them from the stored source) so they
   survive a server restart.
5. **AND / OR conditions:** split into constraints in the tracer and decide them with known values.
6. **External calls and SQL:** model the data a CALL reads and writes from its interface definition,
   and the SQLCA fields a statement sets.
7. **EXEC SQL INCLUDE** expansion for SQLCA and similar members.
8. **Copybook note reuse:** show saved notes in the flow and summary views, and report stale notes.
9. **Converter coverage:** GO TO to other paragraphs, EVALUATE ranges, and the remaining verbs.
10. **Retire the Streamlit app** once the React UI covers its screens.

---

## 14. Change log

| Date | Change |
|---|---|
| 2026-11-06 | COMMAREA analysis, copybook expansion (`.cpy` and `.txt`), copybook layout and field notes, program log. |
| 2026-11-06 | Paragraph summary with plain-language conditions and 88-level explanations; program insights. |
| 2026-11-06 | Local variable tracer, WORKING-STORAGE listing, sample buffer builder and buffer search. |
| 2026-11-07 | Input buffer detection (EXEC CICS RETRIEVE, MOVE DFHCOMMAREA); Program Values page. |
| 2026-11-08 | Input record simulation (INP389-TRANSACTION-AREA), COMP-3 packed decimal, demo sample values. |
| 2026-11-08 | Paragraph headers from Area A; comment lines after column 7; top-level PERFORMs and PERFORMs inside IFs in summaries. |
| 2026-11-09 | Used-variable list per paragraph; work budget in the tracer; Summary panel shows PERFORMs in program order. |
| 2026-11-09 | Python conversion (runtime and generator); Convert to Python button; PERFORM VARYING; numeric 88 values; SQL text kept whole. |
| 2026-11-09 | Business Logic Extraction Engine reading the Python module: rules, explanations, review findings. |
| 2026-11-10 | Flow diagrams per paragraph with zoom and scrolling. |
| 2026-11-10 | Procedure copybooks recognised and shown as code; copybook origin shown in summaries, Python, business logic and flow charts. |
| 2026-11-10 | This document brought up to date. |
