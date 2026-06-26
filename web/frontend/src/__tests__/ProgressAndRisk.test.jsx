import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ProgressTracker from '../components/ProgressTracker.jsx';
import RiskTrafficLight from '../components/RiskTrafficLight.jsx';

describe('ProgressTracker', () => {
  it('maps dynamic step progress from step list', () => {
    render(
      <ProgressTracker
        steps={[
          {
            key: 'source_data_findings',
            title: 'Source Data 发现',
            phase: '数据分析',
            phase_order: 4,
            status: 'completed',
            duration_seconds: 1,
            started_at: '2026-06-21T00:00:00Z',
          },
        ]}
        runStatus="running"
        caseId="case-1"
      />
    );

    expect(screen.getByText(/步骤 1\/1/)).toBeInTheDocument();
  });
});

describe('RiskTrafficLight', () => {
  it('shows evidence-unavailable state separately from info risk', () => {
    const { rerender } = render(
      <RiskTrafficLight
        riskLevel="unknown"
        riskCounts={{ critical: 0, high: 0, medium: 0, low: 0, info: 0 }}
      />
    );

    expect(screen.getByText('证据不足')).toBeInTheDocument();

    rerender(
      <RiskTrafficLight
        riskLevel="info"
        riskCounts={{ critical: 0, high: 0, medium: 0, low: 0, info: 1 }}
      />
    );

    expect(screen.getByText('未发现中高风险')).toBeInTheDocument();
    expect(screen.queryByText('无风险')).not.toBeInTheDocument();
  });
});
