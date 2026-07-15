#!/usr/bin/env python3
"""NAIVE reproduction of medge-104-1: single direct exact join, NO food-label
harmonization. 'Alcohol' (food_microbe) never matches 'Alcoholic Beverages'
(food_metabolite), so every Alcohol-based mediation triplet is silently dropped.
Same support criterion as the reference; only the harmonization step is omitted.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control as bh

DATA = os.environ.get("DATA_DIR", "/app/data")
def bhfdr(p): return bh(np.asarray(p, float).clip(1e-300, 1))

fm_raw = pd.read_excel(f"{DATA}/food_metabolite_assoc.xlsx", header=1)
fb_raw = pd.read_excel(f"{DATA}/food_microbe_assoc.xlsx", header=1)
bm_raw = pd.read_excel(f"{DATA}/microbe_metabolite_assoc.xlsx", header=1)

# NAIVE: use raw food label directly, no CANON reconciliation
fm_raw["food"] = fm_raw["Food and Beverage Group"]
fb_raw["food"] = fb_raw["Food and Beverage Group"]

fm_raw["fm_stat"] = bhfdr(fm_raw["p value"])
fm = fm_raw[fm_raw["Significant"] == True].rename(
    columns={"Faecal Metabolite": "metabolite", "Beta": "fm_beta"})[["food","metabolite","fm_beta","fm_stat"]]
fb = fb_raw[(fb_raw["FDR"] < 0.05) & (fb_raw["Beta Same Direction"] == True)].rename(
    columns={"Gut Microbial Species": "microbe", "Beta": "fb_beta", "FDR": "fb_stat"})[["food","microbe","fb_beta","fb_stat"]]
bm_raw["bm_stat"] = bhfdr(bm_raw["p value"])
bm = bm_raw[bm_raw["Significant"] == True].rename(
    columns={"Gut Microbial Species": "microbe", "Faecal Metabolite": "metabolite", "Beta": "bm_beta"})[["microbe","metabolite","bm_beta","bm_stat"]]

t = fb.merge(fm, on="food").merge(bm, on=["microbe","metabolite"])
t = t.drop_duplicates(["food","microbe","metabolite"]).reset_index(drop=True)
t["direction_coherent"] = (np.sign(t.fm_beta)*np.sign(t.fb_beta)*np.sign(t.bm_beta)) > 0

alc_food_metab = fm[fm.food.str.contains("Alcohol")].food.unique().tolist()
alc_food_microbe = fb[fb.food.str.contains("Alcohol")].food.unique().tolist()
n_alcoholic = (t.food == "Alcoholic Beverages").sum()
n_alcohol = (t.food == "Alcohol").sum()
print(f"NAIVE (no harmonization): candidates={len(t)}")
print(f"direction_coherent={int(t.direction_coherent.sum())}")
print(f"food labels in food_metabolite Alcohol-like: {alc_food_metab}")
print(f"food labels in food_microbe   Alcohol-like: {alc_food_microbe}")
print(f"triplets with food=='Alcoholic Beverages'={n_alcoholic} | food=='Alcohol'={n_alcohol}")
print(f"per-food top: {t.food.value_counts().head(5).to_dict()}")
