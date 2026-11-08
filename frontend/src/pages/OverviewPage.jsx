import { useState } from "react";
import { useAnalysis } from "../state.jsx";
import { api } from "../api.js";
import { Alert, Card, DataTable, Empty, Field, PageTag, StatStrip, Tabs } from "../components/ui.jsx";
import Icon from "../components/Icon.jsx";

const EXPORTS = [
  { fmt: "xlsx", label: "Excel report", detail: "Summary, paragraphs, call sites, statements, trace", icon: "download" },
  { fmt: "json", label: "Full analysis (JSON)", detail: "Everything the UI shows, for other tools", icon: "file" },
  { fmt: "paragraphs.csv", label: "Paragraphs (CSV)", detail: "One row per paragraph with status", icon: "list" },
  { fmt: "callsites.csv", label: "Call sites (CSV)", detail: "Every PERFORM and GO TO with conditions", icon: "flow" },
];

export default function OverviewPage() {
  const { analysis } = useAnalysis();
  const [tab, setTab] = useState("divisions");

  if (!analysis) {
    return (
      <div className="page">
        <div className="page-head">
          <PageTag>Program Overview</PageTag>
        </div>
        <Card>
          <Empty>No program loaded. Analyze a program on the Program Upload screen first.</Empty>
        </Card>
      </div>
    );
  }

  const p = analysis.program;
  const items = [
    { label: "Divisions", value: analysis.divisions.length, icon: "layers" },
    { label: "Sections", value: analysis.sections.length, icon: "list" },
    { label: "Data items (01/77)", value: p.data_item_count, icon: "file" },
    { label: "Source lines", value: p.line_count, icon: "code" },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Program Overview</PageTag>
        <p className="lede">
          <strong>{p.name}</strong> from {p.source_name}. The PROCEDURE DIVISION starts at {analysis.program.procedure_origin}.
        </p>
      </div>

      <StatStrip items={items} />

      {analysis.stats.never_called > 0 && (
        <Alert tone="error">
          Never called: {analysis.paragraphs.filter((x) => x.never_called).map((x) => x.name).join(", ")}
        </Alert>
      )}
      {analysis.stats.unreachable > 0 && (
        <Alert tone="warn">
          Unreachable from the entry point: {analysis.paragraphs.filter((x) => !x.reachable).map((x) => x.name).join(", ")}
        </Alert>
      )}

      <Card className="tab-card">
        <Tabs
          tabs={[
            { key: "divisions", label: "Divisions", count: analysis.divisions.length },
            { key: "sections", label: "Sections", count: analysis.sections.length },
            { key: "export", label: "Export" },
          ]}
          active={tab}
          onChange={setTab}
        />

        {tab === "divisions" && (
          <DataTable
            columns={[
              { key: "name", label: "Division" },
              { key: "origin", label: "Source line" },
            ]}
            rows={analysis.divisions}
            rowKey={(r) => r.name}
          />
        )}

        {tab === "sections" && (
          <DataTable
            columns={[
              { key: "name", label: "Section" },
              { key: "division", label: "Division" },
              { key: "origin", label: "Source line" },
              { key: "paragraph_count", label: "Paragraphs", className: "num" },
            ]}
            rows={analysis.sections}
            rowKey={(r) => r.name}
            empty="No sections found."
          />
        )}

        {tab === "export" && (
          <div className="export-grid">
            {EXPORTS.map((x) => (
              <a key={x.fmt} className="export-card" href={api.exportUrl(analysis.id, x.fmt)} download>
                <span className="stat-icon"><Icon name={x.icon} size={20} /></span>
                <span>
                  <span className="export-title">{x.label}</span>
                  <span className="export-detail">{x.detail}</span>
                </span>
                <Icon name="download" size={18} className="export-dl" />
              </a>
            ))}
            <div className="export-note">
              <Field icon="file">{analysis.program.source_name}</Field>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
