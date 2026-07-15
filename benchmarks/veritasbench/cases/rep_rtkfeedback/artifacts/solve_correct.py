#!/usr/bin/env python3
"""Reference solution for medge-ext011-1 (CORRECT path).
1. per drug x model DE vs control; response_magnitude = nDEG; note that the biggest
   responses are cell-cycle ARREST (G1 shift), not target-specific.
2. identify the actionable vulnerability = a compensatory RTK/EGFR up-regulation present
   in a SUBSET of drugs and only in one model (feedback model). Flag those, exclude the
   big-arrest decoys. target_gene = EGFR.
3. trace/answer diagnosing both hidden failure modes.
Writes to $OUT (default ./ref_out).
"""
import os, sys, csv, numpy as np, pandas as pd

DATA = os.getenv("DATA_DIR", "/Users/chaco/Desktop/medgebench/medge-bench/04_待创建/medge-ext011-1/environment/data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "ref_out"
os.makedirs(OUT, exist_ok=True)
RTK = ["EGFR", "ERBB2", "ERBB3", "AXL", "MET"]

meta = pd.read_csv(f"{DATA}/cell_metadata.tsv", sep="\t")
df = pd.read_csv(f"{DATA}/expression_counts.tsv.gz", sep="\t", index_col=0)
genes = df.index.values; gidx = {g: i for i, g in enumerate(genes)}
X = df.values.astype(np.float32); lib = X.sum(0); lib[lib == 0] = 1; logn = np.log1p(X / lib * 1e4)
drugs = sorted([d for d in meta["drug_id"].unique() if d != "control"])
models = sorted(meta["model"].unique())

resp_rows, comb_rows = [], []
for M in models:
    ctrl = ((meta["drug_id"] == "control") & (meta["model"] == M)).values
    g1c = (meta.loc[ctrl, "cell_cycle_phase"] == "G1").mean()
    for d in drugs:
        m = ((meta["drug_id"] == d) & (meta["model"] == M)).values
        if m.sum() < 20:
            continue
        lfc = logn[:, m].mean(1) - logn[:, ctrl].mean(1)
        ndeg = int((np.abs(lfc) > 0.25).sum())
        g1 = (meta.loc[m, "cell_cycle_phase"] == "G1").mean()
        dom = "cell_cycle_arrest" if (g1 - g1c) > 0.2 else "mixed"
        resp_rows.append([d, M, ndeg, dom])
        egfr = logn[gidx["EGFR"], m].mean() - logn[gidx["EGFR"], ctrl].mean()
        cav1 = logn[gidx["CAV1"], m].mean() - logn[gidx["CAV1"], ctrl].mean()
        # actionable = compensatory RTK/EGFR up-regulation (CAV1-concordant), NOT arrest magnitude
        if egfr >= 0.25 and cav1 > 0:
            comb_rows.append([d, M, "yes", "EGFR", round(float(egfr), 3), "compensatory_RTK_upregulation"])
        else:
            comb_rows.append([d, M, "no", "", round(float(egfr), 3), "no_adaptive_signal"])

with open(f"{OUT}/drug_response.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["drug_id", "model", "response_magnitude", "dominant_response"]); w.writerows(resp_rows)
with open(f"{OUT}/combination_targets.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["drug_id", "model", "actionable", "target_gene", "score", "rationale_tag"]); w.writerows(comb_rows)

with open(f"{OUT}/answer.txt", "w") as f:
    f.write("Across the three models, the LARGEST transcriptional responses (most genes changed) "
            "are driven by cell-cycle arrest (a strong G1 shift), not by drug-target-specific "
            "programs. Response magnitude is therefore NOT a good guide to which drug matters: the "
            "single biggest responder in the feedback model (Drug_D) is a pure arrester with no "
            "actionable vulnerability. The actionable signal is a subtle compensatory up-regulation "
            "of the receptor tyrosine kinase EGFR (concordant with CAV1), which appears only in a "
            "subset of drugs (Drug_A, C, E, F, G, K) and only in ONE model (Model_A). These drug/"
            "model combinations would rationally be combined with an EGFR inhibitor. The other models "
            "and the high-arrest drugs do not show this feedback.\n")
with open(f"{OUT}/trace.md", "w") as f:
    f.write("# Drug screen analysis\n\n"
            "## Response magnitude is dominated by cell-cycle arrest\n"
            "Per drug x model DE vs control. The drugs with the most DE genes (e.g. Drug_D, ~478 in "
            "Model_A) also show the strongest G1 arrest (cell_cycle_phase shift), so the bulk response "
            "is a proliferation/arrest program. Ranking drugs by response size just recovers the "
            "strongest arresters, not the most actionable drugs.\n\n"
            "## Actionable vulnerability = compensatory RTK/EGFR up-regulation\n"
            "Looking past the arrest program, a subset of drugs induces up-regulation of the RTK EGFR "
            "(logFC ~0.3-0.45), concordant with its mediator CAV1. This compensatory/feedback signal "
            "is model-specific: it appears only in Model_A (a patient-derived model), not in Model_C. "
            "Drug_A/C/E/F/G/K in Model_A are flagged as actionable (co-target EGFR); the high-arrest "
            "Drug_D is not.\n")
print("reference solve done ->", OUT)
