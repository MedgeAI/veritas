import { Suspense, ViewTransition } from 'react';

const PAGE_ENTER = {
  'nav-forward': 'nav-forward',
  'nav-back': 'nav-back',
  'nav-lateral': 'fade-in',
  default: 'none',
};

const PAGE_EXIT = {
  'nav-forward': 'nav-forward',
  'nav-back': 'nav-back',
  'nav-lateral': 'fade-out',
  default: 'none',
};

export function PageViewTransition({ children }) {
  return (
    <ViewTransition enter={PAGE_ENTER} exit={PAGE_EXIT} default="none">
      {children}
    </ViewTransition>
  );
}

export function SuspenseReveal({ fallback, children }) {
  return (
    <Suspense
      fallback={(
        <ViewTransition exit="slide-down" default="none">
          {fallback}
        </ViewTransition>
      )}
    >
      <ViewTransition enter="slide-up" default="none">
        {children}
      </ViewTransition>
    </Suspense>
  );
}

export function ScaleTransition({ children }) {
  return (
    <ViewTransition enter="scale-in" exit="scale-out" default="none">
      {children}
    </ViewTransition>
  );
}

export function ListItemTransition({ children }) {
  return <ViewTransition>{children}</ViewTransition>;
}
