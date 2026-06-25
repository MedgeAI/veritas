import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ProgressTracker from '../components/ProgressTracker.jsx';
import RiskTrafficLight from '../components/RiskTrafficLight.jsx';

describe('ProgressTracker', () => {
  it('maps dynamic step progress from event keys', () => {
    render(
      <ProgressTracker
        events={[
          { event: 'step_start', key: 'source_data_findings', status: 'running', timestamp: '2026-06-21T00:00:00Z' },
          { event: 'step_result', key: 'source_data_findings', status: 'ran', timestamp: '2026-06-21T00:00:01Z' },
        ]}
        runStatus="running"
        _startedAt={null}
        caseId="case-1"
      />
    );

    expect(screen.getByText(/步骤 1\/22/)).toBeInTheDocument();
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
