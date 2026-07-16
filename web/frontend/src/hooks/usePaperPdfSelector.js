import { useCallback, useRef, useState } from 'react';

/**
 * Hook 管理 PaperPdfSelector 弹窗的打开/关闭/选择状态。
 *
 * 使用 Promise 模式调用方：requestSelection(candidates) 返回 Promise<string | null>，
 * 用户在弹窗中选择后 resolve 选中路径，取消则 resolve(null)。
 */
export function usePaperPdfSelector() {
  const [state, setState] = useState({ open: false, candidates: [] });
  const resolveRef = useRef(null);

  const requestSelection = useCallback((candidates) => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setState({ open: true, candidates });
    });
  }, []);

  const close = useCallback((value) => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    setState({ open: false, candidates: [] });
    if (resolve) resolve(value);
  }, []);

  return {
    open: state.open,
    candidates: state.candidates,
    requestSelection,
    close,
  };
}
