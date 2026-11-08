import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import FlowGraph from "../components/FlowGraph.jsx";
import {
  Badge, Card, Conditions, DataTable, Empty, PageTag, SearchBar, StatStrip, Tabs, statusTone,
} from "../components/ui.jsx";

const KIND_TONE = { PERFORM: "blue", "PERFORM THRU": "blue", SIMPLE: "gray", IF: "amber", EVALUATE: "amber",
  GOTO: "red", TERMINATE: "red", EXIT_PARA: "red", NOOP: "gray" };

export default function FlowPage() {
  const { analysis, setError } = useAnalysis();
  const [query, setQuery] = useState("");
  const [name, setName] = useState(null);
  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState("statements");

  useEffect(() => {
    setName(null);
    setDetail(null);
  }, [analysis?.id]);

  useEffect(() => {
    if (!analysis || !name) return;
    api.paragraph(analysis.id, name).then(setDetail).catch((e) => setError(e.message));
  }, [analysis, name, setError]);

  function choose(value) {
    setQuery(value);
    if (analysis?.paragraphs.some((p) => p.name === value)) setName(value);
  }

  if (!analysis) {
    return (
      <div className="page">
        <div className="page-head"><PageTag>Paragraph Flow</PageTag></div>
        <Card><Empty>No results yet. Analyze a program on the Program Upload screen first.</Empty></Card>
      </div>
    );
  }

  const para = analysis.paragraphs.find((p) => p.name === name);
  const items = [
    { label: "Statements", value: para?.statement_count ?? "—", icon: "file", muted: !para },
    { label: "Reached from", value: para ? para.caller_count : "—", icon: "flow", muted: !para },
    { label: "Transfers to", value: detail ? detail.outgoing.length : "—", icon: "network", muted: !detail },
    { label: "Falls through to", value: detail?.falls_through_to || "—", icon: "chart", muted: !detail },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Paragraph Flow</PageTag>
        <p className="lede">Step through one paragraph: its statements, where control comes from, and where it goes.</p>
      </div>

      <StatStrip items={items} />

      <Card className="tab-card">
        <div className="card-inner">
          <h2 className="card-title">Choose a Paragraph</h2>
          <p className="card-subtitle">Type a name or pick one from the list.</p>
          <SearchBar
            value={query}
            onChange={choose}
            onSubmit={() => choose(query)}
            placeholder="Paragraph name"
            actionLabel="SHOW"
            list="paragraph-names"
            onRefresh={() => { setQuery(""); setName(null); }}
          />
          <datalist id="paragraph-names">
            {analysis.paragraphs.map((p) => <option key={p.name} value={p.name} />)}
          </datalist>
        </div>

        {!detail && <Empty>Select a paragraph to see its flow.</Empty>}

        {detail && (
          <>
            <div className="detail-badges">
              <span className="mono strong">{detail.name}</span>
              <Badge tone={statusTone(detail.status)}>{detail.status}</Badge>
            </div>
            <div className="card-inner pad-top">
              <div className="alert alert-info">{detail.after_completion}</div>
            </div>
            <Tabs
              tabs={[
                { key: "statements", label: "Statements", count: detail.outline.length },
                { key: "incoming", label: "Reached from", count: detail.callers.length },
                { key: "outgoing", label: "Transfers to", count: detail.outgoing.length },
                { key: "local", label: "Local flow" },
              ]}
              active={tab}
              onChange={setTab}
            />

            {tab === "statements" && (
              <DataTable
                columns={[
                  { key: "line", label: "Line", className: "num", render: (r) => r.line },
                  { key: "kind", label: "Kind", render: (r) => r.kind === "BRANCH"
                      ? <span className="muted">branch</span>
                      : <Badge tone={KIND_TONE[r.kind] || "gray"}>{r.kind}</Badge> },
                  { key: "text", label: "Statement", className: "mono", render: (r) => (
                      <span style={{ paddingLeft: r.depth * 20 }} className={r.kind === "BRANCH" ? "muted" : ""}>
                        {r.text}
                      </span>) },
                ]}
                rows={detail.outline}
                rowKey={(r) => `${r.line}-${r.depth}-${r.text}`}
                empty="This paragraph has no statements."
              />
            )}

            {tab === "incoming" && (
              <DataTable
                columns={[
                  { key: "caller", label: "From", className: "mono", render: (c) => c.caller },
                  { key: "kind", label: "Kind", render: (c) => c.kind },
                  { key: "line", label: "Line", className: "num", render: (c) => c.line },
                  { key: "conditions", label: "Under conditions", render: (c) => <Conditions items={c.conditions} /> },
                ]}
                rows={detail.callers}
                rowKey={(c) => `${c.caller}-${c.line}`}
                empty="No incoming PERFORM or GO TO. Control reaches this paragraph only by fall-through, or not at all."
              />
            )}

            {tab === "outgoing" && (
              <DataTable
                columns={[
                  { key: "target", label: "To", className: "mono", render: (c) => c.target },
                  { key: "kind", label: "Kind", render: (c) => c.kind },
                  { key: "line", label: "Line", className: "num", render: (c) => c.line },
                  { key: "conditions", label: "Under conditions", render: (c) => <Conditions items={c.conditions} /> },
                ]}
                rows={detail.outgoing}
                rowKey={(c) => `${c.target}-${c.line}`}
                empty="No outgoing PERFORM or GO TO."
              />
            )}

            {tab === "local" && (
              <div className="graph-card">
                <FlowGraph graph={analysis.graph} focus={detail.name} selected={detail.name}
                  onSelect={(n) => choose(n)} />
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
