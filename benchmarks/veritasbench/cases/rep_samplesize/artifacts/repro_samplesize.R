options(repos="https://cloud.r-project.org")
if(!requireNamespace("neuroUp",quietly=TRUE)) install.packages("neuroUp",quiet=TRUE)
library(neuroUp)
sd_fun <- getFromNamespace("sample_diff","neuroUp")
sc_fun <- getFromNamespace("sample_corr","neuroUp")
cat("=====SAMPLE_DIFF_SRC=====\n"); print(sd_fun)
cat("=====SAMPLE_CORR_SRC=====\n"); print(sc_fun)

fmt <- function(lbl,v) cat(sprintf("REPRO|%s|%s\n",lbl,paste(format(v,digits=10),collapse=",")))

# ---- Cohen's d at N = total (deterministic full-sample) ----
d_fb <- sd_fun(feedback, c("mfg_learning","mfg_application"), nrow(feedback))
d_gm <- sd_fun(gambling, c("lnacc_self_win","lnacc_self_loss"), nrow(gambling))
d_se <- sd_fun(self_eval, c("mpfc_self","mpfc_control"), nrow(self_eval))
d_vc <- sd_fun(vicar_char, c("nacc_selfgain","nacc_bothnogain"), nrow(vicar_char))
cat("names sample_diff:\n"); print(names(d_fb)); print(unlist(d_fb))
fmt("feedback_d", c(N=nrow(feedback), d_fb$cohens_d, d_fb$d_lower, d_fb$d_upper))
fmt("gambling_d", c(N=nrow(gambling), d_gm$cohens_d, d_gm$d_lower, d_gm$d_upper))
fmt("selfeval_d", c(N=nrow(self_eval), d_se$cohens_d, d_se$d_lower, d_se$d_upper))
fmt("gaining_d",  c(N=nrow(vicar_char), d_vc$cohens_d, d_vc$d_lower, d_vc$d_upper))

# ---- Correlation with age at N = total ----
fb <- feedback; fb$dif <- fb$mfg_learning - fb$mfg_application
se <- self_eval; se$dif <- se$mpfc_self - se$mpfc_control
vc <- vicar_char; vc$dif <- vc$nacc_selfgain - vc$nacc_bothnogain
c_fb <- sc_fun(fb, c("dif","age"), nrow(fb))
c_gm <- sc_fun(gambling, c("lnacc_self_winvsloss","age"), nrow(gambling))
c_se <- sc_fun(se, c("dif","age"), nrow(se))
c_vc <- sc_fun(vc, c("dif","age"), nrow(vc))
cat("names sample_corr:\n"); print(unlist(c_fb))
fmt("feedback_corr", c(N=nrow(fb), unlist(c_fb)))
fmt("gambling_corr", c(N=nrow(gambling), unlist(c_gm)))
fmt("selfeval_corr", c(N=nrow(se), unlist(c_se)))
fmt("gaining_corr",  c(N=nrow(vc), unlist(c_vc)))
cat("=====DONE=====\n")
