# reproduce.R — rep_mqg86 (Gawehns et al., consumer wearables x dementia PA)
# 复现 manuscript Figure 3 (CorrelationMatrix_5sec_hc.tif) 的底层相关系数矩阵。
#
# 上游未重跑: 原始加速度计 .dat -> MAD/ENMO 5sec-epoch 特征提取 (GGIR/WEARDA 风格,
#   见 ExtractMAD_EN_ENMO_MIMS.R / FormatACCData.R) + MEDLO 行为观测 + Samsung 24hrs
#   活动识别日志的清洗/归一化/连接 (LinkData_Correlations.R)。原始个体数据未公开
#   (README: data not available, 隐私)。采用论文 shipped 中间产物 linkedData.rds
#   (12 residents x 14 measures, PlottingScripts.R L9 读入) 作为确定性下游输入。
#
# 下游确定性复现: PlottingScripts.R L91 `corrplot(cor(LinkedData_21_5sec), ...)`
#   的底层 cor() Pearson 相关矩阵 (hclust 仅重排显示,不改数值)。

d <- readRDS("artifacts/linkedData.rds")
stopifnot(nrow(d) == 12)              # 12 residents (完整配对: 同时有 wearable+observation)
m <- cor(d)                           # Pearson 相关矩阵 = Figure 3 底层数值

cat("n_residents            =", nrow(d), "\n")
cat("MADmean~Light          =", round(m["MADmean","Light"], 4), "\n")     # 0.775
cat("MADmean~Inactive       =", round(m["MADmean","Inactive"], 4), "\n")  # -0.5902
cat("MADsd~MADqant          =", round(m["MADsd","MADqant"], 4), "\n")     # 0.9945
cat("MADmean~MADsd          =", round(m["MADmean","MADsd"], 4), "\n")     # 0.9443
cat("Inactive~Light         =", round(m["Inactive","Light"], 4), "\n")    # -0.8884
cat("Inactive~MLO2          =", round(m["Inactive","MLO2"], 4), "\n")     # 0.8215

write.csv(round(m, 4), "artifacts/repro_cor_matrix_5sec.csv")
