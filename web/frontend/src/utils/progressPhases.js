export const PHASE_STATUS = Object.freeze({
  COMPLETED: 'completed',
  FAILED: 'failed',
  PENDING: 'pending',
  RUNNING: 'running',
  SKIPPED: 'skipped',
  WARNING: 'warning',
});

export const PHASE_STATUS_VALUES = Object.freeze(Object.values(PHASE_STATUS));

export function normaliseStepStatus(status) {
  if (status === 'done') return PHASE_STATUS.COMPLETED;
  return status || PHASE_STATUS.PENDING;
}

export function groupStepsByPhase(steps = []) {
  const phaseMap = new Map();

  for (const step of steps) {
    const phaseName = step.phase || 'Unknown';
    const phaseOrder = step.phase_order ?? 99;

    if (!phaseMap.has(phaseName)) {
      phaseMap.set(phaseName, {
        name: phaseName,
        order: phaseOrder,
        steps: [],
      });
    }
    phaseMap.get(phaseName).steps.push(step);
  }

  return Array.from(phaseMap.values()).sort((a, b) => a.order - b.order);
}

export function computePhaseStatus(phaseSteps = []) {
  if (phaseSteps.length === 0) return PHASE_STATUS.PENDING;

  const statuses = phaseSteps.map((step) => normaliseStepStatus(step.status));

  if (statuses.some((status) => status === PHASE_STATUS.FAILED)) {
    return PHASE_STATUS.FAILED;
  }
  if (statuses.some((status) => status === PHASE_STATUS.RUNNING)) {
    return PHASE_STATUS.RUNNING;
  }
  if (statuses.some((status) => status === PHASE_STATUS.WARNING)) {
    return PHASE_STATUS.WARNING;
  }
  if (statuses.every((status) => status === PHASE_STATUS.SKIPPED)) {
    return PHASE_STATUS.SKIPPED;
  }
  if (
    statuses.every((status) => (
      status === PHASE_STATUS.COMPLETED || status === PHASE_STATUS.SKIPPED
    ))
  ) {
    return PHASE_STATUS.COMPLETED;
  }

  return PHASE_STATUS.PENDING;
}

export function buildPhaseStatuses(phases = []) {
  return Object.fromEntries(
    phases.map((phase) => [phase.name, computePhaseStatus(phase.steps)]),
  );
}

export function hasRunningStep(phase) {
  return (phase?.steps ?? []).some((step) => normaliseStepStatus(step.status) === PHASE_STATUS.RUNNING);
}

export function findCurrentPhase(phases = [], phaseStatuses = {}) {
  const withRunningStep = phases.find((phase) => hasRunningStep(phase));
  if (withRunningStep) return withRunningStep;

  const running = phases.find((phase) => phaseStatuses[phase.name] === PHASE_STATUS.RUNNING);
  if (running) return running;

  const pending = phases.find((phase) => phaseStatuses[phase.name] === PHASE_STATUS.PENDING);
  if (pending) return pending;

  return phases.find((phase) => (
    phaseStatuses[phase.name] === PHASE_STATUS.FAILED
    || phaseStatuses[phase.name] === PHASE_STATUS.WARNING
    || phaseStatuses[phase.name] === PHASE_STATUS.SKIPPED
  ));
}
