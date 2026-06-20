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
    if (!selectedCase) return;
    setLoading(true);
    setError('');

    try {
      const [figuresResult, panelsResult, relationshipsResult, findingsResult, overlapResult, provenanceResult, investigationsResult] =
        await Promise.allSettled([
          fetchVisualFigures(selectedCase.case_id),
          fetchVisualPanels(selectedCase.case_id),
          fetchVisualRelationships(selectedCase.case_id),
          fetchVisualFindings(selectedCase.case_id),
          fetchOverlapReuse(selectedCase.case_id),
          fetchProvenanceGraph(selectedCase.case_id),
          listInvestigations(selectedCase.case_id),
        ]);

      // Extract values or collect errors
      const errors = [];

      if (figuresResult.status === 'fulfilled') {
        setFigures(figuresResult.value.figures || []);
      } else {
        errors.push(`figures: ${figuresResult.reason?.message || 'failed'}`);
        setFigures([]);
      }

      if (panelsResult.status === 'fulfilled') {
        setPanels(panelsResult.value.panels || []);
      } else {
        errors.push(`panels: ${panelsResult.reason?.message || 'failed'}`);
        setPanels([]);
      }

      if (relationshipsResult.status === 'fulfilled') {
        setRelationships(relationshipsResult.value.relationships || []);
      } else {
        errors.push(`relationships: ${relationshipsResult.reason?.message || 'failed'}`);
        setRelationships([]);
      }

      if (findingsResult.status === 'fulfilled') {
        setFindings(findingsResult.value.findings || []);
      } else {
        errors.push(`findings: ${findingsResult.reason?.message || 'failed'}`);
        setFindings([]);
      }

      if (overlapResult.status === 'fulfilled') {
        setOverlapRelationships(overlapResult.value?.relationships || []);
      } else {
        errors.push(`overlap: ${overlapResult.reason?.message || 'failed'}`);
        setOverlapRelationships([]);
      }

      if (provenanceResult.status === 'fulfilled') {
        const pg = provenanceResult.value;
        setProvenanceGraph(pg?.status === 'failed' ? null : pg);
      } else {
        // provenance graph is optional; don't surface as error
        setProvenanceGraph(null);
      }

      if (investigationsResult.status === 'fulfilled') {
        const data = investigationsResult.value;
        setInvestigationRecords(data.records || []);
        setInvestigationResults(data.results || []);
        setInvestigationArtifactErrors(data.artifact_errors || []);
      } else {
        errors.push(`investigations: ${investigationsResult.reason?.message || 'failed'}`);
        setInvestigationRecords([]);
        setInvestigationResults([]);
        setInvestigationArtifactErrors([]);
      }

      if (errors.length > 0) {
        // 区分"没有数据"和"真正的错误"
        const realErrors = errors.filter((e) => !e.includes('not_found') && !e.includes('not found'));

        if (realErrors.length > 0) {
          // 真正的错误：显示技术性错误信息
          setError(`部分数据加载失败：${realErrors.join('; ')}`);
        }
        // 如果只是 "not_found"，不设置 error，让页面显示空状态
      }
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, [selectedCase]);

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
