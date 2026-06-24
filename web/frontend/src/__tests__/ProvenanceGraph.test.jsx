import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ProvenanceGraph from '../components/ProvenanceGraph.jsx';

// Mock the API module
vi.mock('../services/api.js', () => ({
  visualImageUrl: vi.fn((caseId, path) => `/images/${caseId}/${path}`),
}));

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

function makeGraph(overrides = {}) {
  return {
    schema_version: '1.0',
    status: 'ran',
    nodes: [
      { id: 'fig1', label: 'Figure 1', image_path: 'visual/fig1.png', is_query: true },
      { id: 'fig2', label: 'Figure 2', image_path: 'visual/fig2.png', is_query: false },
      { id: 'fig3', label: 'Figure 3', image_path: 'visual/fig3.png', is_query: false },
      { id: 'fig4', label: 'Figure 4 - Extra Long Label Name', image_path: 'visual/fig4.png', is_query: false },
    ],
    edges: [
      { source: 'fig1', target: 'fig2', weight: 0.85, shared_area_source: 0.3, shared_area_target: 0.25, matched_keypoints: 120, is_flipped: false },
      { source: 'fig2', target: 'fig3', weight: 0.45, shared_area_source: 0.15, shared_area_target: 0.1, matched_keypoints: 50, is_flipped: false },
      { source: 'fig1', target: 'fig3', weight: 0.3, shared_area_source: 0.1, shared_area_target: 0.08, matched_keypoints: 30, is_flipped: true },
      { source: 'fig3', target: 'fig4', weight: 0.15, shared_area_source: 0.05, shared_area_target: 0.03, matched_keypoints: 20, is_flipped: false },
    ],
    spanning_tree_edges: [
      { source: 'fig1', target: 'fig2', weight: 0.85 },
      { source: 'fig2', target: 'fig3', weight: 0.45 },
      { source: 'fig3', target: 'fig4', weight: 0.15 },
    ],
    connected_components: [['fig1', 'fig2', 'fig3', 'fig4']],
    statistics: {
      node_count: 4,
      edge_count: 4,
      component_count: 1,
      max_weight: 0.85,
      mean_weight: 0.4375,
    },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProvenanceGraph', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when graph has no nodes', () => {
    const graph = { nodes: [], edges: [], spanning_tree_edges: [], statistics: {} };
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);
    expect(screen.getByText('无溯源图数据')).toBeInTheDocument();
  });

  it('renders empty state when graph is null', () => {
    render(<ProvenanceGraph graph={null} caseId="test-case" />);
    expect(screen.getByText('无溯源图数据')).toBeInTheDocument();
  });

  it('renders SVG with nodes when graph data is provided', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // SVG should be rendered
    expect(screen.getByTestId('provenance-svg')).toBeInTheDocument();

    // All 4 nodes should be rendered
    expect(screen.getByTestId('node-fig1')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig2')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig3')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig4')).toBeInTheDocument();
  });

  it('renders query badge on query nodes', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // fig1 is the query node, should have a Q badge text
    const queryNode = screen.getByTestId('node-fig1');
    expect(queryNode).toBeInTheDocument();

    // The Q text should be present within the SVG
    const qTexts = screen.getByTestId('provenance-svg').querySelectorAll('text');
    const qBadge = Array.from(qTexts).find((t) => t.textContent === 'Q');
    expect(qBadge).toBeTruthy();
  });

  it('truncates long labels', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // fig4 has label "Figure 4 - Extra Long Label Name" which should be truncated
    const svgEl = screen.getByTestId('provenance-svg');
    const texts = Array.from(svgEl.querySelectorAll('text'));
    // Find the label for fig4 node (the one that contains "Figure 4")
    const fig4Label = texts.find((t) => t.textContent?.includes('Figure 4'));
    expect(fig4Label).toBeTruthy();
    // The truncate function slices to maxLen-1 and appends the typographic ellipsis.
    expect(fig4Label.textContent.length).toBeLessThanOrEqual(16);
    expect(fig4Label.textContent).toContain('…');
    // Original label is 34 chars, truncated should be much shorter
    expect(fig4Label.textContent.length).toBeLessThan(34);
  });

  it('shows node detail panel when a node is clicked', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // Click on fig1 node
    const fig1Node = screen.getByTestId('node-fig1');
    fireEvent.click(fig1Node);

    // Detail panel should appear
    expect(screen.getByTestId('node-detail-panel')).toBeInTheDocument();

    // The h4 heading in the detail panel should show the label
    const detailPanel = screen.getByTestId('node-detail-panel');
    expect(detailPanel.querySelector('h4').textContent).toContain('Figure 1');

    // Query badge should appear in the detail panel
    expect(screen.getByText('Query')).toBeInTheDocument();
  });

  it('shows connected edges in detail panel when node is clicked', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // Click on fig2 (connected to fig1 and fig3)
    fireEvent.click(screen.getByTestId('node-fig2'));

    expect(screen.getByTestId('node-detail-panel')).toBeInTheDocument();
    // Connections header should show 2 edges
    expect(screen.getByText(/Connections \(2\)/)).toBeInTheDocument();
    // kpts values
    expect(screen.getByText(/120 kpts/)).toBeInTheDocument();
    expect(screen.getByText(/50 kpts/)).toBeInTheDocument();
  });

  it('closes detail panel when close button is clicked', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // Open detail
    fireEvent.click(screen.getByTestId('node-fig1'));
    expect(screen.getByTestId('node-detail-panel')).toBeInTheDocument();

    // Close it
    const closeButton = screen.getByLabelText('Close detail');
    fireEvent.click(closeButton);
    expect(screen.queryByTestId('node-detail-panel')).not.toBeInTheDocument();
  });

  it('toggles between All Edges and MST Only', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    const toggle = screen.getByTestId('spanning-toggle');
    expect(toggle.textContent).toBe('All Edges');

    fireEvent.click(toggle);
    expect(toggle.textContent).toBe('MST Only');

    fireEvent.click(toggle);
    expect(toggle.textContent).toBe('All Edges');
  });

  it('changes depth when slider is adjusted', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    const slider = screen.getByTestId('depth-slider');
    expect(slider.value).toBe('10'); // default is "All"

    // Change to depth 1 - should only show query node
    fireEvent.change(slider, { target: { value: '1' } });
    expect(slider.value).toBe('1');
  });

  it('filters nodes by depth when depth is reduced', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // All 4 nodes visible initially
    expect(screen.getByTestId('node-fig1')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig2')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig3')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig4')).toBeInTheDocument();

    // Reduce depth to 1 - only query node + direct neighbors should be visible
    const slider = screen.getByTestId('depth-slider');
    fireEvent.change(slider, { target: { value: '1' } });

    // fig1 is query (depth 0), fig2 and fig3 are depth 1 (connected to fig1)
    // fig4 is depth 2 (connected to fig3 only), so should be hidden
    expect(screen.getByTestId('node-fig1')).toBeInTheDocument();
    expect(screen.queryByTestId('node-fig4')).not.toBeInTheDocument();
  });

  it('shows image preview in detail panel when node has image_path', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    fireEvent.click(screen.getByTestId('node-fig1'));

    const img = screen.getByAltText('Figure 1');
    expect(img).toBeInTheDocument();
    expect(img.src).toContain('/images/test-case/visual/fig1.png');
  });

  it('renders with graph that has no spanning tree edges', () => {
    const graph = makeGraph({ spanning_tree_edges: [] });
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    expect(screen.getByTestId('provenance-svg')).toBeInTheDocument();
    // All nodes should still render
    expect(screen.getByTestId('node-fig1')).toBeInTheDocument();
  });

  it('renders with empty edges', () => {
    const graph = {
      nodes: [
        { id: 'fig1', label: 'Figure 1', image_path: 'visual/fig1.png', is_query: true },
      ],
      edges: [],
      spanning_tree_edges: [],
      statistics: { node_count: 1, edge_count: 0 },
    };
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // Should render but no edges
    expect(screen.getByTestId('provenance-svg')).toBeInTheDocument();
    expect(screen.getByTestId('node-fig1')).toBeInTheDocument();
  });

  it('displays flipped badge in edge details', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // fig3 has a flipped edge from fig1
    fireEvent.click(screen.getByTestId('node-fig3'));

    // The flipped edge from fig1 should show "flipped"
    expect(screen.getByText('flipped')).toBeInTheDocument();
  });

  it('displays MST badge on spanning edges in detail panel', () => {
    const graph = makeGraph();
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // Click fig1 - it has MST edge to fig2
    fireEvent.click(screen.getByTestId('node-fig1'));

    // MST badge should appear
    expect(screen.getByText('MST')).toBeInTheDocument();
  });

  it('shows statistics info', () => {
    const graph = makeGraph({
      statistics: {
        node_count: 4,
        edge_count: 4,
        component_count: 2,
        max_weight: 0.85,
        mean_weight: 0.4,
      },
      processing_time_seconds: 3.5,
    });
    render(<ProvenanceGraph graph={graph} caseId="test-case" />);

    // Stats bar should show component count
    expect(screen.getByText(/2 components/)).toBeInTheDocument();
  });
});
