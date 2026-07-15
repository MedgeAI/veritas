#!/usr/bin/env python3
"""Reference solution for medge-ext019-1 (CORRECT path).
Characterizes states by markers: the Tcf7/Sell/Ccr7-high stem-like state is the PROGENITOR.
RNA velocity would place it at terminal pseudotime (reversed - quiescent stem cells have low
unspliced), which is a known artifact. The CARLIN lineage clones spanning states show the
states are clonal siblings (shared progenitor), confirming the stem-like state is the origin.
"""
import os, sys, csv, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, anndata
DATA = os.getenv("DATA_DIR", "environment/data"); OUT = sys.argv[1] if len(sys.argv) > 1 else "ref_out"
os.makedirs(OUT, exist_ok=True)
ad = anndata.read_h5ad(f"{DATA}/expression.h5ad")
meta = pd.read_csv(f"{DATA}/cell_metadata.tsv", sep="\t")
lin = pd.read_csv(f"{DATA}/lineage_barcodes.csv")
ad.obs["cell_state"] = meta.set_index("cell_id").loc[ad.obs_names, "cell_state"].values
import scipy.sparse as sp
X = ad.X if not sp.issparse(ad.X) else ad.X
# log-normalize spliced for markers
tot = np.asarray(X.sum(1)).ravel(); tot[tot == 0] = 1
def gscore(genes):
    g = [x for x in genes if x in ad.var_names]
    sub = ad[:, g].X; sub = sub.toarray() if sp.issparse(sub) else np.asarray(sub)
    return np.log1p(sub / tot[:, None] * 1e4).mean(1)
stem = gscore(["Tcf7", "Sell", "Ccr7", "Il7r", "Lef1", "Bcl2"])
eff = gscore(["Gzmb", "Klrg1", "Cx3cr1", "Havcr2", "Prf1", "Gzma"])
df = pd.DataFrame({"state": ad.obs["cell_state"].values, "stem": stem, "eff": eff})
sm = df.groupby("state").agg(stem=("stem", "mean"), eff=("eff", "mean"), n=("state", "size"))
prog = sm["stem"].idxmax()
# lineage: clones spanning stem-like and effector
ls = lin.copy(); ls["state"] = meta.set_index("cell_id").loc[ls["cell_id"], "cell_state"].values
srole = {s: ("stemlike" if sm.loc[s, "stem"] > sm.loc[s, "eff"] else "effector") for s in sm.index}
ls["role2"] = ls["state"].map(srole)
span = ls.groupby("lineage_clone")["role2"].nunique(); n_span = int((span > 1).sum())

with open(f"{OUT}/state_analysis.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["cell_state", "stem_score", "eff_score", "n_cells", "role"])
    for s in sm.sort_values("stem", ascending=False).index:
        role = "progenitor" if s == prog else ("terminal" if sm.loc[s, "eff"] > sm.loc[s, "stem"] else "intermediate")
        w.writerow([s, round(sm.loc[s, "stem"], 3), round(sm.loc[s, "eff"], 3), int(sm.loc[s, "n"]), role])
with open(f"{OUT}/fate_conclusion.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["role", "cell_state", "evidence"])
    w.writerow(["progenitor", prog, "highest Tcf7/Sell/Ccr7 stem-like signature; confirmed by CARLIN lineage clones spanning states"])
    for s in sm.index:
        if sm.loc[s, "eff"] > sm.loc[s, "stem"] and s != prog:
            w.writerow(["terminal", s, "effector signature (Gzmb/Klrg1), differentiated"])
with open(f"{OUT}/answer.txt", "w") as f:
    f.write(f"The progenitor of this CD8 T-cell response is {prog}, the stem-like state with the "
            f"highest Tcf7/Sell/Ccr7 expression. Note that RNA velocity places {prog} at TERMINAL "
            f"pseudotime - this is a known velocity artifact: {prog} is a quiescent stem-like state "
            f"with low unspliced RNA, so velocity infers a reversed direction. The CARLIN lineage "
            f"barcodes resolve this: {n_span} clones contain cells in BOTH the stem-like and effector "
            f"states, i.e. they are clonal siblings from a shared progenitor, consistent with {prog} "
            f"(stem-like) being the origin that gives rise to effectors - the opposite of the velocity "
            f"trajectory. We therefore do NOT trust the velocity direction here.\n")
with open(f"{OUT}/trace.md", "w") as f:
    f.write(f"# CD8 T-cell fate analysis\n\n## State characterization\n{prog} is the Tcf7/Sell-high "
            f"stem-like state; other states are effector (Gzmb/Klrg1).\n\n## Velocity is reversed here\n"
            f"RNA velocity assigns {prog} the highest pseudotime (terminal). This is an artifact - "
            f"quiescent stem-like cells have low unspliced counts, so velocity infers the wrong "
            f"direction (it appears effectors -> stem, which is biologically backwards).\n\n"
            f"## Lineage barcodes resolve the direction\nCARLIN clones: {n_span} clones span both "
            f"stem-like and effector states = clonal siblings sharing a progenitor. Combined with the "
            f"stem-like phenotype of {prog}, the true progenitor is {prog}, giving rise to effectors.\n")
print("reference solve done ->", OUT, "| progenitor", prog, "| n_span", n_span)
