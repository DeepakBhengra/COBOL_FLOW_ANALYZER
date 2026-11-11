import { useMemo, useRef, useState } from "react";
import dagre from "@dagrejs/dagre";

const BOX_W = 210;
const BOX_H = 58;
const DIAMOND_W = 250;
const DIAMOND_H = 78;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 2.5;

const KIND = {
  start: { fill: "#dcfce7", stroke: "#16a34a" },
  end: { fill: "#dcfce7", stroke: "#16a34a" },
  decision: { fill: "#fef3c7", stroke: "#d97706" },
  repeat: { fill: "#ede9fe", stroke: "#7c3aed" },
  perform: { fill: "#dbeafe", stroke: "#2563eb" },
  data: { fill: "#e0f2fe", stroke: "#0284c7" },
  call: { fill: "#ccfbf1", stroke: "#0d9488" },
  stop: { fill: "#fee2e2", stroke: "#dc2626" },
  warning: { fill: "#fff7ed", stroke: "#ea580c" },
  action: { fill: "#f8fafc", stroke: "#64748b" },
};

function wrap(text, width, maxLines) {
  const words = String(text).split(" ");
  const lines = [];
  let line = "";
  words.forEach((word) => {
    if ((line + " " + word).trim().length > width) {
      if (line) lines.push(line);
      line = word;
    } else {
      line = (line + " " + word).trim();
    }
  });
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    lines[maxLines - 1] = lines[maxLines - 1].slice(0, width - 3) + "...";
  }
  return lines;
}

/**
 * The flow of one paragraph as a chart. Use the buttons, or Ctrl + mouse wheel, to zoom.
 * The frame scrolls up, down and sideways.
 */
export default function FlowDiagram({ flow, name }) {
  const [zoom, setZoom] = useState(1);
  const frame = useRef(null);
  const markerId = `arrow-${name.replace(/[^A-Za-z0-9]/g, "_")}`;

  const layout = useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "TB", nodesep: 34, ranksep: 46, marginx: 24, marginy: 24 });
    g.setDefaultEdgeLabel(() => ({}));
    flow.nodes.forEach((n) => {
      const diamond = n.kind === "decision";
      const round = n.kind === "start" || n.kind === "end";
      g.setNode(n.id, {
        width: diamond ? DIAMOND_W : BOX_W,
        height: diamond ? DIAMOND_H : BOX_H,
        node: n,
        diamond,
        round,
      });
    });
    flow.edges.forEach((e) => g.setEdge(e.source, e.target, { label: e.label, edge: e }));
    dagre.layout(g);
    const nodes = g.nodes().map((id) => ({ id, ...g.node(id) }));
    const edges = g.edges().map((ref) => ({ ...g.edge(ref), ref }));
    const { width, height } = g.graph();
    return { nodes, edges, width: width || 400, height: height || 200 };
  }, [flow]);

  const setZ = (value) => setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2)))));

  function onWheel(event) {
    if (!event.ctrlKey) return;
    event.preventDefault();
    setZ(zoom * (event.deltaY < 0 ? 1.1 : 0.9));
  }

  function fit() {
    const available = frame.current ? frame.current.clientWidth - 24 : layout.width;
    setZ(Math.min(1, available / layout.width));
  }

  const w = layout.width * zoom;
  const h = layout.height * zoom;

  return (
    <div className="flow-diagram">
      <div className="flow-toolbar">
        <span className="flow-name">{name} flow</span>
        <button type="button" className="icon-btn" onClick={() => setZ(zoom - 0.1)} aria-label="Zoom out">-</button>
        <span className="flow-zoom">{Math.round(zoom * 100)}%</span>
        <button type="button" className="icon-btn" onClick={() => setZ(zoom + 0.1)} aria-label="Zoom in">+</button>
        <button type="button" className="text-btn" onClick={() => setZ(1)}>100%</button>
        <button type="button" className="text-btn" onClick={fit}>Fit width</button>
        <span className="muted flow-hint">Ctrl + wheel also zooms. Scroll to see the rest.</span>
      </div>
      <div className="flow-frame" ref={frame} onWheel={onWheel}>
        <svg width={w} height={h} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img"
             aria-label={`Flow chart of ${name}`}>
          <defs>
            <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
                    orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
            </marker>
          </defs>
          {layout.edges.map((e, i) => {
            const pts = e.points || [];
            const d = pts.map((p, k) => `${k === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
            const mid = pts[Math.floor(pts.length / 2)] || { x: 0, y: 0 };
            const label = typeof e.label === "string" ? e.label : "";
            return (
              <g key={i}>
                <path d={d} fill="none" stroke="#475569" strokeWidth="1.6" markerEnd={`url(#${markerId})`} />
                {label ? (
                  <g>
                    <rect x={mid.x - 16} y={mid.y - 9} width="32" height="16" rx="4" fill="#ffffff" stroke="#cbd5e1" />
                    <text x={mid.x} y={mid.y + 3} textAnchor="middle" fontSize="10" fill="#334155">{label}</text>
                  </g>
                ) : null}
              </g>
            );
          })}
          {layout.nodes.map((n) => {
            const style = KIND[n.node.kind] || KIND.action;
            const lines = wrap(n.node.label, n.diamond ? 26 : 30, 3);
            const top = n.y - n.height / 2;
            const left = n.x - n.width / 2;
            return (
              <g key={n.id}>
                {n.diamond ? (
                  <polygon
                    points={`${n.x},${top} ${left + n.width},${n.y} ${n.x},${top + n.height} ${left},${n.y}`}
                    fill={style.fill} stroke={style.stroke} strokeWidth="1.6" />
                ) : (
                  <rect x={left} y={top} width={n.width} height={n.height}
                        rx={n.round ? n.height / 2 : 8} fill={style.fill} stroke={style.stroke} strokeWidth="1.6" />
                )}
                {lines.map((line, i) => (
                  <text key={i} x={n.x} y={n.y - ((lines.length - 1) * 7) + i * 14 + 4}
                        textAnchor="middle" fontSize="11" fill="#0f172a">{line}</text>
                ))}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
