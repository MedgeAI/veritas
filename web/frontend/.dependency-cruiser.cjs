/**
 * dependency-cruiser configuration for Veritas frontend.
 * Enforces architectural boundaries within the React app.
 * See docs/architecture/DESLOP_SOP.md for full specification.
 */
module.exports = {
  forbidden: [
    // ── Layer boundary: components must not reach into pages ──
    {
      name: "no-component-importing-page",
      comment:
        "Components are reusable building blocks — they must not know about specific pages. " +
        "If a component needs page-level data, lift it via props or context.",
      severity: "error",
      from: { path: "^src/components/" },
      to: { path: "^src/pages/" },
    },

    // ── Layer boundary: hooks must not import components or pages ──
    {
      name: "no-hook-importing-ui",
      comment:
        "Hooks encapsulate stateful logic — they must not depend on specific UI components. " +
        "Return data from hooks; let components decide how to render it.",
      severity: "error",
      from: { path: "^src/hooks/" },
      to: { path: "^src/(components|pages)/" },
    },

    // ── Layer boundary: services must not import UI ──
    {
      name: "no-service-importing-ui",
      comment:
        "Services handle API communication — they must not depend on React components or pages.",
      severity: "error",
      from: { path: "^src/services/" },
      to: { path: "^src/(components|pages|hooks)/" },
    },

    // ── No test code in production ──
    {
      name: "no-test-in-production",
      comment: "Production code must not import from test directories.",
      severity: "error",
      from: { pathNot: "^src/(__tests__|test)/" },
      to: { path: "^src/(__tests__|test)/" },
    },

    // ── No unreachable (orphan) modules ──
    // Note: this is handled by Knip, not dependency-cruiser rules.
    // dependency-cruiser focuses on forbidden dependency directions.

    // ── No circular dependencies ──
    {
      name: "no-circular",
      comment: "Circular dependencies make code harder to understand and test.",
      severity: "error",
      from: {},
      to: { circular: true },
    },
  ],
  options: {
    doNotFollow: {
      path: "node_modules",
    },
    exclude: {
      path: "^node_modules/",
    },
  },
};
