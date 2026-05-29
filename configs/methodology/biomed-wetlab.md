# 生物医药干实验/湿实验审查方法论

本文件覆盖 Veritas 第一阶段主打的生物医药干实验静态审查，同时兼容常见湿实验材料。

## 常见材料

- Western blot、免疫荧光、免疫组化、流式、qPCR、ELISA、质谱、显微图。
- 动物实验、肿瘤体积、体重、组织重量、细胞活性、迁移/侵袭实验。
- densitometry、relative intensity、percentage、replicate measurements、normalized expression。

## 常见误报源

- 分子量 marker、lane 编号、时间点、剂量浓度、样本编号。
- loading control、housekeeping gene、同一 control 合法复用。
- 肿瘤体积公式，例如 `0.5 * length * width * width` 及其等价变体。
- 背景扣除、归一化到 control、fold change、百分比列。
- PDF/OCR 把 panel label、marker、legend 误抽成表格数据。

## 干实验优先核查点

- figure panel 与 Source Data sheet 是否能互相定位。
- 图注中的 n、p value、统计检验、误差线类型是否与 Source Data 一致。
- barplot/boxplot/scatter 的聚合方式是否可从底层值解释。
- 相同 control 或 loading control 是否跨图复用，是否有合理说明。
- 数字结果是否存在机械重复、固定关系或反向构造迹象。

## 判读原则

实验数据可能有自然变异，也可能有合法派生关系。数学上“整齐”不是结论，必须结合列语义、实验条件、图表用途和良性解释压力测试。

