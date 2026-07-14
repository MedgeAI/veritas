# rep_lazar : deterministic reproduction of demographic (Table 1) and
# subdataset descriptors from the pupil-size / lifespan study.
#
# Paper : Lazar & Spitschan (2024) "Regulation of pupil size in natural vision
#         across the human lifespan", R Soc Open Sci. CODECHECK cert. 2024-001.
# Repo  : github.com/codecheckers/LazarEtAl_RSocOpenSci_2024
#
# This script re-runs, in base R (fully deterministic, no MCMC), the merge +
# demographic + subdataset logic of the repo scripts
#   03_datamerge/30_datamerge.R, 04_demographics/40_demographics.R,
#   05_analysis/50_subdatasets.R
# from the two shipped intermediate data files (adjusted 0.75 data-loss
# threshold => n=83 included, the manuscript's primary analysis):
#   cleaned_survey.rda  -> object 'surveydata'
#   rawdata_ID_all.rda  -> object 'rawdata_ID_all'
#
# Output: repro_values.csv  (metric,value)
# Run   : Rscript repro_pupil.R   (from the directory holding the two .rda files)

options(stringsAsFactors = FALSE)

load("cleaned_survey.rda")
load("rawdata_ID_all.rda")

## --- 30_datamerge.R : left join raw observations with survey data by id ------
merged_data_all <- merge(rawdata_ID_all, surveydata, by = "id", all.x = TRUE)
merged_data_all$id <- factor(merged_data_all$id)

## --- 40_demographics.R : one row per participant; Table 1 by exclusion time --
dem_all <- merged_data_all[!duplicated(merged_data_all[c("id")]), ]
inc     <- merged_data_all[merged_data_all$excl == "results", ]   # included only
dem_inc <- inc[!duplicated(inc[c("id")]), ]

## --- 50_subdatasets.R : valid-pupil subset + experimental-phase subdatasets --
cf_data   <- inc[!is.na(inc$diameter_3d), ]
Fielddata <- cf_data[!is.na(cf_data$exp_phase) & cf_data$exp_phase == "Field" & !is.na(cf_data$Mel_EDI), ]
Darkdata  <- cf_data[!is.na(cf_data$exp_phase) & cf_data$exp_phase == "Dark", ]
Labdata   <- cf_data[!is.na(cf_data$exp_phase) & cf_data$exp_phase == "Lab"   & !is.na(cf_data$Mel_EDI), ]

out <- data.frame(
  metric = c(
    "n_invited_total", "n_included_primary", "n_excluded_post", "n_excluded_pre",
    "included_age_mean", "included_age_sd", "included_age_min", "included_age_max",
    "included_bmi_mean", "included_bmi_sd", "included_sex_female", "included_sex_male",
    "obs_field", "obs_dark", "obs_lab", "n_ids_field"),
  value = c(
    length(unique(merged_data_all$id)), length(unique(inc$id)),
    sum(dem_all$excl_time == "POST", na.rm = TRUE),
    sum(dem_all$excl_time == "PRE",  na.rm = TRUE),
    round(mean(dem_inc$age, na.rm = TRUE), 4), round(sd(dem_inc$age, na.rm = TRUE), 4),
    min(dem_inc$age, na.rm = TRUE), max(dem_inc$age, na.rm = TRUE),
    round(mean(dem_inc$BMI, na.rm = TRUE), 4), round(sd(dem_inc$BMI, na.rm = TRUE), 4),
    sum(dem_inc$sex == "Female", na.rm = TRUE), sum(dem_inc$sex == "Male", na.rm = TRUE),
    nrow(Fielddata), nrow(Darkdata), nrow(Labdata), length(unique(Fielddata$id)))
)
write.csv(out, "repro_values.csv", row.names = FALSE)
print(out)
cat("\nDONE\n")
