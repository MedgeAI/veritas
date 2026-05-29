# 图像与视觉取证方法论

视觉审查必须先用确定性候选，再用 VLM 或人工复核。

## 当前内测方向

Veritas 下一阶段借鉴 ELIS (Scientific Integrity System) 的完整图像取证栈。ELIS-style 能力包括：

- PDF 图片提取和 panel 拆分。
- copy-move dense/keypoint 图内复用检测。
- TruFor 神经网络伪造检测。
- CBIR + Milvus 单论文内部相似检索。
- 视觉证据包和人工复核 checklist。

这些工具输出不能直接等同于不端结论。它们只能产生候选视觉事实、相似关系、伪造热区、人工复核优先级和良性解释压力测试。

## Canonical Evidence

所有视觉工具必须回链到同一套 canonical evidence：

- `figure_evidence`：来自 PDF/MinerU/ELIS pdf-extractor 的图像证据入口。
- `panel_evidence`：从 figure 中拆出的 panel、crop、bbox、label。
- `visual_finding`：copy-move、TruFor、VLM 或人工复核生成的视觉问题候选。
- `image_relationship`：exact duplicate、near duplicate、CBIR 相似关系、跨 panel 关系。

不要让 MinerU 图片、ELIS 图片、panel crop、mask、heatmap 各自成为互不相干的 truth。报告必须能从 finding 回溯到 PDF、figure、panel、工具输出和人工复核动作。

## 确定性候选

- 字节级重复：只能发现完全相同文件。
- 近似相似：裁剪、缩放、翻转、旋转、亮度/对比度修改。
- 局部复用：panel 内局部 copy-paste、细胞/组织区域重复。
- 同一主体不同信号：同一 mouse、cell、gel/blot 结构被标成不同条件。
- copy-move：应输出疑似复用区域、mask/overlay、方法、score 和目标 panel。
- TruFor：应输出 heatmap、score、模型版本、阈值和人工复核建议。
- CBIR：应输出候选图像对、相似分数、检索范围和是否同一论文内部。

## VLM 使用边界

- VLM 只做初筛和描述，不做最终裁决。
- 问题应聚焦具体视觉事实：主体轮廓、姿态、band 结构、细胞分布、signal layer、label/caption 冲突。
- VLM 输出必须回到图片路径、panel、caption、Source Data 或人工复核。
- 不用 AI 生成图作为 primary evidence。

## 人工复核入口

高优先级视觉 finding 应提供：

- 原图路径或裁图路径。
- 相似候选对。
- 相似方法和分数。
- copy-move mask、TruFor heatmap 或 CBIR relationship artifact。
- 对应 figure/panel/caption。
- 声称不同的实验条件。
- 最强良性解释。
