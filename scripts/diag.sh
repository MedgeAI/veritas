#!/usr/bin/env bash
#
# Veritas 运行时诊断
#
# 检查所有基础设施、依赖、模型权重、环境变量是否就绪。
# 在跑 audit 之前执行一次，避免浪费时间后发现环境缺东西。
#
# 用法:
#   ./scripts/diag.sh          # 完整检查
#   ./scripts/diag.sh --json   # JSON 输出（供机器消费）
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

export VERITAS_DATABASE_URL="${VERITAS_DATABASE_URL:-postgresql://veritas:veritas@127.0.0.1:5433/veritas}"
export OPENCODE_BIN="${OPENCODE_BIN:-$(which opencode 2>/dev/null || echo opencode)}"

if [[ "${1:-}" == "--json" ]]; then
    uv run python -c "
from web.backend.veritas_web.diagnostics import run_full_diagnostics
import json
print(json.dumps(run_full_diagnostics().to_dict(), indent=2, ensure_ascii=False))
"
    exit 0
fi

uv run python -c "
from web.backend.veritas_web.diagnostics import run_full_diagnostics

report = run_full_diagnostics()

RESET  = '\033[0m'
GREEN  = '\033[32m'
RED    = '\033[31m'
YELLOW = '\033[33m'
CYAN   = '\033[36m'

print()
print(f'{CYAN}Veritas 运行时诊断{RESET}')
print('=' * 60)
print()

current_category = ''
category_labels = {
    'postgres': '── 基础设施 ──',
    'docker': '── 基础设施 ──',
    'opencode': '── 基础设施 ──',
    'gpu': '── 基础设施 ──',
    'pip': '── Python 依赖 ──',
    'model': '── 模型权重 ──',
    'image': '── Docker 镜像 ──',
    'env': '── 环境变量 ──',
    'fs': '── 文件系统 ──',
}

for c in report.checks:
    cat = c.name.split(':')[0] if ':' in c.name else c.name.split('_')[0]
    label = category_labels.get(cat, '')
    if label and label != current_category:
        current_category = label
        print(f'{CYAN}{label}{RESET}')

    if c.ok:
        icon = f'{GREEN}✔{RESET}'
    elif c.severity == 'critical':
        icon = f'{RED}✘{RESET}'
    else:
        icon = f'{YELLOW}⚠{RESET}'

    detail = f' — {c.detail}' if c.detail else ''
    print(f'  {icon} {c.name}{detail}')
    if not c.ok and c.fix_hint:
        print(f'    {YELLOW}→ {c.fix_hint}{RESET}')

print()
print('=' * 60)
cc = len(report.critical_failures)
ww = len(report.warnings)
if report.all_ok and not ww:
    print(f'{GREEN}全部就绪 ✔{RESET}')
elif report.all_ok:
    print(f'{GREEN}核心就绪 ✔{RESET}  {YELLOW}{ww} 个警告{RESET}')
else:
    print(f'{RED}{cc} 个关键问题{RESET}  {YELLOW}{ww} 个警告{RESET}')
print()
"
