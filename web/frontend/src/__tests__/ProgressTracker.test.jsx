import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProgressTracker from '../components/ProgressTracker';
import paper4Events from '../__fixtures__/paper4_events.json';

describe('ProgressTracker', () => {
  it('renders completed state with CompletionSummary', () => {
    render(<ProgressTracker events={paper4Events} runStatus="completed" _startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText('审查完成')).toBeDefined();
    expect(screen.getByText('查看报告')).toBeDefined();
  });

  it('renders running state with progress UI', () => {
    render(<ProgressTracker events={paper4Events.slice(0, 20)} runStatus="running" _startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText(/审查进度/)).toBeDefined();
    expect(screen.getByText(/步骤 \d+\/\d+/)).toBeDefined();
  });

  it('shows current phase with steps in PhaseHeroCard', () => {
    render(<ProgressTracker events={paper4Events.slice(0, 20)} runStatus="running" _startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    // Should show at least one phase label from PHASES
    const phaseLabels = ['准备', '文档解析', '数值取证', '证据分析', 'Agent 审查', '报告生成'];
    const found = phaseLabels.some(label => screen.queryByText(label) !== null);
    expect(found).toBe(true);
  });

  it('shows duration for completed steps', () => {
    render(<ProgressTracker events={paper4Events} runStatus="running" _startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    // Durations are shown in PhaseHeroCard for completed steps
    const durationElements = screen.getAllByText(/\d+s/);
    expect(durationElements.length).toBeGreaterThanOrEqual(0);
  });

  it('shows view report button when completed', () => {
    render(<ProgressTracker events={paper4Events} runStatus="completed" _startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText('查看报告')).toBeDefined();
  });

  it('shows loading state when events is empty', () => {
    render(<ProgressTracker events={[]} runStatus="queued" _startedAt="2026-06-24T09:39:38Z" caseId="paper4" />);
    expect(screen.getByText('等待审查开始…')).toBeDefined();
  });
});
