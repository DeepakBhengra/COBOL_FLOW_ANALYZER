import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import { Alert, Card, DataTable, Empty, Field, PageTag, SearchBar, StatStrip, Tabs } from "../components/ui.jsx";

const TABS = [
  { key: "divisions", label: "Divisions" },
  { key: "sections", label: "Sections" },
  { key: "source", label: "Source" },
];

export default function UploadPage() {
  const { analysis, load, busy, error, setError, clear } = useAnalysis();
  const [pending, setPending] = useState(null); // { name, source }
  const [tab, setTab] = useState("divisions");
  const [sourceLines, setSourceLines] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => {
    if (tab === "source" && analysis && !sourceLines) {
      api.source(analysis.id).then((d) => setSourceLines(d.lines)).catch((e) => setError(e.message));
    }
  }, [tab, analysis, sourceLines, setError]);

  useEffect(() => setSourceLines(null), [analysis?.id]);

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
    setSourceLines(null);
    if (fileRef.current) fileRef.current.value = "";
    clear();
  }

  const divisionRows = analysis?.divisions ?? [];
  const sectionRows = analysis?.sections ?? [];

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

        <Tabs
          tabs={[
            { ...TABS[0], count: divisionRows.length },
            { ...TABS[1], count: sectionRows.length },
            { ...TABS[2] },
          ]}
          active={tab}
          onChange={setTab}
        />

        {!analysis && tab !== "source" && (
          <Empty>No results yet. Choose a COBOL file or load the sample, then click ANALYZE.</Empty>
        )}

        {analysis && tab === "divisions" && (
          <DataTable
            columns={[
              { key: "name", label: "Division" },
              { key: "origin", label: "Source line" },
            ]}
            rows={divisionRows}
            rowKey={(r) => r.name}
          />
        )}

        {analysis && tab === "sections" && (
          <DataTable
            columns={[
              { key: "name", label: "Section" },
              { key: "division", label: "Division" },
              { key: "origin", label: "Source line" },
              { key: "paragraph_count", label: "Paragraphs", className: "num" },
            ]}
            rows={sectionRows}
            rowKey={(r) => r.name}
            empty="No sections found."
          />
        )}

        {tab === "source" && (
          <div className="code-block">
            {!analysis && <Empty>Analyze a program to see its source.</Empty>}
            {analysis && !sourceLines && <Empty>Loading source…</Empty>}
            {analysis && sourceLines && (
              <pre className="code">
                {sourceLines.map((l) => (
                  <div key={l.number} className="code-line">
                    <span className="ln">{l.number}</span>
                    <span>{l.text || " "}</span>
                  </div>
                ))}
              </pre>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
