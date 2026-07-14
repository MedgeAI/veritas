## Reproduce the downstream `results table` chunk of PowerCalc.qmd (Zauner et al. 2024, PLoS ONE)
## on the paper's shipped code-output Results/Power_data.csv.
## This is verbatim the paper's dplyr/tidyr logic (lines 781-796 of PowerCalc.qmd).
suppressMessages({library(readr); library(dplyr); library(tidyr)})

Power_level <- 0.8   # params$Power_level in the qmd

Power_data <- read_csv("/work/Results/Power_data.csv", show_col_types = FALSE)

# --- verbatim paper logic (results table chunk) ---
Power_summary <-
  Power_data %>%
  group_by(Name) %>%
  mutate(Power_reached = power >= Power_level) %>%
  filter(Power_reached, .preserve = TRUE) %>%
  slice_min(sample_size) %>%
  select(-Power_reached) %>%
  ungroup()

set1 <- Power_summary$Name
set2 <- unique(Power_data$Name)
missing <- base::setdiff(set2, set1)   # metrics that never reach 80% power

Power_summary <- Power_summary %>% arrange(sample_size, power)

dir.create("/out", showWarnings = FALSE)
write_csv(Power_summary, "/out/Power_summary_reproduced.csv")
writeLines(missing, "/out/missing_metrics.txt")

cat("=== Required sample size per metric (power >= 0.8) ===\n")
print(as.data.frame(Power_summary), row.names = FALSE)
cat("\n=== Metrics that never reach 80% power ===\n")
print(missing)
cat("\nn_metrics_total =", length(set2), "\n")
cat("n_metrics_reaching_80 =", length(set1), "\n")
cat("dplyr_version =", as.character(packageVersion("dplyr")), "\n")
cat("REPRODUCE_OK\n")
