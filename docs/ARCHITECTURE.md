# COBOL Flow Analyzer: Architecture

This document describes how the COBOL Flow Analyzer is built: the layers, the modules in each,
the data it stores, the API it exposes, how a program moves through the system, and what is
still missing. It reflects the code as of the latest change set.

---

## 1. Purpose

The tool reads a COBOL program (fixed or free format) with its copybooks and produces:

- the paragraph structure, PERFORM / GO TO call graph, and execution trace;
- which paragraphs are never called or unreachable;
- the CICS COMMAREA layout and standards checks;
- the layout of every copybook field, with the meaning written by people;
- plain-language summaries of paragraphs and of the program's decision logic;
- the values of local (WS-) variables along a paragraph's path, and a sample input buffer
  (for example `RCV-DATA-BUFFER-AREA`) that drives the program down a chosen path;
- a log of every analysis, with each paragraph's summary, decisions and changes, indexed by
  program name and paragraph.

---

## 2. Layers

```
 +-----------------------------------------------------------------------+
 | React UI (frontend/)           Streamlit UI (app.py, earlier version)  |
 +----------------------------------+------------------------------------+
                                    | JSON over HTTP  (/api/...)
 +----------------------------------v------------------------------------+
 | FastAPI backend (api/)                                                |
 |   server.py            analysis, paragraph, values, summary endpoints |
 |   copybook_routes.py   copybook library, layouts, field notes          |
 |   programlog_routes.py program log, paragraph records                 |
 +----------------------------------+------------------------------------+
                                    |
 +----------------------------------v------------------------------------+
 | Analysis core (src/)                                                  |
 |   pipeline.py   one call: source text -> Analysis                      |
 |   parser/       tokens -> divisions, sections, paragraphs, statements  |
 |   copybooks/    COPY expansion, library, layouts, field notes          |
 |   analyzer/     references, call graph, reachability, trace, detail    |
 |   commarea/     CICS COMMAREA layout and checks                        |
 |   summary/      paragraph summaries and program insights               |
 |   values/      local variables, WORKING-STORAGE, buffer building       |
 |   programlog/   SQLite log of runs and paragraph records                |
 |   export/       Excel, CSV, JSON export                                |
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

---

## 3. Repository layout

```
COBOL_FLOW_ANALYZER/
  api/                     FastAPI routes
    server.py              main app: analysis, paragraph, values, summary endpoints
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
    values/                local variable tracer, WORKING-STORAGE, buffer builder, buffer search
    programlog/            program log store
    export/                report generator (xlsx, csv, json)
    models/                Program, Paragraph, Statement, CallSite, ExecEvent, ...
    visualization/         DOT flow diagram
  frontend/                Vite + React UI
    src/pages/             Upload, Overview, Explorer, Flow, Flow Map, Copybook, Program Log
    src/components/        ui, FlowGraph, ParagraphSummary, Sidebar, Header, Icon
  sample_programs/         sample COBOL programs and the copybook sample folder
  tests/                   pytest suite (85+ tests)
  output/                  runtime databases and exports (created on demand)
  docs/ARCHITECTURE.md     this file
```

---

## 4. Analysis pipeline

Entry points: `src.pipeline.analyze_source(text, source_name, library, knowledge)` and
`analyze_file(path, copybook_dirs)`.

Steps in `analyze_source`:

1. **Normalise** (`parser/source_format.py`): fixed-format layout. Columns 1–6 (sequence) and
   73 onward (identification) are ignored. A `*` or `/` in column 7 makes the line a comment. A
   `-` in column 7 continues the previous line. Lines without a valid layout are kept as free
   format.
2. **Expand copybooks** (`copybooks/expander.py`): every `COPY name [REPLACING ...]` is replaced
   by the copybook text, recursively, with cycle detection (depth limit 10). Each expanded line
   records its origin (`file:line`). `EXEC SQL INCLUDE` is not expanded yet.
3. **Tokenise** (`parser/lexer.py`): words (including `:PFX:` placeholders), numbers, strings,
   periods, parentheses and operators.
4. **Parse structure** (`parser/division_parser.py`): divisions, sections, PROGRAM-ID, the raw
   DATA DIVISION entries, and the PROCEDURE DIVISION blocks.
5. **Build paragraphs** (`parser/paragraph_parser.py`) and parse each paragraph's statements into
   a tree (`parser/statement_parser.py`): IF / ELSE, EVALUATE / WHEN, PERFORM (out-of-line,
   inline, THRU, TIMES, UNTIL), GO TO, EXEC CICS/SQL, and simple statements.
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

### Data model (`models/`)

- `Program`: name, source name, line count, divisions, sections, paragraphs, data item count,
  procedure start line, source lines by number, line origins.
- `Paragraph`: name, index, section, start and end lines, statements, source text.
- `Statement`: kind (SIMPLE, IF, EVALUATE, PERFORM, GOTO, TERMINATE, EXIT_PARA, NOOP), verb,
  text, line, condition, target, targets, branches (labelled bodies).
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
  OCCURS, REDEFINES, and 88-level condition names, plus a fingerprint of the text.
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

## 6. Analyses that use the copybook notes

### 6.1 Paragraph summary (`summary/paragraph_summary.py`)

- `build_catalog(analysis, library)`: the field names with notes, and the 88-level condition
  names of the copybooks in use (with their parent fields and values). Meanings are cleaned of
  the appended "Values:" list.
- `plain_condition(text, catalog)`: turns `X = 'Y'` into "X (meaning) is Y", and an 88 name into
  "NAME is true when PARENT (meaning) is 'Y'".
- `paragraph_summary(analysis, name)`: decisions (with the true and else actions), fields
  changed with their values, fields tested, calls out, and the after-completion note. Each
  decision and change becomes a sentence.
- `program_insights(analysis)`: for each field that drives a decision: its meaning, every test,
  every place it is set, and whether the program sets it. 88-level tests are grouped under the
  parent field.

### 6.2 Local variable tracer (`values/local_values.py`)

A symbolic and partly concrete walk over a paragraph and the paragraphs it PERFORMs.

- **Values:** each name holds a `Val`: a known number, a known text literal, or a symbolic
  expression written in full (for example `WS-FUNC-LEN + 1`). A name with no value stays as its
  own name, meaning "comes from outside this program".
- **Initial values:** from VALUE clauses (numbers, strings, SPACES, ZEROS, HIGH/LOW-VALUE, and
  X'hh' hex). A condition name's VALUE is not the item's value.
- **Statements:** MOVE (including MOVE LENGTH OF), COMPUTE, ADD, SUBTRACT, SET ... TO TRUE, and
  the IF / EVALUATE / PERFORM / GO TO statement kinds.
- **Decisions:** when a condition can be decided from known values, only the branch taken is
  applied. Otherwise both branches run and a value that differs is shown as "(X or Y)". Each
  decision records its true and else actions. EVALUATE TRUE treats each WHEN as a condition.
- **Reference modification:** `NAME(start:len)` is a slice. Its symbolic form is kept
  (`RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)`), and when the positions are known the
  resolved form is shown too.
- **Tests on slices:** each comparison of a slice (or a local holding a slice) to literals is
  recorded as a constraint with its allowed values, line, and the paragraph it came from.
- **Group moves:** a slice moved into a group item is recorded with the group name.
- **Depth:** PERFORMs are followed up to 3 levels deep, not recursively.
- **Buffer bytes:** `trace_paragraph(..., buffer=(name, contents))` reads real bytes for
  slices whose positions are known.

### 6.3 WORKING-STORAGE (`values/working_storage.py`)

- `working_storage(analysis)`: every WORKING-STORAGE item with level, PICTURE, USAGE, type,
  bytes, OCCURS, offset, group, VALUE, and whether it is a local (WS- prefix). 88-level
  condition names are included with their parent and the values that make them true.
- `undeclared(analysis, names)`: names a paragraph uses that are not declared, ignoring COBOL
  words, paragraph names and string literals.
- `names_in_code(text)`: data-name-like words in a paragraph, without string literals.

### 6.4 Sample buffer builder, one round (`values/buffer_builder.py`)

- `build_sample(analysis, paragraph, buffer_name, assumptions)`: places the first allowed value
  of each test on the buffer at its position, and builds a full sample of each group that is
  moved from the buffer. Each group field takes the value a test requires, else its first 88
  VALUE, else blank or zeros. Conflicts and unresolved positions are listed, not guessed.

### 6.5 Sample buffer search (`values/buffer_search.py`)

- `build_by_execution(analysis, entry, buffer_name, assumptions, rounds)`: starts from a blank
  buffer and repeatedly runs the tracer with the real bytes. Each test not met by the current
  bytes gets its first allowed value written in. The loop stops when no test needs a change, or
  after 25 rounds. Returns the buffer, the placement log, the decision path, conflicts,
  unsatisfied tests and notes.
- `analyze_with_buffer(analysis, paragraph, buffer_text)`: runs one paragraph (and what it
  PERFORMs) on a given buffer and reports the decisions taken and the slices read.

### 6.6 Other analysis outputs

- `analyze_values` output: locals (type, bytes, initial, final, history), the change chain,
  decisions, slices, calls, condition names, and notes.

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
- `program_name` is the PROGRAM-ID, not the file name.
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
| GET | `/analyses/{id}/paragraphs/{name}/summary` | plain-language summary |
| GET | `/analyses/{id}/paragraphs/{name}/locals` | local variable values, chain, decisions, slices |
| GET | `/analyses/{id}/paragraphs/{name}/sample-buffer?assume=` | one-round buffer for a paragraph |
| GET | `/analyses/{id}/buffer-search?entry=&paragraph=&assume=` | buffer built by running the tests, optionally with a paragraph run on it |
| GET | `/analyses/{id}/working-storage?local_only=` | WORKING-STORAGE items |
| GET | `/analyses/{id}/insights` | decision fields of the program and where they are set |
| GET | `/analyses/{id}/search?q=` | paragraph name search |
| GET | `/analyses/{id}/export/{fmt}` | xlsx, json, paragraphs.csv, callsites.csv |

`assume` takes comma-separated `NAME=value` pairs for positions the program does not set, for
example `WS-NEXT-POS=1`.

### 8.2 Copybooks (`/api/copybooks`)

| Method | Path | Purpose |
|---|---|---|
| GET | `` | list copybooks (search with `q`, limit) |
| GET | `/categories` | the allowed field categories |
| GET | `/export` | all descriptions and field notes as JSON |
| GET | `/{name}` | the layout, with saved notes and description |
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
  `http://127.0.0.1:8000`), `@dagrejs/dagre` for the flow graph.
- **State:** `state.jsx` holds the current analysis and the error message. The last analysis id
  is kept in `sessionStorage` (if the browser allows it).
- **Pages:**
  - *Program Upload:* choose or load a sample, analyse, see divisions and sections, source.
  - *Program Overview:* statistics, divisions, sections, export.
  - *Paragraph Explorer:* search and filter paragraphs; detail with callers, calls, occurrences,
    source, and the Summary panel (`components/ParagraphSummary.jsx`).
  - *Paragraph Flow* and *Program Flow Map:* the call graph and execution trace.
  - *Copybook Layout:* browse copybooks, edit descriptions and field notes inline.
  - *Program Log:* programs logged, run history, details with add / edit / remove.
- **Styling:** `styles.css` (base), `summary.css`, `programlog.css`; design follows the
  "Order Re-Build" reference screen.

Not yet in the UI: working-storage view, local values, buffer search, buffer builder, paragraph
records and decisions from the program log.

---

## 10. Tests

`tests/` (pytest). Test files:

- `test_analysis.py`: parser, paragraphs, flow, statements.
- `test_commarea.py`: COMMAREA layout and checks.
- `test_copybooks.py`, `test_copybook_reader.py`, `test_copybook_layout.py`: expansion, reader,
  layout, knowledge store, API.
- `test_programlog.py`: runs, details, paragraph records, the analyze endpoint.
- `test_paragraph_summary.py`: summary, insights, 88-level explanations.
- `test_local_values.py`: value tracking, slices, decisions, else branches.
- `test_buffer_builder.py`: one-round sample buffer and group samples.
- `test_buffer_search.py`: buffer built by running the tests, and a paragraph run on it.

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

- **Loops are followed once.** `PERFORM UNTIL` and `PERFORM VARYING` bodies run one time in the
  tracer, so a character-by-character delimiter scan only yields its first step. This is the
  main gap for the header and line parsing.
- **Conditions with AND / OR** are shown as text and are not decided. Their tests are not split
  into separate constraints.
- **Only the first allowed value** of a test is placed in a buffer; the others are listed.
- **Only the first occurrence** of an OCCURS table is built.
- **Numeric fields** in samples are zero-filled without the sign.
- **Partial MOVE** into a reference-modified target is recorded but does not change the variable.
- **Undeclared names** (for example `TB-IL2-*` in ORP694) are reported; their values are unknown.
- **PERFORMs** are followed up to three levels deep and not recursively. A PERFORM of a paragraph
  that is not in the program is noted, and its effect is unknown.
- **EXEC SQL INCLUDE** is not expanded.
- **External CALL** effects are not modelled.
- **Analyses are in memory** in the API; they are lost on restart.
- **The Streamlit app** (`app.py`) and `src/storage.py` are older and use an earlier format.

---

## 13. Roadmap

1. **Loop model:** bounded iteration for `PERFORM UNTIL` and `PERFORM VARYING`, so the buffer
   builder can produce several records and delimiters.
2. **UI for the new analyses:** working-storage view, local values, buffer search with the
   built buffer and its path, and the paragraph records in the Program Log page.
3. **Persistence of analyses:** store analyses (or rebuild them from the stored source) so they
   survive a server restart.
4. **AND / OR conditions:** split into constraints and decide them with known values.
5. **External calls:** model the data a CALL reads and writes from its interface definition.
6. **EXEC SQL INCLUDE** expansion for SQLCA and similar members.
7. **Copybook note reuse:** show saved notes in the flow and summary views, and report stale notes.
8. **Retire the Streamlit app** once the React UI covers its screens.
