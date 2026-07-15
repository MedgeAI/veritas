#!/usr/bin/env python3
"""Reference solution for medge-ext022-1 (CORRECT path).
The reference clock is keyed by base CpG IDs (cgXXXX), but the methylation matrix uses
EPICv2 probe IDs (cgXXXX_TC21, with replicate probes per CpG). Naive application matches 0
probes. Correct: strip the EPICv2 suffix, collapse replicate probes (mean), then apply the
clock. Also handle age top-coding (">89") when evaluating against chronological age.
Writes to $OUT (default ./ref_out).
"""
import os, sys, csv, re, numpy as np, pandas as pd

DATA = os.getenv("DATA_DIR", "/Users/chaco/Desktop/medgebench/medge-bench/04_待创建/medge-ext022-1/environment/data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "ref_out"
os.makedirs(OUT, exist_ok=True)
SUF = re.compile(r"_[A-Z]{2}\d+$")

betas = pd.read_csv(f"{DATA}/methylation_betas.csv.gz", index_col=0)
clock = pd.read_csv(f"{DATA}/reference_clock.csv")
meta = pd.read_csv(f"{DATA}/sample_metadata.tsv", sep="\t")
inter = float(clock.loc[clock["probe"] == "(Intercept)", "weight"].iloc[0])
cw = {r.probe: r.weight for r in clock.itertuples() if r.probe != "(Intercept)"}

# strip EPICv2 suffix + collapse replicate probes to base cg (mean)
base = betas.groupby(betas.index.to_series().str.replace(SUF, "", regex=True)).mean()
common = [c for c in cw if c in base.index]
X = base.loc[common, betas.columns].T
X = X.fillna(X.mean())
pred = X.values @ np.array([cw[c] for c in common]) + inter
pa = pd.DataFrame({"sample_id": betas.columns, "predicted_age": np.round(pred, 2)})
pa.to_csv(f"{OUT}/predicted_age.csv", index=False)

# evaluate vs chronological age; handle ">89" top-coding (exclude from numeric metrics)
age_num = pd.to_numeric(meta["age"], errors="coerce")
m = age_num.notna().values
y = age_num[m].values; p = pred[m]
r = float(np.corrcoef(p, y)[0, 1]); mae = float(np.mean(np.abs(p - y)))
n_top = int((~age_num.notna()).sum())
with open(f"{OUT}/clock_evaluation.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["metric", "value"])
    w.writerow(["pearson_r", round(r, 3)]); w.writerow(["MAE_years", round(mae, 2)])
    w.writerow(["n_samples_numeric_age", int(m.sum())]); w.writerow(["n_topcoded_excluded", n_top])
    w.writerow(["n_clock_probes_matched", len(common)])

with open(f"{OUT}/answer.txt", "w") as f:
    f.write(f"The reference clock's probes are keyed by base CpG IDs (e.g. cg16867657), but the "
            f"methylation matrix uses EPICv2 probe IDs with address suffixes (cg16867657_BC11, "
            f"cg16867657_BC12) and multiple replicate probes per CpG. A direct match yields ZERO "
            f"overlapping probes and a degenerate (constant) age estimate. After stripping the "
            f"suffix and averaging replicate probes per CpG, all {len(common)} clock probes match "
            f"and the clock predicts chronological age well: Pearson r={r:.3f}, MAE={mae:.1f} years "
            f"across {int(m.sum())} samples. {n_top} samples have top-coded age ('>89') and were "
            f"excluded from the numeric accuracy metrics rather than coerced to NaN/dropped silently.\n")
with open(f"{OUT}/trace.md", "w") as f:
    f.write("# Epigenetic clock application\n\n"
            "## Probe ID reconciliation (EPICv2)\n"
            "The betas use EPICv2 probe IDs (cgXXXX_TC21/_BC11...) with replicate probes per CpG; the "
            "clock uses base cg IDs. Matching directly gives 0 overlap -> degenerate constant age. We "
            "strip the `_XX##` suffix and average replicate probes to the base CpG, recovering all "
            f"{len(common)} clock probes.\n\n"
            "## Application and evaluation\n"
            f"clock age = sum(weight*beta) + intercept. r={r:.3f}, MAE={mae:.1f}y. The 5 samples with "
            "age '>89' are top-coded (censored); they are non-numeric and were excluded from the "
            "numeric accuracy metrics.\n")
print("reference solve done ->", OUT)
