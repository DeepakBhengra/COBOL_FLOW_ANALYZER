import { useEffect, useState } from "react";
import { api } from "../api.js";
import FlowDiagram from "./FlowDiagram.jsx";
import { Alert, Badge, Card, DataTable, Empty } from "./ui.jsx";

const TONE = { error: "red", warning: "amber", info: "blue" };

/** The summary, business logic and flow chart of a copybook that holds procedure code. */
export default function CopybookFlow({ name }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .copybookProcedure(name)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, [name]);

  return (
    <Card className="tab-card" title="What this copybook does" subtitle="Summary, logic and flow of its statements">
      <div className="card-inner">
        {error && <Alert tone="error">{error}</Alert>}
        {!data && !error && <Empty>Reading the statements…</Empty>}
        {data && (
          <div className="summary-body">
            <p className="summary-after">{data.summary || "No summary could be written."}</p>

            <h3 className="sub-title">Business logic in plain language</h3>
            <ol className="values-chain">
              {data.explanation.map((s, i) => <li key={i}>{s}</li>)}
            </ol>

            <h3 className="sub-title">Flow diagram</h3>
            <FlowDiagram flow={data.flow} name={data.name} />

            <h3 className="sub-title">Review findings</h3>
            <DataTable
              columns={[
                { key: "sev", label: "Severity", render: (f) => <Badge tone={TONE[f.severity] || "gray"}>{f.severity}</Badge> },
                { key: "kind", label: "Check", className: "mono small", render: (f) => f.kind },
                { key: "msg", label: "Finding", render: (f) => f.message },
              ]}
              rows={data.findings}
              rowKey={(f, i) => i}
              empty="No findings."
            />
            <Alert tone="info">
              Names this copybook uses but does not declare (for example WS-ERROR-INTERFACE) belong to the
              program that copies it. Analyse that program to see their values in context.
            </Alert>
          </div>
        )}
      </div>
    </Card>
  );
}
