#!/usr/bin/env python3
"""Deterministic reproduction of the wearablehrv group-level validity analysis
for the manuscript 'Quality in Question' (OSF wkzsn).

Replicates the exact MAPE and Bland-Altman formulas from
wearablehrv/group.py (mape_analysis, blandaltman_analysis) on the shipped
aggregated dataset group.pickle. Criterion device = VU-AMS ECG ('vu').

Run: python3 reproduce.py  ->  writes mape_summary.csv
Only requires numpy (no GUI / plotly / pingouin deps).
"""
import pickle, csv, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
data = pickle.load(open(os.path.join(HERE, "group.pickle"), "rb"))
CRIT = "vu"

def mape(device, feature, condition):
    dc = data[device][feature][condition]
    cc = data[CRIT][feature][condition]
    errs = []
    for a, b in zip(dc.values(), cc.values()):
        if a and b and b[0] != 0:
            errs.append(abs(a[0] - b[0]) / abs(b[0]) * 100.0)
    return (float(np.mean(errs)) if errs else None), len(errs)

def ba_bias(device, feature, condition):
    dc = data[device][feature][condition]
    cc = data[CRIT][feature][condition]
    fd, fc = [], []
    for a, b in zip(dc.values(), cc.values()):
        if a and b:
            fd.append(a[0]); fc.append(b[0])
    if not fd:
        return None, None, 0
    diff = np.array(fd) - np.array(fc)
    return float(np.mean(diff)), float(np.std(diff, ddof=1)), len(diff)

rows = []
for feature in ["mean_hr", "rmssd"]:
    for condition in ["sitting", "biking"]:
        for device in ["heartmath", "kyto", "rhythm", "empatica"]:
            m, n = mape(device, feature, condition)
            bias, sd, nb = ba_bias(device, feature, condition)
            rows.append({
                "device": device, "feature": feature, "condition": condition,
                "MAPE": round(m, 4) if m is not None else "",
                "n": n,
                "BA_bias": round(bias, 4) if bias is not None else "",
                "BA_sd": round(sd, 4) if sd is not None else "",
            })

out = os.path.join(HERE, "mape_summary.csv")
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["device","feature","condition","MAPE","n","BA_bias","BA_sd"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
print("wrote", out)
for r in rows:
    print(r)
