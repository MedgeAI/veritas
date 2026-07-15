#!/usr/bin/env python3
"""Reference solution for medge-ext008-1 (the CORRECT path).
1. pseudobulk per-donor DE -> establishes the mechanism genes are NON-DE (stat_unit=donor)
2. donor-aware (Simpson-controlled) differential co-expression, EXCLUDING the cytosolic
   heat-shock/stress program -> final dysregulated beta-cell program.
3. trace/answer diagnosing both hidden failure modes.
Writes to $OUT (default ./ref_out).
"""
import os, sys, csv, numpy as np, pandas as pd
from scipy import stats

DATA = os.getenv("DATA_DIR", "/Users/chaco/Desktop/medgebench/medge-bench/04_待创建/medge-ext008-1/environment/data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "ref_out"
os.makedirs(OUT, exist_ok=True)

HSP = {"HSPA1A","HSPA1B","HSPA6","HSPA7","HSPB1","HSPH1","HSPE1","HSPD1","HSP90AA1","HSP90AB1",
       "DNAJA1","DNAJB1","DNAJB2","DNAJB4","DNAJB6","BAG3","AHSA1","CACYBP","PTGES3","FKBP4",
       "FOS","FOSB","JUN","JUNB","JUND","EGR1","DUSP1","IER2","ZFP36","CIRBP","RBM3"}
def base(g): return g.split("##")[0].upper()

meta = pd.read_csv(f"{DATA}/cell_metadata.tsv", sep="\t")
df = pd.read_csv(f"{DATA}/expression_counts.tsv.gz", sep="\t", index_col=0)
genes = df.index.values
X = df.values.astype(np.float32)
beta = (meta["cell_type"] == "Beta").values
grp = meta["condition"].values[beta]; donor = meta["donor_id"].values[beta]
Xb = X[:, beta]
lib = Xb.sum(0); lib[lib == 0] = 1
logn = np.log1p(Xb / lib * 1e4)

# ---- 1. pseudobulk per-donor DE (CORRECT unit = donor) ----
donors = pd.unique(donor)
pb = {}
for d in donors:
    m = donor == d; s = Xb[:, m].sum(1); s = s / max(s.sum(), 1) * 1e6; pb[d] = np.log1p(s)
pbdf = pd.DataFrame(pb, index=genes)
dgrp = {d: ("T2D" if grp[donor == d][0] == "T2D" else "control") for d in donors}
nd = [d for d in donors if dgrp[d] == "control"]; t2 = [d for d in donors if dgrp[d] == "T2D"]
rows = []
for g in genes:
    a = pbdf.loc[g, nd].values; b = pbdf.loc[g, t2].values
    if a.std() == 0 and b.std() == 0:
        continue
    tt, p = stats.ttest_ind(a, b, equal_var=False)
    lfc = (b.mean() - a.mean()) / np.log(2)
    if not np.isnan(p):
        rows.append((g, lfc, p))
ps = np.array([r[2] for r in rows]); order = ps.argsort()
padj = np.empty_like(ps); m = len(ps); ranked = ps[order]
adj = ranked * m / (np.arange(m) + 1); adj = np.minimum.accumulate(adj[::-1])[::-1]
padj[order] = np.clip(adj, 0, 1)
with open(f"{OUT}/de_analysis.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["gene", "log2fc", "pvalue", "padj", "stat_unit"])
    for (g, lfc, p), pa in zip(rows, padj):
        w.writerow([g, round(float(lfc), 4), f"{p:.4g}", f"{pa:.4g}", "donor"])

# ---- 2. donor-aware differential co-expression, exclude HSP stress program ----
det = (Xb > 0); keep = (det[:, grp == "control"].mean(1) >= 0.10) & (det[:, grp == "T2D"].mean(1) >= 0.10)
gk = genes[keep]
def corr(M):
    Mc = M - M.mean(1, keepdims=True); s = np.sqrt((Mc ** 2).sum(1, keepdims=True)); s[s == 0] = 1
    Mn = Mc / s; return Mn @ Mn.T
def wc(M, cd):
    Mc = M.copy()
    for d in np.unique(cd):
        mm = cd == d
        Mc[:, mm] = M[:, mm] - M[:, mm].mean(1, keepdims=True) if mm.sum() > 1 else 0.0
    return Mc
Ln = wc(logn[keep][:, grp == "control"], donor[grp == "control"])
Lt = wc(logn[keep][:, grp == "T2D"], donor[grp == "T2D"])
dC = np.abs(corr(Lt) - corr(Ln)); np.fill_diagonal(dC, 0)
score = pd.Series(dC.sum(1), index=gk).sort_values(ascending=False)
prog = [(g, s) for g, s in score.items() if base(g) not in HSP][:40]
with open(f"{OUT}/dysregulated_program.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["gene", "rank", "score", "evidence_type"])
    for i, (g, s) in enumerate(prog, 1):
        w.writerow([g, i, round(float(s), 3), "differential_coexpression"])

with open(f"{OUT}/answer.txt", "w") as f:
    f.write("Beta-cell dysregulation in T2D is NOT captured by differential expression: with a "
            "proper per-donor pseudobulk test (donors as the unit of replication) the key mechanism "
            "genes are not significant after FDR. The disease signal instead appears as altered gene "
            "co-expression / coordination within beta cells (unfolded protein response, cytoskeleton/"
            "microfilament, mitochondrial and proliferation programs). A naive pooled cross-cell "
            "co-expression analysis is dominated by a cytosolic heat-shock/stress (dissociation) "
            "program driven by between-donor differences (Simpson mixing); controlling for donor "
            "structure and excluding the stress program yields the biological coordination signal.\n")
with open(f"{OUT}/trace.md", "w") as f:
    f.write("# Beta-cell dysregulation in T2D\n\n"
            "## DE is insufficient (pseudoreplication vs pseudobulk)\n"
            "Per-cell Wilcoxon flags ~25% of the transcriptome — pseudoreplication across the donors. "
            "Using per-donor pseudobulk (donor as unit), the mechanism genes are non-significant.\n\n"
            "## Differential co-expression\n"
            "Signal is in changed gene coordination, not mean expression. A pooled cross-cell "
            "correlation contrast is confounded by donor structure (Simpson) and dominated by a "
            "cytosolic heat-shock / dissociation-stress program (HSPA1A/B, HSP90, DNAJB, immediate-early). "
            "Donor-centering removes this; we exclude the stress module and report the biological "
            "coordination program (UPR incl. ER chaperones, cytoskeleton, mitochondrial, proliferation).\n")
print("reference solve done ->", OUT)
