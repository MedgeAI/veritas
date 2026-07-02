import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import IssuePage from '../pages/client/IssuePage.jsx';
import { fetchClientReport } from '../services/api';

vi.mock('../services/api', () => ({
  fetchClientReport: vi.fn(),
  saveReviewDecision: vi.fn(),
}));

const READY_REPORT = {
  status: 'ready',
  risk: {
    findings_by_layer: {
      layer_1: [
        {
          finding_id: 'finding-1',
          summary: '第一项发现',
          risk_level: 'high',
          location: 'Table 1',
          certainty: {
            fact: '事实 A',
            inference: '推断 A',
            suggestion: '建议 A',
          },
          review_decision_allowed: true,
          source_ref: 'source-1',
        },
        {
          finding_id: 'finding-2',
          summary: '第二项发现',
          risk_level: 'medium',
          location: 'Figure 2',
          certainty: {
            fact: '事实 B',
            inference: '推断 B',
            suggestion: '建议 B',
          },
          review_decision_allowed: true,
          source_ref: 'source-2',
        },
      ],
      layer_2: [],
      layer_3: [],
    },
  },
};

describe('IssuePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchClientReport.mockResolvedValue(READY_REPORT);
  });

  it('renders the findings list after the report loads', async () => {
    render(<IssuePage caseId="case-1" onNavigate={vi.fn()} />);

    expect(screen.getByText('加载中…')).toBeInTheDocument();
    expect(await screen.findByText('选择需要复核的发现')).toBeInTheDocument();
    expect(screen.getByText('第一项发现')).toBeInTheDocument();
    expect(screen.getByText('第二项发现')).toBeInTheDocument();
  });

  it('navigates from the list view when a finding is selected', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<IssuePage caseId="case-1" onNavigate={onNavigate} />);

    await user.click(await screen.findByRole('button', { name: /第一项发现/ }));

    expect(onNavigate).toHaveBeenCalledWith('issue', { finding: 'finding-1' });
  });

  it('renders a finding detail after the report loads', async () => {
    render(<IssuePage caseId="case-1" findingId="finding-1" onNavigate={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: '第一项发现' })).toBeInTheDocument();
    expect(screen.getByText('事实 A')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
  });

  it('uses arrow-key navigation only in detail view', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<IssuePage caseId="case-1" findingId="finding-1" onNavigate={onNavigate} />);

    await screen.findByRole('heading', { name: '第一项发现' });
    await user.keyboard('{ArrowRight}');

    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalledWith('issue', { finding: 'finding-2' });
    });
  });

  it('shows a not-found state for an unknown finding id', async () => {
    render(<IssuePage caseId="case-1" findingId="missing" onNavigate={vi.fn()} />);

    expect(await screen.findByText('未找到该发现 (ID: missing)')).toBeInTheDocument();
  });
});
