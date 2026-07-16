import { addTransitionType } from 'react';

export function markNavigationTransition(type) {
  if (type) addTransitionType(type);
}

export function viewTransitionName(prefix, value) {
  const safeValue = String(value || 'unknown').replace(/[^A-Za-z0-9_-]/g, '-');
  return `${prefix}-${safeValue}`;
}
