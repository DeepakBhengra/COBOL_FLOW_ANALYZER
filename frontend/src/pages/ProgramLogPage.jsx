import { useEffect, useMemo, useState } from "react";
import "../programlog.css";
import { api } from "../api.js";
import { useAnalysis } from "../state.jsx";
import { Alert, Badge, Card, DataTable, Empty, PageTag, SearchBar, StatStrip } from "../components/ui.jsx";

const DEFAULT_CATEGORY = "general";

function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function shortFingerprint(fp) {
  return fp ? `${fp.slice(0, 12)}…` : "—";
}

export default function ProgramLogPage() {
  const { analysis, setError } = useAnalysis();
  const [programs, setPrograms] = useState(null);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selected, setSelected] = useState(null);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState(null);
  const [form, setForm] = useState({ category: DEFAULT_CATEGORY, key: "", value: "" });
  const [editing, setEditing] = useState(null); // { category, key } of the detail being edited
  const [busy, setBusy] = useState(false);

  const currentFingerprint = analysis?.log?.fingerprint || null;

  function loadPrograms() {
    return api.programLog().then((d) => setPrograms(d.programs)).catch((e) => setError(e.message));
  }

  useEffect(() => { loadPrograms(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Opening the page with a program just analysed selects that program.
  useEffect(() => {
    if (currentFingerprint) setSelected(currentFingerprint);
  }, [currentFingerprint]);

  useEffect(() => {
    if (!selected) {
      setHistory(null);
      return;
    }
    setLoading(true);
    api
      .programHistory(selected)
      .then(setHistory)
      .catch((e) => {
        setHistory(null);
        setError(e.message);
      })
      .finally(() => setLoading(false));
  }, [selected, setError]);

  const rows = useMemo(() => {
    if (!programs) return [];
    const needle = submitted.trim().toUpperCase();
    return programs.filter(
      (p) => !needle || p.program.toUpperCase().includes(needle) || p.source.toUpperCase().includes(needle),
    );
  }, [programs, submitted]);

  const categories = useMemo(() => {
    const set = new Set([DEFAULT_CATEGORY]);
    (history?.details || []).forEach((d) => set.add(d.category));
    return [...set].sort();
  }, [history]);

  const detailsByCategory = useMemo(() => {
    const groups = {};
    (history?.details || []).forEach((d) => {
      (groups[d.category] ||= []).push(d);
    });
    return groups;
  }, [history]);

  async function saveDetail(event) {
    event.preventDefault();
    if (!selected || !form.key.trim()) return;
    setBusy(true);
    try {
      await api.saveProgramDetail(selected, {
        category: form.category.trim() || DEFAULT_CATEGORY,
        key: form.key.trim(),
        value: form.value,
      });
      setForm({ category: form.category.trim() || DEFAULT_CATEGORY, key: "", value: "" });
      setNotice({ tone: "info", text: "Detail saved to the program log." });
      setEditing(null);
      setHistory(await api.programHistory(selected));
      loadPrograms();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeDetail(detail) {
    if (!window.confirm(`Remove "${detail.key}" from ${detail.category}?`)) return;
    setBusy(true);
    try {
      await api.deleteProgramDetail(selected, detail.category, detail.key);
      setHistory(await api.programHistory(selected));
      setNotice({ tone: "info", text: "Detail removed." });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(detail) {
    setEditing({ category: detail.category, key: detail.key });
    setForm({ category: detail.category, key: detail.key, value: detail.value });
  }

  function cancelEdit() {
    setEditing(null);
    setForm({ category: DEFAULT_CATEGORY, key: "", value: "" });
  }

  const summary = history?.runs?.[0]?.summary;
  const headerItems = [
    { label: "Programs logged", value: programs?.length ?? "—", icon: "list", muted: !programs },
    { label: "Runs (this program)", value: history?.run_count ?? "—", icon: "chart", muted: !history },
    { label: "Details saved", value: history?.details?.length ?? "—", icon: "file", muted: !history },
    { label: "Never called (latest)", value: summary?.stats ? (summary.never_called?.length ?? 0) : "—", icon: "alert", muted: !summary },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Program Log</PageTag>
        <p className="lede">
          Every analysed program is recorded here, with its past runs. Add what you learn about a program as details,
          and they are shown again the next time the same program is analysed.
        </p>
      </div>

      <StatStrip items={headerItems} />

      {notice && <Alert tone={notice.tone} icon="check">{notice.text}</Alert>}

      <div className="two-col program-log-layout">
        <Card className="program-log-list" title="Programs" subtitle={programs ? `${programs.length} logged` : "Loading…"}>
          <div className="card-inner">
            <SearchBar
              value={query}
              onChange={setQuery}
              onSubmit={() => setSubmitted(query)}
              placeholder="Program or file name"
              actionLabel="SEARCH"
              onRefresh={() => { setQuery(""); setSubmitted(""); }}
            />
          </div>
          <DataTable
            columns={[
              { key: "program", label: "Program", className: "mono", render: (p) => p.program },
              { key: "last", label: "Last run", render: (p) => formatTime(p.last_analysed) },
              { key: "runs", label: "Runs", className: "num", render: (p) => p.run_count },
            ]}
            rows={rows}
            rowKey={(p) => p.fingerprint}
            selectedKey={selected}
            onRowClick={(p) => setSelected(p.fingerprint)}
            empty={programs && programs.length === 0 ? "Nothing logged yet. Analyze a program first." : "No program matches this search."}
          />
        </Card>

        <div className="program-log-detail">
          {!selected && (
            <Card><Empty>Select a program to see its history and details.</Empty></Card>
          )}

          {selected && loading && <Card><Empty>Loading…</Empty></Card>}

          {selected && !loading && history && (
            <>
              <Card
                title={history.runs[0]?.program || "Program"}
                subtitle={`Fingerprint ${shortFingerprint(selected)} · ${history.run_count} run${history.run_count === 1 ? "" : "s"}`}
              >
                <div className="card-inner">
                  <h3 className="sub-title">Run history</h3>
                  <DataTable
                    columns={[
                      { key: "when", label: "Analysed", render: (r) => formatTime(r.analysed_at) },
                      { key: "source", label: "Source file", className: "mono", render: (r) => r.source },
                      { key: "paragraphs", label: "Paragraphs", className: "num", render: (r) => r.summary?.stats?.paragraphs ?? "—" },
                      { key: "calls", label: "Call sites", className: "num", render: (r) => r.summary?.stats?.call_sites ?? "—" },
                      { key: "copybooks", label: "Copybooks", className: "num", render: (r) => r.summary?.copybooks?.used?.length ?? 0 },
                      {
                        key: "never",
                        label: "Never called",
                        render: (r) => {
                          const n = r.summary?.never_called?.length ?? 0;
                          return n > 0 ? <Badge tone="red">{n}</Badge> : "0";
                        },
                      },
                    ]}
                    rows={history.runs}
                    rowKey={(r) => r.id}
                    empty="No runs recorded for this program."
                  />
                </div>
              </Card>

              <Card className="tab-card" title="Details" subtitle="Your notes about this program. Categories and keys are created as you add them.">
                {history.details.length === 0 && <Empty>No details yet. Add the first one below.</Empty>}

                {Object.entries(detailsByCategory).map(([category, items]) => (
                  <div key={category} className="card-inner program-log-group">
                    <h3 className="sub-title">{category}</h3>
                    <DataTable
                      columns={[
                        { key: "key", label: "Detail", className: "mono", render: (d) => d.key },
                        { key: "value", label: "Value", render: (d) => <span className="pre-wrap">{d.value}</span> },
                        { key: "updated", label: "Updated", render: (d) => formatTime(d.updated_at) },
                        {
                          key: "actions",
                          label: "",
                          render: (d) => (
                            <span className="row-actions">
                              <button type="button" className="text-btn" disabled={busy} onClick={() => startEdit(d)}>Edit</button>
                              <button type="button" className="text-btn danger" disabled={busy} onClick={() => removeDetail(d)}>Remove</button>
                            </span>
                          ),
                        },
                      ]}
                      rows={items}
                      rowKey={(d) => `${d.category}::${d.key}`}
                      empty="No details."
                    />
                  </div>
                ))}

                <form className="card-inner program-log-form" onSubmit={saveDetail}>
                  <h3 className="sub-title">{editing ? `Edit “${editing.key}”` : "Add a detail"}</h3>
                  <div className="form-grid">
                    <label className="form-field">
                      <span>Category</span>
                      <input
                        list="program-log-categories"
                        value={form.category}
                        onChange={(e) => setForm({ ...form, category: e.target.value })}
                        placeholder="e.g. Business rules, Database, Known issues"
                        disabled={!!editing}
                      />
                      <datalist id="program-log-categories">
                        {categories.map((c) => <option key={c} value={c} />)}
                      </datalist>
                    </label>
                    <label className="form-field">
                      <span>Detail name</span>
                      <input
                        value={form.key}
                        onChange={(e) => setForm({ ...form, key: e.target.value })}
                        placeholder="e.g. owner, batch window, ABEND code"
                        disabled={!!editing}
                      />
                    </label>
                  </div>
                  <label className="form-field">
                    <span>What you learned</span>
                    <textarea
                      rows={3}
                      value={form.value}
                      onChange={(e) => setForm({ ...form, value: e.target.value })}
                      placeholder="Write the detail. It is saved with this program's fingerprint."
                    />
                  </label>
                  <div className="form-actions">
                    <button type="submit" className="action-btn" disabled={busy || !form.key.trim()}>
                      {editing ? "SAVE CHANGES" : "SAVE DETAIL"}
                    </button>
                    {editing && (
                      <button type="button" className="text-btn" onClick={cancelEdit}>Cancel</button>
                    )}
                  </div>
                </form>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
