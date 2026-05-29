# CLI

The CLI is the only user-facing surface in the MVP.

Supported commands:

- `veritas precheck <manifest>`
- `veritas run <manifest>`
- `veritas report <report.json>`
- `veritas audit-paper <paper_dir>`

Paper-audit first-stage example:

```bash
python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --agent-mode review --agent-timeout-seconds 180 --agent-max-retries 1 --progress plain
```

当前老板 demo 推荐使用 `--agent-mode review`：先生成 `material_inventory.json`，由 opencode material planner 选择可执行 optional lane；再复用或执行确定性 MinerU/evidence/source-data/image 检查；最后由 opencode 读取结构化产物生成 claim/finding 复核 JSON、role trace、Markdown 和 HTML 报告。`--agent-mode full` 会额外调用 `agent_plan`，目前仍可能遇到模型非 JSON 输出，不作为稳定 demo 默认路径。

`audit-paper` 的进度输出使用 `--progress auto|plain|jsonl|off` 控制。进度写入 `stderr`，最终 summary JSON 仍写入 `stdout`，方便命令行观察同时保留脚本可解析性。`auto` 在交互终端等价于 `plain`，在管道/测试环境默认安静；如果需要强制显示，使用 `--progress plain`。MinerU 子进程的 `state/pages` 输出会作为 `OUT mineru` 进度行转发。

只跑确定性链路时使用：

```bash
python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --agent-mode off
```

从零重跑并禁止复用既有 MinerU 产物：

```bash
python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --fresh --force --agent-mode review --progress plain
```
