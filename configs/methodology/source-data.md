# Source Data 静态审查方法论

Source Data 是 Veritas 静态审查的最高优先级证据层之一。

## 必查对象

- workbook、sheet、隐藏 sheet、公式单元格、外部链接、命名区域、注释。
- 合并单元格、多层表头、空值结构、分组标签、单位和统计说明。
- 原始值、派生值、归一化值、百分比、均值、SD、SEM、CI。

## 通用异常线索

- 整列重复、整行重复、长连续重复序列。
- 固定差、固定比、线性变换、重复小数部分。
- 末位 0/5 集中、过于整齐的小数、异常圆整。
- 公式派生列、反向构造的百分比/分母关系。
- 同一数据在不同 figure/panel/condition 中机械复用。

## 误报排除顺序

1. 是否是编号列、样本 ID、lane 编号、坐标轴、时间点、浓度梯度。
2. 是否是设计矩阵、dummy variable、group label、contrast label。
3. 是否是公式派生、单位换算、归一化、背景扣除、百分比列。
4. 是否是合法 control 复用、同一数据多视角展示、技术重复。
5. 是否由合并单元格、多层表头、空值填充或解析器造成。

只有在排除上述路径后，才提升人工复核优先级。

## 输出要求

每个 Source Data finding 至少包含：

- workbook、sheet、row/column/cell 范围。
- 原始值样例。
- finding category。
- support rows / overlap rows / support rate。
- artifact likelihood。
- benign explanations。
- pressure-test result。
- manual review note。

claim-to-source-data 映射第一版允许到 sheet / figure 级，但必须标注尚未达到 panel 级强确认。

