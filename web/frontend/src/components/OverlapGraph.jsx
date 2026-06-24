import { useMemo, useState } from 'react';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force';

/**
 * SVG-based overlap graph using d3-force for layout.
 * Panels are nodes, overlap relationships are edges.
 *
 * @param {object} props
 * @param {Array} props.relationships - overlap_reuse relationships
 * @param {Array} props.panels - panel evidence list
 * @param {Function} props.onSelectRelationship - callback when edge is clicked
 * @param {number} [props.width=500] - SVG width
 * @param {number} [props.height=400] - SVG height
 */
export default function OverlapGraph({
  relationships = [],
  panels = [],
  onSelectRelationship,
  width = 500,
  height = 400,
}) {
  const [hoveredNode, setHoveredNode] = useState(null);

  const { nodes, links, nodeById, nodeRadius, nodeDegree, maxDegree } = useMemo(() => {
    if (!relationships.length || !panels.length) {
      return {
        nodes: [],
        links: [],
        nodeById: new Map(),
        nodeRadius: new Map(),
        nodeDegree: new Map(),
        maxDegree: 1,
      };
    }

    // Collect panel ids that participate in relationships
    const panelIds = new Set();
    const linkList = [];

    for (const rel of relationships) {
      if (!rel?.source_panel_id || !rel?.target_panel_id) continue;
      panelIds.add(rel.source_panel_id);
      panelIds.add(rel.target_panel_id);
      linkList.push({
        source: rel.source_panel_id,
        target: rel.target_panel_id,
        score: rel.score || 0,
        relationship_id: rel.relationship_id,
        overlap_src: rel.overlap_area_ratio_source || 0,
        overlap_tgt: rel.overlap_area_ratio_target || 0,
        _relationship: rel,
      });
    }

    // Build simulation nodes with original panel data
    const panelMap = new Map();
    for (const p of panels) {
      if (p?.panel_id) panelMap.set(p.panel_id, p);
    }

    const simNodes = Array.from(panelIds).map((id) => {
      const panel = panelMap.get(id);
      return {
        id,
        label: panel?.label || id,
        ...panel,
      };
    });

    if (simNodes.length > 80 || linkList.length > 200) {
      const cx = width / 2;
      const cy = height / 2;
      const radius = Math.max(80, Math.min(width, height) / 2 - 45);
      simNodes.forEach((node, index) => {
        const angle = (2 * Math.PI * index) / Math.max(1, simNodes.length) - Math.PI / 2;
        node.x = cx + radius * Math.cos(angle);
        node.y = cy + radius * Math.sin(angle);
      });
    } else {
      // Keep the force layout bounded; this runs on the main thread during render.
      const simulation = forceSimulation(simNodes)
        .force(
          'link',
          forceLink(linkList)
            .id((d) => d.id)
            .distance(120)
        )
        .force('charge', forceManyBody().strength(-200))
        .force('center', forceCenter(width / 2, height / 2))
        .force('collision', forceCollide(30))
        .stop();

      const ticks = Math.min(120, 30 + simNodes.length * 2 + linkList.length);
      for (let i = 0; i < ticks; i += 1) simulation.tick();
    }

    // Scale positions to fit within bounds with padding
    const padding = 40;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of simNodes) {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    }

    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const scaleX = (width - 2 * padding) / rangeX;
    const scaleY = (height - 2 * padding) / rangeY;
    const scale = Math.min(scaleX, scaleY);

    const offsetX = (width - rangeX * scale) / 2;
    const offsetY = (height - rangeY * scale) / 2;

    for (const n of simNodes) {
      n.x = (n.x - minX) * scale + offsetX;
      n.y = (n.y - minY) * scale + offsetY;
    }

    // Build lookup map for O(1) edge coordinate resolution
    const nodeByIdMap = new Map(simNodes.map((n) => [n.id, n]));

    // Compute relationship count per node for sizing
    const degreeMap = new Map();
    for (const n of simNodes) degreeMap.set(n.id, 0);
    for (const l of linkList) {
      const sid = typeof l.source === 'object' ? l.source.id : l.source;
      const tid = typeof l.target === 'object' ? l.target.id : l.target;
      degreeMap.set(sid, (degreeMap.get(sid) || 0) + 1);
      degreeMap.set(tid, (degreeMap.get(tid) || 0) + 1);
    }

    const maxDegree = Math.max(1, ...degreeMap.values());
    const radiusMap = new Map();
    for (const n of simNodes) {
      const degree = degreeMap.get(n.id) || 0;
      radiusMap.set(n.id, 6 + (degree / maxDegree) * 8);
    }

    return {
      nodes: simNodes,
      links: linkList,
      nodeById: nodeByIdMap,
      nodeRadius: radiusMap,
      nodeDegree: degreeMap,
      maxDegree,
    };
  }, [relationships, panels, width, height]);

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

  const nodeColor = (degree) => {
    const t = degree / Math.max(1, maxDegree);
    // Interpolate from light blue (#93c5fd) to deep blue (#1d4ed8)
    const r = Math.round(147 - t * 118);
    const g = Math.round(197 - t * 119);
    const b = Math.round(253 - t * 39);
    return `rgb(${r},${g},${b})`;
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full bg-gray-50 rounded-lg border border-gray-200"
        style={{ height: Math.max(256, height * 0.6) }}
        role="img"
        aria-label="Overlap relationship graph"
      >
        {/* Edges */}
        {links.map((link) => {
          const src = nodeById.get(
            typeof link.source === 'object' ? link.source.id : link.source
          );
          const tgt = nodeById.get(
            typeof link.target === 'object' ? link.target.id : link.target
          );
          if (!src || !tgt) return null;

          const key = link.relationship_id || `${src.id}--${tgt.id}`;
          const midX = (src.x + tgt.x) / 2;
          const midY = (src.y + tgt.y) / 2;

          return (
            <g
              key={key}
              onClick={() => onSelectRelationship?.(link._relationship || link)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelectRelationship?.(link._relationship || link); } }}
              role="button"
              tabIndex={0}
              aria-label={`查看 ${src.label || src.id} 与 ${tgt.label || tgt.id} 的 overlap 关系，score ${link.score.toFixed(2)}`}
              className="cursor-pointer focus-visible:[filter:drop-shadow(0_0_0.35rem_rgba(34,120,99,0.72))]"
            >
              <line
                x1={src.x}
                y1={src.y}
                x2={tgt.x}
                y2={tgt.y}
                stroke={scoreColor(link.score)}
                strokeWidth={Math.max(1, link.score * 4)}
                strokeOpacity={0.7}
              />
              <text
                x={midX}
                y={midY - 4}
                textAnchor="middle"
                className="text-[8px] fill-gray-600 pointer-events-none select-none"
              >
                {link.score.toFixed(2)}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const r = nodeRadius.get(node.id) || 8;
          const degree = nodeDegree.get(node.id) || 0;
          const displayLabel =
            node.label.length > 16 ? node.label.slice(0, 14) + '…' : node.label;

          return (
            <g
              key={node.id}
              onMouseEnter={() => setHoveredNode(node)}
              onMouseLeave={() => setHoveredNode(null)}
              tabIndex={0}
              aria-label={`Panel ${node.label || node.id}`}
              role="img"
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={r}
                fill={nodeColor(degree)}
                stroke="#1d4ed8"
                strokeWidth={1.5}
                className="transition-[r,stroke-width] duration-150"
              />
              <text
                x={node.x}
                y={node.y + r + 12}
                textAnchor="middle"
                className="text-[7px] fill-gray-700 pointer-events-none select-none"
              >
                {displayLabel}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hoveredNode && (
        <div role="tooltip" className="absolute top-2 left-2 text-xs bg-white/95 border border-gray-200 shadow-sm rounded px-2 py-1 pointer-events-none max-w-[200px]">
          <div className="font-medium text-gray-800 truncate">{hoveredNode.label}</div>
          <div className="text-gray-500 text-[10px]">{hoveredNode.id}</div>
        </div>
      )}

      {/* Stats badge */}
      <div className="absolute top-2 right-2 text-xs text-gray-500 bg-white/80 px-2 py-1 rounded">
        {nodes.length} panels · {links.length} overlap edges
      </div>
    </div>
  );
}
