import { useState } from "react";
import { useAnalysis } from "../state.jsx";
import FlowGraph, { FlowLegend } from "../components/FlowGraph.jsx";
import { Badge, Card, DataTable, Empty, PageTag, StatStrip, Tabs, eventTone } from "../components/ui.jsx";

export default function FlowMapPage() {
  const { analysis } = useAnalysis();
  const [tab, setTab] = useState("graph");
  const [showFallThrough, setShowFallThrough] = useState(true);
  const [kindFilter, setKindFilter] = useState("all");

  if (!analysis) {
    return (
      <div className="page">
        <div className="page-head"><PageTag>Program Flow Map</PageTag></div>
        <Card><Empty>No results yet. Analyze a program on the Program Upload screen first.</Empty></Card>
      </div>
    );
  }

  const s = analysis.stats;
  const neverCalled = analysis.paragraphs.filter((p) => p.never_called);
  const trace = kindFilter === "all" ? analysis.trace : analysis.trace.filter((e) => e.kind === kindFilter);
  const kinds = [...new Set(analysis.trace.map((e) => e.kind))];

  const items = [
    { label: "Paragraphs", value: s.paragraphs, icon: "list" },
    { label: "Call sites", value: s.call_sites, icon: "flow" },
    { label: "Never called", value: s.never_called, icon: "alert" },
    { label: "Trace steps", value: s.trace_events, icon: "network" },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Program Flow Map</PageTag>
        <p className="lede">
          How the paragraphs of <strong>{analysis.program.name}</strong> connect, and the order execution would follow.
        </p>
      </div>

      <StatStrip items={items} />

      <Card className="tab-card">
        <div className="card-inner">
          <FlowLegend />
        </div>
        <Tabs
          tabs={[
            { key: "graph", label: "Flow Map" },
            { key: "trace", label: "Execution Trace", count: analysis.trace.length },
            { key: "never", label: "Never Called", count: neverCalled.length },
          ]}
          active={tab}
          onChange={setTab}
        />

        {tab === "graph" && (
          <div className="graph-card">
            <label className="checkbox">
              <input type="checkbox" checked={showFallThrough} onChange={(e) => setShowFallThrough(e.target.checked)} />
              Show fall-through edges (source order)
            </label>
            <FlowGraph graph={analysis.graph} showFallThrough={showFallThrough} />
          </div>
        )}

        {tab === "trace" && (
          <>
            <div className="card-inner">
              <p className="card-subtitle">
                Static walk from the entry paragraph. PERFORM returns to its caller, GO TO transfers control, and
                every IF or EVALUATE branch is listed with its condition.
              </p>
              <div className="chip-row">
                <button type="button" className={`chip${kindFilter === "all" ? " on" : ""}`} onClick={() => setKindFilter("all")}>All</button>
                {kinds.map((k) => (
                  <button key={k} type="button" className={`chip${kindFilter === k ? " on" : ""}`} onClick={() => setKindFilter(k)}>{k}</button>
                ))}
              </div>
            </div>
            <DataTable
              columns={[
                { key: "seq", label: "Step", className: "num", render: (e) => e.seq },
                { key: "event", label: "Event", render: (e) => <Badge tone={eventTone(e.kind)}>{e.kind}</Badge> },
                { key: "paragraph", label: "Paragraph", className: "mono", render: (e) => e.paragraph || "—" },
                { key: "detail", label: "Detail", render: (e) => <span style={{ paddingLeft: e.depth * 18 }}>{e.detail}</span> },
                { key: "cond", label: "Condition path", className: "mono small", render: (e) => e.condition_path || "—" },
              ]}
              rows={trace}
              rowKey={(e) => e.seq}
              empty="No execution events."
            />
          </>
        )}

        {tab === "never" && (
          <DataTable
            columns={[
              { key: "name", label: "Paragraph", className: "mono", render: (p) => p.name },
              { key: "section", label: "Section", render: (p) => p.section || "—" },
              { key: "origin", label: "Source line", render: (p) => p.origin },
              { key: "reach", label: "Reachable from entry", render: (p) => (p.reachable ? "Yes" : <Badge tone="red">No</Badge>) },
            ]}
            rows={neverCalled}
            rowKey={(p) => p.name}
            empty="Every paragraph is called from somewhere."
          />
        )}
      </Card>
    </div>
  );
}
