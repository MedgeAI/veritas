#!/usr/bin/env python3
"""Reference solution for medge-ext017-1 (CORRECT path).
1. Within each disease sample, compute spatial neighborhood composition (30um) and
   NORMALIZE to tissue background -> enrichment (fold over expected).
2. The disease/fibrotic niche = the reciprocally-enriched disease-driver cells, NOT the
   globally abundant cells that merely dominate raw neighbor counts.
3. trace/answer diagnosing: must normalize to background (Alveolar FBs dominate raw counts
   but are not enriched); co-abundance across samples != spatial co-localization.
Writes to $OUT (default ./ref_out).
"""
import os, sys, csv, numpy as np, pandas as pd
from scipy.spatial import cKDTree

DATA = os.getenv("DATA_DIR", "/Users/chaco/Desktop/medgebench/medge-bench/04_待创建/medge-ext017-1/environment/data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "ref_out"
os.makedirs(OUT, exist_ok=True)
R = 30.0

md = pd.read_csv(f"{DATA}/cell_metadata.tsv", sep="\t")
cts = sorted(md["cell_type"].dropna().unique())
bg = md["cell_type"].value_counts(normalize=True)
dis = md[md["disease_status"] == "Disease"]

# background-normalized neighborhood enrichment, center x neighbor (disease samples)
enrich = {c: {} for c in cts}
counts = {c: {} for c in cts}
for s, g in dis.groupby("sample"):
    xy = g[["x_centroid", "y_centroid"]].values
    ct = g["cell_type"].values
    tree = cKDTree(xy)
    idx_by_ct = {}
    for i, c in enumerate(ct):
        idx_by_ct.setdefault(c, []).append(i)
    for c, idxs in idx_by_ct.items():
        for i in idxs:
            for j in tree.query_ball_point(xy[i], R):
                if j != i:
                    counts[c][ct[j]] = counts[c].get(ct[j], 0) + 1
rows = []
for c in cts:
    tot = sum(counts[c].values()) or 1
    for n in cts:
        e = (counts[c].get(n, 0) / tot) / bg.get(n, 1e-9)
        enrich[c][n] = e
        if counts[c].get(n, 0) > 20:
            rows.append([c, n, round(float(e), 3)])
with open(f"{OUT}/neighborhood_enrichment.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["center_cell_type", "neighbor_cell_type", "enrichment_score"]); w.writerows(rows)

# fibrotic niche = disease-driver cells that reciprocally enrich each other (>1.7x), excluding
# generic-abundant cells that only dominate raw counts
seeds = ["Activated Fibrotic FBs", "KRT5-/KRT17+", "SPP1+ Macrophages"]
niche = set()
for sd in seeds:
    niche.add(sd)
    for n, e in enrich[sd].items():
        if e >= 1.7 and n != sd:
            niche.add(n)
# require reciprocity with a seed to stay in the fibrotic focus (drops airway-only)
core = {"KRT5-/KRT17+", "Activated Fibrotic FBs", "SPP1+ Macrophages"}
fn_rows = []
for c in cts:
    inn = "yes" if c in core else ("yes" if (c in niche and any(enrich[c].get(sd, 0) >= 1.7 for sd in seeds)) else "no")
    sc = round(float(np.mean([enrich[sd].get(c, 0) for sd in seeds])), 3)
    ev = "reciprocal_enrichment_in_disease" if inn == "yes" else "not_specifically_enriched"
    fn_rows.append([c, inn, sc, ev])
with open(f"{OUT}/fibrotic_niche.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["cell_type", "in_fibrotic_niche", "score", "evidence"]); w.writerows(fn_rows)

with open(f"{OUT}/answer.txt", "w") as f:
    f.write("The disease (fibrotic) spatial niche is formed by the reciprocal co-localization of "
            "aberrant basaloid epithelium (KRT5-/KRT17+), Activated Fibrotic fibroblasts and SPP1+ "
            "macrophages, which are enriched in each other's spatial neighborhoods (~2-4x over "
            "expected) within fibrotic tissue. Crucially, RAW neighbor counts are dominated by the "
            "globally most abundant cell types (e.g. Alveolar FBs, Interstitial Macrophages, "
            "Capillary), which are NOT specifically enriched once normalized to tissue background — "
            "so they are not true niche partners. Likewise, several cell types co-vary in abundance "
            "across disease samples (e.g. Venous, some immune cells) without being focally "
            "co-localized; co-abundance is not co-localization.\n")
with open(f"{OUT}/trace.md", "w") as f:
    f.write("# Spatial niche analysis\n\n"
            "## Neighborhood enrichment (normalized to background)\n"
            "For each disease sample, cells within 30um were counted per cell-type pair and the "
            "neighbor composition was normalized to each type's overall tissue abundance to get "
            "enrichment (fold over expected). Without this normalization the top neighbors are just "
            "the most abundant cell types (Alveolar FBs etc.), which is misleading.\n\n"
            "## Fibrotic niche\n"
            "KRT5-/KRT17+, Activated Fibrotic FBs and SPP1+ Macrophages are reciprocally enriched "
            "(1.8-2.3x) in each other's neighborhoods within fibrotic regions = the disease niche. "
            "Alveolar FBs dominate raw neighbor counts of Activated Fibrotic FBs (~19%) but enrich "
            "only ~1.3x = not a specific partner. Co-abundance across samples (Venous, immune) does "
            "not imply spatial co-localization.\n")
print("reference solve done ->", OUT)
