#!/usr/bin/env python3
"""medge-082-1 REFERENCE solution (correct path).

Per-KO differential expression vs control gives Tfam/Opa1 (masked KO_13/KO_05) the
LARGEST signatures — but those are the strongest mtDNA depleters, and their big DE is
the SHARED mtDNA-depletion (integrated stress) response, not gene-specificity. The
genuinely gene-specific perturbation is the one with a substantial signature at NORMAL
mtDNA copy number (Atg5 = KO_11). Correct path: recognize DE size tracks mtDNA depletion,
flag the depleters' signatures as confounded/shared, and nominate the non-depleter with
a real signature as gene-specific.
"""
import os
import numpy as np
import pandas as pd
import gzip

DATA = os.environ.get("DATA_DIR", "/app/data")
OUT = os.environ.get("OUT_DIR", "/app/output")
APP = os.environ.get("APP_DIR", "/app")
os.makedirs(OUT, exist_ok=True)

meta = pd.read_csv(f"{DATA}/cell_metadata.csv")
# expression: gene x cell
with gzip.open(f"{DATA}/expression.tsv.gz", "rt") as f:
    cells = f.readline().rstrip("\n").split("\t")[1:]
    genes, rows = [], []
    for line in f:
        p = line.rstrip("\n").split("\t")
        genes.append(p[0]); rows.append(np.array(p[1:], dtype=np.float32))
X = np.vstack(rows)
lib = X.sum(0); lib[lib == 0] = 1
Xl = np.log1p(X / lib * 1e4)

m = meta.set_index("cell_id").loc[cells]
pert = m["perturbation"].values
mt = m["mtDNA_copy_number"].values.astype(float)
ctrl = pert == "control"
cm, cv, cn = Xl[:, ctrl].mean(1), Xl[:, ctrl].var(1) + 1e-6, ctrl.sum()
ctrl_med_mt = np.median(mt[ctrl])
depl_thr = 0.75 * ctrl_med_mt

rows_out = []
for ko in sorted(set(pert) - {"control"}):
    k = pert == ko
    t = (Xl[:, k].mean(1) - cm) / np.sqrt(Xl[:, k].var(1) / k.sum() + cv / cn)
    n_deg = int((np.abs(t) > 3).sum())
    mmt = float(np.mean(mt[k]))
    depleter = mmt < depl_thr
    # gene_specific = substantial DE AND NOT an mtDNA depleter; shared = big DE but depleter
    if depleter and n_deg >= 200:
        call = "shared"          # big signature but confounded by mtDNA depletion
    elif (not depleter) and n_deg >= 200:
        call = "gene_specific"   # real signature at normal mtDNA
    else:
        call = "uncertain"
    rows_out.append([ko, int(k.sum()), n_deg, round(mmt), call])
summ = pd.DataFrame(rows_out, columns=["perturbation", "n_cells", "n_deg",
                                       "mean_mtDNA_copy_number", "gene_specific_call"])
summ = summ.sort_values("n_deg", ascending=False)
summ.to_csv(f"{OUT}/perturbation_summary.csv", index=False)

gs = summ[summ["gene_specific_call"] == "gene_specific"]["perturbation"].tolist()
gsdf = pd.DataFrame({"perturbation": gs, "confidence": ["high"] * len(gs),
                     "justification": ["Large DE program at near-control mtDNA copy number "
                                       "(effect not attributable to mtDNA depletion)"] * len(gs)})
gsdf.to_csv(f"{OUT}/gene_specific_perturbations.csv", index=False)

depleters = summ[summ["mean_mtDNA_copy_number"] < depl_thr]["perturbation"].tolist()
open(f"{APP}/trace.md", "w").write(f"""# medge-082-1 trace (reference)

## Objective
Distinguish gene-specific transcriptional programs from a shared response across KOs.

## Approach
1. log-CPM normalized {X.shape[0]} genes x {X.shape[1]} cells.
2. Per-KO DE vs control (Welch t, |t|>3). Naive ranking by n_deg puts
   {summ.iloc[0]['perturbation']} ({summ.iloc[0]['n_deg']}) and
   {summ.iloc[1]['perturbation']} ({summ.iloc[1]['n_deg']}) on top.
3. CRUCIAL CHECK: n_deg tracks mtDNA_copy_number. Control median mtDNA={round(ctrl_med_mt)}.
   The top-DE KOs {depleters} are strong mtDNA DEPLETERS (mtDNA well below control),
   so their large signatures are the SHARED mtDNA-depletion (integrated stress) response,
   not gene-specificity — their effect is inseparable from depletion (their cells barely
   overlap control mtDNA levels).
4. Gene-specific = substantial DE at NORMAL mtDNA. -> {gs} shows a large program while
   NOT depleting mtDNA (mtDNA ~ control) = genuine perturbation-specific response.

## Results
Gene-specific: {gs}. Depletion-confounded (shared response, NOT gene-specific despite
largest raw DE): {depleters}.

## Limitations
mtDNA-depleting KOs cannot be cleanly separated into gene-specific vs shared components
from these data because their cells occupy a mtDNA range with little control overlap.

## References
Perturb-seq / mixscape (Papalexi 2021); integrated stress response to mtDNA depletion.
""")
open(f"{APP}/answer.txt", "w").write(
    f"Genuinely gene-specific: {', '.join(gs)} — large DE program at near-control mtDNA "
    f"copy number. The KOs with the LARGEST raw DE ({', '.join(depleters)}) are strong "
    f"mtDNA depleters; their signatures are the shared mtDNA-depletion response, not "
    f"gene-specific, so ranking perturbations by DE size mis-identifies them.\n")
print("reference done:", gs, "depleters", depleters)
