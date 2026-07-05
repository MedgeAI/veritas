"""CSS styles for the static audit HTML report."""

# This constant is imported by _core.py to keep the entry-point module small.
REPORT_CSS = """
    :root {
      --bg: #FFFFFF;
      --paper: #F9FAFB;
      --ink: #111827;
      --muted: #6B7280;
      --line: #E5E7EB;
      --accent: #1E40AF;
      --accent2: #2563EB;
      --danger: #DC2626;
      --soft: #F3F4F6;
      --green: #D1FAE5;
      --amber: #FEF3C7;
      --red: #FEE2E2;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: #FFFFFF;
      font: 15px/1.55 "Inter", "Source Sans 3", "Noto Sans SC", "Source Han Sans SC", system-ui, sans-serif;
    }
    a { color: var(--accent); text-decoration: none; }
    code { font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace; font-size: 12px; }
    .wrap { max-width: 1440px; margin: 0 auto; padding: 28px; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.04fr) minmax(420px, .96fr);
      gap: 20px;
      align-items: stretch;
      margin-bottom: 20px;
    }
    .panel {
      background: #FFFFFF;
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
      padding: 24px;
    }
    .hero-brief {
      display: flex;
      flex-direction: column;
      min-height: 560px;
      color: #FFFFFF;
      background: linear-gradient(180deg, #1E3A5F 0%, #1E40AF 100%);
      border-color: rgba(255, 255, 255, .24);
    }
    .hero-brief .eyebrow,
    .hero-brief .muted {
      color: rgba(255, 255, 255, .72);
    }
    .hero-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 28px;
    }
    .meta-chip {
      display: inline-flex;
      max-width: 100%;
      align-items: center;
      border: 1px solid rgba(255, 255, 255, .24);
      border-radius: 999px;
      padding: 5px 10px;
      color: rgba(255, 255, 255, .78);
      background: rgba(255, 255, 255, .08);
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
    }
    .verdict-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }
    .verdict-badge {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 8px 12px;
      color: #1E3A5F;
      background: #DBEAFE;
      border: 1px solid rgba(219, 234, 254, .8);
      font-weight: 900;
      letter-spacing: .02em;
    }
    .verdict-badge.outline {
      color: rgba(255, 255, 255, .86);
      background: rgba(255, 255, 255, .06);
      border-color: rgba(255, 255, 255, .28);
    }
    .hero-brief h1 {
      max-width: 920px;
      color: #FFFFFF;
      font-size: clamp(42px, 5.3vw, 82px);
      letter-spacing: -.055em;
    }
    .hero-brief .lead {
      max-width: 980px;
      color: rgba(255, 255, 255, .86);
      font-size: clamp(18px, 1.55vw, 24px);
      line-height: 1.5;
    }
    .hero-stat-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: auto;
      padding-top: 28px;
    }
    .hero-stat {
      border: 1px solid rgba(255, 255, 255, .22);
      border-radius: 6px;
      padding: 14px;
      background: rgba(255, 255, 255, .08);
    }
    .hero-stat .num {
      color: #FFFFFF;
      font-size: 32px;
      line-height: 1;
      font-weight: 900;
      letter-spacing: -.04em;
    }
    .hero-stat .label {
      margin-top: 8px;
      color: rgba(255, 255, 255, .68);
      font-size: 13px;
    }
    .action-panel {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .hero-evidence-list {
      display: grid;
      gap: 12px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .hero-evidence-list li {
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #FFFFFF;
    }
    .evidence-kicker {
      color: var(--accent);
      font-weight: 900;
      font-size: 13px;
    }
    .action-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 20px;
      color: #374151;
    }
    .pattern-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 24px;
      background: #FFFFFF;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
      margin-bottom: 18px;
      content-visibility: auto;
      contain-intrinsic-size: 360px;
    }
    .pattern-head {
      display: grid;
      grid-template-columns: 72px minmax(0, 1fr) minmax(220px, .34fr);
      gap: 18px;
      align-items: start;
    }
    .pattern-id {
      display: grid;
      place-items: center;
      width: 58px;
      height: 58px;
      border-radius: 6px;
      color: #FFFFFF;
      background: var(--accent);
      font-weight: 900;
      letter-spacing: -.03em;
    }
    .pattern-title {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .pattern-title h3 {
      font-size: 24px;
    }
    .pattern-thesis {
      font-size: 18px;
      color: #111827;
      margin: 0;
    }
    .pattern-facts {
      display: grid;
      gap: 8px;
      border-left: 4px solid var(--accent);
      padding-left: 14px;
    }
    .pattern-facts div {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid rgba(229, 231, 235, .65);
      padding-bottom: 6px;
    }
    .pattern-actions {
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }
    .noise-table {
      margin-top: 12px;
      overflow-x: auto;
    }
    .noise-cell {
      max-width: 320px;
      overflow-wrap: anywhere;
    }
    .eyebrow { color: var(--accent); font-weight: 800; letter-spacing: .08em; text-transform: uppercase; font-size: 12px; }
    h1, h2, h3 { margin: 0; line-height: 1.1; }
    h1 { font-size: clamp(34px, 5vw, 68px); letter-spacing: -.04em; margin-top: 10px; }
    h2 { font-size: 26px; margin-bottom: 16px; }
    h3 { font-size: 18px; margin-bottom: 10px; }
    .lead { max-width: 900px; font-size: 19px; color: #374151; margin: 18px 0 0; }
    .muted { color: var(--muted); }
    .grid { display: grid; gap: 16px; }
    .cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metric { border: 1px solid var(--line); border-radius: 6px; padding: 16px; background: var(--soft); }
    .metric .num { font-size: 34px; line-height: 1; font-weight: 900; letter-spacing: -.04em; }
    .metric .label { color: var(--muted); margin-top: 8px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
      border: 1px solid var(--line);
      background: #fff;
      white-space: nowrap;
    }
    .badge.critical { background: #FEE2E2; color: #991B1B; border-color: #FECACA; }
    .badge.high { background: #FEE2E2; color: #991B1B; border-color: #FECACA; }
    .badge.medium, .badge.warning { background: #FEF3C7; color: #92400E; border-color: #FDE68A; }
    .badge.low, .badge.info, .badge.context { background: #F3F4F6; color: #6B7280; }
    .badge.ran, .badge.reused { background: #D1FAE5; color: #065F46; border-color: #A7F3D0; }
    .badge.skipped { background: #F3F4F6; color: #6B7280; }
    .section { margin-top: 20px; }
    .panel.section, .cluster-card, .compact-details, .finding-card {
      content-visibility: auto;
      contain-intrinsic-size: 280px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 18px;
      margin-bottom: 16px;
    }
    .quick-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }
    .quick-nav a {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 7px 12px;
      background: #FFFFFF;
      font-weight: 800;
      font-size: 13px;
    }
    .brief-list {
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .brief-list li {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }
    .rank {
      display: inline-grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border-radius: 999px;
      background: var(--accent);
      color: #FFFFFF;
      font-weight: 900;
      font-size: 12px;
    }
    .cluster-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 22px;
      background: #FFFFFF;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
      margin-bottom: 16px;
    }
    .cluster-top {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 18px;
    }
    .cluster-title {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }
    .signal-list {
      display: grid;
      gap: 8px;
      margin: 12px 0 0;
      padding-left: 18px;
    }
    .compact-details > summary {
      list-style: none;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 4px 0;
    }
    .compact-details > summary::-webkit-details-marker { display: none; }
    .appendix-grid {
      display: grid;
      gap: 14px;
    }
    .finding-card {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 18px;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #FFFFFF;
      margin-bottom: 16px;
    }
    .finding-title { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .kv { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 8px 12px; font-size: 14px; }
    .kv div:nth-child(odd) { color: var(--muted); }
    .quote { border-left: 4px solid var(--accent); padding: 10px 12px; background: var(--soft); border-radius: 0 4px 4px 0; margin: 10px 0; }
    .samples { display: grid; gap: 8px; margin-top: 10px; }
    .sample-row { display: grid; grid-template-columns: 52px 1fr 1fr; gap: 8px; font-family: "JetBrains Mono", monospace; font-size: 12px; }
    .lane { padding: 10px; border: 1px solid var(--line); border-radius: 6px; background: #F9FAFB; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    .artifact-list { display: grid; gap: 8px; }
    .artifact { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
    details { border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; background: #F9FAFB; }
    summary { cursor: pointer; font-weight: 800; }
    .footer { margin: 24px 0 8px; color: var(--muted); text-align: center; }
    @media (max-width: 980px) {
      .hero, .finding-card, .cluster-top, .pattern-head, .hero-stat-grid, .cols-4, .cols-3, .cols-2 { grid-template-columns: 1fr; }
      .hero-brief { min-height: auto; }
      .section-head { align-items: flex-start; flex-direction: column; }
      .wrap { padding: 14px; }
      .panel { padding: 18px; border-radius: 6px; }
    }
    .category-group { margin-bottom: 32px; }
    .category-heading {
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
      margin: 0 0 16px 0;
      padding-bottom: 8px;
      border-bottom: 2px solid var(--accent);
    }
    .category-count {
      font-size: 14px;
      font-weight: 400;
      color: var(--muted);
      margin-left: 8px;
    }
    /* PRD2-T7: Layer-grouped findings */
    .layer-group { margin-bottom: 32px; }
    .layer-heading {
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
      margin: 0 0 8px 0;
    }
    .layer-count {
      font-size: 14px;
      font-weight: 400;
      color: var(--muted);
      margin-left: 8px;
    }
    .layer-group.layer-1 .layer-heading { border-left: 4px solid var(--critical); padding-left: 12px; }
    .layer-group.layer-2 .layer-heading { border-left: 4px solid var(--warn); padding-left: 12px; }
    .layer-group.layer-3 .layer-heading { border-left: 4px solid var(--muted); padding-left: 12px; }
    /* Visual Evidence Package styles */
    .visual-figure-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .visual-figure-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
      background: #FFFFFF;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
    }
    .visual-figure-card img {
      width: 100%;
      height: 180px;
      object-fit: cover;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #F3F4F6;
    }
    .visual-figure-card h4 {
      margin: 12px 0 8px;
      font-size: 16px;
    }
    .visual-figure-card .muted {
      font-size: 13px;
    }
    .visual-panel-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .visual-panel-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #F9FAFB;
    }
    .visual-panel-card img {
      width: 100%;
      height: 120px;
      object-fit: cover;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #F3F4F6;
    }
    .visual-panel-card .panel-label {
      font-weight: 800;
      margin-top: 8px;
      font-size: 14px;
    }
    .visual-panel-card .panel-meta {
      font-size: 11px;
      color: var(--muted);
      margin-top: 4px;
    }
    .visual-relationship-table {
      margin-top: 16px;
    }
    .visual-finding-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 20px;
      background: #FFFFFF;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
      margin-bottom: 16px;
    }
    .visual-finding-card .finding-header {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .visual-finding-card .overlay-compare {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .visual-finding-card .overlay-compare img {
      width: 100%;
      height: 160px;
      object-fit: cover;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #F3F4F6;
    }
    .visual-placeholder {
      display: grid;
      place-items: center;
      width: 100%;
      height: 160px;
      border-radius: 12px;
      border: 1px dashed var(--line);
      background: var(--soft);
      color: var(--muted);
      font-size: 12px;
    }
    .visual-review-checklist {
      margin-top: 16px;
    }
    .visual-review-checklist li {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #F9FAFB;
      margin-bottom: 8px;
    }
    .finding-card, [id^="finding-"] { scroll-margin-top: 80px; }
    .conf-badge { display: inline-flex; align-items: center; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; font-weight: 600; }
    .conf-rule { background: #F3F4F6; color: #374151; }
    .conf-data { background: #DBEAFE; color: #1E40AF; }
    .conf-agent { background: #EDE9FE; color: #5B21B6; }
    /* Three-layer certainty model */
    .certainty-fact {
      background: #F8FAFC;
      color: #1E293B;
      font-size: 13px;
      padding: 8px 12px;
      border-radius: 6px;
      margin: 6px 0;
      line-height: 1.5;
      border-left: 3px solid #1E40AF;
    }
    .certainty-fact .layer-label {
      display: inline-block;
      color: #1E40AF;
      font-weight: 700;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: 2px;
    }
    .certainty-inference {
      background: #F5F3FF;
      color: #5B21B6;
      font-style: italic;
      font-size: 13px;
      padding: 8px 12px;
      border-radius: 6px;
      margin: 6px 0;
      line-height: 1.5;
      border-left: 3px solid #8B5CF6;
    }
    .certainty-inference .layer-label {
      display: inline-block;
      color: #7C3AED;
      font-weight: 700;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .06em;
      font-style: normal;
      margin-bottom: 2px;
    }
    .certainty-inference .layer-disclaimer {
      display: block;
      margin-top: 4px;
      font-size: 10px;
      color: #9333EA;
      font-style: normal;
      opacity: .6;
    }
    .certainty-suggestion {
      background: #F0FDF4;
      color: #166534;
      font-size: 13px;
      padding: 8px 12px;
      border-radius: 6px;
      margin: 6px 0;
      line-height: 1.5;
      border-left: 3px solid #4ADE80;
    }
    .certainty-suggestion .layer-label {
      display: inline-block;
      color: #15803D;
      font-weight: 700;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: 2px;
    }
    /* Grade badge */
    .grade-badge-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      margin: 18px 0 6px;
    }
    .grade-badge {
      display: grid;
      place-items: center;
      width: 84px;
      height: 84px;
      border-radius: 50%;
      font-family: "Inter", system-ui, sans-serif;
      font-size: 44px;
      font-weight: 900;
      letter-spacing: -.04em;
      color: #FFFFFF;
      border: 3px solid rgba(255, 255, 255, .32);
    }
    .grade-badge.grade-a { background: #059669; }
    .grade-badge.grade-b { background: #2563EB; }
    .grade-badge.grade-c { background: #D97706; }
    .grade-badge.grade-d { background: #DC2626; }
    .grade-label {
      color: rgba(255, 255, 255, .82);
      font-size: 14px;
      font-weight: 700;
      letter-spacing: .04em;
    }
    /* Four-dimension summary grid */
    .dimension-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 14px 0;
    }
    .dim-card {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px 14px;
      background: #FFFFFF;
    }
    .dim-card .dim-name {
      font-size: 13px;
      font-weight: 800;
      color: var(--ink);
      margin-bottom: 6px;
    }
    .dim-card .dim-status {
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 999px;
      margin-bottom: 6px;
    }
    .dim-card .dim-status.status-ok { background: var(--green); color: #065F46; }
    .dim-card .dim-status.status-warn { background: var(--amber); color: #92400E; }
    .dim-card .dim-status.status-fail { background: var(--red); color: #991B1B; }
    .dim-card .dim-status.status-info { background: #DBEAFE; color: #1E40AF; }
    .dim-card .dim-detail {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }
    /* View-mode toggle (author / gatekeeper) */
    .view-gatekeeper .author-only { display: none; }
    .view-author .gatekeeper-only { display: none; }
    .gatekeeper-banner {
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 14px;
      color: var(--muted);
      font-size: 13px;
      text-align: center;
      margin-bottom: 16px;
    }
    .gatekeeper-footer {
      margin-top: 24px;
      padding: 14px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      text-align: center;
      letter-spacing: .02em;
    }
    .finding-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    .finding-actions a,
    .finding-actions button {
      font-size: 12px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--accent);
      cursor: pointer;
      font-weight: 700;
    }
    .evidence-link {
      font-size: 12px;
      color: var(--accent);
      font-weight: 700;
    }
    /* Formal document heading style */
    h1, h2, h3 { font-family: "Inter", system-ui, sans-serif; }
    /* ============================================
     * Formal "legal opinion" Hero layout (W1-1)
     * ============================================ */
    .report-header-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-weight: 700;
      color: rgba(255, 255, 255, 0.72);
      font-family: "IBM Plex Sans", "Inter", sans-serif;
      margin-bottom: 10px;
    }
    .report-id-hero {
      font-family: "IBM Plex Mono", "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 26px;
      letter-spacing: 0.05em;
      font-weight: 600;
      color: #FFFFFF;
      line-height: 1.1;
      margin-bottom: 18px;
      word-break: break-all;
    }
    .hero-title-row {
      display: flex;
      align-items: center;
      gap: 18px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .hero-title-row .grade-badge-wrap {
      margin: 0;
      flex-shrink: 0;
    }
    .hero-title-row .hero-title-text {
      flex: 1 1 auto;
      min-width: 0;
    }
    .hero-title-row .hero-title-text h1 {
      font-size: clamp(28px, 4vw, 48px);
      letter-spacing: -.02em;
      margin: 0;
    }
    .hero-title-row .hero-title-text .lead {
      margin-top: 6px;
      font-size: 15px;
    }
    .hero-meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 14px;
      color: rgba(255, 255, 255, 0.78);
      font-family: "IBM Plex Mono", "JetBrains Mono", monospace;
      font-size: 12px;
    }
    .hero-meta-row .meta-divider {
      color: rgba(255, 255, 255, 0.36);
    }
    .immutable-statement {
      font-style: italic;
      color: rgba(255, 255, 255, 0.62);
      border-top: 1px solid rgba(255, 255, 255, 0.18);
      padding-top: 12px;
      margin-top: 18px;
      font-size: 13px;
      line-height: 1.5;
      text-align: center;
      font-family: "Inter", system-ui, sans-serif;
    }
    /* ============================================
     * Risk-level color bar (W2-3)
     * ============================================ */
    .has-risk-bar {
      display: grid;
      grid-template-columns: 5px minmax(0, 1fr);
      gap: 14px;
    }
    .pattern-card.has-risk-bar {
      grid-template-columns: 5px minmax(0, 1fr);
    }
    .finding-card.has-risk-bar {
      grid-template-columns: 5px minmax(0, 1fr) 320px;
    }
    .risk-bar {
      border-radius: 4px;
      align-self: stretch;
      min-height: 100%;
    }
    .risk-bar-critical { background: #991B1B; }
    .risk-bar-high     { background: #DC2626; }
    .risk-bar-medium   { background: #D97706; }
    .risk-bar-low      { background: #059669; }
    .risk-bar-info,
    .risk-bar-context  { background: #9CA3AF; }
    @media (max-width: 980px) {
      .hero-title-row { flex-direction: column; align-items: flex-start; }
      .report-id-hero { font-size: 20px; }
      .has-risk-bar { grid-template-columns: 1fr; }
      .finding-card.has-risk-bar { grid-template-columns: 1fr; }
      .risk-bar { min-height: 5px; width: 100%; }
    }
    @media (max-width: 980px) {
      .dimension-grid { grid-template-columns: 1fr 1fr; }
    }
    /* Inline evidence table (inside finding cards) */
    .evidence-details {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 12px;
      background: #FFFFFF;
      margin: 8px 0;
    }
    .evidence-details > summary {
      font-size: 12px;
      color: var(--muted);
    }
    .ev-table {
      width: 100%;
      border-collapse: collapse;
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      margin: 12px 0;
    }
    .ev-table th,
    .ev-table td {
      border: 1px solid var(--line);
      padding: 4px 8px;
      text-align: right;
      max-width: 200px;
      overflow-wrap: anywhere;
    }
    .ev-table th {
      background: var(--soft);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
      position: sticky;
      top: 0;
      z-index: 1;
    }
    .ev-row-label {
      color: var(--muted);
      text-align: right;
      font-size: 11px;
      background: var(--soft);
      min-width: 32px;
      white-space: nowrap;
    }
    .ev-cell-hi {
      background: #FEF3C7;
      color: #92400E;
      font-weight: 600;
    }
    .ev-col-hi {
      background: rgba(254, 243, 199, .35);
    }
    /* Report filter sidebar */
    .report-filters {
      position: sticky;
      top: 0;
      z-index: 10;
      background: #FFFFFF;
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
      padding: 12px 24px;
      display: flex;
      gap: 24px;
      align-items: center;
      flex-wrap: wrap;
      font-size: 13px;
      margin-bottom: 20px;
    }
    .report-filters fieldset {
      border: none;
      padding: 0;
      margin: 0;
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .report-filters legend {
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      color: var(--muted);
      margin-right: 6px;
      letter-spacing: .04em;
    }
    .report-filters label {
      display: flex;
      gap: 4px;
      align-items: center;
      cursor: pointer;
      font-size: 12px;
    }
    .report-filters input[type="search"] {
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 6px 10px;
      font-size: 13px;
      min-width: 200px;
      outline: none;
    }
    .report-filters input[type="search"]:focus {
      border-color: var(--accent2);
      box-shadow: 0 0 0 2px rgba(37, 99, 235, .15);
    }
    .report-filters button {
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 6px 12px;
      background: var(--soft);
      cursor: pointer;
      font-size: 12px;
      color: var(--ink);
    }
    .report-filters button:hover {
      background: var(--line);
    }
    .filter-count {
      font-size: 12px;
      color: var(--muted);
      margin-left: auto;
      font-variant-numeric: tabular-nums;
    }
    @media print {
      .report-filters {
        display: none !important;
      }
    }
"""
