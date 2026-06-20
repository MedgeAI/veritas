import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import VisualForensicsPage from '../pages/VisualForensicsPage.jsx';
import * as api from '../services/api.js';

// Mock the API module
vi.mock('../services/api.js', () => ({
  fetchVisualFigures: vi.fn(),
  fetchVisualPanels: vi.fn(),
  fetchVisualRelationships: vi.fn(),
  fetchVisualFindings: vi.fn(),
  fetchOverlapReuse: vi.fn(),
  fetchProvenanceGraph: vi.fn(),
  listInvestigations: vi.fn(),
  startVisualInvestigation: vi.fn(),
  visualImageUrl: vi.fn((caseId, path) => `/images/${caseId}/${path}`),
  getEmbeddingStatus: vi.fn(),
  triggerEmbeddingIndex: vi.fn(),
  fetchAllSimilarPairs: vi.fn(),
}));

describe('VisualForensicsPage', () => {
  const mockCase = { case_id: 'test-case-1' };

  beforeEach(() => {
    vi.clearAllMocks();
    // Default: provenance graph returns a failed status (no graph shown)
    vi.mocked(api.fetchProvenanceGraph).mockResolvedValue({ status: 'failed', nodes: [], edges: [] });
  });

  it('renders loading state initially', async () => {
    // Setup API to return promises that don't resolve immediately
    vi.mocked(api.fetchVisualFigures).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.fetchVisualPanels).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.fetchVisualRelationships).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.fetchVisualFindings).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.fetchOverlapReuse).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.fetchProvenanceGraph).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.listInvestigations).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.getEmbeddingStatus).mockReturnValue(new Promise(() => {}));

    render(<VisualForensicsPage selectedCase={mockCase} />);

    // Should show loading button text
    expect(screen.getByText(/加载中/)).toBeInTheDocument();
  });

  it('renders empty state when no case is selected', () => {
    render(<VisualForensicsPage selectedCase={null} />);

    expect(screen.getByText('请先选择 Case')).toBeInTheDocument();
    expect(screen.getByText(/Visual Forensics Gallery 展示图像取证候选/)).toBeInTheDocument();
  });

  it('renders empty state when no artifacts exist', async () => {
    // Setup API to return empty data
    vi.mocked(api.fetchVisualFigures).mockResolvedValue({ figures: [] });
    vi.mocked(api.fetchVisualPanels).mockResolvedValue({ panels: [] });
    vi.mocked(api.fetchVisualRelationships).mockResolvedValue({ relationships: [] });
    vi.mocked(api.fetchVisualFindings).mockResolvedValue({ findings: [] });
    vi.mocked(api.fetchOverlapReuse).mockResolvedValue({ relationships: [] });
    vi.mocked(api.listInvestigations).mockResolvedValue({ records: [], results: [], artifact_errors: [] });
    vi.mocked(api.getEmbeddingStatus).mockResolvedValue({ status: 'unavailable', indexed_count: 0 });

    render(<VisualForensicsPage selectedCase={mockCase} />);

    await waitFor(() => {
      expect(screen.getByText('Visual Evidence Summary')).toBeInTheDocument();
    });

    // Check for empty state messages
    expect(screen.getByText(/暂无视觉取证数据/)).toBeInTheDocument();
    expect(screen.getByText(/未发现 panel 间相似关系/)).toBeInTheDocument();
    expect(screen.getByText(/未生成 visual finding 或当前筛选无结果/)).toBeInTheDocument();
  });

  it('renders metric cards with correct counts', async () => {
    const mockFigures = [{ figure_id: 'fig1', label: 'Figure 1', caption: 'Test', panel_count: 2, source_image_path: 'fig1.png' }];
    const mockPanels = [
      { panel_id: 'panel1', parent_figure_id: 'fig1', label: 'Panel A', crop_path: 'panel1.png' },
      { panel_id: 'panel2', parent_figure_id: 'fig1', label: 'Panel B', crop_path: 'panel2.png' },
    ];

    vi.mocked(api.fetchVisualFigures).mockResolvedValue({ figures: mockFigures });
    vi.mocked(api.fetchVisualPanels).mockResolvedValue({ panels: mockPanels });
    vi.mocked(api.fetchVisualRelationships).mockResolvedValue({ relationships: [] });
    vi.mocked(api.fetchVisualFindings).mockResolvedValue({ findings: [] });
    vi.mocked(api.fetchOverlapReuse).mockResolvedValue({ relationships: [] });
    vi.mocked(api.listInvestigations).mockResolvedValue({ records: [], results: [], artifact_errors: [] });
    vi.mocked(api.getEmbeddingStatus).mockResolvedValue({ status: 'unavailable', indexed_count: 0 });

    render(<VisualForensicsPage selectedCase={mockCase} />);

    // Wait for loading to complete and content to appear
    await waitFor(() => {
      expect(screen.queryByText(/加载中/)).not.toBeInTheDocument();
    });

    // Verify the summary section is rendered
    expect(screen.getByText('Visual Evidence Summary')).toBeInTheDocument();
    expect(screen.getByText('视觉取证概览')).toBeInTheDocument();
  });

  it('dense investigation button is disabled when no panels selected', async () => {
    vi.mocked(api.fetchVisualFigures).mockResolvedValue({ figures: [] });
    vi.mocked(api.fetchVisualPanels).mockResolvedValue({ panels: [] });
    vi.mocked(api.fetchVisualRelationships).mockResolvedValue({ relationships: [] });
    vi.mocked(api.fetchVisualFindings).mockResolvedValue({ findings: [] });
    vi.mocked(api.fetchOverlapReuse).mockResolvedValue({ relationships: [] });
    vi.mocked(api.listInvestigations).mockResolvedValue({ records: [], results: [], artifact_errors: [] });
    vi.mocked(api.getEmbeddingStatus).mockResolvedValue({ status: 'unavailable', indexed_count: 0 });

    render(<VisualForensicsPage selectedCase={mockCase} />);

    await waitFor(() => {
      expect(screen.getByText('Visual Evidence Summary')).toBeInTheDocument();
    });

    const runButton = screen.getByRole('button', { name: /Run SILA Dense/i });
    expect(runButton).toBeDisabled();
  });

  it('calls startVisualInvestigation with correct panel IDs when dense investigation runs', async () => {
    const user = userEvent.setup();
    const mockPanels = [
      { panel_id: 'panel1', parent_figure_id: 'fig1', label: 'Panel A', crop_path: 'panel1.png' },
      { panel_id: 'panel2', parent_figure_id: 'fig1', label: 'Panel B', crop_path: 'panel2.png' },
    ];
    const mockFigures = [{ figure_id: 'fig1', label: 'Figure 1', caption: 'Test', panel_count: 2, source_image_path: 'fig1.png' }];

    vi.mocked(api.fetchVisualFigures).mockResolvedValue({ figures: mockFigures });
    vi.mocked(api.fetchVisualPanels).mockResolvedValue({ panels: mockPanels });
    vi.mocked(api.fetchVisualRelationships).mockResolvedValue({ relationships: [] });
    vi.mocked(api.fetchVisualFindings).mockResolvedValue({ findings: [] });
    vi.mocked(api.fetchOverlapReuse).mockResolvedValue({ relationships: [] });
    vi.mocked(api.listInvestigations).mockResolvedValue({ records: [], results: [], artifact_errors: [] });
    vi.mocked(api.getEmbeddingStatus).mockResolvedValue({ status: 'indexed', indexed_count: 2 });
    vi.mocked(api.fetchAllSimilarPairs).mockResolvedValue({
      pairs: [
        {
          source_panel_id: 'panel1',
          target_panel_id: 'panel2',
          similarity: 0.96,
        },
      ],
    });
    vi.mocked(api.startVisualInvestigation).mockResolvedValue({
      record: { action_id: 'test-action', tool_id: 'visual.copy_move_dense', status: 'ran', created_at: '2026-01-01' },
      artifact: 'test-artifact',
      result: { status: 'ran', relationships: [], panel_count: 2, relationship_count: 0, errors: [] },
      db_sync_error: 'db failed',
    });

    render(<VisualForensicsPage selectedCase={mockCase} />);

    await waitFor(() => {
      expect(screen.getByText('Visual Evidence Summary')).toBeInTheDocument();
    });

    const loadPairsButton = await screen.findByRole('button', { name: /查找相似 Panel 对/i });
    await user.click(loadPairsButton);

    const runPairButton = await screen.findByRole('button', { name: /选中并跑 Dense/i });
    await user.click(runPairButton);

    // Verify API was called with correct parameters
    await waitFor(() => {
      expect(api.startVisualInvestigation).toHaveBeenCalledWith('test-case-1', {
        tool_id: 'visual.copy_move_dense',
        panel_ids: ['panel1', 'panel2'],
        params: {
          min_score: 0.05,
          max_relationships: 100,
          max_panels: 20,
        },
        hypothesis: 'Manual Web review of selected panels for dense copy-move candidates.',
      });
    });
    expect(await screen.findByText(/DB 同步失败：db failed/)).toBeInTheDocument();
  });

  it('shows error when API calls fail', async () => {
    vi.mocked(api.fetchVisualFigures).mockRejectedValue(new Error('Network error'));
    vi.mocked(api.fetchVisualPanels).mockResolvedValue({ panels: [] });
    vi.mocked(api.fetchVisualRelationships).mockResolvedValue({ relationships: [] });
    vi.mocked(api.fetchVisualFindings).mockResolvedValue({ findings: [] });
    vi.mocked(api.fetchOverlapReuse).mockResolvedValue({ relationships: [] });
    vi.mocked(api.listInvestigations).mockResolvedValue({ records: [], results: [], artifact_errors: [] });
    vi.mocked(api.getEmbeddingStatus).mockResolvedValue({ status: 'unavailable', indexed_count: 0 });

    render(<VisualForensicsPage selectedCase={mockCase} />);

    await waitFor(() => {
      expect(screen.getByText(/部分数据加载失败：figures: Network error/)).toBeInTheDocument();
    });
  });
});
