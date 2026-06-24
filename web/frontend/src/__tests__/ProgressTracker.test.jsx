import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProgressTracker from '../components/ProgressTracker';
import paper4Events from '../__fixtures__/paper4_events.json';

describe('ProgressTracker', () => {
  it('renders completed state', () => {
    render(<ProgressTracker events={paper4Events} runStatus="completed" startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText('已完成')).toBeDefined();
    expect(screen.getByText('100%')).toBeDefined();
  });

  it('renders running state', () => {
    render(<ProgressTracker events={paper4Events.slice(0, 20)} runStatus="running" startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText(/步骤/)).toBeDefined();
  });

  it('shows step groups', () => {
    render(<ProgressTracker events={paper4Events} runStatus="completed" startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText('MinerU PDF 解析')).toBeDefined();
    expect(screen.getByText('Source Data Findings')).toBeDefined();
  });

  it('shows duration for completed steps', () => {
    render(<ProgressTracker events={paper4Events} runStatus="completed" startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    // mineru took about 12 seconds
    const durationElements = screen.getAllByText(/s$/);
    expect(durationElements.length).toBeGreaterThan(0);
  });

  it('shows view results button when completed', () => {
    render(<ProgressTracker events={paper4Events} runStatus="completed" startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText('查看结果')).toBeDefined();
  });
});
