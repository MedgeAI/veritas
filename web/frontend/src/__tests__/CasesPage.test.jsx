import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CasesPage from '../pages/CasesPage.jsx';

describe('CasesPage', () => {
  it('places review-needed cases in the pending column', () => {
    const cases = [
      {
        case_id: 'needs-review',
        paper_title: 'Needs Review',
        status: 'Review Needed',
        technical_risk: 'medium',
        review_needed_count: 3,
        created_at: '2026-06-21T00:00:00Z',
      },
      {
        case_id: 'ready',
        paper_title: 'Ready Case',
        status: 'Report Ready',
        technical_risk: 'info',
        review_needed_count: 0,
        created_at: '2026-06-20T00:00:00Z',
      },
    ];

    render(
      <CasesPage
        cases={cases}
        selectedCaseId=""
        onSelectCase={vi.fn()}
        onNavigate={vi.fn()}
      />
    );

    const pendingSection = screen.getByText('待处理').closest('section');
    const doneSection = screen.getByRole('heading', { name: '已完成' }).closest('section');

    expect(within(pendingSection).getByText('Needs Review')).toBeInTheDocument();
    expect(within(doneSection).getByText('Ready Case')).toBeInTheDocument();
  });
});
