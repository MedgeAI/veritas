#!/usr/bin/env python3
"""Reproduce key quantitative values from Urhan & Abeel 2021 (Sci Rep) SARS-CoV-2
Netherlands variants paper, using shipped intermediate data (metadata + coronapp
mutations). Deterministic counts only; no MAFFT/IQ-TREE re-run."""
import json, sys
import numpy as np
import pandas as pd

DATA = sys.argv[1] if len(sys.argv) > 1 else "data"
meta = pd.read_csv(f"{DATA}/sarscov2_metadata.tsv", index_col=0, header=0, sep="\t")
mut = pd.read_csv(f"{DATA}/sarscov2_mutations_coronapp.tsv", sep="\t", index_col=0, header=0)

out = {}
# 1. total genomes
out["n_genomes_total"] = int(meta.shape[0])

# 2. regional distribution (Fig 1A): number of genomes per region
region_counts = meta.groupby("region")["date"].count().sort_values(ascending=False)
out["region_counts"] = {k: int(v) for k, v in region_counts.items()}
out["top_region"] = region_counts.index[0]
out["top_region_count"] = int(region_counts.iloc[0])

# 3. Netherlands: number of genomes
nl_idx = meta[meta.country == "Netherlands"].index
out["n_genomes_netherlands"] = int(len(nl_idx))

# 4. Fig 5 logic: samples with full date, intersect with mutation table
idx_all = meta[meta.date.apply(lambda x: len(str(x)) == 10)].index.intersection(set(mut.index))
out["n_samples_full_date_with_mutations"] = int(len(idx_all))

# Netherlands top-15 variants by count (Fig 5), frequency = count / n_NL_samples
nl_full = meta.loc[idx_all][meta.loc[idx_all].country == "Netherlands"].index
out["n_netherlands_full_date_mut"] = int(len(nl_full))
nl_top = mut.loc[nl_full].groupby("varname").count().refpos.nlargest(15)
nl_freq = (nl_top / len(nl_full)).round(6)
out["netherlands_top15_variants"] = {k: {"count": int(nl_top[k]), "freq": float(nl_freq[k])} for k in nl_top.index}

# D614G spike frequency in Netherlands (global near-fixation claim)
sp = [v for v in mut.loc[nl_full].varname.unique() if "D614G" in str(v)]
out["netherlands_D614G_varnames"] = sp
if sp:
    d614_counts = {}
    for v in sp:
        c = int((mut.loc[nl_full].varname == v).sum())
        d614_counts[v] = {"count": c, "freq": round(c/len(nl_full), 6)}
    out["netherlands_D614G"] = d614_counts

print(json.dumps(out, indent=2, ensure_ascii=False))
