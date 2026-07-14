import argparse, io, json, sys, hashlib, warnings, os
from typing import List, Dict, Tuple, Optional
import numpy as np, pandas as pd, requests

from lifelines.utils import concordance_index
from lifelines import KaplanMeierFitter

from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression

from scipy.stats import norm
import xgboost as xgb

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from lifelines import CoxPHFitter, WeibullAFTFitter
    HAVE_COX = HAVE_WAFT = True
except Exception:
    HAVE_COX = HAVE_WAFT = False

try:
    from lifelines import RandomSurvivalForest
    HAVE_RSF = True
except Exception:
    HAVE_RSF = False

FEATURES_17 = [
    "trt","age","sex","ascites","hepato","spiders","edema",
    "bili","chol","albumin","copper","alk.phos","ast","trig",
    "platelet","protime","stage"
]

def ensure_dirs():
    os.makedirs("figures", exist_ok=True)
    os.makedirs("results", exist_ok=True)

def download_pbc():
    urls = [
        "https://vincentarelbundock.github.io/Rdatasets/csv/survival/pbc.csv",
        "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/survival/pbc.csv",
    ]
    last_err = None
    for url in urls:
        try:
            r = requests.get(url, timeout=30); r.raise_for_status()
            raw = r.content
            df = pd.read_csv(io.BytesIO(raw))
            first = df.columns[0].lower()
            if first in ("unnamed: 0","x1","rowname","row.names","rowname","rownames"):
                df = df.drop(columns=df.columns[0])
            if "rownames" in df.columns:
                df = df.drop(columns=["rownames"])
            sha = hashlib.sha256(raw).hexdigest()
            return df, url, sha
        except Exception as e:
            last_err = e
    raise RuntimeError(f"download failed: {last_err}")

def build_pbc276(df: pd.DataFrame):
    cols = ["time","status"] + FEATURES_17
    missing = [c for c in cols if c not in df.columns]
    if missing: raise ValueError(f"missing columns: {missing}")
    sub = df[cols].dropna(subset=cols).copy()
    time = sub["time"].astype(float).to_numpy()
    event = (sub["status"] == 2).astype(int).to_numpy()
    y_lower = time.copy()
    y_upper = np.where(event == 1, time, np.inf)
    X = sub.drop(columns=["time","status"])
    return X, y_lower, y_upper, time, event, sub.shape[0]

def _ohe_kwargs():
    kw = {}
    if "sparse_output" in OneHotEncoder.__init__.__code__.co_varnames:
        kw["sparse_output"] = False
    else:
        kw["sparse"] = False
    kw["handle_unknown"] = "ignore"
    return kw

def fit_preprocess(X_fit: pd.DataFrame, X_transform_list: List[pd.DataFrame]):
    cat_cols = [c for c in X_fit.columns if X_fit[c].dtype == "object"]
    for c in ["trt","stage","sex","ascites","hepato","spiders","edema"]:
        if c in X_fit.columns and c not in cat_cols and X_fit[c].nunique(dropna=True) <= 8:
            X_fit[c] = X_fit[c].astype("category"); cat_cols.append(c)
            for Xt in X_transform_list:
                if c in Xt.columns: Xt[c] = Xt[c].astype("category")
    num_cols = [c for c in X_fit.columns if c not in cat_cols]
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(**_ohe_kwargs()), cat_cols),
         ("num", "passthrough", num_cols)]
    )
    Xs = [pre.fit_transform(X_fit)] + [pre.transform(Xt) for Xt in X_transform_list]
    Xs = [np.asarray(X, dtype=np.float32) for X in Xs]
    return Xs, cat_cols, num_cols, pre

def get_feature_names(pre: ColumnTransformer, num_cols: List[str]) -> List[str]:
    cat_names = []
    try:
        cat_trf = pre.named_transformers_["cat"]
        cat_input = pre.transformers_[0][2]
        if hasattr(cat_trf, "get_feature_names_out"):
            cat_names = list(cat_trf.get_feature_names_out(cat_input))
    except Exception:
        cat_names = []
    names = cat_names + (num_cols or [])
    return [str(n) for n in names]

def dmatrix_from(X: np.ndarray, y_lower: np.ndarray, y_upper: np.ndarray):
    d = xgb.DMatrix(np.asarray(X, dtype=np.float32), missing=np.nan)
    d.set_float_info("label_lower_bound", y_lower.astype(np.float32))
    d.set_float_info("label_upper_bound", y_upper.astype(np.float32))
    return d

def train_xgb_aft(Xtr, yl_tr, yu_tr, params, rounds, seed):
    p = dict(params); p["seed"] = int(seed)
    bst = xgb.train(params=p, dtrain=dmatrix_from(Xtr, yl_tr, yu_tr),
                    num_boost_round=rounds,
                    evals=[(dmatrix_from(Xtr, yl_tr, yu_tr),"train")],
                    verbose_eval=False)
    return bst, p

def predict_mu(bst, X):
    return bst.predict(xgb.DMatrix(np.asarray(X, dtype=np.float32), missing=np.nan)).ravel()

def orient_risk_on_train(mu_tr, t_tr, e_tr):
    c1 = float(concordance_index(event_times=t_tr, predicted_scores=mu_tr,   event_observed=e_tr))
    c2 = float(concordance_index(event_times=t_tr, predicted_scores=-mu_tr,  event_observed=e_tr))
    return (+1, c1) if c1 >= c2 else (-1, c2)

def F_standard(z, dist: str):
    d = (dist or "normal").lower()
    if d == "logistic": return 1.0/(1.0+np.exp(-z))
    if d == "extreme":  return np.exp(-np.exp(-z))
    return norm.cdf(z)

def cindex(scores, times, events):
    return float(concordance_index(event_times=times, predicted_scores=scores, event_observed=events))

def _ipcw_from_train(times_train, events_train, eval_times, gmin: float):
    km = KaplanMeierFitter()
    cens_train = (events_train == 0).astype(int)
    km.fit(durations=times_train, event_observed=cens_train)
    def G(u):
        g = float(km.predict(u))
        return max(g, 0.0)
    G_grid = np.array([G(t) for t in eval_times])
    mask = G_grid > gmin
    return G, G_grid, mask

def ibs_from_survival_curves(times_train, events_train,
                             times_test, events_test,
                             S_mat, eval_times, gmin: float):
    assert S_mat.shape[1] == len(eval_times)
    G_fn, G_grid, mask = _ipcw_from_train(times_train, events_train, eval_times, gmin=gmin)
    if not np.any(mask):
        tau_fb = float(np.quantile(times_test[events_test == 1], 0.90)) if np.any(events_test == 1) else float(np.quantile(times_test, 0.90))
        mask = eval_times <= tau_fb
    eval_eff = eval_times[mask]
    S_eff = S_mat[:, mask]
    G_grid_eff = np.maximum(G_grid[mask], 1e-6)
    G_T = np.array([max(G_fn(tt), 1e-6) for tt in times_test])
    bs = []
    for k, t in enumerate(eval_eff):
        S_t = S_eff[:, k]
        m1 = (times_test <= t) & (events_test == 1)
        m2 = (times_test > t)
        part1 = np.where(m1, (S_t)**2 / G_T, 0.0)
        part2 = np.where(m2, (1.0 - S_t)**2 / G_grid_eff[k], 0.0)
        bs.append(np.mean(part1 + part2))
    bs = np.asarray(bs, float)
    if len(eval_eff) < 2:
        return float(bs[0]) if len(bs) == 1 else float("nan")
    return float(np.trapz(bs, eval_eff) / (eval_eff[-1] - eval_eff[0]))

def bootstrap_ci(values: np.ndarray, alpha: float = 0.05, n_boot: int = 2000, seed: int = 0):
    vals = np.array(values, float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n = len(vals)
    means = []
    for _ in range(n_boot):
        samp = vals[rng.integers(0, n, size=n)]
        means.append(float(np.mean(samp)))
    lo, hi = np.percentile(means, [100*alpha/2.0, 100*(1-alpha/2.0)])
    return float(lo), float(hi)

def compute_numeric_stats(X_df: pd.DataFrame, num_cols: List[str]):
    X_num = X_df[num_cols].astype(float).to_numpy()
    means = np.nanmean(X_num, axis=0)
    stds = np.nanstd(X_num, axis=0)
    stds = np.where(stds == 0.0, 1e-8, stds)
    mins = np.nanmin(X_num, axis=0); maxs = np.nanmax(X_num, axis=0)
    return means, stds, mins, maxs

def standardize_num(X_df: pd.DataFrame, num_cols: List[str], means: np.ndarray, stds: np.ndarray):
    return (X_df[num_cols].astype(float).to_numpy() - means) / stds

def unstandardize_num(Z: np.ndarray, means: np.ndarray, stds: np.ndarray):
    return Z * stds + means

def define_concepts_train(X_train_df: pd.DataFrame):
    q75_bili = X_train_df["bili"].astype(float).quantile(0.75)
    q75_alp  = X_train_df["alk.phos"].astype(float).quantile(0.75)
    q75_prot = X_train_df["protime"].astype(float).quantile(0.75)
    q75_age  = X_train_df["age"].astype(float).quantile(0.75)
    q25_alb  = X_train_df["albumin"].astype(float).quantile(0.25)
    c = {}
    c["cholestasis"] = ((X_train_df["bili"].astype(float) >= q75_bili) &
                        (X_train_df["alk.phos"].astype(float) >= q75_alp)).astype(int).to_numpy()
    c["coagulopathy"] = (X_train_df["protime"].astype(float) >= q75_prot).astype(int).to_numpy()
    c["low_albumin"]  = (X_train_df["albumin"].astype(float) <= q25_alb).astype(int).to_numpy()
    c["older_age"]    = (X_train_df["age"].astype(float) >= q75_age).astype(int).to_numpy()
    comp = ((X_train_df["ascites"].astype(float) > 0.5) |
            (X_train_df["edema"].astype(float) > 0.0) |
            (X_train_df["spiders"].astype(float) > 0.5)).astype(int)
    c["clinical_complications"] = comp.to_numpy()
    return c

def train_cav_probes(Z_num_train: np.ndarray, concepts: Dict[str, np.ndarray]):
    cav = {}
    for name, y in concepts.items():
        if y.mean() == 0.0 or y.mean() == 1.0: continue
        lr = LogisticRegression(penalty="l2", C=1.0, class_weight="balanced",
            solver="liblinear", max_iter=200)
        lr.fit(Z_num_train, y)
        w = lr.coef_.ravel()
        n = np.linalg.norm(w)
        if n == 0.0: continue
        cav[name] = w / n
    return cav

def gen_alpha_grid(h: float):
    return np.array([-5*h, -2*h, -h, -0.5*h, 0.5*h, h, 2*h, 5*h], dtype=float)

def predict_mu_smoothed(bst, pre, X_df, num_cols, means, stds, mins, maxs,
                        sigma=0.04, K=80, seed=0):
    rng = np.random.default_rng(seed)
    n = len(X_df); mu_acc = np.zeros(n, dtype=float)
    Z0 = standardize_num(X_df, num_cols, means, stds)
    for _ in range(K):
        noise = rng.normal(0.0, sigma, size=Z0.shape)
        Zp = Z0 + noise
        Xp_num = np.minimum(np.maximum(unstandardize_num(Zp, means, stds), mins), maxs)
        Xp = X_df.copy(); Xp.loc[:, num_cols] = Xp_num
        Xp_enc = pre.transform(Xp).astype(np.float32)
        mu_acc += predict_mu(bst, Xp_enc)
    return mu_acc / float(K)

def tcav_mu_slope_smoothed(bst, pre, X_val_df, num_cols, means, stds, mins, maxs,
                           w_hat, h=0.02, sigma=0.04, K=80, seed=0):
    rng = np.random.default_rng(seed)
    alphas = gen_alpha_grid(h)
    mu_list = []
    for a in alphas:
        Xs = X_val_df.copy()
        Z0 = standardize_num(Xs, num_cols, means, stds)
        Zp = Z0 + a * w_hat
        Xs.loc[:, num_cols] = np.minimum(np.maximum(unstandardize_num(Zp, means, stds), mins), maxs)
        mu_s = predict_mu_smoothed(bst, pre, Xs, num_cols, means, stds, mins, maxs,
                                   sigma=sigma, K=K, seed=rng.integers(0, 1_000_000))
        mu_list.append(mu_s)
    mu_mat = np.vstack(mu_list)
    A = np.vstack([np.ones_like(alphas), alphas]).T
    slope = np.linalg.pinv(A) @ mu_mat
    return slope[1, :]

def winsorize(x: np.ndarray, p: float = 10.0) -> np.ndarray:
    if len(x) == 0: return x
    lo, hi = np.percentile(x, [p, 100.0 - p]); return np.clip(x, lo, hi)

def trimmed_mean(x: np.ndarray, proportion_to_cut: float = 0.10) -> float:
    if len(x) == 0: return float("nan")
    k = int(np.floor(proportion_to_cut * len(x))); xs = np.sort(x)
    if 2*k >= len(xs): return float(np.mean(xs))
    return float(np.mean(xs[k:len(xs)-k]))

def bootstrap_ci_fn(x: np.ndarray, fn, n_boot: int = 1000, alpha: float = 0.05, seed: int = 0):
    rng = np.random.default_rng(seed); vals = []; n = len(x)
    for _ in range(n_boot):
        samp = x[rng.integers(0, n, size=n)]; vals.append(fn(samp))
    lower, upper = np.percentile(vals, [100*alpha/2.0, 100*(1-alpha/2.0)])
    return float(lower), float(upper)

def plot_validation_metrics(c_list, ibs_list, outpath: str):
    c = np.array(c_list, float)
    ibs = np.array(ibs_list, float)
    fig = plt.figure(figsize=(9,4))
    ax1 = fig.add_subplot(1,2,1)
    ax1.hist(c, bins=10)
    ax1.set_title("C-index across runs")
    ax1.set_xlabel("C-index")
    ax1.set_ylabel("Count")
    ax2 = fig.add_subplot(1,2,2)
    ax2.scatter(c, ibs, s=20)
    ax2.set_title("IBS vs C-index (validation)")
    ax2.set_xlabel("C-index")
    ax2.set_ylabel("IBS")
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()

def plot_tcav_bar(rows: pd.DataFrame, outpath: str):
    order = rows.sort_values("dmu_es").index
    x = np.arange(len(order))
    y = rows.loc[order, "dmu_es"].to_numpy()
    ylo = rows.loc[order, "dmu_es_lo"].to_numpy()
    yhi = rows.loc[order, "dmu_es_hi"].to_numpy()
    labels = rows.loc[order, "concept"].tolist()
    yerr = np.vstack([y - ylo, yhi - y])
    plt.figure(figsize=(9,5))
    plt.bar(x, y, yerr=yerr, capsize=4)
    plt.xticks(x, labels, rotation=20, ha="right")
    plt.ylabel("Δμ / SD(μ)")
    plt.title("Surv-TCAV directional effects (last split)")
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()

def plot_calibration_at_horizon(times, events, S_pred, horizon, outpath: str, n_bins=10):
    risk = 1.0 - S_pred
    bins = pd.qcut(risk, q=np.linspace(0,1,n_bins+1), labels=False, duplicates="drop")
    df = pd.DataFrame({"time":times,"event":events,"bin":bins,"risk":risk})
    obs, pred = [], []
    km = KaplanMeierFitter()
    for b in sorted(df["bin"].dropna().unique()):
        sub = df[df["bin"]==b]
        if len(sub)==0: continue
        km.fit(sub["time"].values, event_observed=sub["event"].values)
        S_obs = float(km.predict(horizon))
        obs.append(1.0 - S_obs)
        pred.append(float(sub["risk"].mean()))
    if len(obs)==0: return
    plt.figure(figsize=(5,5))
    plt.plot([0,1],[0,1], linestyle="--")
    plt.scatter(pred, obs)
    plt.xlabel("Predicted event probability by t*")
    plt.ylabel("Observed event probability by t* (KM)")
    plt.title(f"Calibration at t*={horizon:.0f}")
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()

def _to_df_with_time_event(X_enc: np.ndarray, feature_names: List[str], times: np.ndarray, events: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(X_enc, columns=feature_names)
    df["__T__"] = times.astype(float)
    df["__E__"] = events.astype(int)
    return df

def eval_baseline_cox(Xtr_enc, Xva_enc, feat_names, t_tr, e_tr, t_va, e_va, eval_times, gmin) -> Tuple[float,float,np.ndarray]:
    if not HAVE_COX:
        return np.nan, np.nan, np.full((len(t_va), len(eval_times)), np.nan)
    df_tr = _to_df_with_time_event(Xtr_enc, feat_names, t_tr, e_tr)
    cox = CoxPHFitter(penalizer=0.1)
    cox.fit(df_tr, duration_col="__T__", event_col="__E__", show_progress=False)
    risk_scores = cox.predict_partial_hazard(pd.DataFrame(Xva_enc, columns=feat_names)).values.ravel()
    c_val = max(cindex(risk_scores, t_va, e_va), cindex(-risk_scores, t_va, e_va))
    surv_df = cox.predict_survival_function(pd.DataFrame(Xva_enc, columns=feat_names), times=eval_times)
    S_mat = surv_df.T.values
    ibs_val = ibs_from_survival_curves(t_tr, e_tr, t_va, e_va, S_mat, eval_times, gmin=gmin)
    return c_val, ibs_val, S_mat

def eval_baseline_waft(Xtr_enc, Xva_enc, feat_names, t_tr, e_tr, t_va, e_va, eval_times, gmin) -> Tuple[float,float,np.ndarray]:
    if not HAVE_WAFT:
        return np.nan, np.nan, np.full((len(t_va), len(eval_times)), np.nan)
    df_tr = _to_df_with_time_event(Xtr_enc, feat_names, t_tr, e_tr)
    waft = WeibullAFTFitter(penalizer=0.0)
    waft.fit(df_tr, duration_col="__T__", event_col="__E__")
    med = waft.predict_median(pd.DataFrame(Xva_enc, columns=feat_names)).values
    scores = -np.log(np.maximum(med, 1e-8))
    c_val = max(cindex(scores, t_va, e_va), cindex(-scores, t_va, e_va))
    surv_df = waft.predict_survival_function(pd.DataFrame(Xva_enc, columns=feat_names), times=eval_times)
    S_mat = surv_df.T.values
    ibs_val = ibs_from_survival_curves(t_tr, e_tr, t_va, e_va, S_mat, eval_times, gmin=gmin)
    return c_val, ibs_val, S_mat

def eval_baseline_rsf(Xtr_enc, Xva_enc, feat_names, t_tr, e_tr, t_va, e_va, eval_times, gmin) -> Tuple[float,float,np.ndarray]:
    if not HAVE_RSF:
        return np.nan, np.nan, np.full((len(t_va), len(eval_times)), np.nan)
    rsf = RandomSurvivalForest(
        n_estimators=300, max_depth=None, min_samples_split=10, min_samples_leaf=3,
        random_state=0, n_jobs=-1
    )
    df_tr = _to_df_with_time_event(Xtr_enc, feat_names, t_tr, e_tr)
    rsf.fit(df_tr, duration_col="__T__", event_col="__E__", show_progress=False)
    S_curves = rsf.predict_survival_function(pd.DataFrame(Xva_enc, columns=feat_names), times=eval_times)
    S_mat = np.vstack([np.interp(eval_times, s.index.values, s.values) for s in S_curves])
    t_ref = float(np.median(t_va))
    scores = 1.0 - np.array([np.interp(t_ref, eval_times, S_mat[i, :]) for i in range(S_mat.shape[0])])
    c_val = max(cindex(scores, t_va, e_va), cindex(-scores, t_va, e_va))
    ibs_val = ibs_from_survival_curves(t_tr, e_tr, t_va, e_va, S_mat, eval_times, gmin=gmin)
    return c_val, ibs_val, S_mat

def load_and_print_sota(sota_json_path: Optional[str], protocol_tag: str):
    print("--- Reference SOTA (same dataset/task; user-supplied) ---")
    if not sota_json_path:
        print("No --sota_json provided. Add one to print verified reference numbers for EXACTLY the same protocol.")
        return
    try:
        with open(sota_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(json.dumps({
            "dataset": data.get("dataset",""),
            "protocol_expected": protocol_tag,
            "protocol_in_file": data.get("protocol",""),
            "entries": data.get("entries",[])
        }, ensure_ascii=False))
    except Exception as e:
        print(f"[warn] SOTA file not loaded: {e}")

def parse_args():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--repeats", type=int, default=25)
    ap.add_argument("--val_size", type=float, default=0.20)
    ap.add_argument("--rounds", type=int, default=800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--aft_dist", type=str, default="extreme")
    ap.add_argument("--aft_scale", type=float, default=0.4)
    ap.add_argument("--lr", type=float, default=0.02)
    ap.add_argument("--max_depth", type=int, default=10)
    ap.add_argument("--min_child_weight", type=float, default=5.0)
    ap.add_argument("--subsample", type=float, default=0.6)
    ap.add_argument("--colsample_bytree", type=float, default=0.6)
    ap.add_argument("--lambda_", type=float, default=4.0)
    ap.add_argument("--alpha", type=float, default=0.0)
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--gmin", type=float, default=1e-3, help="Min G(t) for IBS integration (IPCW). Increase to 5e-3/1e-2 if unstable.")
    ap.add_argument("--tcav_trim", type=float, default=0.10)
    ap.add_argument("--tcav_winsor", type=float, default=10.0)
    ap.add_argument("--tcav_boot", type=int, default=1000)
    ap.add_argument("--tcav_h", type=float, default=0.02)
    ap.add_argument("--tcav_sigma", type=float, default=0.04)
    ap.add_argument("--tcav_K", type=int, default=80)
    ap.add_argument("--no_shap", action="store_true")
    ap.add_argument("--fig_validation", type=str, default="figures/validation_metrics.png")
    ap.add_argument("--fig_treeshap", type=str, default="figures/treeshap_summary.png")
    ap.add_argument("--fig_tcav", type=str, default="figures/tcav_bar.png")
    ap.add_argument("--fig_calib", type=str, default="figures/calibration_tstar.png")
    ap.add_argument("--results_csv", type=str, default="results/split_metrics.csv")
    ap.add_argument("--summary_csv", type=str, default="results/summary_metrics.csv")
    ap.add_argument("--no_cox", action="store_true")
    ap.add_argument("--no_waft", action="store_true")
    ap.add_argument("--no_rsf", action="store_true")
    ap.add_argument("--sota_json", type=str, default=None, help="Path to a JSON with verified SOTA numbers for this exact protocol.")
    return ap.parse_args()

def main():
    warnings.filterwarnings("ignore")
    ensure_dirs()
    args = parse_args()

    params = {
        "objective": "survival:aft",
        "eval_metric": "aft-nloglik",
        "aft_loss_distribution": args.aft_dist,
        "aft_loss_distribution_scale": args.aft_scale,
        "tree_method": "gpu_hist" if args.gpu else "hist",
        "learning_rate": args.lr,
        "max_depth": args.max_depth,
        "min_child_weight": args.min_child_weight,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
        "lambda": args.lambda_,
        "alpha": args.alpha,
    }

    df_raw, src_url, src_sha = download_pbc()
    X_all, yl_all, yu_all, t_all, e_all, n_rows = build_pbc276(df_raw)
    miss_any = int(df_raw[["time","status"]+FEATURES_17].isna().any(axis=1).sum())
    cens_rate = float(1.0 - e_all.mean())
    print(json.dumps({
        "dataset":"PBC-276","source":src_url,"sha256":src_sha,
        "n_rows":n_rows,"features":len(FEATURES_17),
        "rows_dropped_missing": miss_any, "censoring_rate": round(cens_rate,3)
    }, ensure_ascii=False))

    load_and_print_sota(args.sota_json, protocol_tag="25x_80_20_internal")

    rows_split = []
    c_xgb, ibs_xgb = [], []
    c_cox, ibs_cox = [], []
    c_waft, ibs_waft = [], []
    c_rsf, ibs_rsf = [], []

    last_bst = last_pre = last_train_df = None
    last_num_cols = None; last_num_stats = None
    last_feat_names = None
    last_eval_times = None
    last_Xva_enc, last_t_va, last_e_va = None, None, None
    last_params = None

    for i in range(args.repeats):
        seed = args.seed + i
        X_tr, X_va, yl_tr, yl_va, yu_tr, yu_va, t_tr, t_va, e_tr, e_va = train_test_split(
            X_all, yl_all, yu_all, t_all, e_all, test_size=args.val_size,
            random_state=seed, stratify=e_all
        )
        (Xtr, Xva), cat_cols, num_cols, pre = fit_preprocess(X_tr.copy(), [X_va.copy()])
        feat_names = get_feature_names(pre, num_cols)

        tau = float(np.max(t_va))
        eps = max(1e-6, float(np.min(t_va[t_va > 0])) if np.any(t_va > 0) else 1e-6)
        eval_times = np.linspace(eps, tau, 100)

        bst, used = train_xgb_aft(Xtr, yl_tr, yu_tr, params, args.rounds, seed)
        mu_tr = predict_mu(bst, Xtr)
        mu_va = predict_mu(bst, Xva)

        sign, c_tr_best = orient_risk_on_train(mu_tr, t_tr, e_tr)
        c_va = cindex(sign * mu_va, t_va, e_va)

        Tgrid = np.log(np.clip(eval_times, 1e-8, None))
        z = (Tgrid[None,:] - mu_va[:,None]) / params["aft_loss_distribution_scale"]
        dist = params["aft_loss_distribution"].lower()
        if dist == "logistic":
            F = 1.0/(1.0+np.exp(-z))
        elif dist == "extreme":
            F = np.exp(-np.exp(-z))
        else:
            F = norm.cdf(z)
        S_mat_xgb = 1.0 - F

        ibs_val = ibs_from_survival_curves(t_tr, e_tr, t_va, e_va, S_mat_xgb, eval_times, gmin=args.gmin)
        c_xgb.append(c_va); ibs_xgb.append(ibs_val)

        Xtr_enc = Xtr; Xva_enc = Xva
        if (not args.no_cox) and HAVE_COX:
            c_b, ibs_b, _ = eval_baseline_cox(Xtr_enc, Xva_enc, feat_names, t_tr, e_tr, t_va, e_va, eval_times, gmin=args.gmin)
            c_cox.append(c_b); ibs_cox.append(ibs_b)

        if (not args.no_waft) and HAVE_WAFT:
            c_b, ibs_b, _ = eval_baseline_waft(Xtr_enc, Xva_enc, feat_names, t_tr, e_tr, t_va, e_va, eval_times, gmin=args.gmin)
            c_waft.append(c_b); ibs_waft.append(ibs_b)

        if (not args.no_rsf) and HAVE_RSF:
            try:
                c_b, ibs_b, _ = eval_baseline_rsf(Xtr_enc, Xva_enc, feat_names, t_tr, e_tr, t_va, e_va, eval_times, gmin=args.gmin)
                c_rsf.append(c_b); ibs_rsf.append(ibs_b)
            except Exception as e:
                print(f"[warn] RSF skipped this run: {e}")

        rows_split.append({
            "run": i+1, "seed": seed, "tau": round(tau,3),
            "c_xgb": c_va, "ibs_xgb": ibs_val,
            "c_cox": (c_cox[-1] if len(c_cox)>0 else np.nan),
            "ibs_cox": (ibs_cox[-1] if len(ibs_cox)>0 else np.nan),
            "c_waft": (c_waft[-1] if len(c_waft)>0 else np.nan),
            "ibs_waft": (ibs_waft[-1] if len(ibs_waft)>0 else np.nan),
            "c_rsf": (c_rsf[-1] if len(c_rsf)>0 else np.nan),
            "ibs_rsf": (ibs_rsf[-1] if len(ibs_rsf)>0 else np.nan),
        })

        print(f"[run {i+1:02d} seed={seed}] XGB-AFT C={c_va:.3f} | IBS={ibs_val:.3f} | tau={tau:.3f}")

        last_bst, last_pre, last_train_df = bst, pre, X_tr.copy()
        last_num_cols = num_cols.copy()
        last_feat_names = feat_names
        last_num_stats = compute_numeric_stats(last_train_df, last_num_cols)
        last_eval_times = eval_times
        last_Xva_enc, last_t_va, last_e_va = Xva_enc, t_va, e_va
        last_params = params.copy()

    df_splits = pd.DataFrame(rows_split)
    df_splits.to_csv("results/split_metrics.csv", index=False)
    print(f"[info] per-split metrics saved -> results/split_metrics.csv")

    def summarize(name: str, c_list: List[float], i_list: List[float]):
        arr_c = np.array(c_list, float)
        arr_i = np.array(i_list, float)
        mC = float(np.nanmean(arr_c)) if arr_c.size else float("nan")
        sC = float(np.nanstd(arr_c, ddof=1)) if arr_c.size>1 else float("nan")
        loC, hiC = bootstrap_ci(arr_c, seed=123)
        mI = float(np.nanmean(arr_i)) if arr_i.size else float("nan")
        sI = float(np.nanstd(arr_i, ddof=1)) if arr_i.size>1 else float("nan")
        loI, hiI = bootstrap_ci(arr_i, seed=456)
        return {
            "model": name,
            "C_mean": mC, "C_sd": sC, "C_boot_lo": loC, "C_boot_hi": hiC,
            "IBS_mean": mI, "IBS_sd": sI, "IBS_boot_lo": loI, "IBS_boot_hi": hiI
        }

    summaries = [summarize("xgb", c_xgb, ibs_xgb)]
    if len(c_cox)>0:  summaries.append(summarize("cox",  c_cox,  ibs_cox))
    if len(c_waft)>0: summaries.append(summarize("waft", c_waft, ibs_waft))
    if len(c_rsf)>0:  summaries.append(summarize("rsf",  c_rsf,  ibs_rsf))

    df_sum = pd.DataFrame(summaries)
    if not df_sum.empty:
        best_c = df_sum["C_mean"].max()
        best_ibs = df_sum["IBS_mean"].min()
        df_sum["gap_C_to_best"] = best_c - df_sum["C_mean"]
        df_sum["gap_IBS_to_best"] = df_sum["IBS_mean"] - best_ibs
    df_sum.to_csv("results/summary_metrics.csv", index=False)
    print(f"[info] summary metrics saved -> results/summary_metrics.csv")
    print("=== FAIR COMPARISON SUMMARY (PBC-276, 25× 80/20; IBS[0, tau_eff], KM on TRAIN, G>gmin) ===")
    print(df_sum.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    try:
        plot_validation_metrics(c_xgb, ibs_xgb, "figures/validation_metrics.png")
        print(f"[info] validation plot saved -> figures/validation_metrics.png")
    except Exception as e:
        print(f"[warn] validation plot skipped: {e}")

    if (not args.no_shap) and (last_bst is not None):
        try:
            import shap
            Xtrain_enc = last_pre.transform(last_train_df).astype(np.float32)
            feat_names = get_feature_names(last_pre, last_num_cols)
            if len(feat_names) != Xtrain_enc.shape[1]:
                feat_names = [f"f{i}" for i in range(Xtrain_enc.shape[1])]
            explainer = shap.TreeExplainer(last_bst)
            shap_values = explainer.shap_values(Xtrain_enc)
            plt.figure(figsize=(9,6))
            shap.summary_plot(shap_values, Xtrain_enc, feature_names=feat_names, show=False)
            plt.tight_layout()
            plt.savefig("figures/treeshap_summary.png", dpi=200)
            plt.close()
            print(f"[info] TreeSHAP saved -> figures/treeshap_summary.png")
        except Exception as e:
            print(f"[warn] SHAP skipped: {e}")

    print("=== Surv-TCAV (last split) — directional effect on μ ===")
    if last_bst is None or last_pre is None or last_train_df is None:
        print("TCAV skipped"); sys.exit(0)

    concepts = define_concepts_train(last_train_df)
    means, stds, mins, maxs = last_num_stats
    seed_last = args.seed + (args.repeats - 1)
    X_tr2, X_va_last, *_ = train_test_split(
        X_all, yl_all, yu_all, t_all, e_all,
        test_size=0.20, random_state=seed_last, stratify=e_all
    )

    Z_num_train = standardize_num(last_train_df, last_num_cols, means, stds)
    cav_dirs = train_cav_probes(Z_num_train, concepts)

    mu_val_base = predict_mu(last_bst, last_Xva_enc)
    sd_mu_val = float(np.std(mu_val_base, ddof=1)) or 1.0

    rows = []
    for name, w_hat in cav_dirs.items():
        pos_rate = float(concepts[name].mean())
        if pos_rate <= 0.0 or pos_rate >= 1.0:
            print(f"[{name}] skip"); continue
        slope_mu = tcav_mu_slope_smoothed(
            last_bst, last_pre, X_va_last.copy(), last_num_cols, means, stds, mins, maxs,
            w_hat, h=0.02, sigma=0.04, K=80, seed=seed_last
        )
        slope_mu_w = winsorize(slope_mu, p=10.0)
        dmu = trimmed_mean(slope_mu_w, proportion_to_cut=0.10)
        dmu_lo, dmu_hi = bootstrap_ci_fn(slope_mu_w, lambda v: trimmed_mean(v, 0.10),
                                         n_boot=1000, seed=seed_last)
        dmu_es = dmu / sd_mu_val
        dmu_es_lo, dmu_es_hi = dmu_lo / sd_mu_val, dmu_hi / sd_mu_val
        rows.append({"concept":name,"dmu":dmu,"dmu_lo":dmu_lo,"dmu_hi":dmu_hi,
                     "dmu_es":dmu_es,"dmu_es_lo":dmu_es_lo,"dmu_es_hi":dmu_es_hi,"pos_rate":pos_rate})
        print(f"[TCAV] {name:20s}  Δμ = {dmu:+.6f} ({dmu_lo:+.6f},{dmu_hi:+.6f})  "
              f"Δμ/SD(μ) = {dmu_es:+.3f} ({dmu_es_lo:+.3f},{dmu_es_hi:+.3f})  pos_rate={pos_rate:.2f}")

    try:
        df_tcav = pd.DataFrame(rows)
        if not df_tcav.empty:
            plot_tcav_bar(df_tcav, "figures/tcav_bar.png")
            print(f"[info] TCAV bar saved -> figures/tcav_bar.png")
    except Exception as e:
        print(f"[warn] TCAV plot skipped: {e}")

    try:
        t_star = float(np.median(last_t_va))
        mu_last = predict_mu(last_bst, last_Xva_enc)
        z = (np.log(np.clip(t_star,1e-8,None)) - mu_last) / last_params["aft_loss_distribution_scale"]
        dist = last_params["aft_loss_distribution"].lower()
        if dist == "logistic":
            F = 1.0/(1.0+np.exp(-z))
        elif dist == "extreme":
            F = np.exp(-np.exp(-z))
        else:
            F = norm.cdf(z)
        S_pred = 1.0 - F
        plot_calibration_at_horizon(last_t_va, last_e_va, S_pred, t_star, "figures/calibration_tstar.png", n_bins=10)
        print(f"[info] calibration plot saved -> figures/calibration_tstar.png")
    except Exception as e:
        print(f"[warn] calibration plot skipped: {e}")

    print("=== Reporting notes (TRIPOD-lite) ===")
    print("* Internal validation (25× 80/20)")
    print("* Event of interest: death (status==2). Transplant treated as censored.")

if __name__ == "__main__":
    main()
