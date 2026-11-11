import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Alert, Badge, DataTable, Empty } from "./ui.jsx";
import FlowDiagram from "./FlowDiagram.jsx";

const TONE = { error: "red", warning: "amber", info: "blue" };

/** Business rules and review findings, read from the Python representation of the paragraph. */
export default function BusinessLogic({ analysisId, name }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .businessLogic(analysisId, name)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, [analysisId, name]);

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!data) return <Empty>Reading the business logic…</Empty>;
  const counts = data.summary.by_severity;

  return (
    <div className="bl-block">
      <div className="convert-actions">
        <Badge tone="red">{counts.error || 0} error(s)</Badge>
        <Badge tone="amber">{counts.warning || 0} warning(s)</Badge>
        <Badge tone="blue">{data.summary.paragraphs} paragraph(s)</Badge>
      </div>

      <h3 className="sub-title">Review findings</h3>
      <DataTable
        columns={[
          { key: "sev", label: "Severity", render: (f) => <Badge tone={TONE[f.severity] || "gray"}>{f.severity}</Badge> },
          { key: "kind", label: "Check", className: "mono small", render: (f) => f.kind },
          { key: "para", label: "Paragraph", className: "mono small", render: (f) => f.paragraph || "—" },
          { key: "msg", label: "Finding", render: (f) => f.message },
        ]}
        rows={data.findings}
        rowKey={(f, i) => i}
        empty="No findings."
      />

      <h3 className="sub-title">Business logic in plain language</h3>
      {data.paragraphs.map((para) => (
        <div key={para.name} className="bl-para">
          <div className="sim-para">
            {para.name}
            {para.name === data.selected && <span className="muted"> (selected)</span>}
          </div>
          <ol className="values-chain">
            {para.explanation.map((sentence, i) => <li key={i}>{sentence}</li>)}
          </ol>
          <details open={para.name === data.selected} className="bl-flow">
            <summary>Flow diagram</summary>
            <FlowDiagram flow={para.flow} name={para.name} />
          </details>
        </div>
      ))}
    </div>
  );
}
