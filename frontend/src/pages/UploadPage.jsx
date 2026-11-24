import { useRef, useState } from "react";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import { Alert, Card, Empty, Field, PageTag, SearchBar, StatStrip } from "../components/ui.jsx";

/** The program's own description, from the comment block between DATE-COMPILED and REVISIONS INFO. */
function Description({ analysis }) {
  const text = analysis?.program?.description || "";
  if (!analysis) return <Empty>No program loaded yet. Choose a COBOL file or load the sample, then click ANALYZE.</Empty>;
  if (!text) {
    return (
      <Empty>
        This program has no description block between DATE-COMPILED and REVISIONS INFO.
      </Empty>
    );
  }
  return (
    <div className="program-description">
      <h3 className="sub-title">Program description</h3>
      <pre className="program-description-text">{text}</pre>
    </div>
  );
}

export default function UploadPage() {
  const { analysis, load, busy, error, setError, clear } = useAnalysis();
  const [pending, setPending] = useState(null); // { name, source }
  const fileRef = useRef(null);

  const stats = analysis?.stats;
  const statItems = [
    { label: "Paragraphs", value: stats?.paragraphs ?? "—", icon: "list", muted: !stats },
    { label: "Statements", value: stats?.statements ?? "—", icon: "file", muted: !stats },
    { label: "Call sites", value: stats?.call_sites ?? "—", icon: "flow", muted: !stats },
    { label: "External CALLs", value: stats?.external_calls ?? "—", icon: "network", muted: !stats },
  ];

  async function readFile(file) {
    const text = await file.text();
    setPending({ name: file.name, source: text });
    setError(null);
  }

  async function loadSample() {
    try {
      const sample = await api.sample();
      setPending({ name: sample.name, source: sample.source });
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }

  async function analyze() {
    if (!pending) return;
    await load(pending.name, pending.source);
  }

  function reset() {
    setPending(null);
    if (fileRef.current) fileRef.current.value = "";
    clear();
  }

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Program Upload</PageTag>
        <p className="lede">Upload a COBOL source file (fixed or free format), or load the sample program, then analyze it.</p>
      </div>

      <StatStrip items={statItems} />

      {error && <Alert tone="error">{error}</Alert>}

      <Card className="tab-card">
        <div className="card-inner">
          <h2 className="card-title">Upload COBOL Source</h2>
          <p className="card-subtitle">Files are analyzed in memory on the local server.</p>

          <SearchBar
            value={pending ? pending.name : ""}
            onChange={() => {}}
            placeholder="Choose a .cbl file or load the sample program"
            actionLabel={busy ? "ANALYZING…" : "ANALYZE"}
            disabled={!pending || busy}
            onSubmit={analyze}
            onRefresh={reset}
          >
            <button type="button" className="inline-btn" onClick={() => fileRef.current?.click()}>
              Choose file
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".cbl,.cob,.cobol,.txt"
              hidden
              onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])}
            />
          </SearchBar>

          <div className="toolbar">
            <button type="button" className="text-btn" onClick={loadSample}>Load sample program</button>
            {analysis && (
              <Field icon="calendar">
                {analysis.program.name} · {analysis.program.source_name} · {analysis.program.line_count} lines
              </Field>
            )}
          </div>
        </div>

        <div className="card-inner">
          <Description analysis={analysis} />
        </div>
      </Card>
    </div>
  );
}
