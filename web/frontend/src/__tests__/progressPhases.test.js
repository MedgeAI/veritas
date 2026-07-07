import { describe, expect, it } from 'vitest';
import {
  computePhaseStatus,
  findCurrentPhase,
  groupStepsByPhase,
} from '../utils/progressPhases.js';

describe('progress phase helpers', () => {
  it('groups steps by phase order', () => {
    const phases = groupStepsByPhase([
      { key: 'b', phase: '报告生成', phase_order: 7, status: 'pending' },
      { key: 'a', phase: '准备', phase_order: 1, status: 'completed' },
    ]);

    expect(phases.map((phase) => phase.name)).toEqual(['准备', '报告生成']);
  });

  it('uses explicit phase status priority', () => {
    expect(computePhaseStatus([
      { status: 'failed' },
      { status: 'running' },
    ])).toBe('failed');
    expect(computePhaseStatus([
      { status: 'warning' },
      { status: 'completed' },
    ])).toBe('warning');
    expect(computePhaseStatus([
      { status: 'skipped' },
      { status: 'skipped' },
    ])).toBe('skipped');
    expect(computePhaseStatus([
      { status: 'completed' },
      { status: 'skipped' },
    ])).toBe('completed');
  });

  it('selects the phase with a running step even if the phase status is failed', () => {
    const phases = groupStepsByPhase([
      { key: 'a', phase: '数据分析', phase_order: 4, status: 'failed' },
      { key: 'b', phase: '数据分析', phase_order: 4, status: 'running' },
      { key: 'c', phase: '报告生成', phase_order: 7, status: 'pending' },
    ]);

    expect(findCurrentPhase(phases, { 数据分析: 'failed', 报告生成: 'pending' })?.name).toBe('数据分析');
  });
});
