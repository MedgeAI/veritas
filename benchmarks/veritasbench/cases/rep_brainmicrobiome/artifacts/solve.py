#!/usr/bin/env python3
"""medge-101-1 REFERENCE solution (correct path).

Runs the tumor-vs-normal-brain differential abundance the agent is asked for, then
performs the two rigor checks that resolve the task:
  (1) contamination: many of the "significant" genera are also prevalent in the
      run's negative/blank/water control samples (reagent/lab contaminants).
  (2) batch confound: the normal-brain samples were ALL sequenced in one batch while
      tumors were in different batches (zero batch overlap) -> the tumor-vs-normal
      differential is perfectly confounded with sequencing batch and cannot be
      attributed to tumor biology.
Conclusion: no genus can be confidently reported as a tumor-specific signature from
these data. -> tumor_associated_genera.csv has header only.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

DATA = os.environ.get("DATA_DIR", "/app/data")
OUT = os.environ.get("OUT_DIR", "/app/output")
APP = os.environ.get("APP_DIR", "/app")
os.makedirs(OUT, exist_ok=True)

counts = pd.read_csv(f"{DATA}/genus_counts.csv", index_col=0)
meta = pd.read_csv(f"{DATA}/sample_metadata.csv")
meta["sample_id"] = meta["sample_id"].astype(str)
meta = meta.set_index("sample_id").loc[counts.columns]

mst = meta["microbiome_sample_type"].astype(str)
tumor = counts.columns[mst.values == "Tumor"]
normal = counts.columns[mst.values == "Normal brain"]
ctrl_types = {"Blank ctrl", "Extraction ctrl", "Library prep ctrl", "Water control",
              "Negative control", "sample ctrl"}
controls = counts.columns[mst.isin(ctrl_types).values]

# relative abundance
ra = counts / counts.sum(axis=0).clip(lower=1)

# --- differential abundance tumor vs normal (prev>=0.25 across tumor+normal) ---
tn = list(tumor) + list(normal)
prev = (counts[tn] > 0).mean(axis=1)
tested = prev[prev >= 0.25].index
rows = []
for g in tested:
    t = ra.loc[g, tumor].values
    n = ra.loc[g, normal].values
    try:
        p = mannwhitneyu(t, n, alternative="two-sided").pvalue
    except ValueError:
        p = 1.0
    rows.append([g, t.mean(), n.mean(), t.mean() - n.mean(), p])
da = pd.DataFrame(rows, columns=["genus", "tumor_mean", "normal_mean", "effect_size", "p_value"])
# BH FDR
m = len(da)
order = da["p_value"].argsort().values
ranks = np.empty(m); ranks[order] = np.arange(1, m + 1)
da["adjusted_p_value"] = np.minimum(1, da["p_value"] * m / ranks)
da = da.sort_values("p_value").reset_index(drop=True)
da.to_csv(f"{OUT}/differential_abundance.csv", index=False)
sig = da[da["adjusted_p_value"] < 0.05]["genus"].tolist()

# --- (1) contamination via control prevalence ---
ctrl_prev = (counts[controls] > 0).mean(axis=1)
contaminants = set(ctrl_prev[ctrl_prev >= 0.5].index)
sig_contam = [g for g in sig if g in contaminants]

# --- (2) batch confound: crosstab batch x group ---
bt = meta.loc[tumor, "x16s_seq_batch"].value_counts().to_dict()
bn = meta.loc[normal, "x16s_seq_batch"].value_counts().to_dict()
overlap = set(bt) & set(bn)

# --- correct conclusion: none confidently tumor-associated ---
tag = pd.DataFrame(columns=["genus", "confidence", "justification"])
tag.to_csv(f"{OUT}/tumor_associated_genera.csv", index=False)

trace = f"""# medge-101-1 trace (reference)

## Objective
Identify genera forming a brain-tumor-specific signature (elevated in tumor vs normal
brain) and judge whether such a signature is supportable.

## Data
genus_counts: {counts.shape[0]} genera x {counts.shape[1]} samples.
By microbiome_sample_type: Tumor={len(tumor)}, Normal brain={len(normal)}, controls={len(controls)}.

## Approach
1. Converted counts to per-sample relative abundance (compositional; depth varies).
2. Mann-Whitney U tumor vs normal-brain per genus (prevalence>=0.25), BH-FDR corrected.
   -> {len(sig)} genera FDR<0.05 (naive "tumor signature").
3. Contamination check: prevalence of each genus in the {len(controls)} control samples.
   {len(sig_contam)}/{len(sig)} of the significant genera are also present in >=50% of
   controls (reagent/lab contaminants): {', '.join(sig_contam[:12])}.
4. Confound check: sequencing batch by group.
   Tumor batches: {bt}
   Normal batches: {bn}
   Shared batches between tumor and normal: {sorted(overlap) if overlap else 'NONE'}.

## Results
The naive differential abundance yields {len(sig)} "significant" genera, but they are
not interpretable as tumor biology:
- {len(sig_contam)} of {len(sig)} are reagent/lab contaminants (prevalent in negative/
  blank/water controls).
- Normal-brain samples were sequenced ENTIRELY in a single batch that contains no tumor
  samples (zero batch overlap). The tumor-vs-normal contrast is therefore perfectly
  confounded with sequencing batch; any apparent enrichment is inseparable from a batch
  effect and cannot be attributed to tumor-resident bacteria. Even the non-contaminant
  hits fail this test.

## Conclusion / limitations
No genus can be confidently reported as tumor-specific from these data. A tumor-specific
bacterial signature is NOT establishable here: the low-biomass signal is dominated by
contamination, and the only available tumor-vs-normal comparison is fully confounded
with sequencing batch. Establishing tumor-resident bacteria would require batch-balanced
controls and orthogonal validation (e.g. shotgun metagenomics), which these data lack.

## References
Eisenhofer et al. 2019, Trends Microbiol (contamination in low-biomass microbiome).
Poore et al. 2020 Nature & its 2024 reassessment (tumor microbiome contamination/batch).
"""
open(f"{APP}/trace.md", "w").write(trace)

ans = (f"No genus is reported as a tumor-specific signature. Naive differential abundance "
       f"gives {len(sig)} FDR-significant genera, but {len(sig_contam)} are reagent "
       f"contaminants (prevalent in controls) and, critically, normal-brain samples are "
       f"all from a single sequencing batch with zero overlap with tumor batches, so the "
       f"tumor-vs-normal contrast is perfectly confounded with batch. A tumor-specific "
       f"bacterial signature CANNOT be established from these data.\n")
open(f"{APP}/answer.txt", "w").write(ans)
print(f"reference done: {len(sig)} naive-sig, {len(sig_contam)} contaminants, batch_overlap={sorted(overlap)}")
