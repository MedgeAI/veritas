import { useMemo } from 'react';

/**
 * Simple SVG-based overlap graph showing panels as nodes and overlap relationships as edges.
 * Uses a force-directed-like layout based on relationship scores.
 *
 * @param {object} props
 * @param {Array} props.relationships - overlap_reuse relationships
 * @param {Array} props.panels - panel evidence list
 * @param {Function} props.onSelectRelationship - callback when edge is clicked
 */
export default function OverlapGraph({ relationships = [], panels = [], onSelectRelationship }) {
  const { nodes, edges } = useMemo(() => {
    const panelMap = new Map();
    for (const p of panels) {
      if (p?.panel_id) panelMap.set(p.panel_id, p);
    }

    const panelIds = new Set();
    const edgeList = [];

    for (const rel of relationships) {
      if (!rel?.source_panel_id || !rel?.target_panel_id) continue;
      panelIds.add(rel.source_panel_id);
      panelIds.add(rel.target_panel_id);
      edgeList.push({
        source: rel.source_panel_id,
        target: rel.target_panel_id,
        score: rel.score || 0,
        relationship_id: rel.relationship_id,
        overlap_src: rel.overlap_area_ratio_source || 0,
        overlap_tgt: rel.overlap_area_ratio_target || 0,
        _relationship: rel,
      });
    }

    // Simple circular layout
    const nodeArr = Array.from(panelIds);
    const cx = 200, cy = 150, radius = 120;
    const nodePositions = new Map();
    nodeArr.forEach((id, i) => {
      const angle = (2 * Math.PI * i) / Math.max(1, nodeArr.length) - Math.PI / 2;
      nodePositions.set(id, {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        label: id.length > 16 ? id.slice(0, 14) + '…' : id,
      });
    });

    return { nodes: nodeArr.map(id => ({ id, ...nodePositions.get(id) })), edges: edgeList };
  }, [relationships, panels]);

  if (!relationships.length) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        无 overlap 关系可展示
      </div>
    );
  }

  const scoreColor = (score) => {
    if (score >= 0.7) return '#ef4444';
    if (score >= 0.4) return '#f59e0b';
    return '#6b7280';
  };

  return (
    <div className="relative">
      <svg viewBox="0 0 400 300" className="w-full h-64 bg-gray-50 rounded-lg border border-gray-200">
        {/* Edges */}
        {edges.map((edge, i) => {
          const src = nodes.find(n => n.id === edge.source);
          const tgt = nodes.find(n => n.id === edge.target);
          if (!src || !tgt) return null;
          return (
            <g key={i} onClick={() => onSelectRelationship?.(edge._relationship || edge)} className="cursor-pointer">
              <line
                x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                stroke={scoreColor(edge.score)}
                strokeWidth={Math.max(1, edge.score * 4)}
                strokeOpacity={0.7}
              />
              <text
                x={(src.x + tgt.x) / 2}
                y={(src.y + tgt.y) / 2 - 4}
                textAnchor="middle"
                className="text-[8px] fill-gray-600"
              >
                {edge.score.toFixed(2)}
              </text>
            </g>
          );
        })}
        {/* Nodes */}
        {nodes.map((node) => (
          <g key={node.id}>
            <circle cx={node.x} cy={node.y} r={8} fill="#3b82f6" stroke="#1d4ed8" strokeWidth={1.5} />
            <text
              x={node.x}
              y={node.y + 20}
              textAnchor="middle"
              className="text-[7px] fill-gray-700"
            >
              {node.label}
            </text>
          </g>
        ))}
      </svg>
      <div className="absolute top-2 right-2 text-xs text-gray-500 bg-white/80 px-2 py-1 rounded">
        {nodes.length} panels · {edges.length} overlap edges
      </div>
    </div>
  );
}
