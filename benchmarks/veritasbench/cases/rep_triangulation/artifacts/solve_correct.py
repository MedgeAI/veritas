#!/usr/bin/env python3
"""Reference solution for medge-104-1 v2: diet-microbe-metabolite mediation
triangulation WITH robustness/specificity triage.

v2 note: the agent is NOT handed the support criterion, the direction rule, the
mediator rule, or the specificity metric — it must devise and defend them. This
reference encodes one sound set of choices and is used only to anchor the rubric.

Sound support criterion used here: an edge is supported iff it is replicated-
significant in the meta analysis (precomputed Significant flag where provided;
else meta FDR<0.05) AND the two cohorts agree in direction.

Specificity/robustness idea: a metabolite or microbe associated with MANY foods
is a non-specific marker, so a triplet built on it is more likely confounded.
specificity_score rewards low promiscuity of both nodes.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control as bh

DATA = os.environ.get("DATA_DIR", "/app/data")
OUT = os.environ.get("OUT_DIR", "/app/output")
os.makedirs(OUT, exist_ok=True)


def bhfdr(p):
    return bh(np.asarray(p, float).clip(1e-300, 1))


fm_raw = pd.read_excel(f"{DATA}/food_metabolite_assoc.xlsx", header=1)
fb_raw = pd.read_excel(f"{DATA}/food_microbe_assoc.xlsx", header=1)
bm_raw = pd.read_excel(f"{DATA}/microbe_metabolite_assoc.xlsx", header=1)

# food-label harmonization (food_microbe uses 'Alcohol' vs 'Alcoholic Beverages')
CANON = {"Alcohol": "Alcoholic Beverages"}
rows = []
for tbl, df in [("food_metabolite", fm_raw), ("food_microbe", fb_raw)]:
    for raw in sorted(df["Food and Beverage Group"].unique()):
        canon = CANON.get(raw, raw)
        rule = "alias->Alcoholic Beverages" if raw in CANON else "identity"
        rows.append([raw, canon, tbl, rule])
pd.DataFrame(rows, columns=["raw_food_name", "canonical_food_name", "source_table", "mapping_rule"]).to_csv(
    f"{OUT}/food_label_map.csv", index=False)
fm_raw["food"] = fm_raw["Food and Beverage Group"].replace(CANON)
fb_raw["food"] = fb_raw["Food and Beverage Group"].replace(CANON)

# supported edges
fm_raw["fm_stat"] = bhfdr(fm_raw["p value"])
fm = fm_raw[fm_raw["Significant"] == True].rename(  # noqa: E712
    columns={"Faecal Metabolite": "metabolite", "Beta": "fm_beta", "Super Pathway": "super_pathway"}
)[["food", "metabolite", "fm_beta", "fm_stat", "super_pathway"]]
fb = fb_raw[(fb_raw["FDR"] < 0.05) & (fb_raw["Beta Same Direction"] == True)].rename(  # noqa: E712
    columns={"Gut Microbial Species": "microbe", "Beta": "fb_beta", "FDR": "fb_stat"}
)[["food", "microbe", "fb_beta", "fb_stat"]]
bm_raw["bm_stat"] = bhfdr(bm_raw["p value"])
bm = bm_raw[bm_raw["Significant"] == True].rename(  # noqa: E712
    columns={"Gut Microbial Species": "microbe", "Faecal Metabolite": "metabolite", "Beta": "bm_beta"}
)[["microbe", "metabolite", "bm_beta", "bm_stat"]]

pd.DataFrame([
    ["food_metabolite", len(fm_raw), len(fm), "Significant flag True (meta-sig + cross-cohort replication)"],
    ["food_microbe", len(fb_raw), len(fb), "meta FDR<0.05 AND Beta Same Direction True"],
    ["microbe_metabolite", len(bm_raw), len(bm), "Significant flag True (meta-sig + cross-cohort replication)"],
], columns=["table", "n_total_edges", "n_supported_edges", "support_criterion"]).to_csv(
    f"{OUT}/edge_summary.csv", index=False)

# triangulate
t = fb.merge(fm, on="food").merge(bm, on=["microbe", "metabolite"])
t = t.drop_duplicates(["food", "microbe", "metabolite"]).reset_index(drop=True)
t["direction_coherent"] = (np.sign(t.fm_beta) * np.sign(t.fb_beta) * np.sign(t.bm_beta)) > 0


def mediator(r):
    f, b, m = abs(r.fm_beta), abs(r.fb_beta), abs(r.bm_beta)
    if b > f and m > f:
        return "microbe"
    if f > b and m > b:
        return "metabolite"
    return "both"


t["mediator_hypothesis"] = t.apply(mediator, axis=1)

# promiscuity degrees over supported edges
metab_deg = fm.groupby("metabolite")["food"].nunique()
microbe_deg = fb.groupby("microbe")["food"].nunique()
t["metabolite_food_degree"] = t.metabolite.map(metab_deg).astype(int)
t["microbe_food_degree"] = t.microbe.map(microbe_deg).astype(int)

# specificity: higher when both nodes are tied to few foods; weakest-edge strength as the base strength
t["min_beta"] = t[["fm_beta", "fb_beta", "bm_beta"]].abs().min(axis=1)
t["specificity_score"] = 1.0 / (t.metabolite_food_degree * t.microbe_food_degree)

t = t.sort_values("min_beta", ascending=False).reset_index(drop=True)
t["naive_rank"] = np.arange(1, len(t) + 1)
# robustness-adjusted: specificity first, then coherent, then strength
t = t.sort_values(["specificity_score", "direction_coherent", "min_beta"], ascending=[False, False, False]).reset_index(drop=True)
t["robustness_adjusted_rank"] = np.arange(1, len(t) + 1)

cols = ["food", "microbe", "metabolite", "fm_beta", "fm_stat", "fb_beta", "fb_stat", "bm_beta", "bm_stat",
        "direction_coherent", "mediator_hypothesis", "metabolite_food_degree", "microbe_food_degree",
        "specificity_score", "naive_rank", "robustness_adjusted_rank"]
t.sort_values("robustness_adjusted_rank")[cols].to_csv(f"{OUT}/candidate_triplets.csv", index=False)

high_spec = ((t.metabolite_food_degree == 1) & (t.microbe_food_degree == 1)).sum()
promisc = (t.metabolite_food_degree >= 5).sum()
naive_top = set(t.sort_values("naive_rank").head(20).apply(lambda r: (r.food, r.microbe, r.metabolite), axis=1))
rob_top = set(t.sort_values("robustness_adjusted_rank").head(20).apply(lambda r: (r.food, r.microbe, r.metabolite), axis=1))
print(f"supported: fm={len(fm)} fb={len(fb)} bm={len(bm)} | candidates={len(t)}")
print(f"direction_coherent={int(t.direction_coherent.sum())} | mediator={t.mediator_hypothesis.value_counts().to_dict()}")
print(f"highly-specific (both deg 1)={high_spec} | promiscuous-metabolite(>=5 foods)={promisc}")
print(f"top-20 naive vs robustness overlap={len(naive_top & rob_top)}/20")
print(f"most promiscuous metabolites: {metab_deg.sort_values(ascending=False).head(4).to_dict()}")
