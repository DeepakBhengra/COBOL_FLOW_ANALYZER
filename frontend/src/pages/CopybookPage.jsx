import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { Alert, Card, Empty, PageTag, Badge } from "../components/ui.jsx";
import Icon from "../components/Icon.jsx";

const FALLBACK_CATEGORIES = [
  "Identifier", "Amount", "Date / time", "Code / flag", "Status", "Counter",
  "Message / text", "Filler / reserved", "Group / record", "Other",
];

const RULES = [
  ["Columns 1–6", "Sequence numbers. Ignored by the compiler."],
  ["Column 7", "Indicator: * is a comment, - continues a line."],
  ["Columns 8–72", "Area A (levels 01, 77, 88 start here) and Area B (PIC clauses, indented sub-levels)."],
  ["Columns 73–80", "Identification area. Ignored."],
  ["Level numbers", "01 is the record. 05, 10, … are fields inside it. 88 is a condition name for the field above."],
  ["PIC X(n)", "Alphanumeric text, n bytes."],
  ["PIC 9(n) / S9(n)", "Zoned decimal (DISPLAY), one byte per digit. S means signed."],
  ["COMP-3 (PACKED-DECIMAL)", "Packed decimal: two digits per byte, sign in the last nibble. Size is digits ÷ 2 + 1."],
  ["COMP / BINARY / COMP-4 / COMP-5", "Binary integer: 2 bytes for 1–4 digits, 4 for 5–9, 8 for 10–18."],
  ["COMP-1 / COMP-2", "Floating point: 4 bytes (single) or 8 bytes (double)."],
  ["OCCURS n", "The field repeats n times. Its length is multiplied by n."],
  ["REDEFINES x", "The field shares the storage of field x, so it adds no length."],
];

function formatPic(item) {
  if (item.is_group) return "—";
  return item.pic ? `${item.pic}` : "—";
}

function NoteBadge({ note }) {
  if (!note) return <span className="muted">—</span>;
  return (
    <span className="note-preview">
      {note.category && <Badge tone="blue">{note.category}</Badge>}
      <span className="note-text">{note.meaning}</span>
      {note.stale && <Badge tone="amber">changed since noted</Badge>}
    </span>
  );
}

function InlineDescription({ item, busy, onCommit }) {
  const saved = item.note?.meaning || "";
  const [draft, setDraft] = useState(saved);
  const cancelled = useRef(false);

  useEffect(() => setDraft(saved), [saved, item.path]);

  return (
    <div className="inline-desc" onClick={(e) => e.stopPropagation()}>
      <input
        className="inline-input"
        value={draft}
        disabled={busy}
        placeholder="Add a description"
        aria-label={`Description of ${item.name}`}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            cancelled.current = true;
            e.currentTarget.blur();
          }
        }}
        onBlur={() => {
          if (cancelled.current) {
            cancelled.current = false;
            setDraft(saved);
            return;
          }
          if (draft.trim() !== saved.trim()) onCommit(draft);
        }}
      />
      {busy && <span className="muted small">saving…</span>}
      {item.note?.stale && <Badge tone="amber">changed since noted</Badge>}
    </div>
  );
}

export default function CopybookPage() {
  const [query, setQuery] = useState("");
  const [list, setList] = useState({ total: 0, items: [] });
  const [selected, setSelected] = useState(null);
  const [layout, setLayout] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selectedPath, setSelectedPath] = useState(null);
  const [categories, setCategories] = useState(FALLBACK_CATEGORIES);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  // Form state for the field editor and the copybook description.
  const [meaning, setMeaning] = useState("");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    api.copybookCategories().then((d) => setCategories(d.categories)).catch(() => {});
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      api.copybooks(query).then(setList).catch((e) => setLoadError(e.message));
    }, 150);
    return () => clearTimeout(timer);
  }, [query]);

  function loadLayout(name) {
    setLoadError(null);
    api
      .copybook(name)
      .then((data) => {
        setLayout(data);
        setDescription(data.description || "");
      })
      .catch((e) => setLoadError(e.message));
  }

  useEffect(() => {
    if (selected) {
      setSelectedPath(null);
      loadLayout(selected);
    }
  }, [selected]);

  const item = useMemo(
    () => (layout && selectedPath ? layout.items.find((i) => i.path === selectedPath) : null),
    [layout, selectedPath]
  );

  useEffect(() => {
    if (item) {
      setMeaning(item.note?.meaning || "");
      setCategory(item.note?.category || "");
      setTags((item.note?.tags || []).join(", "));
    }
  }, [item]);

  const annotated = layout ? layout.items.filter((i) => i.note).length : 0;
  const staleCount = layout ? layout.items.filter((i) => i.note?.stale).length : 0;

  async function saveField() {
    if (!layout || !item) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.saveFieldNote(layout.name, item.path, {
        meaning,
        category,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      setMessage({ tone: "info", text: `Saved the description of ${item.name}.` });
      loadLayout(layout.name);
    } catch (e) {
      setMessage({ tone: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function commitDescription(path, text) {
    if (!layout) return;
    const current = layout.items.find((i) => i.path === path);
    const trimmed = text.trim();
    setBusy(true);
    setMessage(null);
    try {
      if (!trimmed) {
        if (!current?.note) return;
        await api.deleteFieldNote(layout.name, path);
        setMessage({ tone: "info", text: `Removed the description of ${current.name}.` });
      } else {
        await api.saveFieldNote(layout.name, path, {
          meaning: trimmed,
          category: current?.note?.category || "",
          tags: current?.note?.tags || [],
        });
        setMessage({ tone: "info", text: `Saved the description of ${current.name}.` });
      }
      loadLayout(layout.name);
    } catch (e) {
      setMessage({ tone: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function removeField() {
    if (!layout || !item) return;
    setBusy(true);
    try {
      await api.deleteFieldNote(layout.name, item.path);
      setMeaning("");
      setCategory("");
      setTags("");
      setMessage({ tone: "info", text: `Removed the description of ${item.name}.` });
      loadLayout(layout.name);
    } catch (e) {
      setMessage({ tone: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function saveDescription() {
    if (!layout) return;
    setBusy(true);
    try {
      await api.saveCopybookDescription(layout.name, description);
      setMessage({ tone: "info", text: `Saved the description of ${layout.name}.` });
      loadLayout(layout.name);
    } catch (e) {
      setMessage({ tone: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <PageTag>Copybook Layout</PageTag>
        <p className="lede">
          Pick a copybook to see every field laid out in storage. Describe what each field means. Those notes are
          saved, and they are shown again whenever a program that copies this copybook is analyzed.
        </p>
      </div>

      <div className="copybook-grid">
        <Card className="copybook-list-card">
          <div className="card-inner">
            <h2 className="card-title">Copybooks</h2>
            <p className="card-subtitle">{list.total.toLocaleString()} found. Type to narrow the list.</p>
            <div className="search-input copybook-search">
              <Icon name="search" size={18} className="search-icon" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Copybook name"
                aria-label="Copybook name" />
              {query && (
                <button type="button" className="clear-btn" onClick={() => setQuery("")} aria-label="Clear search">×</button>
              )}
            </div>
          </div>
          <ul className="copybook-list">
            {list.items.map((c) => (
              <li key={c.name}>
                <button type="button" className={`copybook-item${selected === c.name ? " active" : ""}`}
                  onClick={() => setSelected(c.name)}>
                  <span className="mono">{c.name}</span>
                  {c.annotated_fields > 0 && <Badge tone="green">{c.annotated_fields} noted</Badge>}
                </button>
              </li>
            ))}
            {list.items.length === 0 && <li className="copybook-empty">No copybook matches.</li>}
          </ul>
        </Card>

        <div className="copybook-main">
          {loadError && <Alert tone="error">{loadError}</Alert>}
          {message && <Alert tone={message.tone === "error" ? "error" : "info"} icon="check">{message.text}</Alert>}

          {!layout && !loadError && (
            <Card><Empty>Choose a copybook on the left to see its layout.</Empty></Card>
          )}

          {layout && (
            <>
              <Card className="copybook-head-card">
                <div className="card-inner">
                  <div className="title-row">
                    <h2 className="card-title mono">{layout.name}</h2>
                    <span className="muted small">{layout.file}</span>
                  </div>
                  <div className="stat-row">
                    <div><span className="stat-label">Total length</span><span className="stat-value small-value">{layout.total_length} bytes</span></div>
                    <div><span className="stat-label">Fields</span><span className="stat-value small-value">{layout.items.length}</span></div>
                    <div><span className="stat-label">Described</span><span className="stat-value small-value">{annotated} of {layout.items.length}</span></div>
                    <div><span className="stat-label">Record</span><span className="stat-value small-value mono">{layout.roots.join(", ") || "—"}</span></div>
                  </div>

                  {!layout.has_data && (
                    <Alert tone="warn">This copybook has no data entries. It probably holds procedure code.</Alert>
                  )}
                  {(layout.description_stale || staleCount > 0) && (
                    <Alert tone="warn">
                      {staleCount > 0 && `${staleCount} note(s) were written before the copybook last changed. Check them. `}
                      {layout.description_stale && "The description was written before the copybook last changed."}
                    </Alert>
                  )}
                  {layout.problems.length > 0 && (
                    <Alert tone="warn">{layout.problems.slice(0, 5).join(" · ")}</Alert>
                  )}

                  <label className="field-label" htmlFor="cb-desc">What this copybook is for</label>
                  <textarea id="cb-desc" className="text-area" rows={2} value={description}
                    onChange={(e) => setDescription(e.target.value)} placeholder="For example: customer inquiry communication area" />
                  <div className="form-row">
                    <button type="button" className="action-btn" disabled={busy} onClick={saveDescription}>SAVE DESCRIPTION</button>
                  </div>
                </div>
              </Card>

              <Card className="tab-card" title="Fields" subtitle="Click a field to describe it.">
                <div className="table-wrap">
                  <table className="data-table layout-table">
                    <thead>
                      <tr>
                        <th>Level</th>
                        <th>Field</th>
                        <th>Type</th>
                        <th>PIC</th>
                        <th>USAGE</th>
                        <th className="num">Offset</th>
                        <th className="num">Length</th>
                        <th className="num">Occurs</th>
                        <th>Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {layout.items.map((it) => (
                        <tr key={it.path}
                          className={`clickable${selectedPath === it.path ? " selected" : ""}${it.is_group ? " group-row" : ""}`}
                          onClick={() => setSelectedPath(it.path)}>
                          <td className="mono">
                            <span style={{ paddingLeft: it.depth * 14 }}>{String(it.level).padStart(2, "0")}</span>
                          </td>
                          <td className="mono">
                            {it.name}
                            {it.redefines && <span className="muted small"> redefines {it.redefines}</span>}
                            {it.conditions.map((c) => (
                              <span key={c.name} className="condition-chip cond-inline">{c.name} = {c.values}</span>
                            ))}
                          </td>
                          <td>{it.type_label}</td>
                          <td className="mono small">{formatPic(it)}</td>
                          <td className="mono small">{it.is_group ? "GROUP" : it.usage}</td>
                          <td className="num mono small">{it.offset}</td>
                          <td className="num mono small">{it.length}</td>
                          <td className="num">{it.occurs > 1 ? it.occurs : ""}</td>
                          <td><InlineDescription item={it} busy={busy} onCommit={(text) => commitDescription(it.path, text)} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {item && (
                <Card className="detail-card" title={item.path}
                  subtitle={`${item.type_label}${item.digits ? ` · ${item.digits} digits` : ""}${item.decimals ? `, ${item.decimals} after the point` : ""}${item.signed ? ", signed" : ""} · offset ${item.offset}, ${item.length} bytes${item.occurs > 1 ? `, OCCURS ${item.occurs}` : ""}`}>
                  <div className="card-inner editor">
                    <label className="field-label" htmlFor="meaning">Description</label>
                    <textarea id="meaning" className="text-area" rows={3} value={meaning}
                      onChange={(e) => setMeaning(e.target.value)}
                      placeholder="For example: the customer number keyed on the inquiry screen. Blank if unknown." />
                    <div className="editor-grid">
                      <div>
                        <label className="field-label" htmlFor="category">Category</label>
                        <select id="category" className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
                          <option value="">(none)</option>
                          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="field-label" htmlFor="tags">Tags (comma separated)</label>
                        <input id="tags" className="text-input" value={tags} onChange={(e) => setTags(e.target.value)}
                          placeholder="key, screen, mandatory" />
                      </div>
                    </div>
                    <div className="form-row">
                      <button type="button" className={`action-btn${!meaning.trim() || busy ? " disabled" : ""}`}
                        disabled={!meaning.trim() || busy} onClick={saveField}>SAVE DESCRIPTION</button>
                      {item.note && (
                        <button type="button" className="secondary-btn" disabled={busy} onClick={removeField}>Remove description</button>
                      )}
                    </div>

                    {item.conditions.length > 0 && (
                      <>
                        <h3 className="sub-title">Condition names (88)</h3>
                        <ul className="plain-list">
                          {item.conditions.map((c) => <li key={c.name}><span className="mono">{c.name}</span> when {c.values}</li>)}
                        </ul>
                      </>
                    )}
                  </div>
                </Card>
              )}

              <details className="rules card">
                <summary>How to read this layout</summary>
                <table className="data-table">
                  <tbody>
                    {RULES.map(([k, v]) => (
                      <tr key={k}><td className="mono small strong">{k}</td><td>{v}</td></tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
