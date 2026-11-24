import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import { Alert, Badge, Card, Empty, PageTag, StatStrip } from "../components/ui.jsx";

function valuesText(values) {
  if (!values) return "";
  return Array.isArray(values) ? values.map((v) => `'${v}'`).join(" ") : String(values);
}

/**
 * An editable description. It is saved when the field loses focus or Enter is pressed;
 * onSave(text) returns a promise for the save.
 */
function DescriptionCell({ name, description, onSave }) {
  const [text, setText] = useState(description || "");
  const [state, setState] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => setText(description || ""), [description]);

  function save() {
    if ((description || "") === text) return;
    setState("saving");
    setError(null);
    onSave(text)
      .then(() => setState("saved"))
      .catch((e) => {
        setState("");
        setError(e.message);
      });
  }

  return (
    <div className="desc-cell">
      <input
        className="desc-input"
        value={text}
        placeholder="Add a description"
        aria-label={`Description of ${name}`}
        onChange={(e) => { setText(e.target.value); setState(""); }}
        onBlur={save}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
      />
      {state === "saving" && <span className="muted small">saving…</span>}
      {state === "saved" && <span className="muted small">saved</span>}
      {error && <span className="desc-error small">{error}</span>}
    </div>
  );
}

/** The copybook layout format for one set of items, with a description column. */
function ItemsTable({ items, analysisId, onSaved, withDescription }) {
  if (!items || items.length === 0) return <Empty>No data items.</Empty>;
  return (
    <div className="table-wrap">
      <table className="data-table layout-table">
        <thead>
          <tr>
            <th>Level</th>
            <th>Field</th>
            <th>Type</th>
            <th>PIC</th>
            <th>Usage</th>
            <th className="num">Offset</th>
            <th className="num">Length</th>
            <th className="num">Occurs</th>
            <th>Conditions (88)</th>
            {withDescription && <th>Description</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={`${it.name}-${i}`}>
              <td className="mono">{String(it.level).padStart(2, "0")}</td>
              <td className="mono" style={{ paddingLeft: 8 + (it.depth || 0) * 18 }}>{it.name}</td>
              <td>{it.type_label || (it.is_group ? "Group" : "—")}</td>
              <td className="mono">{it.pic || "—"}</td>
              <td className="mono small">{it.usage || "—"}</td>
              <td className="num">{it.offset}</td>
              <td className="num">{it.length}</td>
              <td className="num">{it.occurs > 1 ? it.occurs : ""}</td>
              <td>
                {(it.conditions || []).map((c) => (
                  <div key={c.name} className="mono small">{c.name} = {valuesText(c.values)}</div>
                ))}
              </td>
              {withDescription && (
                <td>
                  <DescriptionCell
                    name={it.name}
                    description={it.description}
                    onSave={(text) =>
                      api
                        .saveItemDescription(analysisId, { name: it.name, line: it.line, description: text })
                        .then(() => onSaved(it.name, text))
                    }
                  />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Search any variable name across the program's working storage and every copybook and DCLGEN it uses. */
function FieldSearch({ analysisId }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResult(null);
      setError(null);
      setBusy(false);
      return undefined;
    }
    setBusy(true);
    const timer = setTimeout(() => {
      api
        .searchLayout(analysisId, q)
        .then((r) => { setResult(r); setError(null); })
        .catch((e) => setError(e.message))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, analysisId]);

  const q = query.trim();
  return (
    <div className="field-search">
      <input
        type="search"
        className="field-search-input"
        placeholder="Search any variable name, e.g. CUST-ID"
        aria-label="Search variable names"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {busy && <span className="muted small">searching…</span>}
      {error && <Alert tone="error">{error}</Alert>}
      {result && q && (
        <>
          <p className="muted small">
            {result.count} match{result.count === 1 ? "" : "es"}
            {result.truncated ? `, first ${result.matches.length} shown` : ""}
          </p>
          {result.matches.length === 0 ? (
            <Empty>No field name contains “{q}”.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="data-table layout-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Found in</th>
                    <th>Level</th>
                    <th>Type</th>
                    <th>PIC</th>
                    <th className="num">Offset</th>
                    <th className="num">Length</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {result.matches.map((m, i) => (
                    <tr key={`${m.source}-${m.name}-${i}`}>
                      <td className="mono">{m.name}</td>
                      <td className="mono small">
                        {m.kind === "program" ? "This program" : m.source}
                        {m.kind === "dclgen" && <span className="muted"> (DCLGEN)</span>}
                      </td>
                      <td className="mono">{String(m.level).padStart(2, "0")}</td>
                      <td>{m.type_label || "—"}</td>
                      <td className="mono">{m.pic || "—"}</td>
                      <td className="num">{m.offset}</td>
                      <td className="num">{m.length}</td>
                      <td>
                        <DescriptionCell
                          name={m.name}
                          description={m.description}
                          onSave={(text) =>
                            api
                              .saveItemDescription(analysisId, {
                                name: m.name,
                                kind: m.kind,
                                source: m.source,
                                path: m.path,
                                description: text,
                              })
                              .then(() => setResult((r) => r && {
                                ...r,
                                matches: r.matches.map((x, j) => (j === i ? { ...x, description: text } : x)),
                              }))
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** A copybook or DCLGEN member the program uses, with its layout one click away. */
function MemberRow({ member }) {
  const [open, setOpen] = useState(false);
  const [layout, setLayout] = useState(null);
  const [error, setError] = useState(null);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !layout && member.found) {
      api
        .copybook(member.name)
        .then(setLayout)
        .catch((e) => setError(e.message));
    }
  }

  return (
    <div className="member-row">
      <div className="member-head">
        <span className="mono">{member.name}</span>
        <Badge tone={member.kind === "dclgen" ? "blue" : "gray"}>
          {member.kind === "dclgen" ? "DCLGEN (EXEC SQL INCLUDE)" : "COPY"}
        </Badge>
        {member.line && <span className="muted small">line {member.line}</span>}
        {!member.found && <Badge tone="red">not in the copybook library</Badge>}
        {member.found && (
          <button type="button" className="text-btn" onClick={toggle}>
            {open ? "Hide layout" : "Show layout"}
          </button>
        )}
      </div>
      {open && error && <Alert tone="error">{error}</Alert>}
      {open && member.found && !layout && !error && <Empty>Loading layout…</Empty>}
      {open && layout && (
        <>
          <p className="muted small">
            {layout.file} · {layout.total_length} bytes · {layout.items.length} fields
          </p>
          <ItemsTable items={layout.items} withDescription={false} />
        </>
      )}
    </div>
  );
}

export default function WorkingStoragePage() {
  const { analysis, setError } = useAnalysis();
  const [layout, setLayout] = useState(null);

  useEffect(() => {
    setLayout(null);
    if (!analysis) return;
    api
      .programLayout(analysis.id)
      .then(setLayout)
      .catch((e) => setError(e.message));
  }, [analysis?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function onSaved(name, description) {
    setLayout((current) => current && {
      ...current,
      items: current.items.map((i) => (i.name === name ? { ...i, description } : i)),
    });
  }

  if (!analysis) {
    return (
      <div className="page">
        <div className="page-head"><PageTag>Working Storage</PageTag></div>
        <Card><Empty>No results yet. Analyze a program on the Program Upload screen first.</Empty></Card>
      </div>
    );
  }

  const items = layout?.items || [];
  const copies = (layout?.copybooks || []).filter((m) => m.kind === "copy");
  const dclgens = (layout?.copybooks || []).filter((m) => m.kind === "dclgen");
  const stats = [
    { label: "Working-storage items", value: items.length || "—", icon: "layers", muted: !layout },
    { label: "Copybooks used", value: copies.length, icon: "book", muted: !layout },
    { label: "DCLGEN members", value: dclgens.length, icon: "file", muted: !layout },
    { label: "Not found", value: layout?.missing?.length ?? "—", icon: "alert", muted: !layout },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Working Storage</PageTag>
        <p className="lede">
          The WORKING-STORAGE of <strong>{analysis.program.name}</strong>, laid out like a copybook, with the
          copybooks and DCLGEN members it uses.
        </p>
      </div>

      <StatStrip items={stats} />

      {layout && layout.missing.length > 0 && (
        <Alert tone="warn">
          {layout.missing.length} member(s) are not in the copybook library: {layout.missing.join(", ")}.
          Set COBOL_COPYBOOKS to the folder that holds them, then analyse again.
        </Alert>
      )}

      <Card className="tab-card" title="Copybooks used" subtitle="Expand a copybook to see its layout in the same format">
        <div className="card-inner">
          <FieldSearch analysisId={analysis.id} />
          {!layout && <Empty>Loading…</Empty>}
          {layout && copies.length === 0 && <Empty>The program copies no copybooks.</Empty>}
          {copies.map((m) => <MemberRow key={`copy-${m.name}`} member={m} />)}
        </div>
      </Card>

      <Card className="tab-card" title="DCLGEN area" subtitle="SQL declarations pulled in with EXEC SQL INCLUDE">
        <div className="card-inner">
          {layout && dclgens.length === 0 && <Empty>The program has no EXEC SQL INCLUDE.</Empty>}
          {dclgens.map((m) => <MemberRow key={`dclgen-${m.name}`} member={m} />)}
        </div>
      </Card>

      <Card className="tab-card" title="Working-storage layout" subtitle="Every item the program declares. Edit a description and it is saved when you leave the cell.">
        <div className="card-inner">
          {!layout ? <Empty>Reading the working storage…</Empty> : (
            <ItemsTable items={items} analysisId={analysis.id} onSaved={onSaved} withDescription />
          )}
        </div>
      </Card>
    </div>
  );
}
