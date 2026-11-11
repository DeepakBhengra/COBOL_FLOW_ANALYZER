import { useEffect, useState } from "react";
import "../summary.css";
import { api } from "../api.js";
import { Alert, Card, DataTable, Empty, Badge } from "./ui.jsx";
import SimulatedInput from "./SimulatedInput.jsx";

/** Plain-language summary of one paragraph, built from the saved copybook field notes. */
export default function ParagraphSummary({ analysisId, name }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!analysisId || !name) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    api
      .paragraphSummary(analysisId, name)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [analysisId, name]);

  return (
    <Card className="summary-card" title="Summary" subtitle={`What ${name} does, based on the saved field notes`}>
      {loading && <Empty>Summarizing…</Empty>}
      {error && <Alert tone="error">{error}</Alert>}
      {data && (
        <div className="summary-body">
          <ul className="summary-sentences">
            {data.summary.split(/(?<=\.) (?=[A-Z])/).map((sentence, i) => (
              <li key={i}>{sentence}</li>
            ))}
          </ul>

          <div className="summary-stats">
            <Badge tone="blue">{data.decisions.length} decisions</Badge>
            <Badge tone="green">{data.changes.length} fields changed</Badge>
            <Badge tone="gray">{data.calls.length} calls out</Badge>
          </div>

          <h3 className="sub-title">Decisions</h3>
          <DataTable
            columns={[
              { key: "line", label: "Line", className: "num", render: (d) => d.line },
              { key: "when", label: "When", render: (d) => d.plain },
              { key: "true", label: "If true", className: "mono small", render: (d) => (d.when_true.length ? d.when_true.join(" · ") : "—") },
            ]}
            rows={data.decisions}
            rowKey={(d) => `${d.line}-${d.condition}`}
            empty="No IF or EVALUATE decisions in this paragraph."
          />

          <h3 className="sub-title">Fields changed</h3>
          <DataTable
            columns={[
              { key: "field", label: "Field", className: "mono", render: (c) => c.field },
              { key: "meaning", label: "Meaning", render: (c) => c.meaning || <span className="muted">no note</span> },
              { key: "values", label: "Set to", className: "mono", render: (c) => c.values.join(", ") },
              { key: "lines", label: "Lines", render: (c) => c.lines.join(", ") },
            ]}
            rows={data.changes}
            rowKey={(c) => c.field}
            empty="No fields changed in this paragraph."
          />

          <p className="summary-after">{data.after_completion}</p>

          {data.simulation && <SimulatedInput sim={data.simulation} />}
        </div>
      )}
    </Card>
  );
}
