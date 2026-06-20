import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CBIRSearchPage from '../pages/CBIRSearchPage.jsx';
import * as cbirApi from '../services/cbir.js';

// Mock the CBIR API module
vi.mock('../services/cbir.js', () => ({
  searchSimilarPanels: vi.fn(),
  searchByImageUpload: vi.fn(),
}));

// Mock the visual image URL helper
vi.mock('../services/api.js', () => ({
  visualImageUrl: vi.fn((caseId, path) => `/images/${caseId}/${path}`),
}));

describe('CBIRSearchPage', () => {
  const mockCase = { case_id: 'test-case-1' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when no case is selected', () => {
    render(<CBIRSearchPage selectedCase={null} />);
    expect(screen.getByText('请先选择 Case')).toBeInTheDocument();
    expect(screen.getByText(/CBIR Search 支持通过 Panel ID 或图片上传搜索相似 panel/)).toBeInTheDocument();
  });

  it('renders search controls when case is selected', () => {
    render(<CBIRSearchPage selectedCase={mockCase} />);
    expect(screen.getByText('相似 Panel 搜索')).toBeInTheDocument();
    expect(screen.getByText('Panel ID 搜索')).toBeInTheDocument();
    expect(screen.getByText('图片上传搜索')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('例如: panel_001')).toBeInTheDocument();
  });

  it('search button is disabled when panel ID is empty', () => {
    render(<CBIRSearchPage selectedCase={mockCase} />);
    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    expect(searchButton).toBeDisabled();
  });

  it('does not call API when panel ID is empty', async () => {
    render(<CBIRSearchPage selectedCase={mockCase} />);
    expect(cbirApi.searchSimilarPanels).not.toHaveBeenCalled();
  });

  it('calls searchSimilarPanels with correct parameters', async () => {
    const user = userEvent.setup();
    vi.mocked(cbirApi.searchSimilarPanels).mockResolvedValue({
      query_panel_id: 'panel_001',
      similar_panels: [],
      total_candidates: 0,
      threshold: 0.85,
    });

    render(<CBIRSearchPage selectedCase={mockCase} />);

    const panelInput = screen.getByPlaceholderText('例如: panel_001');
    await user.type(panelInput, 'panel_001');

    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    await user.click(searchButton);

    await waitFor(() => {
      expect(cbirApi.searchSimilarPanels).toHaveBeenCalledWith('panel_001', {
        caseId: 'test-case-1',
        topK: 20,
        threshold: 0.85,
        label: undefined,
      });
    });
  });

  it('displays search results in grid', async () => {
    const user = userEvent.setup();
    const mockResults = [
      {
        panel_id: 'panel_002',
        figure_id: 'fig_001',
        case_id: 'test-case-1',
        image_path: 'panels/panel_002.png',
        similarity: 0.95,
        label: 'Western Blot',
      },
      {
        panel_id: 'panel_003',
        figure_id: 'fig_001',
        case_id: 'test-case-2',
        image_path: 'panels/panel_003.png',
        similarity: 0.87,
        label: 'Western Blot',
      },
    ];

    vi.mocked(cbirApi.searchSimilarPanels).mockResolvedValue({
      query_panel_id: 'panel_001',
      similar_panels: mockResults,
      total_candidates: 2,
      threshold: 0.85,
    });

    render(<CBIRSearchPage selectedCase={mockCase} />);

    const panelInput = screen.getByPlaceholderText('例如: panel_001');
    await user.type(panelInput, 'panel_001');

    // Wait for button to be enabled
    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    await waitFor(() => {
      expect(searchButton).not.toBeDisabled();
    });

    await user.click(searchButton);

    // Wait for results to appear - use findByText for async
    expect(await screen.findByText('panel_002')).toBeInTheDocument();
    expect(screen.getByText('panel_003')).toBeInTheDocument();
    expect(screen.getByText('95.0%')).toBeInTheDocument();
    expect(screen.getByText('87.0%')).toBeInTheDocument();
  });

  it('shows no results message when search returns empty', async () => {
    const user = userEvent.setup();
    vi.mocked(cbirApi.searchSimilarPanels).mockResolvedValue({
      query_panel_id: 'panel_001',
      similar_panels: [],
      total_candidates: 0,
      threshold: 0.85,
    });

    render(<CBIRSearchPage selectedCase={mockCase} />);

    const panelInput = screen.getByPlaceholderText('例如: panel_001');
    await user.type(panelInput, 'panel_001');

    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    await waitFor(() => {
      expect(searchButton).not.toBeDisabled();
    });

    await user.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText('未找到相似 panel')).toBeInTheDocument();
    });
  });

  it('displays error message when search fails', async () => {
    const user = userEvent.setup();
    vi.mocked(cbirApi.searchSimilarPanels).mockRejectedValue(new Error('Network error'));

    render(<CBIRSearchPage selectedCase={mockCase} />);

    const panelInput = screen.getByPlaceholderText('例如: panel_001');
    await user.type(panelInput, 'panel_001');

    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    await user.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('switches to image upload mode', async () => {
    const user = userEvent.setup();
    render(<CBIRSearchPage selectedCase={mockCase} />);

    const uploadTab = screen.getByRole('button', { name: /图片上传搜索/i });
    await user.click(uploadTab);

    expect(screen.getByText(/点击或拖拽图片到此处上传/)).toBeInTheDocument();
    expect(screen.getByText(/图片上传搜索功能尚未实现/)).toBeInTheDocument();
  });

  it('shows warning that image upload is not implemented', async () => {
    const user = userEvent.setup();
    render(<CBIRSearchPage selectedCase={mockCase} />);

    const uploadTab = screen.getByRole('button', { name: /图片上传搜索/i });
    await user.click(uploadTab);

    expect(screen.getByText(/后端仅提供 Panel ID 搜索接口/)).toBeInTheDocument();
  });

  it('adjusts topK and threshold with sliders', () => {
    render(<CBIRSearchPage selectedCase={mockCase} />);

    // Find all sliders - there should be 2 (topK and threshold)
    const sliders = screen.getAllByRole('slider');
    expect(sliders.length).toBe(2);

    const topKSlider = sliders[0];
    const thresholdSlider = sliders[1];

    expect(topKSlider).toHaveValue('20');
    expect(thresholdSlider).toHaveValue('0.85');

    // Sliders are range inputs, just verify they exist and have correct defaults
    expect(topKSlider).toHaveAttribute('min', '5');
    expect(topKSlider).toHaveAttribute('max', '100');
    expect(thresholdSlider).toHaveAttribute('min', '0.5');
    expect(thresholdSlider).toHaveAttribute('max', '0.99');
  });

  it('search button is disabled when loading', async () => {
    const user = userEvent.setup();
    vi.mocked(cbirApi.searchSimilarPanels).mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    render(<CBIRSearchPage selectedCase={mockCase} />);

    const panelInput = screen.getByPlaceholderText('例如: panel_001');
    await user.type(panelInput, 'panel_001');

    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    await user.click(searchButton);

    await waitFor(() => {
      expect(searchButton).toBeDisabled();
      expect(searchButton).toHaveTextContent('搜索中...');
    });
  });

  it('search button is disabled when panel ID is empty', () => {
    render(<CBIRSearchPage selectedCase={mockCase} />);
    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    expect(searchButton).toBeDisabled();
  });

  it('supports label filter in search', async () => {
    const user = userEvent.setup();
    vi.mocked(cbirApi.searchSimilarPanels).mockResolvedValue({
      query_panel_id: 'panel_001',
      similar_panels: [],
      total_candidates: 0,
      threshold: 0.85,
    });

    render(<CBIRSearchPage selectedCase={mockCase} />);

    const panelInput = screen.getByPlaceholderText('例如: panel_001');
    await user.type(panelInput, 'panel_001');

    const labelInput = screen.getByPlaceholderText('例如: Western Blot');
    await user.type(labelInput, 'Western Blot');

    const searchButton = screen.getByRole('button', { name: /开始搜索/i });
    await user.click(searchButton);

    await waitFor(() => {
      expect(cbirApi.searchSimilarPanels).toHaveBeenCalledWith('panel_001', {
        caseId: 'test-case-1',
        topK: 20,
        threshold: 0.85,
        label: 'Western Blot',
      });
    });
  });
});
