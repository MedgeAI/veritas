#!/usr/bin/env python3
"""NAIVE audit of the in vivo CRISPR screen medge-150-1.

A naive auditor ranks guides by the raw cohort enrichment ratio
tumor_representation / baseline_representation (a "fold over starting pool")
and calls the top hits drivers. No control-guide null, no per-tumor
reproducibility, no baseline floor. This is exactly the winner's-curse trap:
guides with a near-zero starting-pool baseline get an explosively inflated
ratio even when they are actually fold-change depleted in vivo.

Result: the top "driver" by this ranking is Trp63 (enrichment ~491x, baseline
~0.001) which the real analysis correctly REJECTS. A naive auditor could
conclude the paper "missed" Trp63 / mis-called drivers."""
import pandas as pd, numpy as np, os
DATA = os.environ.get("DATA_DIR", "environment/data")
OUT = os.environ.get("OUTPUT_DIR", "out_naive"); os.makedirs(OUT, exist_ok=True)
per = pd.read_csv(f"{DATA}/screen_per_tumor.csv")
rep = pd.read_csv(f"{DATA}/guide_representation.csv")

# naive per-guide fold-change mean (no control null, no reproducibility)
g = per.groupby("guide_target").agg(
    target_type=("target_type", "first"),
    fc_mean=("fold_change", "mean")).reset_index()
g = g.merge(rep, on="guide_target", how="left")
# naive cohort enrichment ratio -- NO baseline floor
g["enrichment"] = g.tumor_representation / g.baseline_representation

# NAIVE CALL: top-15 by raw enrichment ratio are "drivers"
ranked = g.sort_values("enrichment", ascending=False)
TOPN = 15
ranked["is_driver_naive"] = False
ranked.iloc[:TOPN, ranked.columns.get_loc("is_driver_naive")] = True
out = ranked[["guide_target", "target_type", "fc_mean",
              "tumor_representation", "baseline_representation",
              "enrichment", "is_driver_naive"]].round(3)
out.to_csv(f"{OUT}/driver_calls_naive.csv", index=False)

print("=== NAIVE top-15 by raw enrichment ratio (tumor/baseline) ===")
print(out.head(TOPN).to_string(index=False))
top = out.iloc[0]
print(f"\nNAIVE #1 'driver' = {top.guide_target}: enrichment={top.enrichment:.1f}x "
      f"but baseline={top.baseline_representation:.4f}, fc_mean={top.fc_mean:.3f} "
      f"(fold-change DEPLETED -> pure winner's-curse artifact)")
real = {"Notch1", "Fat1", "Trp53"}
print("\nWhere the real drivers rank by this naive metric:")
for gene in ["Notch1", "Fat1", "Trp53"]:
    r = out.reset_index(drop=True)
    pos = r.index[r.guide_target == gene][0] + 1
    print(f"  {gene:7s} naive-rank #{pos} (enrichment={r[r.guide_target==gene].enrichment.iloc[0]:.1f})")
