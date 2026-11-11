# COBOL Flow Analyzer: architecture

This is the architecture of the whole tool. It reads a COBOL program and its copybooks,
explains the program as it is, and can propose one field assignment on top of that
explanation. It does not compile or execute the program, and a proposal does not modify
the source file.

A closer look at the proposal feature is in [CHANGE_PROPOSAL.md](CHANGE_PROPOSAL.md).

---

## 1. What the tool is for

Someone uploads a program, or names a sample, and the tool answers:

- what the divisions, sections, and paragraphs are;
- which paragraphs call which, under which conditions, and which are never reached;
- how a CICS COMMAREA is laid out and which standards it meets;
- what each copybook field is, and what a person has written that it means;
- what a paragraph does, in plain language, from its decisions and the fields it changes;
- what local values and input-buffer bytes would be along a path;
- what was analysed before, kept in a log keyed by the program;
- where a requested assignment such as "set this column to Y" would go, and the COBOL
  lines that would do it.

Two ways in:

- the React UI talks to the FastAPI service;
- `python -m src.changes` proposes an edit from the command line, with no UI.

`scripts/agent_query.py` is a third, narrower door: a JSON request on stdin for an
outside agent that asks for an overview or one paragraph. It does not propose edits.

`app.py` is an older Streamlit screen over an earlier storage format. The React UI is
the one to use.

---

## 2. How a program moves through the tool

```
 COBOL source + copybook folders
        |
        v
 parser  -->  COPY expansion  -->  paragraphs and statement trees
        |
        +--> call graph, reachability, execution trace
        +--> COMMAREA layout, CICS commands, standards
        +--> copybook layouts and saved field notes
        +--> paragraph summaries and program insights
        +--> local values, working-storage, sample input buffer
        |
        v
 Analysis  (held in memory by the API, also written to the program log)
        |
        +--> React pages: Upload, Overview, Explorer, Flow, Map, Copybooks, Log, Values
        +--> exports: Excel, CSV, JSON
        |
        +--> src/changes: one requirement + this Analysis --> a proposed edit
             (the source file stays as it was)
```

Every later feature calls the analysis core. The API and the UI do not re-parse COBOL.

---

## 3. Layers

```
 React UI (frontend/)                         Streamlit (app.py, earlier)
        |  JSON /api
 FastAPI (api/)
   server.py             analyse, paragraph, summary, values, export
   copybook_routes.py    library, layouts, field notes
   programlog_routes.py  runs and paragraph records
        |
 Analysis core (src/)
   pipeline.py      source text -> Analysis
   parser/          tokens, divisions, paragraphs, statement trees
   copybooks/       COPY expansion, library, layout, notes
   analyzer/        references, call graph, trace, paragraph detail
   commarea/        CICS COMMAREA
   summary/         plain-language paragraph and program summaries
   values/          locals, working-storage, buffers
   changes/         one requirement -> a proposed edit
   programlog/      SQLite log
   export/          Excel, CSV, JSON
   visualization/   Graphviz DOT for the flow map
        |
 Storage
   output/copybook_knowledge.db    what a person said a field means
   output/program_log.db           runs, details, paragraph records
   output/program_log.jsonl        one JSON line per analysis
   copybook folders                .cpy and .txt members
```

---

## 4. Repository

```
cobol-flow-analyzer/
  api/                  HTTP routes
  app.py                older Streamlit UI
  frontend/             Vite + React
    src/pages/          Upload, Overview, Explorer, Flow, Flow Map,
                        Copybook Layout, Program Log, Program Values
    src/components/     Sidebar, Header, FlowGraph, ParagraphSummary, ui
  src/                  analysis core (no web code)
  scripts/agent_query.py
  sample_programs/      sample programs and copybooks/
  tests/                pytest
  output/               databases and exports, created as the tool runs
  docs/ARCHITECTURE.md  this file
  docs/CHANGE_PROPOSAL.md
```

---

## 5. Analysis pipeline

`analyze_source(text, source_name, library, knowledge)` and
`analyze_file(path, copybook_dirs)` in `src/pipeline.py` build one `Analysis`.

1. **Normalise** (`parser/source_format.py`). In fixed format, columns 1–6 and 73
   onward are ignored. A `*` or `/` in column 7 is a comment. A `-` in column 7
   continues the previous line. A line that is not fixed format is kept as free format.
2. **Expand COPY** (`copybooks/expander.py`). `COPY name`, `COPY name OF library`, and
   `COPY name REPLACING` are replaced by the member text, including nested copies.
   A cycle or nesting past 10 levels is reported and skipped. A missing member is
   reported and the rest of the program is still analysed. Each expanded line keeps
   its origin, such as `INP389.cbl.txt:61` or `INR389.txt:9`. `EXEC SQL INCLUDE` is
   not expanded here.
3. **Tokenise** (`parser/lexer.py`). Words, numbers, strings, periods, parentheses,
   operators. Commas are not tokens, so a later reader that needs a SET-clause comma
   uses the source line, not the flattened statement text.
4. **Structure** (`parser/division_parser.py`). PROGRAM-ID, divisions, sections, DATA
   DIVISION entries, PROCEDURE DIVISION blocks.
5. **Paragraphs and statements** (`parser/paragraph_parser.py`,
   `parser/statement_parser.py`). A period closes open IF, EVALUATE, and PERFORM
   scopes. The tree covers IF / ELSE, EVALUATE / WHEN, PERFORM (inline, out-of-line,
   THRU, TIMES, UNTIL), GO TO, EXEC CICS and EXEC SQL, and ordinary statements.
6. **References** (`analyzer/reference_analyzer.py`). PERFORM and GO TO sites, the
   conditions around them, and external CALL targets.
7. **Flow** (`analyzer/flow_analyzer.py`). A networkx graph. Reachability starts at
   the first paragraph and follows PERFORM and GO TO. Fall-through does not leak out
   of a performed range. The trace walks each paragraph once and labels every branch.
8. **COMMAREA** (`commarea/`). Layout of DFHCOMMAREA, CICS commands, which paragraphs
   read and write each field, and the standards checks.
9. **Field notes** (`copybooks/meanings.py`). Saved notes are attached to expanded
   fields by copybook name and declared path.
10. **Data layout** (`commarea/data_layout.py`). `data_roots` is every DATA DIVISION
    item with offset and length. `data_entries` keeps the raw entries, including
    VALUE and 88-level names.

`Analysis` holds `program`, `analyzer`, `call_sites`, `external_calls`, `graph`,
`statuses`, `trace`, `commarea`, `copybooks`, `field_meanings`, `data_roots`, and
`data_entries`. The API also keeps `analysis.library` so a later summary can read
88-level names again.

### Data model (`src/models/`)

- **Program.** Name, source name, line count, divisions, sections, paragraphs, source
  lines, and `line_origin`.
- **Paragraph.** Name, index, section, line range, statement tree, source text.
- **Statement.** Kind is SIMPLE, IF, EVALUATE, PERFORM, GOTO, TERMINATE, EXIT_PARA,
  or NOOP. It carries the verb, text, line, condition, target, and branches.
- **CallSite, ExternalCall, ExecEvent.** The flow records.

---

## 6. Copybooks

`CopybookLibrary` resolves a name from, in order: text supplied in memory (an upload
or a test), the program's folder, a `copybooks` folder beside it, extra folders, and
`COBOL_COPYBOOKS`. `.cpy` is preferred to `.txt`. The reader accepts UTF-8, UTF-16
with a BOM, and Windows-1252.

`layout_of_copybook` lays a member out on its own, before any program copies it:
level, dotted path, PICTURE, USAGE, offset, length, OCCURS, REDEFINES, and 88-level
names. A fingerprint of the text is stored with any note, so a note can be marked
stale after the member changes.

Notes live in `output/copybook_knowledge.db` (`COBOL_KNOWLEDGE_DB` overrides the path):

- `copybook_notes`: one description per copybook;
- `field_notes`: meaning, category, and tags, keyed by copybook and the declared
  path, not the name after REPLACING.

Notes are written from the Copybook Layout page. They are also filled from TBX table
documents and by copying a note from a copybook onto its twin (`CORORx` to `ORRORx`)
when the field names match.

---

## 7. Flow, COMMAREA, and summaries

**Paragraph detail** (`analyzer/paragraph_analyzer.py`) is what Paragraph Explorer
shows: where the paragraph is defined, who calls it and under what condition, what it
calls, the statement outline, and the source.

**COMMAREA** (`commarea/analyzer.py`, `cics_commands.py`, `usage.py`, `report.py`)
names the area in the LINKAGE SECTION, computes its length, lists EXEC CICS commands,
and checks the usual rules: the area is named DFHCOMMAREA, the length is within
32,767 bytes, LENGTH is passed where a command needs it, EIBCALEN is tested, and a
pseudo-conversational RETURN carries a TRANSID. A length that depends on EIBCALEN is
reported as 0 bytes because the declared size is not fixed.

**Paragraph summary** (`summary/paragraph_summary.py`) turns decisions and field
changes into sentences. An 88-level name is explained through its parent when that
parent has a saved note (`DEMO-ON` is true when `DEMO-FLAG-SW` is `'Y'`).
`program_insights` groups every test of a field with the paragraphs that set it.
If no field notes exist, the summary stays mechanical and can omit an ELSE branch.
The statement outline is the fuller record. The change proposer uses the outline
and the source lines, not these sentences.

---

## 8. Values and buffers

**Local values** (`values/local_values.py`) walk a paragraph and the paragraphs it
PERFORMs, up to three levels and not recursively. A name holds a known number, a
known literal, or a symbolic expression. VALUE clauses supply the initial value.
When a condition can be decided, only that branch is applied. Otherwise both branches
run and a conflict is shown as "(X or Y)". Reference modification keeps the symbolic
slice and, when the positions are known, the resolved one.

**Working-storage** (`values/working_storage.py`) lists every WORKING-STORAGE item
with its picture, usage, size, offset, VALUE, and 88-level names, and names used in
a paragraph that were never declared.

**Input buffer** (`values/input_buffer.py`) finds the area the program fills from
EXEC CICS RETRIEVE or RECEIVE, READ INTO, ACCEPT, or a MOVE of DFHCOMMAREA, and
counts reference-modified reads of that area. The busiest one is the primary input.

**Sample buffer** (`values/buffer_builder.py`, `values/buffer_search.py`). One round
places the first allowed value of each test. The search starts from a blank buffer
and repeats until the tests are met or 25 rounds pass. Positions the program never
sets can be supplied as `NAME=value` assumptions. Only the first allowed value and
the first OCCURS element are written.

---

## 9. Program log

`programlog/store.py` writes `output/program_log.db`. `COBOL_PROGRAM_LOG_DB` and
`COBOL_PROGRAM_LOG_FILE` override the database and the JSON-lines file.

| Table | What it stores | Key |
| --- | --- | --- |
| `program_runs` | one row per analysis: name, time, summary JSON | SHA-256 of the source |
| `program_details` | notes a person attached to a program | fingerprint, category, key |
| `paragraph_records` | summary, counts, changes, calls | fingerprint + paragraph |
| `paragraph_decisions` | one row per IF or EVALUATE | fingerprint + paragraph + sequence |
| `paragraph_changes` | one row per field a paragraph changes | fingerprint + paragraph + sequence |

The program name on a record is the PROGRAM-ID. Analysing the same source again
replaces that source's paragraph rows. Every run is also appended to
`output/program_log.jsonl`. A failure to write the log does not hide the analysis.

---

## 10. Change proposal

`src/changes` answers a different question from the rest of the tool: given this
analysis, where would one requested assignment go?

```bash
python -m src.changes sample_programs/INP389.cbl.txt "update SETATRK-ACOP-PROMO-FLG with 'Y'"
```

`requirement.py` accepts any one field and one value (`update`, `set`, `change`,
`assign`, or `MOVE ... TO`). It does not know the program. A quoted token or a number
is a literal. A hyphenated name is another field to move from.

`dclgen.py` reads a DB2 DCLGEN member the program names with `EXEC SQL INCLUDE`,
because the pipeline does not expand INCLUDE. It pairs each COBOL host name with the
column in the comment above it, and keeps the PICTURE and the SQL type.

`propose.py` then:

1. resolves the name to a host variable or a column (`ACOP_PROMO_FLG` and
   `SETATRK-ACOP-PROMO-FLG` are the same field);
2. finds `UPDATE` and `INSERT` statements in the statement trees;
3. keeps the statement that writes that field's table, preferring a reachable
   paragraph and a statement that already touches the column;
4. inserts a MOVE and a SET-list column, or replaces an existing MOVE when the
   column is already assigned.

The new lines copy the indentation of the neighbouring MOVE and the column of `=`.
The WHERE clause is left as it is. If the program already moves the requested value,
the result is that no edit is required. If the field is not in an included DCLGEN or
the expanded DATA DIVISION, or the program never writes that table, there is no edit.
The feature does not invent a new SQL statement. INSERT column lists are not rewritten.
The UI does not show proposals yet.

On INP389, `update SETATRK-ACOP-PROMO-FLG with 'Y'` adds the MOVE and
`ACOP_PROMO_FLG = :SETATRK-ACOP-PROMO-FLG` to the existing `UPDATE ACOP_TRK` in
`1000-UPDATE-ACOP-TRK`. The same path serves any other column of a table the program
already updates.

---

## 11. HTTP API

The service is `api/server.py`. Analyses are kept in memory, the 20 most recent, and
are dropped when the process stops. Routes are under `/api`.

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/analyze` | analyse `{name, source, copybooks}`, store it, write the log |
| GET | `/sample` | bundled `sample01.cbl` |
| GET | `/analyses/{id}` | divisions, paragraphs, graph, COMMAREA, copybooks, trace |
| GET | `/analyses/{id}/source` | numbered source lines |
| GET | `/analyses/{id}/paragraphs/{name}` | callers, outgoing calls, outline, source |
| GET | `/analyses/{id}/paragraphs/{name}/summary` | plain-language summary |
| GET | `/analyses/{id}/paragraphs/{name}/locals` | values, decisions, slices |
| GET | `/analyses/{id}/paragraphs/{name}/sample-buffer` | one-round buffer |
| GET | `/analyses/{id}/working-storage` | WORKING-STORAGE items |
| GET | `/analyses/{id}/input-buffer` | detected input area and a built sample |
| GET | `/analyses/{id}/buffer-search` | buffer built by repeating the tests |
| GET | `/analyses/{id}/insights` | fields that drive decisions |
| GET | `/analyses/{id}/search?q=` | paragraph name search |
| GET | `/analyses/{id}/export/{fmt}` | xlsx, json, paragraphs.csv, callsites.csv |

`assume` is a comma-separated list of `NAME=value` for positions the program does not set.

Copybooks, under `/api/copybooks`: list, categories, export, one layout, save or
delete a description or a field note.

Program log, under `/api/program-log`: programs, one history, details, and paragraph
records by PROGRAM-ID.

---

## 12. React UI

React 18, React Router, and Vite. The dev server proxies `/api` to `API_PROXY`,
which defaults to `http://127.0.0.1:8000`. The flow graph is laid out with
`@dagrejs/dagre`. `state.jsx` holds the current analysis. The last analysis id is
kept in `sessionStorage` when the browser allows it.

| Page | Route | What it shows |
| --- | --- | --- |
| Program Upload | `/` | choose a file or the sample, analyse, divisions and source |
| Program Overview | `/overview` | counts, divisions, sections, export |
| Paragraph Explorer | `/explorer` | search, callers, calls, outline, source, summary |
| Paragraph Flow | `/flow` | one paragraph's statement tree and local diagram |
| Program Flow Map | `/map` | the whole call graph and the trace |
| Copybook Layout | `/copybooks` | field layout, descriptions, notes |
| Program Log | `/program-log` | earlier runs and the notes attached to a program |
| Program Values | `/values` | input buffer, the built sample, local variables and decisions |

The change proposal is not a page. Working-storage as its own screen, and the
paragraph decision rows from the log, are also not pages yet. Program Values already
shows locals and the built input sample.

---

## 13. Agent query

`scripts/agent_query.py` reads one JSON object from stdin and writes one JSON object
to stdout. Commands are `samples`, `analyze`, and `paragraph`. It runs the same
pipeline and the same paragraph summary, and it trims the trace, the outline, and
the returned source so a caller is not handed the whole listing. The sibling
`cobol-analyst` agent uses this script. It does not call `src/changes`.

---

## 14. Tests

From `cobol-flow-analyzer/`:

```bash
.venv/bin/python -m pytest -q tests
```

| File | Covers |
| --- | --- |
| `test_analysis.py` | parser, paragraphs, flow, statements |
| `test_commarea.py` | COMMAREA layout and checks |
| `test_copybooks.py`, `test_copybook_reader.py`, `test_copybook_layout.py` | expansion, encoding, layout, notes, copybook API |
| `test_paragraph_summary.py` | summaries, insights, 88-level notes |
| `test_local_values.py` | values, slices, decisions |
| `test_buffer_builder.py`, `test_buffer_search.py` | sample buffers |
| `test_program_log.py` | runs, details, paragraph records, the analyse endpoint |
| `test_agent_query.py` | the JSON bridge |
| `test_change_proposal.py` | a requirement becoming an edit, including INP389 |

---

## 15. Running it

```bash
cd cobol-flow-analyzer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000
```

```bash
cd cobol-flow-analyzer/frontend
npm install
npm run dev
```

Environment variables:

- `COBOL_COPYBOOKS`: extra copybook folders, separated by the OS path separator;
- `COBOL_KNOWLEDGE_DB`: the notes database;
- `COBOL_PROGRAM_LOG_DB` and `COBOL_PROGRAM_LOG_FILE`: the log database and the JSON-lines file;
- `API_PROXY`: where Vite sends `/api`.

Restart the API after a backend change. A process started earlier keeps the old code,
and the analyses it holds are only in that process.

---

## 16. Limits

- The trace and the value walker follow a loop body once. `PERFORM UNTIL` and
  `PERFORM VARYING` do not iterate.
- AND and OR stay as text. They are not split into separate constraints.
- A sample buffer writes the first allowed value and the first OCCURS element.
  Numeric samples are zero-filled without a sign.
- A partial MOVE into a reference-modified target is recorded and does not change
  the traced value.
- PERFORMs are followed three levels deep and are not recursive. A PERFORM whose
  target is missing is reported.
- `EXEC SQL INCLUDE` is not part of the expanded program. The change proposer reads
  those members itself, and only when they are DCLGEN copybooks.
- The body of an external CALL, including `DSNTIAC`, is not analysed.
- `ALTER` and a GO TO with no static target are reported and not followed.
- The API forgets analyses when it stops.
- A proposal is one field and one value, placed on an UPDATE or INSERT the program
  already has. It is not written back to the file.
