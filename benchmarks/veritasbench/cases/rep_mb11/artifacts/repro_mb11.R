suppressMessages({
  library(dplyr); library(tidyr); library(readr); library(stringr)
})

## Load package data objects from data/*.rda
e <- new.env()
for (f in list.files("/work/data", pattern="\\.rda$", full.names=TRUE)) load(f, envir=e)
demography      <- get("demography", e)
metadata        <- get("metadata", e)
uhplc_data_comb <- get("uhplc_data_comb", e)

## ---- A. Demography counts (paper _materials.qmd) ----
n_ind <- nrow(demography)
n_m   <- sum(demography$sex == "m")
n_pm  <- sum(demography$sex == "pm")
n_pf  <- sum(demography$sex == "pf")
n_f   <- sum(demography$sex == "f")

## ---- B. Rebuild uhplc_calculus_long (from analysis/scripts/setup-qmd.R) ----
weight <- uhplc_data_comb %>%
  select(sample, batch1_weight, batch2_weight) %>%
  pivot_longer(cols=-sample, names_to="batch", values_to="weight") %>%
  mutate(batch=str_remove(batch,"_weight"), sample=as.character(sample))

uhplc_data_long <- uhplc_data_comb %>%
  mutate(sample=as.character(sample)) %>%
  select(!c(batch1_weight, batch2_weight)) %>%
  left_join(select(metadata, id, sample), by="sample") %>%
  pivot_longer(-c(sample,id), names_to=c("compound","extraction","batch"),
               names_pattern="(.*)_(.*)_(.*)", values_to="quant")

uhplc_calculus_long <- uhplc_data_long %>%
  filter(extraction=="calc") %>%
  left_join(weight, by=c("sample","batch")) %>%
  mutate(presence=if_else(quant>0,1,quant)) %>%
  group_by(id, sample, compound, batch) %>%
  mutate(conc=quant/weight) %>%
  left_join(demography, by="id")

## ---- Tobacco accuracy (paper _results.qmd) ----
tobacco <- uhplc_calculus_long %>%
  filter(batch=="batch2", compound %in% c("nicotine","cotinine"), sex=="m" | sex=="pm") %>%
  mutate(detection=if_else(quant==0,0,1))

tobacco_accuracy <- tobacco %>%
  filter(!is.na(quant)) %>%
  group_by(sample, id, .drop=FALSE) %>%
  summarise(detection=sum(detection), .groups="drop") %>%
  left_join(select(demography, id, pipe_notch, preservation, age), by="id") %>%
  mutate(pipe_notch=if_else(pipe_notch>0,"Y","N"),
         correct=case_when(
           detection==0 & pipe_notch=="N" ~ 1,
           detection>0  & pipe_notch=="Y" ~ 1,
           detection>0  & pipe_notch=="N" ~ NaN,
           TRUE ~ 0))

n_pipe        <- nrow(filter(tobacco_accuracy, pipe_notch=="Y"))
n_pipe_detect <- nrow(filter(tobacco_accuracy, pipe_notch=="Y", detection>0))
pct_pipe      <- 100*n_pipe_detect/n_pipe
overall_acc   <- 100*mean(tobacco_accuracy$correct, na.rm=TRUE)
old_acc       <- 100*mean(filter(tobacco_accuracy, age=="old")$correct, na.rm=TRUE)
n_old         <- sum(tobacco_accuracy$age=="old")

cat("REPRO_START\n")
cat(sprintf("n_individuals,%d\n", n_ind))
cat(sprintf("n_males,%d\n", n_m))
cat(sprintf("n_prob_males,%d\n", n_pm))
cat(sprintf("n_prob_females,%d\n", n_pf))
cat(sprintf("n_females,%d\n", n_f))
cat(sprintf("n_pipe_notch_indiv,%d\n", n_pipe))
cat(sprintf("n_pipe_notch_tobacco_detected,%d\n", n_pipe_detect))
cat(sprintf("pct_pipe_notch_detected,%.4f\n", pct_pipe))
cat(sprintf("overall_accuracy_pct,%.4f\n", overall_acc))
cat(sprintf("old_accuracy_pct,%.4f\n", old_acc))
cat(sprintf("n_old_adult,%d\n", n_old))
cat("REPRO_END\n")
