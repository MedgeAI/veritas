"""CSS styles for the static audit HTML report."""

# This constant is imported by _core.py to keep the entry-point module small.
REPORT_CSS = """
    :root {
      --bg: #f3efe4;
      --paper: #fffdf7;
      --ink: #20241d;
      --muted: #687064;
      --line: #d8d0bf;
      --accent: #1e5c4f;
      --accent2: #a35f26;
      --danger: #9b3d2f;
      --soft: #f8f3e8;
      --green: #dfeee7;
      --amber: #f4e1bf;
      --red: #f2d7d0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 0%, rgba(30, 92, 79, .18), transparent 28rem),
        radial-gradient(circle at 86% 12%, rgba(163, 95, 38, .16), transparent 30rem),
        linear-gradient(180deg, #f6f0e3 0%, #ede6d7 100%);
      font: 15px/1.55 "Alegreya Sans", "Noto Serif SC", "Source Han Serif SC", Georgia, serif;
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
      background: rgba(255, 253, 247, .92);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 22px 60px rgba(54, 45, 28, .10);
      padding: 24px;
    }
    .hero-brief {
      display: flex;
      flex-direction: column;
      min-height: 560px;
      color: #fffaf0;
      background:
        radial-gradient(circle at 12% 20%, rgba(244, 225, 191, .20), transparent 18rem),
        linear-gradient(135deg, #18251f 0%, #214f45 56%, #7f4b25 140%);
      border-color: rgba(255, 250, 240, .24);
    }
    .hero-brief .eyebrow,
    .hero-brief .muted {
      color: rgba(255, 250, 240, .72);
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
      border: 1px solid rgba(255, 250, 240, .24);
      border-radius: 999px;
      padding: 5px 10px;
      color: rgba(255, 250, 240, .78);
      background: rgba(255, 250, 240, .08);
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
      color: #2b1810;
      background: #f4e1bf;
      border: 1px solid rgba(244, 225, 191, .8);
      font-weight: 900;
      letter-spacing: .02em;
    }
    .verdict-badge.outline {
      color: rgba(255, 250, 240, .86);
      background: rgba(255, 250, 240, .06);
      border-color: rgba(255, 250, 240, .28);
    }
    .hero-brief h1 {
      max-width: 920px;
      color: #fffdf7;
      font-size: clamp(42px, 5.3vw, 82px);
      letter-spacing: -.055em;
    }
    .hero-brief .lead {
      max-width: 980px;
      color: rgba(255, 250, 240, .86);
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
      border: 1px solid rgba(255, 250, 240, .22);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255, 250, 240, .08);
    }
    .hero-stat .num {
      color: #fffdf7;
      font-size: 32px;
      line-height: 1;
      font-weight: 900;
      letter-spacing: -.04em;
    }
    .hero-stat .label {
      margin-top: 8px;
      color: rgba(255, 250, 240, .68);
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
      border-radius: 18px;
      background: #fffaf0;
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
      color: #3f463c;
    }
    .pattern-card {
      border: 1px solid var(--line);
      border-radius: 30px;
      padding: 24px;
      background:
        linear-gradient(135deg, rgba(255,253,247,.96) 0%, rgba(255,247,233,.96) 100%);
      box-shadow: 0 18px 48px rgba(54, 45, 28, .08);
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
      border-radius: 18px;
      color: #fffaf0;
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
      color: #343b31;
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
      border-bottom: 1px solid rgba(216, 208, 191, .65);
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
    .lead { max-width: 900px; font-size: 19px; color: #3f463c; margin: 18px 0 0; }
    .muted { color: var(--muted); }
    .grid { display: grid; gap: 16px; }
    .cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metric { border: 1px solid var(--line); border-radius: 18px; padding: 16px; background: #fffaf0; }
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
    .badge.critical { background: #f4c7bd; color: #6b1e16; border-color: #e4a99d; }
    .badge.high { background: var(--red); color: #6b1e16; border-color: #e4b4aa; }
    .badge.medium, .badge.warning { background: var(--amber); color: #70430f; border-color: #e3c48d; }
    .badge.low, .badge.info, .badge.context { background: #ece7dc; color: #625a4c; }
    .badge.ran, .badge.reused { background: var(--green); color: #214d3e; border-color: #bdd8ca; }
    .badge.skipped { background: #ece7dc; color: #625a4c; }
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
      background: rgba(255,255,255,.62);
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
      color: #fffaf0;
      font-weight: 900;
      font-size: 12px;
    }
    .cluster-card {
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 22px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff4df 100%);
      box-shadow: 0 18px 48px rgba(54, 45, 28, .08);
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
      border-radius: 24px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff7e9 100%);
      margin-bottom: 16px;
    }
    .finding-title { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .kv { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 8px 12px; font-size: 14px; }
    .kv div:nth-child(odd) { color: var(--muted); }
    .quote { border-left: 4px solid var(--accent); padding: 10px 12px; background: #f4f0e6; border-radius: 0 12px 12px 0; margin: 10px 0; }
    .samples { display: grid; gap: 8px; margin-top: 10px; }
    .sample-row { display: grid; grid-template-columns: 52px 1fr 1fr; gap: 8px; font-family: "JetBrains Mono", monospace; font-size: 12px; }
    .lane { padding: 10px; border: 1px solid var(--line); border-radius: 14px; background: rgba(255,255,255,.72); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    .artifact-list { display: grid; gap: 8px; }
    .artifact { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
    details { border: 1px solid var(--line); border-radius: 16px; padding: 12px 14px; background: rgba(255,255,255,.65); }
    summary { cursor: pointer; font-weight: 800; }
    .footer { margin: 24px 0 8px; color: var(--muted); text-align: center; }
    @media (max-width: 980px) {
      .hero, .finding-card, .cluster-top, .pattern-head, .hero-stat-grid, .cols-4, .cols-3, .cols-2 { grid-template-columns: 1fr; }
      .hero-brief { min-height: auto; }
      .section-head { align-items: flex-start; flex-direction: column; }
      .wrap { padding: 14px; }
      .panel { padding: 18px; border-radius: 18px; }
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
      border-radius: 20px;
      padding: 16px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff7e9 100%);
      box-shadow: 0 12px 32px rgba(54, 45, 28, .06);
    }
    .visual-figure-card img {
      width: 100%;
      height: 180px;
      object-fit: cover;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #f4f0e6;
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
      border-radius: 16px;
      padding: 12px;
      background: #fffaf0;
    }
    .visual-panel-card img {
      width: 100%;
      height: 120px;
      object-fit: cover;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #f4f0e6;
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
      border-radius: 24px;
      padding: 20px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff4df 100%);
      box-shadow: 0 18px 48px rgba(54, 45, 28, .08);
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
      background: #f4f0e6;
    }
    .visual-placeholder {
      display: grid;
      place-items: center;
      width: 100%;
      height: 160px;
      border-radius: 12px;
      border: 1px dashed var(--line);
      background: #f4f0e6;
      color: var(--muted);
      font-size: 12px;
    }
    .visual-review-checklist {
      margin-top: 16px;
    }
    .visual-review-checklist li {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,.65);
      margin-bottom: 8px;
    }
    .finding-card, [id^="finding-"] { scroll-margin-top: 80px; }
    .conf-badge { display: inline-flex; align-items: center; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; font-weight: 600; }
    .conf-rule { background: #e8e0d0; color: #5a5040; }
    .conf-data { background: #dfeee7; color: #1e5c4f; }
    .conf-agent { background: #e0e8f4; color: #2c4a7c; }
    /* Three-Layer Certainty UI */
    .certainty-layers {
      display: grid;
      gap: 12px;
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px dashed var(--line);
    }
    .certainty-fact {
      background: #2a2f28;
      color: #e8e4d8;
      padding: 12px 14px;
      border-radius: 12px;
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
      line-height: 1.6;
    }
    .certainty-fact::before {
      content: "FACT";
      display: block;
      font-size: 10px;
      font-weight: 900;
      letter-spacing: .08em;
      color: #a8a090;
      margin-bottom: 6px;
    }
    .certainty-inference {
      background: rgba(139, 92, 246, .08);
      border-left: 3px solid #8b5cf6;
      padding: 12px 14px;
      border-radius: 0 12px 12px 0;
      font-style: italic;
      color: #5b21b6;
      font-size: 14px;
    }
    .certainty-inference::before {
      content: "INFERENCE";
      display: block;
      font-size: 10px;
      font-weight: 900;
      letter-spacing: .08em;
      color: #8b5cf6;
      margin-bottom: 6px;
      font-style: normal;
    }
    .certainty-suggestion {
      background: rgba(34, 197, 94, .08);
      border-left: 3px solid #22c55e;
      padding: 12px 14px;
      border-radius: 0 12px 12px 0;
      color: #166534;
      font-size: 14px;
    }
    .certainty-suggestion::before {
      content: "SUGGESTION";
      display: block;
      font-size: 10px;
      font-weight: 900;
      letter-spacing: .08em;
      color: #22c55e;
      margin-bottom: 6px;
    }
"""
