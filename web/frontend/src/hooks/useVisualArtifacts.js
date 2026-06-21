import { useCallback, useEffect, useState } from 'react';
import {
  fetchVisualFigures,
  fetchVisualPanels,
  fetchVisualRelationships,
  fetchVisualFindings,
  fetchOverlapReuse,
  fetchProvenanceGraph,
  listInvestigations,
} from '../services/api.js';

/**
 * Returns true when the error message represents an expected absence of data
 * (e.g. "not_found", "no data") rather than a real failure.
 */
function isExpectedAbsence(msg) {
  return /not[_ ]found|no data|empty/i.test(msg || '');
}

/**
 * Hook to fetch and manage visual artifacts for a case.
 * Uses Promise.allSettled to make errors visible instead of silently swallowing them.
 *
 * @param {Object} selectedCase - The selected case object with case_id
 * @returns {Object} figures, panels, relationships, findings, overlapRelationships,
 *                   provenanceGraph, investigationRecords, investigationResults,
 *                   investigationArtifactErrors, loading, error, loadData
 */
export function useVisualArtifacts(selectedCase) {
  const [figures, setFigures] = useState([]);
  const [panels, setPanels] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [findings, setFindings] = useState([]);
  const [overlapRelationships, setOverlapRelationships] = useState([]);
  const [provenanceGraph, setProvenanceGraph] = useState(null);
  const [investigationRecords, setInvestigationRecords] = useState([]);
  const [investigationResults, setInvestigationResults] = useState([]);
  const [investigationArtifactErrors, setInvestigationArtifactErrors] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    const caseId = selectedCase?.case_id;
    if (!caseId) return;
    setLoading(true);
    setError('');

    try {
      const [figuresResult, panelsResult, relationshipsResult, findingsResult, overlapResult, provenanceResult, investigationsResult] =
        await Promise.allSettled([
          fetchVisualFigures(caseId),
          fetchVisualPanels(caseId),
          fetchVisualRelationships(caseId),
          fetchVisualFindings(caseId),
          fetchOverlapReuse(caseId),
          fetchProvenanceGraph(caseId),
          listInvestigations(caseId),
        ]);

      const fetchTargets = [
        { key: 'figures', result: figuresResult, set: setFigures, get: (v) => v.figures || [] },
        { key: 'panels', result: panelsResult, set: setPanels, get: (v) => v.panels || [] },
        { key: 'relationships', result: relationshipsResult, set: setRelationships, get: (v) => v.relationships || [] },
        { key: 'findings', result: findingsResult, set: setFindings, get: (v) => v.findings || [] },
        { key: 'overlap', result: overlapResult, set: setOverlapRelationships, get: (v) => v?.relationships || [] },
        { key: 'investigations', result: investigationsResult, set: null, get: null },
      ];

      const errors = [];
      for (const { key, result, set, get } of fetchTargets) {
        if (result.status === 'fulfilled') {
          if (key === 'investigations') {
            const data = result.value;
            setInvestigationRecords(data.records || []);
            setInvestigationResults(data.results || []);
            setInvestigationArtifactErrors(data.artifact_errors || []);
          } else {
            set(get(result.value));
          }
        } else {
          errors.push(`${key}: ${result.reason?.message || 'failed'}`);
          if (key !== 'investigations') {
            set([]);
          } else {
            setInvestigationRecords([]);
            setInvestigationResults([]);
            setInvestigationArtifactErrors([]);
          }
        }
      }

      // provenance is handled separately (optional, no error surfacing)
      if (provenanceResult.status === 'fulfilled') {
        const pg = provenanceResult.value;
        setProvenanceGraph(pg?.status === 'failed' ? null : pg);
      } else {
        setProvenanceGraph(null);
      }

      if (errors.length > 0) {
        const realErrors = errors.filter((e) => !isExpectedAbsence(e));

        if (realErrors.length > 0) {
          setError(`部分数据加载失败：${realErrors.join('; ')}`);
        }
      }
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, [selectedCase?.case_id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return {
    figures,
    panels,
    relationships,
    findings,
    overlapRelationships,
    provenanceGraph,
    investigationRecords,
    investigationResults,
    investigationArtifactErrors,
    loading,
    error,
    loadData,
    setInvestigationRecords,
    setInvestigationResults,
  };
}
