# 静态审查工具脚本

当前 `scripts/` 下的脚本已从产品主链路降级为兼容 wrapper 或独立工具。实际静态审查逻辑位于 `engine/static_audit/tools/`，由 `engine/static_audit/orchestrator.py` 的 `run_static_audit()` 统一编排。

## 当前角色

| 脚本 | 当前状态 | 实际逻辑位置 |
| --- | --- | --- |
| `run_paper_audit.py` | 9 行兼容 wrapper | `engine/static_audit/orchestrator.py` |
| `source_data_profile.py` | wrapper，调用 first-party 实现 | `engine/static_audit/tools/source_data_profile.py` |
| `source_data_findings.py` | wrapper，调用 first-party 实现 | `engine/static_audit/tools/source_data_findings.py` |
| `image_similarity_candidates.py` | wrapper，调用 first-party 实现 | `engine/static_audit/tools/image_similarity.py` |
| `opencode-server.sh` | 独立工具脚本，不进入产品主链路 | `scripts/opencode-server.sh` |

## 历史说明

早期 `run_paper_audit.py` 是完整的 877 行编排脚本，直接调用 MinerU、Source Data 脚本、Agent review 和报告生成。现在它的职责是：

1. 接收 CLI 参数（与 `cli/main.py audit-paper` 兼容）。
2. 调用 `engine.static_audit.orchestrator.run_static_audit()`。
3. 将 orchestrator 返回的 summary JSON 打印到 stdout。

这样做的目的是保持向后兼容：习惯直接运行 `python3 scripts/run_paper_audit.py` 的用户仍可用，但产品主入口已统一到 `cli/main.py` 和 Web backend。

Source Data 脚本保留了同样的 CLI 接口，但实际检测逻辑已迁入 `engine/static_audit/tools/`，包括：

- XLSX workbook/sheet profile
- duplicate column / fixed ratio / fixed difference / formula-derived column 检测
- row-offset pair forensics / scalar-multiple / low-width duplicate row
- claim-to-source-data deterministic scaffolding

这些工具现在通过 `engine/tools/registry.py` 注册，由 orchestrator 控制执行顺序，而不是被脚本直接硬编码调用。
