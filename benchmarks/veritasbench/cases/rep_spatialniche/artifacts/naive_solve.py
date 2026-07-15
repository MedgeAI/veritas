#!/usr/bin/env python3
"""NAIVE-DECOY solution for medge-ext017-1 (plausible-but-wrong path).
Computes RAW spatial neighbor composition (30um) WITHOUT normalizing to tissue background,
then calls the most frequent raw neighbors of the disease-driver cells the "niche" -> flags
the globally-abundant cells (Alveolar FBs, Interstitial Macrophages, ...) as niche partners.
Also mixes in cell types that co-vary in disease abundance. Misses the specific enrichment.
Writes to $OUT (default ./naive_out).
"""
import os, sys, csv, numpy as np, pandas as pd
from scipy.spatial import cKDTree

DATA = os.getenv("DATA_DIR", "/Users/chaco/Desktop/medgebench/medge-bench/04_待创建/medge-ext017-1/environment/data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "naive_out"
os.makedirs(OUT, exist_ok=True)
R = 30.0

md = pd.read_csv(f"{DATA}/cell_metadata.tsv", sep="\t")
cts = sorted(md["cell_type"].dropna().unique())
dis = md[md["disease_status"] == "Disease"]

counts = {c: {} for c in cts}
for s, g in dis.groupby("sample"):
    xy = g[["x_centroid", "y_centroid"]].values
    ct = g["cell_type"].values
    tree = cKDTree(xy)
    for i, c in enumerate(ct):
        for j in tree.query_ball_point(xy[i], R):
            if j != i:
                counts[c][ct[j]] = counts[c].get(ct[j], 0) + 1

# raw neighbor fractions as "enrichment"
rows = []
for c in cts:
    tot = sum(counts[c].values()) or 1
    for n, v in counts[c].items():
        if v > 20:
            rows.append([c, n, round(v / tot, 3)])
with open(f"{OUT}/neighborhood_enrichment.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["center_cell_type", "neighbor_cell_type", "enrichment_score"]); w.writerows(rows)

# niche = raw-most-frequent neighbors of the fibrotic FBs (biggest disease FB)
drv = "Activated Fibrotic FBs"
tot = sum(counts[drv].values()) or 1
top = [n for n, v in sorted(counts[drv].items(), key=lambda kv: -kv[1])[:6]]
niche_yes = set(top)  # includes Alveolar FBs, Interstitial Macrophages, Capillary ...
fn_rows = []
for c in cts:
    inn = "yes" if c in niche_yes else "no"
    fn_rows.append([c, inn, counts[drv].get(c, 0), "frequent_raw_neighbor" if inn == "yes" else "infrequent"])
with open(f"{OUT}/fibrotic_niche.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["cell_type", "in_fibrotic_niche", "score", "evidence"]); w.writerows(fn_rows)

with open(f"{OUT}/answer.txt", "w") as f:
    f.write("We counted the cell types found within 30um of the fibrotic fibroblasts across disease "
            "samples. The most frequent neighbors are Alveolar FBs, Interstitial Macrophages, "
            "Capillary and AT2 cells, so these form the fibrotic tissue niche together with the "
            "fibroblasts.\n")
with open(f"{OUT}/trace.md", "w") as f:
    f.write("# Spatial niche\n\nFor each disease sample, cells within 30um of each cell were "
            "counted. Ranking the neighbors of the Activated Fibrotic FBs by frequency gives "
            "Alveolar FBs, Interstitial Macrophages, Capillary, AT2 as the top neighbors, which we "
            "report as the fibrotic niche.\n")
print("naive solve done ->", OUT)
