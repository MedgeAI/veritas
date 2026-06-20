import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getEmbeddingStatus,
  triggerEmbeddingIndex,
  fetchAllSimilarPairs,
} from '../services/api.js';

const BLOCKING_EMBEDDING_STATUSES = new Set(['failed', 'model_unavailable', 'unavailable', 'no_database']);
const TERMINAL_EMBEDDING_STATUSES = new Set([
  'completed',
  'failed',
  'indexed',
  'model_unavailable',
  'no_panels',
  'partial',
  'unavailable',
]);

function isBlockingEmbeddingStatus(status) {
  return Boolean(status?.status && BLOCKING_EMBEDDING_STATUSES.has(status.status));
}

function isTerminalEmbeddingStatus(status) {
  return Boolean(
    status?.status && (TERMINAL_EMBEDDING_STATUSES.has(status.status) || Number(status.indexed_count || 0) > 0),
  );
}

function describeEmbeddingStatus(status, fallback) {
  return status?.detail || status?.failure_category || fallback;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Hook to manage SSCD embedding indexing and similarity search.
 * Supports AbortController for cleanup on unmount/caseId change.
 *
 * @param {Object} selectedCase - The selected case object with case_id
 * @returns {Object} embeddingStatus, similarPairs, similarityThreshold, setSimilarityThreshold,
 *                   isIndexing, similarityError, handleIndexPanels, handleLoadSimilarPairs,
 *                   setEmbeddingStatus, setSimilarPairs, setSimilarityError
 */
export function useEmbeddingIndex(selectedCase) {
  const [embeddingStatus, setEmbeddingStatus] = useState(null);
  const [indexingInProgress, setIndexingInProgress] = useState(false);
  const [similarPairs, setSimilarPairs] = useState([]);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.85);
  const [similarityError, setSimilarityError] = useState('');

  const abortControllerRef = useRef(null);
  const loadGenerationRef = useRef(0);

  const indexedPanelCount = Number(embeddingStatus?.indexed_count || 0);
  const embeddingStatusBlocked = isBlockingEmbeddingStatus(embeddingStatus);
  const canFindSimilarPairs = indexedPanelCount > 0 && !embeddingStatusBlocked;

  const caseId = selectedCase?.case_id;

  // Load initial embedding status when case changes
  useEffect(() => {
    loadGenerationRef.current += 1;
    const generation = loadGenerationRef.current;
    const controller = new AbortController();

    if (!caseId) {
      setEmbeddingStatus(null);
      setSimilarPairs([]);
      setSimilarityError('');
      return () => controller.abort();
    }

    getEmbeddingStatus(caseId, { signal: controller.signal })
      .then((status) => {
        if (!controller.signal.aborted && generation === loadGenerationRef.current) {
          setEmbeddingStatus(status);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted && generation === loadGenerationRef.current) {
          setEmbeddingStatus({
            case_id: caseId,
            status: 'unavailable',
            indexed_count: 0,
            detail: err.message || String(err),
          });
        }
      });

    return () => {
      controller.abort();
      // Cleanup on unmount or caseId change
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [caseId]);

  // Trigger panel indexing with polling
  const handleIndexPanels = useCallback(async () => {
    if (!selectedCase) return;

    // Abort any previous polling
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    const { signal } = abortControllerRef.current;

    setIndexingInProgress(true);
    setSimilarityError('');

    try {
      await triggerEmbeddingIndex(selectedCase.case_id, { signal });

      for (let attempt = 0; attempt < 12; attempt += 1) {
        if (signal.aborted) break;

        await sleep(1500);

        if (signal.aborted) break;

        const status = await getEmbeddingStatus(selectedCase.case_id, { signal });

        if (signal.aborted) break;

        setEmbeddingStatus(status);

        if (isBlockingEmbeddingStatus(status)) {
          setSimilarityError(describeEmbeddingStatus(status, 'Indexing failed'));
          break;
        }
        if (isTerminalEmbeddingStatus(status)) {
          break;
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setSimilarityError(err.message || 'Indexing failed');
      }
    } finally {
      if (!signal.aborted) {
        setIndexingInProgress(false);
      }
    }
  }, [selectedCase]);

  // Load similar pairs
  const handleLoadSimilarPairs = useCallback(async () => {
    if (!selectedCase) return;
    setSimilarityError('');
    try {
      const data = await fetchAllSimilarPairs(selectedCase.case_id, {
        threshold: similarityThreshold,
        signal: abortControllerRef.current?.signal,
      });
      setSimilarPairs(data.pairs || []);
    } catch (err) {
      setSimilarityError(err.message || 'Failed to load similar pairs');
    }
  }, [selectedCase, similarityThreshold]);

  return {
    embeddingStatus,
    similarPairs,
    similarityThreshold,
    setSimilarityThreshold,
    isIndexing: indexingInProgress,
    similarityError,
    canFindSimilarPairs,
    indexedPanelCount,
    embeddingStatusBlocked,
    handleIndexPanels,
    handleLoadSimilarPairs,
    setEmbeddingStatus,
    setSimilarPairs,
    setSimilarityError,
  };
}
