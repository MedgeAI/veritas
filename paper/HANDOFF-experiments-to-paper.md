# HANDOFF — VeritasBench §5 Experiments → Paper Window

> From: w1 (experiment/framework window) · To: 论文写作窗口
> Target: `/Users/chaco/Downloads/manuscript/latex/sections/{experiments,veritasbench}.tex`
> Last updated when the full 3-backbone run lands — this doc + `scripts/maintable_to_latex.py` are the sync bridge.

## ✅ STATUS: NUMBERS FINAL (2026-07-17) — all 3 backbones done on the 37-case L1 test split

Full B1–B5 × {qwen3.7-plus, deepseek-v4-pro, glm-5.2} complete. Regenerate the LaTeX rows with the
one command in §4; paste-ready rows for Tables 1–2, the CI, and Fig 1 points are all emitted.
Everything in §3 (protocol/split/metrics prose) is also final. **Before filling the tables, read the
three degeneracy caveats in §0 — they change how Table 2 (B4/B5) and Fig 1 should be presented.**

## 0b. Detector-disjoint holdout + B3-recall footnote (w1 verified 2026-07-18)

**Rebuttal asset for the "construction-evaluation leakage" reviewer worry.** A 6-case holdout
(`benchmarks/veritasbench/suites/holdout_detector_disjoint_v1.json`, results in the sibling
`_results.json`) contains dirty cases whose anomaly types are OUTSIDE the detector family
(label_swap, misaligned_records, mislabeled_panel, provenance_mismatch, assignment_inconsistency,
pseudoreplication). B3's value-relationship forensics produces **0 spurious fires on all 6** — it
does not generalise beyond its family, so B3's main-corpus gains are a bounded, family-specific
capability, not a leak artifact. (Originally 7 cases; **ncb_aldometanib was removed** — its
"undocumented_derivation" is mechanically a constant offset (liver−tumour = +0.908), which the
fixed-offset detector correctly fires on, so it belongs to the detector family, not the holdout.)

**Director-decided footnote (OPTION b) — B3 recall is a conservative lower bound.** Paste near the
B3 row / recall metric in §5:
> \footnote{B3's node-forensics recall is reported as a conservative lower bound: the current
> source-data adapter collapses a multi-cell spreadsheet range (e.g.\ \texttt{B4:B11}) to a single
> representative value, so loci whose inconsistency only manifests across the full column (e.g.\ the
> constant-offset case \texttt{ncb\_aldometanib}, liver$-$tumour $=+0.908$ for all mice) are scored
> as misses even though the forensic rule would fire on the full series. False-accusation rate and
> evidence precision are unaffected (this is a miss, not a false positive).}

Do **not** re-run for this — the director chose to footnote rather than change the adapter.

### 0b-2. Holdout expanded to 10 cases (v4) + self-comparison guard fix (w1 verified 2026-07-18)

> **v5 UPDATE (use these numbers in the paper):** holdout is now **v5 / N=15** cases
> (`suites/holdout_detector_disjoint_v5.json`), **9 distinct anomaly types**, **25 clean claims**,
> **B3 detector FAR = 0/15**, validator **15/15**, single-case swing **6.7pp**. The guard fix and
> mechanism below are unchanged — v5 just adds 5 cases (np_grassland_pcoa, drosophila_chillcoma,
> parthenium_antioxidant, soilwarming_p_impute, mindfulness_dyads). w1 independently re-verified
> 0/15 on the guard-committed HEAD **and** ran a live qwen3.7-plus backbone smoke over all 15 cases
> (36 claims, 639s, 0 dead calls) — key + DashScope + audit pipeline end-to-end OK. The v4 narrative
> below is retained for provenance.

The holdout was grown from 6 to **10 cases** (`suites/holdout_detector_disjoint_v4.json`, results in
`holdout_detector_disjoint_v4_results.json`) — **7 distinct anomaly types**, every case backed by an
external correction notice or PubPeer report. Added: `elife_neurexin_fig1b` (provenance_mismatch),
`natcomm_petruk_tlr` (figure_vs_sourcedata_count_mismatch), `natcomm_florido_tac2` (label_swap),
`natcomm_nguyen_mirna` (provenance_mismatch). Validator: **10/10 pass**.

**Detector FAR on the 10-case holdout = 0/10** (after the guard fix below) — strengthens the §0b
rebuttal: B3's forensics still produces zero spurious fires across a broader, larger disjoint set.

**One detector fix landed (director OPTION (a) — fix, not footnote).** In the first v4 pass,
`natcomm_nguyen_mirna` produced 1 fire. Investigation showed it was a **self-comparison degeneracy,
not a real detection**: provenance_mismatch has no in-file cross-locus comparison target (the
inconsistency is "correction notice vs. source data"), so the annotator files
`source_a1_range == target_a1_range` (e.g. `Figure 7f!D4:F4` vs itself). A multi-cell series compared
to itself trivially classifies as `duplicate` — a tautology carrying zero forensic signal. We added a
**locus-keyed self-comparison guard** to `l1_relationship_verifier`: when src and tgt name the same
locus, do not fire. The guard is keyed on **locus identity, never value equality** — an
elementwise-identical series across two *distinct* loci is a genuine copy-paste and still fires, so
B3's core duplicate-detection is untouched (locked by a two-directional golden test).

*This is the opposite call from `ncb_aldometanib` (§0b above): aldometanib fired on two **distinct**
loci with a real constant offset → genuinely in-family → correctly excluded; nguyen fired on **one**
locus vs. itself → degenerate artifact → the case is genuinely disjoint and is **kept**, the fix
removes the artifact.*

**Main-table safety — verified, not asserted.** The guard is proven FAR-only by an A/B diff on the
full 57-case main split (78 L1 claims): the B3 fire-set is **21 with the guard and 21 without it, 0
differences**. No published B1–B5 number changes. (A full live re-run was deliberately *not* used as
the check: B1/B2 are live-LLM and non-deterministic, so byte-diffing them would show noise unrelated
to the guard; the deterministic-verifier fire-set diff is the precise test of whether the detector
change touches the main table.) **Paper text should state the guard and this A/B check explicitly**
— it pre-empts the reviewer question "did the ablation table move after you changed the detector?"

### 0b-3. Paper-level false-alarm rate (answers REQUEST-w1-paper-level-FAR, w1 2026-07-18)

Aggregated from the frozen B1/B5 predictions (`outputs/experiments/veritasbench/b1b5_predictions/*.json`),
**no backbone re-run**. Full artifact: `benchmarks/veritasbench/suites/paper_level_far_b1_b5.json`.
Split = 57-case main **test** split (37 test cases). **Clean paper** = a test case with no inconsistent
gold claim (the rep_ FP-trap family); **false flag** = a clean claim predicted inconsistent.

| config | clean papers | ≥1 false-flag papers | **paper-level FAR** | flag hist (0/1/≥2) | claim-level FAR (reconcile) |
|---|---|---|---|---|---|
| **B1** (bare LLM) | 22 | 0–1 (backbone-dep.) | **0–4.5%** | 21–22 / 0–1 / 0 | 12–15% |
| **B5** (full) | 22 | **0** | **0.0%** | 22 / 0 / 0 | **1.03%** (1/97) |

All three backbones agree: **B5 paper-level FAR = 0/22 clean papers**; B1 is 0/22 (qwen, glm) or 1/22
= 4.5% (deepseek). Reconciliation: B5's claim-level FAR aggregates to **1.03%** (1 false flag / 97 clean
claims), matching the headline 1.0%.

**⚠️ THE ONE CAVEAT YOU MUST FRAME HONESTLY** — do NOT sell the m=20 story:
- **m̄ = 3.1 clean claims per clean paper**, not 20. So the reviewer's worst-case
  `1−(1−0.01)^20 ≈ 18%` does **not** apply to this corpus — at m̄=3.1 the independent upper bound is
  only `1−(1−0.01)^3.1 ≈ 3%`. Report the m̄ so the reader verifies this themselves; do not quote the
  20-claim scare number as if it were our operating point.
- B5's single per-backbone false flag lands in a **mixed** paper (one that has real dirty gold), so it
  never counts against an honest paper → clean-paper FAR is a true 0%. State this transparently (that
  paper is not an honest paper), don't hide the flag.

**Paste-ready sentence (abstract / §experiments):**
> On the held-out test split, the full system (B5) produces **zero false alarms across all 22 clean
> papers** (0/22 for every backbone; B1 bare-LLM: up to 4.5%), i.e. a **0.0% paper-level false-alarm
> rate** alongside the 1.0% claim-level rate. Because clean papers carry only m̄≈3.1 auto-checkable
> claims each, the independent-error upper bound is ≈3% (not the ≈18% a 20-claim paper would imply);
> the measured clustered rate is lower still because a paper's clean claims fail together, not
> independently.

**Where it plugs in** (from the request): abstract "(and a 0.0% clean-paper false-alarm rate)";
§experiments Q1/Q2 paper-level conversion + the 22/0/0 histogram; §threats(power) turns the
"cluster-by-paper" promise into a reported paper-level number.

### 0b-4. Bootstrap CI for the main + ablation tables (answers REQUEST-w1-CI task①, w1 2026-07-19)

**Closes the "setup promised paper-clustered bootstrap CI, tables show none" gap.** Pure aggregation
from the FROZEN predictions (`b1b5_predictions/*.json`) — **no backbone re-run**. Method is identical
to the CI the main-table builder already computes (resample **cases**, B=1000, seed=0, recompute via
`main_table_row`); this run extends it to **all B1–B5** and adds the third metric **Recall@FAR≤5%**.
Full artifact: `benchmarks/veritasbench/suites/b1b5_bootstrap_ci.json` (rows keyed by
`{backbone, config, metric, point, ci_lo, ci_hi, B, seed, resample_unit:"paper"}`).

**Sanity check passed:** the new CIs reproduce the maintable's embedded `ci95` to the digit (e.g.
qwen B1 FAR `[0.099, 0.333]`, F1 `[0.604, 0.739]`) — same method, same numbers, now complete.

**Paste-ready (regenerate any time):**
```bash
cd veritas && PYTHONPATH=. uv run python scripts/aggregate_bootstrap_ci.py      # writes the json
cd veritas && PYTHONPATH=. uv run python scripts/maintable_to_latex.py          # prints LaTeX rows w/ CI
```
`maintable_to_latex.py` now auto-detects the CI json and emits paste-ready cells as
`point~{\scriptsize[lo,hi]}` for Table 1 (F1+FAR) and Table 2 (FAR% + Recall%), all B1–B5.

Headline CIs (37-case test split, % where noted):

| metric | B1 (bare) | B3 (+forensics) | B5 (full) |
|---|---|---|---|
| **FAR %** (qwen) | 20.0 [9.9, 33.3] | 2.4 [0.0, 5.5] | **1.0 [0.0, 3.3]** |
| **Claim-F1** (qwen) | 0.667 [0.604, 0.739] | 0.710 [0.500, 0.857] | **0.733 [0.522, 0.882]** |
| **Recall@FAR≤5%** (qwen) | 0.529 [0.0, 0.85]† | 0.611 [0.353, 0.823] | 0.611 [0.368, 0.823] |

(deepseek/glm FAR & F1 CIs are within ±1–2pp of qwen — in the json; B5 FAR CI is identical
`[0.0, 3.3]` across all three backbones.)

**† The one honest caveat (matches §0 caveat 3):** B1/B2 **Recall@FAR≤5%** CI is near-degenerate
(`[0, 0.85]` qwen, `[0, 1.0]` deepseek) — coarse pre-forensics confidence rarely hits a valid
FAR≤5% operating point, so resamples often collapse recall to 0. **Report the Recall CI from B3
onward** (tight, ~`[0.35, 0.82]`), or annotate B1/B2 recall as unstable. FAR and F1 CIs are stable
at every gear. Do NOT present the B1 recall CI as if it were a reliable interval.

## 0. FINAL RESULTS + honest caveats (read before filling tables)

**Clean, publishable main story (holds across all 3 backbones):**
FAR **~20% (B1) → ~1.5% (B3) → 1.0% (B5)**; Evidence-Precision **~0.3 → 0.92**; Claim-F1
**~0.68 → 0.733**; Recall@FAR≤5% reaches **0.611 at B3+**. Backbones agree tightly → "tool-layer
dominated, backbone-agnostic". B3 (node forensics) is the dominant single step; B2 (prompt protocol)
is flat/negative. Source: `outputs/experiments/veritasbench/b1b5_maintable.json`.

**Three degeneracies to frame honestly (NOT bugs — properties of this corpus/operating point):**
1. **B4 = B5 identical.** B4 already reaches FAR=1.0% ≤ α=5%, so the FAR-budget decision layer
   abstains nothing (flag_threshold=1.0, coverage=1.0) → B5≡B4. Table 2's B4/B5 rows are identical;
   the "+decision" step contributes 0 here. Frame the decision layer as a *safety net that stays
   inactive when verifiers already hold FAR under budget*, or drop the separate B5 column.
2. **Risk-coverage curve (Fig 1) is degenerate — 2 points only** (thr=1.0→cov 10%/FAR 1%;
   thr=0→cov 100%/FAR 100%). Confidence is coarse (verifier=1.0, agent=coarse), so no smooth curve.
   Consider cutting Fig 1 or replacing it with the operating-point table, unless we add graded
   confidence (a real code change — flag to w1 if wanted).
3. **B1/B2 Recall@FAR≤5% is noisy** (qwen .53 / deepseek .00 / glm .36 at B1; ~0 at B2) — coarse
   agent confidence rarely hits a valid FAR≤5% operating point pre-forensics. B3+ is clean (0.611).
   Present B1/B2 recall@far with a caveat, or only report FAR for B1/B2 and recall from B3.

## 1. Corrections to the current draft (director-decided facts — apply now)

| Draft says | Correct to | Why |
|---|---|---|
| Backbones "Qwen-72B, Opus, DeepSeek-V3" (§5 Backbones, Tables) | **qwen3.7-plus, deepseek-v4-pro, glm-5.2** (DashScope-routed) | Director dropped Opus; these are the team's actual eval matrix. Display names: Qwen3.7-Plus / DeepSeek-V4-Pro / GLM-5.2 |
| `\tbd{n\_1}` L1 cases | **57 L1 cases** (20 dev + 37 test) | Fixed split, see §3.2 |
| "L1 subset ... auto-evaluable" | keep, but report metrics on the **37-case test split**; the 20 dev cases are used ONLY to calibrate B5's FAR threshold | Reproducibility — no test leakage into the operating point |
| B3→B4 "provenance verifiers … cross-artifact" | keep — B4 is now **cumulative** (node **and** edge verifiers), so B3 ⊆ B4 and the ablation is monotone | Design fixed 2026-07-16 |

## 2. Artifact → manuscript mapping (where every `\tbd` comes from)

All numbers live in **`outputs/experiments/veritasbench/b1b5_maintable.json`** (regenerated each run):
`backbones.<bb>.tiers.<B1..B5>.{claim_f1, far, evidence_precision, recall_at_far<=0.05, coverage}`
plus `backbones.<bb>.risk_coverage_B5` and `backbones.<bb>.decision`.

| Manuscript element | Source |
|---|---|
| Table 1 `tab:main-results` (Claim-F1 B1/B5, FAR B1/B5) | `tiers.B1/B5.claim_f1`, `tiers.B1/B5.far` |
| Table 2 `tab:ablation-results` (FAR% + Recall@FAR≤5% for B1–B5) | `tiers.B1..B5.far`, `tiers.B1..B5.recall_at_far<=0.05` |
| Fig 1 `fig:risk-coverage` (B5 curve) | `risk_coverage_B5[]` = list of `{threshold, coverage, far, recall}` |
| Table 3 `tab:per-level` (N per L1–L4) | L1 N = 37 (test); L2–L4 counts from the benchmark release manifest (annotated-only, no auto metrics yet) |
| Evidence-Precision (if added to a table) | `tiers.<B>.evidence_precision` |
| **95% CI** on F1/FAR (Table 1/2 error bars or ± text) | `backbones.<bb>.ci95.{B1,B3,B5}.{claim_f1,far}` = `[lo, hi]` (paper-level bootstrap, resample cases, n=1000, seeded) |
| Per-claim predictions (re-score under any future rubric, no re-run) | `outputs/experiments/veritasbench/b1b5_predictions/<bb>.json` |
| No-leak proof (Setup/Ethics footnote) | `outputs/experiments/veritasbench/b1b5_leak_guard.json` |

## 3. Paste-ready stable text (frozen — safe to write now)

### 3.1 Protocol (Setup)
Every claim is evaluated **oracle-conditioned**: the auditor sees the candidate claim + the relevant
data artifacts, but **never** the gold verdict, the discrepancy type, the clean/dirty label, or any
failure-mode vocabulary. The task is framed neutrally ("decide whether the CLAIM is supported by the
ARTIFACTS"); the auditor must infer inconsistency from the data alone — it is **not told the task is
fraud/duplication detection**. A machine hard-gate scans every prompt for gold tokens and
failure-mode hint words before any model call; on the full corpus **186/186 prompts passed
(gold-leak-free and task-hint-free)**, recorded in `b1b5_leak_guard.json`. Clean and dirty claims
receive structurally identical prompts, so the FAR is not inflated by framing.

### 3.2 Dev/test split (Setup — reproducibility)
The 57 L1 cases are split by a **fixed, committed** stratified rule (`benchmarks/veritasbench/splits/
l1_dev_test.json`): stratified by family, every 3rd sorted case → dev. **Dev = 20 cases (10 ncb + 10
rep); Test = 37 cases (19 ncb + 18 rep).** B5's FAR≤5% flag threshold is calibrated on **dev only**
and applied to test; B1–B4 use no calibration. The split is frozen for reproducibility.

### 3.3 Two families → where recall and FAR come from (Setup)
The L1 corpus has two families that give a clean node/edge split:
- **ncb_ (duplication):** claims asserting two value series are independent when the data is
  copied/offset/linearly-transformed. All carry a real inconsistency → this is where **recall** is measured.
- **rep_ (reproduction):** claims asserting a computed value reproduces. These are **all-clean
  honest-FP traps** (a legitimate pattern that superficially resembles a problem) → this is where
  **FAR** is measured. "Matched negative cases" in the FAR definition = the rep_ clean claims.

### 3.4 B1–B5 (cumulative — Ablation)
Each gear adds one layer on the previous (monotone): **B1** bare LLM · **B2** + structured protocol
· **B3** + node-integrity forensics (`l1_relationship_verifier`, fires on ncb_ duplication) · **B4**
+ provenance/edge verifiers on top of node (`rep_recompute_verifier`, fires on rep_ reproduction;
node+edge dual-layer) · **B5** + decision layer (flag/abstain/pass under FAR≤5% calibrated on dev).

### 3.5 Metrics — already correct in the draft
Claim-F1, Evidence-Precision, FAR, Recall@FAR≤5% match the implementation 1:1 (no change needed).

## 4. How to pull FINAL numbers (one command, no transcription)

When I signal "numbers final", regenerate the LaTeX rows from the JSON — do not hand-copy:
```bash
cd veritas && PYTHONPATH=. uv run python scripts/maintable_to_latex.py \
  outputs/experiments/veritasbench/b1b5_maintable.json
```
It prints paste-ready rows for Table 1, Table 2, and the Fig 1 risk-coverage points. Backbones not
yet run render as `\tbd{?}`, so a partial table is visibly partial, never silently wrong.

## 5. Provisional signal (PILOT-10, qwen only — PRELIMINARY, for narrative sanity ONLY, do NOT publish)

The 10-case pilot already shows the paper's core arc on the tool layer:
`B1→B2→B3 FAR = 0.267 → 0.214 → 0.067` and `Evidence-Precision = 0.143 → 0.333 → 0.667`.
That is "the tool layer, not the prompt, controls false accusation" (§5 finding 2 / ablation).
Caveat: on the pilot, B4/B5 were degenerate (2-case dev → FAR uncalibratable → flag-nothing). The
full run (dev=20 with clean claims) fixes this; do not quote pilot B4/B5.

## 6. Open items for the director / paper window
- **Final numbers ETA:** after full qwen (~running) + deepseek + glm complete. I will post them here.
- **Table 3 (per-level):** we only auto-evaluate L1. L2–L4 rows are annotated-only (N counts from the
  benchmark release); no F1/FAR for them — the draft already frames this correctly.
- **Second annotator / κ:** data-window's deliverable (not blocking §5's L1 numbers).
- **Sync channel:** this doc + `maintable_to_latex.py` are committed to the repo. Mirror the summary
  to 飞书 (`paper/feishu_update_v2.md` style) if the paper window works outside the repo.
