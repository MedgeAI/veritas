import { useCallback, useId, useMemo, useRef, useState } from 'react';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force';
import { visualImageUrl } from '../services/api.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONFIG = {
  NODE_RADIUS_QUERY: 22,
  NODE_RADIUS_DEFAULT: 16,
  COLLISION_RADIUS: 30,
  CHARGE_STRENGTH: -250,
  LINK_DISTANCE_BASE: 100,
  TICKS: 120,
  PADDING: 50,
  EDGE_MIN_WIDTH: 1.5,
  EDGE_MAX_WIDTH: 6,
  MAX_DEPTH: 10,
  DEPTH_SHOW_ALL: 10,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * BFS depth from query nodes through all edges.
 */
function computeNodeDepths(nodes, edges, queryIds) {
  const depths = new Map();
  if (!nodes.length || !queryIds.length) return depths;

  const adjacency = new Map();
  for (const e of edges) {
    if (!adjacency.has(e.source)) adjacency.set(e.source, []);
    if (!adjacency.has(e.target)) adjacency.set(e.target, []);
    adjacency.get(e.source).push(e.target);
    adjacency.get(e.target).push(e.source);
  }

  const queue = [];
  for (const qid of queryIds) {
    depths.set(qid, 0);
    queue.push(qid);
  }

  while (queue.length > 0) {
    const current = queue.shift();
    const d = depths.get(current);
    for (const neighbor of adjacency.get(current) || []) {
      if (!depths.has(neighbor)) {
        depths.set(neighbor, d + 1);
        queue.push(neighbor);
      }
    }
  }
  return depths;
}

/**
 * Build a Set of spanning edge keys for O(1) lookup.
 */
function buildSpanningSet(spanningTreeEdges) {
  const set = new Set();
  for (const e of spanningTreeEdges || []) {
    const key = [e.source, e.target].sort().join('|');
    set.add(key);
  }
  return set;
}

/**
 * Compute similarity color: green(high) -> amber(mid) -> gray(low).
 */
function weightColor(weight, maxWeight) {
  const ratio = maxWeight > 0 ? weight / maxWeight : 0;
  if (ratio >= 0.7) return '#10b981';
  if (ratio >= 0.4) return '#f59e0b';
  return '#94a3b8';
}

/**
 * Compute edge stroke width from weight.
 */
function edgeWidth(weight, maxWeight) {
  const ratio = maxWeight > 0 ? weight / maxWeight : 0;
  return CONFIG.EDGE_MIN_WIDTH + ratio * (CONFIG.EDGE_MAX_WIDTH - CONFIG.EDGE_MIN_WIDTH);
}

/**
 * Truncate a label to maxLen characters.
 */
function truncate(text, maxLen = 14) {
  if (!text) return '';
  return text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text;
}

// ---------------------------------------------------------------------------
// ProvenanceGraph Component
// ---------------------------------------------------------------------------

/**
 * Recursive provenance graph visualization using d3-force layout.
 *
 * Nodes are figures, edges represent shared content detected by RootSIFT matching.
 * Spanning tree edges (MST) are highlighted. Nodes can be filtered by BFS depth
 * from query nodes.
 *
 * @param {object} props
 * @param {object} props.graph - Provenance graph data from provenance_graph.json
 * @param {string} props.caseId - Case ID for image URL resolution
 * @param {number} [props.width=600] - SVG width
 * @param {number} [props.height=450] - SVG height
 */
export default function ProvenanceGraph({
  graph,
  caseId,
  width = 600,
  height = 450,
}) {
  const depthSliderId = useId();
  const svgRef = useRef(null);
  const [maxDepth, setMaxDepth] = useState(CONFIG.DEPTH_SHOW_ALL);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [showSpanningOnly, setShowSpanningOnly] = useState(false);

  const nodes = useMemo(() => graph?.nodes || [], [graph]);
  const edges = useMemo(() => graph?.edges || [], [graph]);
  const spanningTreeEdges = useMemo(() => graph?.spanning_tree_edges || [], [graph]);
  const statistics = useMemo(() => graph?.statistics || {}, [graph]);

  // Identify query node IDs
  const queryIds = useMemo(
    () => nodes.filter((n) => n.is_query).map((n) => n.id),
    [nodes],
  );

  // BFS depths from query nodes
  const nodeDepths = useMemo(
    () => computeNodeDepths(nodes, edges, queryIds),
    [nodes, edges, queryIds],
  );

  // Spanning edge lookup set
  const spanningSet = useMemo(
    () => buildSpanningSet(spanningTreeEdges),
    [spanningTreeEdges],
  );

  // Max weight for normalization
  const maxWeight = useMemo(
    () => statistics.max_weight || Math.max(...edges.map((e) => e.weight || 0), 0.001),
    [edges, statistics],
  );

  // Filter nodes by depth
  const effectiveDepth = maxDepth >= CONFIG.DEPTH_SHOW_ALL ? Infinity : maxDepth;
  const visibleNodeIds = useMemo(() => {
    const set = new Set();
    for (const n of nodes) {
      if (n.is_query) { set.add(n.id); continue; }
      const d = nodeDepths.get(n.id);
      if (d !== undefined && d <= effectiveDepth) set.add(n.id);
    }
    return set;
  }, [nodes, nodeDepths, effectiveDepth]);

  // Compute connected nodes (nodes that have at least one edge)
  const connectedIds = useMemo(() => {
    const set = new Set();
    for (const e of edges) {
      set.add(e.source);
      set.add(e.target);
    }
    return set;
  }, [edges]);

  // Filter visible + connected
  const displayNodeIds = useMemo(() => {
    const set = new Set();
    for (const id of visibleNodeIds) {
      if (connectedIds.has(id) || nodes.find((n) => n.id === id && n.is_query)) {
        set.add(id);
      }
    }
    return set;
  }, [visibleNodeIds, connectedIds, nodes]);

  // Compute force layout
  const { layoutNodes, layoutLinks } = useMemo(() => {
    if (!displayNodeIds.size) return { layoutNodes: [], layoutLinks: [] };

    const simNodes = nodes
      .filter((n) => displayNodeIds.has(n.id))
      .map((n) => ({
        ...n,
        depth: nodeDepths.get(n.id) ?? 0,
      }));

    const simLinks = edges
      .filter((e) => displayNodeIds.has(e.source) && displayNodeIds.has(e.target))
      .map((e) => {
        const key = [e.source, e.target].sort().join('|');
        return {
          source: e.source,
          target: e.target,
          weight: e.weight || 0,
          matched_keypoints: e.matched_keypoints || 0,
          shared_area_source: e.shared_area_source || 0,
          shared_area_target: e.shared_area_target || 0,
          is_flipped: e.is_flipped || false,
          isSpanning: spanningSet.has(key),
          _raw: e,
        };
      });

    // Run simulation synchronously
    const sim = forceSimulation(simNodes)
      .force('link', forceLink(simLinks).id((d) => d.id).distance(CONFIG.LINK_DISTANCE_BASE))
      .force('charge', forceManyBody().strength(CONFIG.CHARGE_STRENGTH))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collision', forceCollide(CONFIG.COLLISION_RADIUS))
      .stop();

    const ticks = Math.min(CONFIG.TICKS, 30 + simNodes.length * 3 + simLinks.length);
    for (let i = 0; i < ticks; i++) sim.tick();

    // Scale to fit
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of simNodes) {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    }
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const scale = Math.min((width - 2 * CONFIG.PADDING) / rangeX, (height - 2 * CONFIG.PADDING) / rangeY);
    const offsetX = (width - rangeX * scale) / 2;
    const offsetY = (height - rangeY * scale) / 2;

    for (const n of simNodes) {
      n.x = (n.x - minX) * scale + offsetX;
      n.y = (n.y - minY) * scale + offsetY;
    }

    return { layoutNodes: simNodes, layoutLinks: simLinks };
  }, [displayNodeIds, nodes, edges, spanningSet, nodeDepths, width, height]);

  // Node lookup for edge rendering
  const nodeById = useMemo(
    () => new Map(layoutNodes.map((n) => [n.id, n])),
    [layoutNodes],
  );

  // Edges connected to selected node
  const selectedEdges = useMemo(() => {
    if (!selectedNode) return [];
    return layoutLinks.filter(
      (l) => (typeof l.source === 'object' ? l.source.id : l.source) === selectedNode.id ||
             (typeof l.target === 'object' ? l.target.id : l.target) === selectedNode.id,
    );
  }, [selectedNode, layoutLinks]);

  const totalVisibleNodes = layoutNodes.length;
  const totalVisibleEdges = layoutLinks.filter((l) => showSpanningOnly ? l.isSpanning : true).length;

  const handleNodeClick = useCallback((node) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  const handleCloseDetail = useCallback(() => setSelectedNode(null), []);

  const handleToggleSpanning = useCallback(() => setShowSpanningOnly((v) => !v), []);

  // Empty state
  if (!nodes.length) {
    return (
      <div className="flex items-center justify-center h-48 text-ink-500 text-sm">
        无溯源图数据
      </div>
    );
  }

  return (
    <div className="relative" data-testid="provenance-graph">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-4 mb-3">
        {/* Depth slider */}
        <div className="flex items-center gap-2">
          <label htmlFor={depthSliderId} className="text-xs text-ink-500">BFS Depth:</label>
          <input
            id={depthSliderId}
            name="provenance_depth"
            type="range"
            min={1}
            max={CONFIG.DEPTH_SHOW_ALL}
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value))}
            aria-valuetext={maxDepth >= CONFIG.DEPTH_SHOW_ALL ? 'All' : `${maxDepth}`}
            className="w-24 accent-emerald-600"
            data-testid="depth-slider"
          />
          <span className="text-xs font-mono text-ink-700 w-8">
            {maxDepth >= CONFIG.DEPTH_SHOW_ALL ? 'All' : maxDepth}
          </span>
        </div>

        {/* Spanning-only toggle */}
        <button
          type="button"
          onClick={handleToggleSpanning}
          className={`rounded-lg px-3 py-1 text-xs transition ${
            showSpanningOnly
              ? 'bg-emerald-600 text-white'
              : 'bg-ink-900/5 text-ink-700 hover:bg-ink-900/10'
          }`}
          data-testid="spanning-toggle"
        >
          {showSpanningOnly ? 'MST Only' : 'All Edges'}
        </button>

        {/* Stats */}
        <span className="text-xs text-ink-500">
          {totalVisibleNodes} nodes / {totalVisibleEdges} edges
          {statistics.component_count > 1 && ` / ${statistics.component_count} components`}
        </span>
      </div>

      {/* SVG Graph */}
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${height}`}
          className="w-full bg-paper-100 rounded-xl border border-ink-900/10"
          style={{ height: Math.max(300, height * 0.65) }}
          role="img"
          aria-label="Evidence provenance graph"
          data-testid="provenance-svg"
        >
          {/* Edges */}
          <g className="edges">
            {layoutLinks.map((link) => {
              if (showSpanningOnly && !link.isSpanning) return null;
              const src = nodeById.get(typeof link.source === 'object' ? link.source.id : link.source);
              const tgt = nodeById.get(typeof link.target === 'object' ? link.target.id : link.target);
              if (!src || !tgt) return null;

              const key = `${src.id}--${tgt.id}`;
              const midX = (src.x + tgt.x) / 2;
              const midY = (src.y + tgt.y) / 2;
              const isSelected = selectedNode && (
                src.id === selectedNode.id || tgt.id === selectedNode.id
              );

              return (
                <g key={key}>
                  <line
                    x1={src.x}
                    y1={src.y}
                    x2={tgt.x}
                    y2={tgt.y}
                    stroke={isSelected ? '#10b981' : weightColor(link.weight, maxWeight)}
                    strokeWidth={link.isSpanning ? edgeWidth(link.weight, maxWeight) : edgeWidth(link.weight, maxWeight) * 0.6}
                    strokeOpacity={link.isSpanning ? 0.85 : 0.4}
                    strokeDasharray={link.isSpanning ? undefined : '4,3'}
                  />
                  {/* Weight label on spanning edges */}
                  {link.isSpanning && (
                    <text
                      x={midX}
                      y={midY - 5}
                      textAnchor="middle"
                      className="text-[8px] fill-ink-500 pointer-events-none select-none"
                    >
                      {link.weight.toFixed(2)}
                    </text>
                  )}
                </g>
              );
            })}
          </g>

          {/* Nodes */}
          <g className="nodes">
            {layoutNodes.map((node) => {
              const r = node.is_query ? CONFIG.NODE_RADIUS_QUERY : CONFIG.NODE_RADIUS_DEFAULT;
              const isHovered = hoveredNode?.id === node.id;
              const isSelected = selectedNode?.id === node.id;
              const displayLabel = truncate(node.label || node.id);

              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x},${node.y})`}
                  onClick={() => handleNodeClick(node)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleNodeClick(node); } }}
                  role="button"
                  tabIndex={0}
                  aria-label={`查看 ${node.label || node.id} 的溯源连接详情`}
                  onMouseEnter={() => setHoveredNode(node)}
                  onMouseLeave={() => setHoveredNode(null)}
                  className="cursor-pointer focus-visible:[filter:drop-shadow(0_0_0.35rem_rgba(34,120,99,0.72))]"
                  data-testid={`node-${node.id}`}
                >
                  {/* Node circle */}
                  <circle
                    r={isHovered ? r + 3 : r}
                    fill={node.is_query ? '#10b981' : '#6366f1'}
                    stroke={isSelected ? '#059669' : node.is_query ? '#059669' : '#818cf8'}
                    strokeWidth={isSelected ? 3 : 2}
                    className="transition-[r,stroke-width,fill] duration-150"
                  />
                  {/* Query badge */}
                  {node.is_query && (
                    <>
                      <circle r={7} cx={r * 0.7} cy={-r * 0.7} fill="#059669" stroke="#fff" strokeWidth={1.5} />
                      <text
                        x={r * 0.7}
                        y={-r * 0.7 + 3.5}
                        textAnchor="middle"
                        className="text-[8px] fill-white font-bold pointer-events-none select-none"
                      >
                        Q
                      </text>
                    </>
                  )}
                  {/* Label */}
                  <text
                    y={r + 14}
                    textAnchor="middle"
                    className="text-[8px] fill-ink-500 pointer-events-none select-none"
                  >
                    {displayLabel}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {/* Hover tooltip */}
        {hoveredNode && !selectedNode && (
          <div className="absolute top-2 left-2 text-xs bg-white/95 border border-ink-900/10 shadow-sm rounded-lg px-3 py-2 pointer-events-none max-w-[240px]">
            <div className="font-medium text-ink-700 truncate">{hoveredNode.label || hoveredNode.id}</div>
            <div className="text-ink-500 text-[10px] mt-0.5">{hoveredNode.id}</div>
            {hoveredNode.depth !== undefined && (
              <div className="text-ink-500 text-[10px]">Depth: {hoveredNode.depth}</div>
            )}
          </div>
        )}

        {/* Legend */}
        <div className="absolute bottom-2 left-2 flex flex-col gap-1 bg-white/90 rounded-lg px-2 py-1.5 text-[10px] shadow-sm border border-ink-900/5">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-emerald-500 border border-emerald-700" />
            <span className="text-ink-500">Query Figure</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-indigo-500 border border-indigo-400" />
            <span className="text-ink-500">Matched Figure</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-0.5 bg-ink-500 rounded" />
            <span className="text-ink-500">MST Edge</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-0.5 bg-ink-300 rounded" style={{ borderTop: '1px dashed #cbd5e1' }} />
            <span className="text-ink-500">Non-MST Edge</span>
          </div>
        </div>
      </div>

      {/* Node Detail Panel */}
      {selectedNode && (
        <div
          className="mt-3 rounded-xl border border-ink-900/10 bg-white p-4"
          data-testid="node-detail-panel"
        >
          <div className="flex items-start justify-between">
            <div>
              <h4 className="text-sm font-semibold text-ink-700">
                {selectedNode.label || selectedNode.id}
                {selectedNode.is_query && (
                  <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] text-emerald-700">
                    Query
                  </span>
                )}
              </h4>
              <p className="text-xs text-ink-500 mt-0.5 font-mono">{selectedNode.id}</p>
            </div>
            <button
              type="button"
              onClick={handleCloseDetail}
              className="text-ink-500 hover:text-ink-700 text-sm"
              aria-label="Close detail"
            >
              &times;
            </button>
          </div>

          {/* Image preview */}
          {selectedNode.image_path && caseId && (
            <div className="mt-3">
              <img
                src={visualImageUrl(caseId, selectedNode.image_path)}
                alt={selectedNode.label || selectedNode.id}
                className="max-h-40 rounded-lg border border-ink-900/10"
                loading="lazy"
                width="320"
                height="160"
              />
            </div>
          )}

          {/* Connected edges */}
          {selectedEdges.length > 0 && (
            <div className="mt-3">
              <h5 className="text-xs font-medium text-ink-500 mb-1">
                Connections ({selectedEdges.length})
              </h5>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {selectedEdges.map((edge) => {
                  const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
                  const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
                  const otherId = srcId === selectedNode.id ? tgtId : srcId;
                  const otherNode = nodeById.get(otherId);
                  return (
                    <div
                      key={`${srcId}--${tgtId}`}
                      className="flex items-center justify-between rounded-lg bg-paper-100 px-2 py-1 text-xs"
                    >
                      <span className="font-mono text-ink-700 truncate">
                        {truncate(otherNode?.label || otherId, 20)}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-ink-500">
                          {edge.matched_keypoints} kpts
                        </span>
                        <span
                          className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                          style={{
                            backgroundColor: weightColor(edge.weight, maxWeight) + '22',
                            color: weightColor(edge.weight, maxWeight),
                          }}
                        >
                          {edge.weight.toFixed(3)}
                        </span>
                        {edge.is_flipped && (
                          <span className="text-[10px] text-amber-600">flipped</span>
                        )}
                        {edge.isSpanning && (
                          <span className="text-[10px] text-emerald-600">MST</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Shared area info */}
          {selectedEdges.length > 0 && (
            <div className="mt-2 text-[10px] text-ink-500">
              Shared area: source avg{' '}
              {(selectedEdges.reduce((s, e) => s + (e.shared_area_source || 0), 0) / selectedEdges.length).toFixed(3)}
              {' / '}target avg{' '}
              {(selectedEdges.reduce((s, e) => s + (e.shared_area_target || 0), 0) / selectedEdges.length).toFixed(3)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
