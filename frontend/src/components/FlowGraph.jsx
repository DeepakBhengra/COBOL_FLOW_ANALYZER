import { useMemo } from "react";
import dagre from "@dagrejs/dagre";

const NODE_W = 170;
const NODE_H = 46;

const EDGE_STYLE = {
  PERFORM: { color: "#2563eb", width: 1.8, dash: "" },
  "PERFORM THRU": { color: "#2563eb", width: 3, dash: "" },
  "GO TO": { color: "#dc2626", width: 1.8, dash: "6 4" },
  "FALL-THROUGH": { color: "#94a3b8", width: 1.4, dash: "2 4" },
};

function nodeTone(node) {
  if (node.is_entry) return { fill: "#dcfce7", stroke: "#16a34a" };
  if (node.never_called) return { fill: "#fee2e2", stroke: "#dc2626" };
  if (node.call_count > 0) return { fill: "#dbeafe", stroke: "#2563eb" };
  return { fill: "#f1f5f9", stroke: "#94a3b8" };
}

/**
 * Lays out paragraphs left to right with dagre and draws them as SVG.
 * Parallel edges between the same pair are merged; a PERFORM or GO TO wins over fall-through.
 */
export default function FlowGraph({ graph, focus = null, showFallThrough = true, selected, onSelect }) {
  const layout = useMemo(() => {
    if (!graph) return null;
    let nodes = graph.nodes;
    let edges = graph.edges;

    if (focus) {
      const keep = new Set([focus]);
      edges.forEach((e) => {
        if (e.source === focus) keep.add(e.target);
        if (e.target === focus) keep.add(e.source);
      });
      nodes = nodes.filter((n) => keep.has(n.id));
      edges = edges.filter((e) => keep.has(e.source) && keep.has(e.target));
    }
    if (!showFallThrough) edges = edges.filter((e) => e.kind !== "FALL-THROUGH");

    const merged = new Map();
    edges.forEach((e) => {
      if (e.source === e.target) return;
      const key = `${e.source}->${e.target}`;
      const prior = merged.get(key);
      if (!prior || (prior.kind === "FALL-THROUGH" && e.kind !== "FALL-THROUGH")) merged.set(key, e);
    });

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 28, ranksep: 70, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H, node: n }));
    merged.forEach((e) => g.setEdge(e.source, e.target, { edge: e }));
    dagre.layout(g);

    const laidOut = g.nodes().map((id) => ({ id, ...g.node(id) }));
    const laidEdges = g.edges().map((ref) => ({ ...g.edge(ref), ref }));
    const { width, height } = g.graph();
    return { nodes: laidOut, edges: laidEdges, width: width || 400, height: height || 200 };
  }, [graph, focus, showFallThrough]);

  if (!layout) return null;

  return (
    <div className="flow-scroll">
      <svg width={layout.width} height={layout.height} className="flow-svg" role="img" aria-label="Paragraph flow graph">
        <defs>
          {Object.entries(EDGE_STYLE).map(([kind, s]) => (
            <marker key={kind} id={`arrow-${kind.replace(/\s/g, "-")}`} viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill={s.color} />
            </marker>
          ))}
        </defs>

        {layout.edges.map((e) => {
          const data = e.edge;
          const style = EDGE_STYLE[data.kind] || EDGE_STYLE.PERFORM;
          const pts = e.points || [];
          if (pts.length < 2) return null;
          const d = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
          const mid = pts[Math.floor(pts.length / 2)];
          const markerId = `arrow-${data.kind.replace(/\s/g, "-")}`;
          return (
            <g key={`${e.ref.v}-${e.ref.w}`}>
              <path d={d} fill="none" stroke={style.color} strokeWidth={style.width}
                strokeDasharray={style.dash} markerEnd={`url(#${markerId})`} />
              {data.conditional && (
                <g>
                  <title>{data.conditions}</title>
                  <circle cx={mid.x} cy={mid.y} r="8" fill="#fff" stroke={style.color} />
                  <text x={mid.x} y={mid.y + 4} textAnchor="middle" fontSize="11" fill={style.color}>?</text>
                </g>
              )}
            </g>
          );
        })}

        {layout.nodes.map((n) => {
          const node = n.node;
          const tone = nodeTone(node);
          const isSel = selected === node.id;
          return (
            <g key={n.id} transform={`translate(${n.x - NODE_W / 2}, ${n.y - NODE_H / 2})`}
              className="flow-node" onClick={() => onSelect?.(node.id)}>
              <rect width={NODE_W} height={NODE_H} rx="10" fill={tone.fill}
                stroke={isSel ? "#0f172a" : tone.stroke} strokeWidth={isSel ? 2.5 : 1.5}
                strokeDasharray={node.reachable ? "" : "5 4"} />
              <text x={NODE_W / 2} y={NODE_H / 2 - 3} textAnchor="middle" fontSize="12" fontWeight="600" fill="#0f172a">
                {n.id.length > 22 ? n.id.slice(0, 21) + "…" : n.id}
              </text>
              <text x={NODE_W / 2} y={NODE_H / 2 + 12} textAnchor="middle" fontSize="10" fill="#64748b">
                {node.status}
              </text>
              <title>{`${n.id}: ${node.status}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function FlowLegend() {
  return (
    <div className="legend">
      <span><i className="swatch" style={{ background: "#dcfce7", borderColor: "#16a34a" }} /> Entry point</span>
      <span><i className="swatch" style={{ background: "#dbeafe", borderColor: "#2563eb" }} /> Called</span>
      <span><i className="swatch" style={{ background: "#f1f5f9", borderColor: "#94a3b8" }} /> Fall-through only</span>
      <span><i className="swatch" style={{ background: "#fee2e2", borderColor: "#dc2626" }} /> Never called</span>
      <span><i className="swatch dashed" /> Unreachable</span>
      <span><i className="line" style={{ background: "#2563eb" }} /> PERFORM</span>
      <span><i className="line dashed" style={{ borderColor: "#dc2626" }} /> GO TO</span>
      <span><i className="line dotted" /> Fall-through</span>
      <span><b className="cond-q">?</b> Conditional</span>
    </div>
  );
}
