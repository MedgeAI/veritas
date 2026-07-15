#!/usr/bin/env python3
"""rep_zebrafish 复现脚本 (grounding lane).
读取 eLife 54937 (Antinucci, Dumitrescu et al 2020) 作者随代码发布的
voltage-clamp 光电流分析中间产物 (Analysis_output/*_master.csv),
确定性重算论文/README 记录的关键光电流值. 无随机性.
CODECHECK 2025-023 认证 (Figs 4/5/8/9 可部分复现).
"""
import json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
vce = pd.read_csv(os.path.join(HERE, "VC_excitatory_opsin_master.csv"))
vci = pd.read_csv(os.path.join(HERE, "VC_inhibitory_opsin_master.csv"))

out = {}

# --- 兴奋性 opsin VC 光电流 ---
chr_rows = vce[vce.trace_number == "18n270027_1"]        # Chrimson
coc_rows = vce[vce.trace_number == "2019_03_19_0038"]    # CoChR

# README 记录的正确性锚点: 18n270027_1 第1次 LED 刺激峰值光电流
out["chrimson_18n270027_1_firststim_max_pA"] = float(chr_rows["Max_photocurrent_pA"].iloc[0])
out["chrimson_18n270027_1_overall_max_pA"]   = float(chr_rows["Max_photocurrent_pA"].max())
out["cochr_2019_03_19_0038_overall_max_pA"]  = float(coc_rows["Max_photocurrent_pA"].max())

# --- 抑制性 opsin VC 光电流 (NpHR3.0, inactivation) ---
nphr = vci[vci.trace_number == "183060053_1"]            # NpHR3.0
idx = nphr["Max_photocurrent_pA"].idxmax()
out["nphr_183060053_1_peak_max_pA"]      = float(nphr["Max_photocurrent_pA"].max())
out["nphr_183060053_1_steady_at_peak_pA"] = float(nphr.loc[idx, "Steady_photocurrent_pA"])
out["nphr_183060053_1_all_steady_lt_max"] = bool((nphr["Steady_photocurrent_pA"] < nphr["Max_photocurrent_pA"]).all())

print(json.dumps(out, indent=2))
with open(os.path.join(HERE, "repro_output.json"), "w") as f:
    json.dump(out, f, indent=2)
