import Icon from "./Icon.jsx";

/** Blue uppercase pill with the page name, as in the reference screen. */
export function PageTag({ children }) {
  return <span className="page-tag">{children}</span>;
}

/** Row of KPI tiles separated by vertical rules. */
export function StatStrip({ items }) {
  return (
    <section className="stat-strip">
      {items.map((item, i) => (
        <div className="stat" key={item.label}>
          <div className="stat-icon">
            <Icon name={item.icon} size={20} />
          </div>
          <div className="stat-body">
            <div className="stat-label">{item.label}</div>
            <div className={`stat-value${item.muted ? " muted" : ""}`}>{item.value}</div>
          </div>
          {i < items.length - 1 && <span className="stat-divider" aria-hidden="true" />}
        </div>
      ))}
    </section>
  );
}

/** White rounded card; children are the body. */
export function Card({ title, subtitle, children, className = "", footer }) {
  return (
    <section className={`card ${className}`}>
      {(title || subtitle) && (
        <div className="card-head">
          {title && <h2 className="card-title">{title}</h2>}
          {subtitle && <p className="card-subtitle">{subtitle}</p>}
        </div>
      )}
      {children}
      {footer}
    </section>
  );
}

/** Underlined tabs with count badges. */
export function Tabs({ tabs, active, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={active === tab.key}
          className={`tab${active === tab.key ? " active" : ""}`}
          onClick={() => onChange(tab.key)}
          type="button"
        >
          {tab.label}
          {tab.count !== undefined && <span className="count-badge">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Search-style input with an action button on the right, as in the reference screen. */
export function SearchBar({
  value,
  onChange,
  onSubmit,
  placeholder,
  actionLabel = "RUN",
  disabled = false,
  onRefresh,
  list,
  children,
}) {
  const empty = !value || !value.trim();
  return (
    <form
      className="search-row"
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled && !empty) onSubmit?.();
      }}
    >
      <div className="search-input">
        <Icon name="search" size={18} className="search-icon" />
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          list={list}
          aria-label={placeholder}
        />
        {children}
      </div>
      <button className={`action-btn${empty || disabled ? " disabled" : ""}`} type="submit" disabled={empty || disabled}>
        {actionLabel}
      </button>
      {onRefresh && (
        <button className="icon-btn" type="button" onClick={onRefresh} title="Reset" aria-label="Reset">
          <Icon name="refresh" size={18} />
        </button>
      )}
    </form>
  );
}

/** Small bordered field with an icon, e.g. a date range or file name. */
export function Field({ icon, children }) {
  return (
    <div className="field">
      <Icon name={icon} size={18} />
      <span>{children}</span>
    </div>
  );
}

/** Table with the blue top rule from the reference design. */
export function DataTable({ columns, rows, rowKey, onRowClick, selectedKey, empty = "No results yet." }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.className}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="empty-cell">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => {
              const key = rowKey ? rowKey(row) : i;
              return (
                <tr
                  key={key}
                  className={`${onRowClick ? "clickable" : ""} ${selectedKey === key ? "selected" : ""}`}
                  onClick={onRowClick ? () => onRowClick(row, key) : undefined}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.className}>
                      {c.render ? c.render(row) : row[c.key]}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Coloured pill for statuses and statement kinds. */
export function Badge({ tone = "neutral", children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function statusTone(status) {
  if (!status) return "neutral";
  if (status.startsWith("Entry")) return "green";
  if (status.startsWith("Never")) return "red";
  if (status.startsWith("Called from") && status.includes("paragraphs")) return "blue";
  if (status.startsWith("Called")) return "blue";
  return "gray";
}

export function eventTone(kind) {
  switch (kind) {
    case "STOP":
      return "red";
    case "GO TO":
      return "red";
    case "BRANCH":
      return "amber";
    case "PERFORM":
    case "RETURN":
      return "blue";
    case "ENTER":
    case "END":
      return "green";
    default:
      return "gray";
  }
}

export function Alert({ tone = "warn", icon = "alert", children }) {
  return (
    <div className={`alert alert-${tone}`} role="status">
      <Icon name={icon} size={18} />
      <div>{children}</div>
    </div>
  );
}

export function Empty({ children }) {
  return <div className="empty-state">{children}</div>;
}

export function Conditions({ items }) {
  if (!items || items.length === 0) return <span className="muted">unconditional</span>;
  return (
    <span className="conditions">
      {items.map((c, i) => (
        <span key={i} className="condition-chip">
          {c}
        </span>
      ))}
    </span>
  );
}
