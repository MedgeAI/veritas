import { useCallback, useState } from 'react';
import { startVisualInvestigation } from '../services/api.js';

/**
 * Hook to manage dense copy-move investigation execution.
 *
 * @param {Object} selectedCase - The selected case object with case_id
 * @param {Function} setInvestigationRecords - Callback to update investigation records
 * @param {Function} setInvestigationResults - Callback to update investigation results
 * @returns {Object} runDense, isRunning, denseError, setDenseError
 */
export function useDenseInvestigation(selectedCase, setInvestigationRecords, setInvestigationResults) {
  const [isRunning, setIsRunning] = useState(false);
  const [denseError, setDenseError] = useState('');

  const runDense = useCallback(
    async (panelIds, denseMaxPanels = 20) => {
      if (!selectedCase || panelIds.length === 0) return;

      setIsRunning(true);
      setDenseError('');

      try {
        const response = await startVisualInvestigation(selectedCase.case_id, {
          tool_id: 'visual.copy_move_dense',
          panel_ids: panelIds,
          params: {
            min_score: 0.05,
            max_relationships: 100,
            max_panels: Number(denseMaxPanels) || 20,
          },
          hypothesis: 'Manual Web review of selected panels for dense copy-move candidates.',
        });

        setInvestigationRecords((current) => [response.record, ...current]);
        setInvestigationResults((current) => [
          { record: response.record, artifact: response.artifact, result: response.result },
          ...current,
        ]);

        if (response.db_sync_error) {
          setDenseError(`DB 同步失败：${response.db_sync_error}`);
        }
      } catch (err) {
        setDenseError(err.message || String(err));
      } finally {
        setIsRunning(false);
      }
    },
    [selectedCase, setInvestigationRecords, setInvestigationResults],
  );

  return {
    runDense,
    isRunning,
    denseError,
    setDenseError,
  };
}
