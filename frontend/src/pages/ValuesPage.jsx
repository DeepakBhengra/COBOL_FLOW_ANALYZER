import { useEffect, useMemo, useState } from "react";
import "../values.css";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import { Alert, Badge, Card, DataTable, Empty, PageTag, StatStrip } from "../components/ui.jsx";

function Sample({ built }) {
  if (!built) return <Empty>No input sample could be built.</Empty>;
  const hasData = built.sample.trim().length > 0;
  return (
    <div className="sample-block">
      <div className="sample-caption">
        {built.buffer} · {built.size} bytes · built from {built.entry} in {built.rounds} round{built.rounds === 1 ? "" : "s"}
      </div>
      {hasData ? <pre className="sample-text">{built.display}</pre> : <Empty>
        Nothing could be placed yet: the tests on this buffer use positions the program has not set.
        Pass them in the assumptions field, for example WS-NEXT-POS=1.
      </Empty>}
    </div>
  );
}

export default function ValuesPage() {
  const { analysis, setError } = useAnalysis();
  const [input, setInput] = useState(null);
  const [paragraph, setParagraph] = useState("");
  const [locals, setLocals] = useState(null);
  const [selectedLocal, setSelectedLocal] = useState(null);
  const [assume, setAssume] = useState("");
  const [applied, setApplied] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!analysis) return;
    setParagraph(analysis.paragraphs[0]?.name || "");
    setSelectedLocal(null);
  }, [analysis?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!analysis) return;
    api
      .inputBuffer(analysis.id, "", applied)
      .then((d) => {
        setInput(d);
        if (d.entry_paragraph && !paragraph) setParagraph(d.entry_paragraph);
      })
      .catch((e) => setError(e.message));
  }, [analysis?.id, applied]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!analysis || !paragraph) return;
    setLoading(true);
    api
      .paragraphLocals(analysis.id, paragraph)
      .then(setLocals)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [analysis?.id, paragraph]); // eslint-disable-line react-hooks/exhaustive-deps

  const localRows = useMemo(() => locals?.locals || [], [locals]);

  if (!analysis) {
    return (
      <div className="page">
        <div className="page-head"><PageTag>Program Values</PageTag></div>
        <Card><Empty>No results yet. Analyze a program on the Program Upload screen first.</Empty></Card>
      </div>
    );
  }

  const chosen = input?.buffers?.find((b) => b.buffer === input.chosen);
  const built = input?.built;
  const stats = [
    { label: "Input buffers", value: input?.buffers?.length ?? "—", icon: "layers", muted: !input },
    { label: "Local variables", value: locals?.used_variables?.length ?? (localRows.length || "—"), icon: "list", muted: !locals },
    { label: "Logic steps", value: locals?.chain?.length ?? "—", icon: "flow", muted: !locals },
    { label: "Decisions", value: locals?.decisions?.length ?? "—", icon: "network", muted: !locals },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Program Values</PageTag>
        <p className="lede">
          The input buffer the program starts from, and the value of each local variable as the program
          sets it, paragraph by paragraph.
        </p>
      </div>

      <StatStrip items={stats} />

      {input && input.buffers.length === 0 && (
        <Alert tone="warn">No input buffer was found. The program does not read a buffer from CICS or a file.</Alert>
      )}

      {chosen && (
        <Card className="tab-card" title="Input buffer" subtitle={`${chosen.buffer} is the starting input the rest of the program reads`}>
          <div className="card-inner values-grid">
            <div>
              <h3 className="sub-title">Where it is set</h3>
              <DataTable
                columns={[
                  { key: "how", label: "Source", render: (r) => r.how },
                  { key: "paragraph", label: "Paragraph", className: "mono", render: (r) => r.paragraph },
                  { key: "line", label: "Line", className: "num", render: (r) => r.line },
                  { key: "stmt", label: "Statement", className: "mono small", render: (r) => r.statement },
                ]}
                rows={chosen.loaded_by}
                rowKey={(r) => `${r.paragraph}-${r.line}`}
                empty="The program does not load this buffer itself. Its bytes come from the caller or the input."
              />
            </div>
            <div>
              <h3 className="sub-title">Declared as</h3>
              <p className="values-line">
                {chosen.declared ? <>{chosen.pic} · {chosen.bytes} bytes</> : <Badge tone="amber">not declared in this program</Badge>}
              </p>
              <h3 className="sub-title">Read in</h3>
              <DataTable
                columns={[
                  { key: "paragraph", label: "Paragraph", className: "mono", render: (r) => r.paragraph },
                  { key: "line", label: "Line", className: "num", render: (r) => r.line },
                  { key: "slice", label: "Slice", className: "mono", render: (r) => `(${r.start}:${r.length})` },
                ]}
                rows={chosen.reads.slice(0, 40)}
                rowKey={(r) => `${r.paragraph}-${r.line}-${r.start}`}
                empty="Not read by any paragraph."
              />
            </div>
          </div>

          <div className="card-inner">
            <h3 className="sub-title">Sample built from the tests on this buffer</h3>
            <form
              className="assume-row"
              onSubmit={(e) => { e.preventDefault(); setApplied(assume.trim()); }}
            >
              <input
                value={assume}
                onChange={(e) => setAssume(e.target.value)}
                placeholder="Positions the program does not set, e.g. WS-NEXT-POS=1, WS-START-POS=3"
                aria-label="Assumed positions"
              />
              <button type="submit" className="action-btn">APPLY</button>
            </form>
            <Sample built={built} />
            {built?.placements?.length > 0 && (
              <DataTable
                columns={[
                  { key: "pos", label: "Position", className: "num", render: (p) => p.position },
                  { key: "len", label: "Length", className: "num", render: (p) => p.length },
                  { key: "value", label: "Value placed", className: "mono", render: (p) => JSON.stringify(p.value) },
                  { key: "round", label: "Round", className: "num", render: (p) => p.round },
                  { key: "line", label: "Line", className: "num", render: (p) => p.line },
                  { key: "cond", label: "Needed by", className: "mono small", render: (p) => p.condition },
                ]}
                rows={built.placements}
                rowKey={(p) => `${p.round}-${p.position}`}
              />
            )}
            {built?.unsatisfied?.length > 0 && (
              <Alert tone="warn">{built.unsatisfied.length} test(s) on this buffer could not be satisfied.</Alert>
            )}
            {built?.conflicts?.length > 0 && (
              <Alert tone="error">{built.conflicts.length} conflicting test(s) on the same bytes.</Alert>
            )}
          </div>
        </Card>
      )}

      <Card className="tab-card" title="Local variables" subtitle="Values as the selected paragraph and the paragraphs it PERFORMs set them">
        <div className="card-inner">
          <label className="field-label" htmlFor="values-paragraph">Paragraph</label>
          <select
            id="values-paragraph"
            className="select"
            value={paragraph}
            onChange={(e) => { setParagraph(e.target.value); setSelectedLocal(null); }}
          >
            {analysis.paragraphs.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>

        {loading && <Empty>Following the values…</Empty>}

        {locals && !loading && (
          <>
            <DataTable
              columns={[
                { key: "name", label: "Variable", className: "mono", render: (v) => v.name },
                { key: "type", label: "Type", render: (v) => v.type || "—" },
                { key: "bytes", label: "Bytes", className: "num", render: (v) => v.bytes ?? "—" },
                { key: "init", label: "Starts as", className: "mono", render: (v) => v.initial ?? "—" },
                { key: "final", label: "Ends as", className: "mono", render: (v) => v.final ?? "—" },
                {
                  key: "used",
                  label: "Used as",
                  render: (v) => [v.read && "read", v.written && "set"].filter(Boolean).join(" + ") || "—",
                },
                { key: "changes", label: "Changes", className: "num", render: (v) => (v.history || []).length },
              ]}
              rows={locals.used_variables || localRows}
              rowKey={(v) => v.name}
              selectedKey={selectedLocal}
              onRowClick={(v) => setSelectedLocal(v.name)}
              empty="No local variable is set in this paragraph."
            />

            {locals.exhausted && (
              <Alert tone="warn">The analysis stopped early for this program size, so some values are partial.</Alert>
            )}

            {selectedLocal && (
              <>
                <h3 className="sub-title">{selectedLocal}: how its value is set</h3>
                <DataTable
                  columns={[
                    { key: "line", label: "Line", className: "num", render: (h) => h.line },
                    { key: "via", label: "In", className: "mono", render: (h) => h.via },
                    { key: "how", label: "By", render: (h) => h.how },
                    { key: "value", label: "Value", className: "mono", render: (h) => h.value },
                  ]}
                  rows={localRows.find((v) => v.name === selectedLocal)?.history || []}
                  rowKey={(h) => `${h.line}-${h.value}`}
                />
              </>
            )}

            <h3 className="sub-title">Logic and calculation, in program order</h3>
            <ol className="values-chain">
              {locals.chain.map((step, i) => <li key={i} className="mono small">{step}</li>)}
            </ol>

            <h3 className="sub-title">Decisions</h3>
            <DataTable
              columns={[
                { key: "line", label: "Line", className: "num", render: (d) => d.line },
                { key: "cond", label: "When", render: (d) => d.condition },
                { key: "decided", label: "Known?", render: (d) => d.decided === null ? <Badge tone="gray">depends on input</Badge> : <Badge tone={d.decided === "true" ? "green" : "red"}>{d.decided}</Badge> },
                { key: "true", label: "If true", className: "mono small", render: (d) => d.when_true.join(" · ") || "—" },
                { key: "else", label: "Else", className: "mono small", render: (d) => d.when_else.join(" · ") || "—" },
              ]}
              rows={locals.decisions}
              rowKey={(d) => `${d.line}-${d.condition}`}
            />

            {locals.slices.length > 0 && (
              <>
                <h3 className="sub-title">Parts of the input read</h3>
                <DataTable
                  columns={[
                    { key: "text", label: "Read", className: "mono", render: (s) => s.text },
                    { key: "explain", label: "Meaning", render: (s) => s.explain },
                  ]}
                  rows={locals.slices}
                  rowKey={(s) => s.text}
                />
              </>
            )}

            {locals.notes.length > 0 && (
              <Alert tone="info">{locals.notes.slice(0, 6).join(" · ")}{locals.notes.length > 6 ? " …" : ""}</Alert>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
