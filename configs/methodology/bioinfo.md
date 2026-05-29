# 生物信息审查方法论

本文件为后续生信代码/数据执行审查保留方法论接口。第一版不做同等深度实现。

## 常见材料

- count matrix、TPM/FPKM、metadata、sample sheet。
- DESeq2、edgeR、limma、Seurat、scanpy、survival analysis 输出。
- PCA、UMAP、heatmap、volcano、enrichment、survival curve 结果表。
- notebook、R/Python scripts、Snakemake/Nextflow、配置文件、随机种子。

## 静态核查点

- 样本 ID 在 metadata、矩阵、结果表、图表之间是否一致。
- 过滤阈值、归一化方法、批次校正、设计矩阵是否与论文声明一致。
- p value、adjusted p value、log2 fold change、排名、top genes 是否可追踪到结果文件。
- reference genome、annotation version、数据库版本是否记录。
- 缺少原始数据但有 processed data 时，只报告材料缺口和复核限制。

## 常见误报源

- gene set、sample ID、rank index、cluster label 合法重复。
- 设计矩阵 dummy variables 和 contrast labels 导致固定关系。
- multiple-testing correction、四舍五入、科学计数法造成表面机械关系。

代码执行型核查由 `runtime/` 负责，本文件只定义静态方法论和未来接口。

