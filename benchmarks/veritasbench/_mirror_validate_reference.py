#!/usr/bin/env python3
# 镜像 data-collection-guide §6 的 9 项检查(非官方validate_veritasbench.py,自检用).
import json, os, hashlib, sys

case_dir = sys.argv[1]
errs, warns = [], []
cj = os.path.join(case_dir, "case.json")
if not os.path.exists(cj):
    print("FAIL: no case.json"); sys.exit(1)
c = json.load(open(cj))

# 2. case_id 匹配目录
if c.get("case_id") != os.path.basename(case_dir.rstrip("/")):
    errs.append(f"case_id {c.get('case_id')} != dir {os.path.basename(case_dir)}")

arts = c.get("artifacts", {})
obs = c.get("observations", {})
claims = c.get("claims", [])

VALID_KIND = {"paper_pdf","source_data","code","code_output","table","figure","supplement"}
ENUM_REL = {"L1","L2","L3","L4"}
ENUM_VERDICT = {"consistent","inconsistent","insufficient"}

# 3. artifact 文件存在 + sha256 一致
art_hashes = {}
for name, a in arts.items():
    p = os.path.join(case_dir, a.get("path",""))
    if not os.path.exists(p):
        errs.append(f"artifact {name}: file missing {a.get('path')}"); continue
    h = hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(65536),b""): h.update(b)
    dig = h.hexdigest()
    if dig != a.get("sha256"):
        errs.append(f"artifact {name}: sha256 mismatch")
    if a.get("kind") not in VALID_KIND:
        warns.append(f"artifact {name}: kind '{a.get('kind')}' 非标准")
    art_hashes[a.get("path")] = dig

# 4/5. observation 有 value/source/hash/span + hash 与 artifact 一致
for ok, o in obs.items():
    for req in ("value","source_artifact","source_artifact_hash","source_span"):
        if req not in o: errs.append(f"obs {ok}: 缺 {req}")
    sa = o.get("source_artifact")
    if sa not in art_hashes:
        errs.append(f"obs {ok}: source_artifact {sa} 不在 artifacts")
    elif o.get("source_artifact_hash") != art_hashes.get(sa):
        errs.append(f"obs {ok}: source_artifact_hash 与 artifact 不一致")

# 6/7. claim 字段/枚举/引用/evidence span
clean_cnt = 0
for cl in claims:
    for req in ("annotation_id","claim_id","claim_atom","relation_type","verdict","source_artifact","target_artifact","annotator_id","annotation_timestamp"):
        if req not in cl: errs.append(f"claim {cl.get('claim_id')}: 缺 {req}")
    if cl.get("relation_type") not in ENUM_REL:
        errs.append(f"claim {cl.get('claim_id')}: relation 非法")
    if cl.get("verdict") not in ENUM_VERDICT:
        errs.append(f"claim {cl.get('claim_id')}: verdict 非法")
    if cl.get("verdict") in ("consistent","inconsistent") and not cl.get("evidence_span"):
        errs.append(f"claim {cl.get('claim_id')}: consistent/inconsistent 须有 evidence_span")
    for ep in ("source_artifact","target_artifact"):
        if cl.get(ep) not in obs:
            errs.append(f"claim {cl.get('claim_id')}: {ep} {cl.get(ep)} 不在 observations")
    if cl.get("is_clean_claim"):
        clean_cnt += 1
        if cl.get("verdict") != "consistent":
            errs.append(f"claim {cl.get('claim_id')}: is_clean_claim=true 须 verdict=consistent")

# 8. 至少一个 clean claim
if clean_cnt < 1: errs.append("无 clean claim")
# 9. metadata
md = c.get("metadata",{})
if "paper_split" not in md: errs.append("metadata 缺 paper_split")
if "primary_failure_mode" not in md: errs.append("metadata 缺 primary_failure_mode")

print(f"=== {c.get('case_id')} ===")
print(f"  artifacts={len(arts)} observations={len(obs)} claims={len(claims)} clean={clean_cnt}")
print(f"  ERRORS ({len(errs)}):")
for e in errs: print("   ✗", e)
print(f"  WARN ({len(warns)}):")
for w in warns: print("   ⚠", w)
print("  RESULT:", "PASS ✅" if not errs else "FAIL ✗")
sys.exit(0 if not errs else 2)
