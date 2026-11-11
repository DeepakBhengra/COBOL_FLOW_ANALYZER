import { Alert, Badge, DataTable, Empty } from "./ui.jsx";

function shown(value) {
  const trimmed = value.replace(/\s+$/, "");
  if (trimmed === "") return <span className="muted">blank</span>;
  return <span className="mono">'{trimmed}'</span>;
}

/** The input record built for a paragraph that receives it, and the logic run on that record. */
export default function SimulatedInput({ sim }) {
  if (!sim) return null;
  const decided = sim.decisions.filter((d) => d.decided !== null).length;
  return (
    <div className="sim-block">
      <h3 className="sub-title">Simulated input: {sim.group}</h3>
      <p className="sim-lede">
        Built field by field at its declared offset ({sim.bytes} bytes). Assumptions: {
          Object.keys(sim.assumptions).length
            ? Object.entries(sim.assumptions).map(([k, v]) => `${k} = ${v}`).join(", ")
            : "none"
        }. Built in {sim.rounds} round{sim.rounds === 1 ? "" : "s"}.
      </p>

      <DataTable
        columns={[
          { key: "offset", label: "Offset", className: "num", render: (f) => f.offset + 1 },
          { key: "name", label: "Field", className: "mono small", render: (f) => f.name },
          {
            key: "value",
            label: "Value",
            render: (f) => (f.packed
              ? <span className="mono">{f.shown} <span className="muted">(packed {f.value.trim()})</span></span>
              : f.shown && f.shown.trim() !== "" ? <span className="mono">{f.shown.replace(/\s+$/, "")}</span> : shown(f.value)),
          },
          { key: "why", label: "Why this value", render: (f) => f.reason },
          {
            key: "possible",
            label: "Possible values (88)",
            render: (f) => f.possible_values.length
              ? f.possible_values.map((p) => `${p.condition} = '${p.value}'`).join("; ")
              : "—",
          },
        ]}
        rows={sim.record.filter((f) => f.value.trim() !== "" || f.reason.includes("test") || f.possible_values.length)}
        rowKey={(f) => f.name}
        empty="No field is set in this record."
      />

      <h4 className="sub-title">The record as it is laid out</h4>
      <pre className="sample-text">{sim.text.replace(/ /g, "·")}</pre>

      {sim.patches.length > 0 && (
        <>
          <h4 className="sub-title">Values set to satisfy the tests</h4>
          <DataTable
            columns={[
              { key: "field", label: "Field", className: "mono small", render: (p) => p.field },
              { key: "value", label: "Set to", className: "mono", render: (p) => `'${p.value.trim()}'` },
              { key: "line", label: "Line", className: "num", render: (p) => p.line },
              { key: "cond", label: "Needed by", className: "mono small", render: (p) => p.condition },
            ]}
            rows={sim.patches}
            rowKey={(p) => `${p.field}-${p.line}`}
          />
        </>
      )}

      <h4 className="sub-title">Downstream logic on this record ({decided} of {sim.decisions.length} decisions known)</h4>
      {sim.downstream.length === 0 && <Empty>No decision follows from this record.</Empty>}
      {sim.downstream.map((group) => (
        <div key={group.paragraph} className="sim-downstream">
          <div className="sim-para">{group.paragraph}</div>
          <DataTable
            columns={[
              { key: "line", label: "Line", className: "num", render: (d) => d.line },
              { key: "when", label: "When", render: (d) => d.condition },
              {
                key: "known",
                label: "Result",
                render: (d) => d.decided === null
                  ? <Badge tone="gray">depends on an input not given</Badge>
                  : <Badge tone={d.decided === "true" ? "green" : "red"}>{d.decided}</Badge>,
              },
              {
                key: "taken",
                label: "Action taken",
                className: "mono small",
                render: (d) => (d.taken.length ? d.taken.join(" · ") : "—"),
              },
            ]}
            rows={group.decisions}
            rowKey={(d) => `${d.line}-${d.condition}`}
          />
        </div>
      ))}

      {sim.unknown_inputs.length > 0 && (
        <Alert tone="info">
          {sim.unknown_inputs.length} decision{sim.unknown_inputs.length === 1 ? "" : "s"} depend on values this
          analysis does not have (for example a database return code). Those branches are shown as both possible.
        </Alert>
      )}

      {sim.chain.length > 0 && (
        <>
          <h4 className="sub-title">Logic and calculation, in order</h4>
          <ol className="values-chain">
            {sim.chain.slice(0, 60).map((step, i) => <li key={i} className="mono small">{step}</li>)}
          </ol>
          {sim.chain.length > 60 && <p className="muted">… {sim.chain.length - 60} more steps.</p>}
        </>
      )}
    </div>
  );
}
