#!/usr/bin/env python3
"""Reference solution medge-150-1. The screen hands two flawed views of selection:
 (1) per-tumor fold_change  -> corrupted by single-tumor clonal BOTTLENECKS
 (2) tumor/baseline representation -> corrupted by LOW-BASELINE ratio instability
Neither alone is trustworthy. A defensible driver call requires BOTH: reproducible
elevation across tumors above the control-guide null, AND enrichment over baseline
with an adequate baseline (no winner's-curse). The contested middle is left as such."""
import pandas as pd, numpy as np, os
DATA=os.environ.get("DATA_DIR","environment/data"); OUT=os.environ.get("OUTPUT_DIR","output"); os.makedirs(OUT,exist_ok=True)
per=pd.read_csv(f"{DATA}/screen_per_tumor.csv")
rep=pd.read_csv(f"{DATA}/guide_representation.csv")

# control null from control guides' per-tumor fold changes
ctrl_fc=per[per.target_type=='Control']['fold_change']
null_hi=ctrl_fc.quantile(0.95)                 # per-tumor "elevated" bar from controls
print(f"control per-tumor FC: median={ctrl_fc.median():.2f} 95th={null_hi:.2f} max={ctrl_fc.max():.2f}")

g=per.groupby('guide_target').agg(
    target_type=('target_type','first'),
    fc_mean=('fold_change','mean'), fc_median=('fold_change','median'),
    fc_max=('fold_change','max'), n_tumors=('fold_change','size'),
    n_elevated=('fold_change', lambda s:(s>null_hi).sum())).reset_index()
g['domination']=g.fc_max/g.fc_median.replace(0,np.nan)
g=g.merge(rep,on='guide_target',how='left')
g['enrichment']=g.tumor_representation/g.baseline_representation
# baseline floor to exclude winner's-curse (near-zero denominators)
base_floor=rep.baseline_representation.quantile(0.10)
print(f"baseline floor (10th pct)={base_floor:.4f}")

# control null on the AGGREGATED metric too
ctrl_med=g[g.target_type=='Control'].fc_median
agg_null=ctrl_med.quantile(0.95)
g['reproducible']=(g.n_elevated>=5) & (g.fc_median>agg_null)         # not single-tumor, above control null
g['enriched_real']=(g.enrichment>1) & (g.baseline_representation>=base_floor)  # enriched w/ adequate baseline
g['is_driver']=g.reproducible & g.enriched_real
g['artifact']=np.where(g.is_driver,'',
   np.where((g.fc_mean>g.fc_mean.quantile(.9))&(~g.reproducible),'bottleneck_singletumor',
   np.where((g.enrichment>2)&(g.baseline_representation<base_floor),'low_baseline_winnerscurse','')))

out=g[['guide_target','target_type','fc_mean','fc_median','n_elevated','domination',
       'tumor_representation','baseline_representation','enrichment','is_driver','artifact']].round(3)
out.to_csv(f"{OUT}/driver_calls.csv",index=False)

print("\n=== reference drivers (is_driver=True) ===")
print(out[out.is_driver].sort_values('fc_mean',ascending=False).to_string(index=False))
print("\n=== clear CASE CHECK ===")
for gene in ['Notch1','Fat1','Trp53','Trp63','Adgrl2','Xirp2','Ttn','Myh2','Zmat3','Prkdc','Notch2']:
    r=out[out.guide_target==gene]
    if len(r): r=r.iloc[0]; print(f"  {gene:8s} driver={str(r.is_driver):5s} fc_mean={r.fc_mean:6.2f} n_elev={int(r.n_elevated)} enrich={r.enrichment:7.2f} base={r.baseline_representation:.4f} {r.artifact}")
