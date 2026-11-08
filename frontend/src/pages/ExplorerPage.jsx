import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import {
  Alert, Badge, Card, Conditions, DataTable, Empty, PageTag, SearchBar, StatStrip, Tabs, statusTone,
} from "../components/ui.jsx";
import ParagraphSummary from "../components/ParagraphSummary.jsx";

const FILTERS = {
  all: () => true,
  never: (p) => p.never_called,
  unreachable: (p) => !p.reachable,
  multiple: (p) => p.caller_count > 1,
};

export default function ExplorerPage() {
  const { analysis, setError } = useAnalysis();
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    setSelected(null);
    setDetail(null);
  }, [analysis?.id]);

  useEffect(() => {
    if (!analysis || !selected) return;
    setLoadingDetail(true);
    api
      .paragraph(analysis.id, selected)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingDetail(false));
  }, [analysis, selected, setError]);

  const rows = useMemo(() => {
    if (!analysis) return [];
    const needle = submitted.trim().toUpperCase();
    return analysis.paragraphs
      .filter(FILTERS[filter])
      .filter((p) => !needle || p.name.toUpperCase().includes(needle));
  }, [analysis, submitted, filter]);

  if (!analysis) {
    return (
      <div className="page">
        <div className="page-head"><PageTag>Paragraph Explorer</PageTag></div>
        <Card><Empty>No results yet. Analyze a program on the Program Upload screen first.</Empty></Card>
      </div>
    );
  }

  const s = analysis.stats;
  const items = [
    { label: "Paragraphs", value: s.paragraphs, icon: "list" },
    { label: "Multiple callers", value: analysis.paragraphs.filter(FILTERS.multiple).length, icon: "flow" },
    { label: "Never called", value: s.never_called, icon: "alert" },
    { label: "Unreachable", value: s.unreachable, icon: "network" },
  ];

  const counts = {
    all: analysis.paragraphs.length,
    never: analysis.paragraphs.filter(FILTERS.never).length,
    unreachable: analysis.paragraphs.filter(FILTERS.unreachable).length,
    multiple: analysis.paragraphs.filter(FILTERS.multiple).length,
  };

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Paragraph Explorer</PageTag>
        <p className="lede">Search paragraphs, then select one to see where it is defined, who calls it, and what happens after it.</p>
      </div>

      <StatStrip items={items} />

      <Card className="tab-card">
        <div className="card-inner">
          <h2 className="card-title">Search Paragraphs</h2>
          <p className="card-subtitle">Matches paragraph names. Try ERROR-PARA in the sample program.</p>
          <SearchBar
            value={query}
            onChange={setQuery}
            onSubmit={() => setSubmitted(query)}
            placeholder="Paragraph name (e.g. ERROR-PARA)"
            actionLabel="SEARCH"
            onRefresh={() => { setQuery(""); setSubmitted(""); }}
          />
        </div>

        <Tabs
          tabs={[
            { key: "all", label: "All Paragraphs", count: counts.all },
            { key: "never", label: "Never Called", count: counts.never },
            { key: "unreachable", label: "Unreachable", count: counts.unreachable },
            { key: "multiple", label: "Multiple Callers", count: counts.multiple },
          ]}
          active={filter}
          onChange={setFilter}
        />

        <DataTable
          columns={[
            { key: "name", label: "Paragraph", className: "mono", render: (p) => p.name },
            { key: "section", label: "Section", render: (p) => p.section || "—" },
            { key: "origin", label: "Source line", render: (p) => p.origin },
            { key: "status", label: "Status", render: (p) => <Badge tone={statusTone(p.status)}>{p.status}</Badge> },
            { key: "callers", label: "Call sites in", className: "num", render: (p) => p.call_count },
          ]}
          rows={rows}
          rowKey={(p) => p.name}
          selectedKey={selected}
          onRowClick={(p) => setSelected(p.name)}
          empty="No paragraph matches this search."
        />
      </Card>

      {selected && (
        <Card className="detail-card" title={selected} subtitle={
          detail ? `Defined at ${detail.origin || `line ${detail.start_line}`}, expanded lines ${detail.start_line}–${detail.end_line}${detail.section ? `, section ${detail.section}` : ""}` : ""
        }>
          {loadingDetail && <Empty>Loading…</Empty>}
          {detail && (
            <>
              <div className="detail-badges">
                <Badge tone={statusTone(detail.status)}>{detail.status}</Badge>
              </div>
              <Alert tone="info" icon="check">{detail.after_completion}</Alert>

              <div className="two-col">
                <div>
                  <h3 className="sub-title">Called by</h3>
                  <DataTable
                    columns={[
                      { key: "caller", label: "Caller", className: "mono", render: (c) => c.caller },
                      { key: "kind", label: "Kind", render: (c) => c.kind },
                      { key: "line", label: "Line", className: "num", render: (c) => c.line },
                      { key: "conditions", label: "Under conditions", render: (c) => <Conditions items={c.conditions} /> },
                    ]}
                    rows={detail.callers}
                    rowKey={(c) => `${c.caller}-${c.line}`}
                    empty="Nothing PERFORMs or GO TOs this paragraph."
                  />
                </div>
                <div>
                  <h3 className="sub-title">Calls out to</h3>
                  <DataTable
                    columns={[
                      { key: "target", label: "Target", className: "mono", render: (c) => c.target },
                      { key: "kind", label: "Kind", render: (c) => c.kind },
                      { key: "line", label: "Line", className: "num", render: (c) => c.line },
                      { key: "conditions", label: "Under conditions", render: (c) => <Conditions items={c.conditions} /> },
                    ]}
                    rows={detail.outgoing}
                    rowKey={(c) => `${c.target}-${c.line}`}
                    empty="No outgoing PERFORM or GO TO."
                  />
                </div>
              </div>

              <h3 className="sub-title">Every mention in the procedure division</h3>
              <DataTable
                columns={[
                  { key: "line", label: "Line", className: "num", render: (o) => o.line },
                  { key: "paragraph", label: "In paragraph", className: "mono", render: (o) => o.paragraph },
                  { key: "text", label: "Source", className: "mono", render: (o) => o.text },
                ]}
                rows={detail.occurrences}
                rowKey={(o) => o.line}
                empty="No mentions found."
              />

              <h3 className="sub-title">Source</h3>
              <pre className="code code-compact">{detail.source}</pre>
            </>
          )}
        </Card>
      )}

      {selected && analysis && <ParagraphSummary analysisId={analysis.id} name={selected} />}
    </div>
  );
}
