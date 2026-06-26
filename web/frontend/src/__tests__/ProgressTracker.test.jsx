import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProgressTracker from '../components/ProgressTracker';
import paper4Steps from '../__fixtures__/paper4_steps.json';

describe('ProgressTracker', () => {
  it('renders completed state with CompletionSummary', () => {
    render(<ProgressTracker steps={paper4Steps} runStatus="completed" caseId="paper4" />);
    expect(screen.getByText('审查完成')).toBeDefined();
    expect(screen.getByText('查看报告')).toBeDefined();
  });

  it('renders running state with progress UI', () => {
    render(<ProgressTracker steps={paper4Steps.slice(0, 20)} runStatus="running" caseId="paper4" />);
    expect(screen.getByText(/审查进度/)).toBeDefined();
    expect(screen.getByText(/步骤 \d+\/\d+/)).toBeDefined();
  });

  it('shows current phase with steps in PhaseHeroCard', () => {
    render(<ProgressTracker steps={paper4Steps.slice(0, 20)} runStatus="running" caseId="paper4" />);
    // Should show at least one phase name from step_labels
    const phaseLabels = ['准备', '文档解析', '数值取证', '数据分析', 'Agent 审查', '报告生成'];
    const found = phaseLabels.some(label => screen.queryByText(label) !== null);
    expect(found).toBe(true);
  });

  it('shows duration for completed steps', () => {
    render(<ProgressTracker steps={paper4Steps} runStatus="running" caseId="paper4" />);
    // Durations are shown in PhaseHeroCard for completed steps
    const durationElements = screen.getAllByText(/\d+s/);
    expect(durationElements.length).toBeGreaterThanOrEqual(0);
  });

  it('shows view report button when completed', () => {
    render(<ProgressTracker steps={paper4Steps} runStatus="completed" caseId="paper4" />);
    expect(screen.getByText('查看报告')).toBeDefined();
  });

  it('shows loading state when steps is empty', () => {
    render(<ProgressTracker steps={[]} runStatus="queued" caseId="paper4" />);
    expect(screen.getByText('等待审查开始…')).toBeDefined();
  });
});
