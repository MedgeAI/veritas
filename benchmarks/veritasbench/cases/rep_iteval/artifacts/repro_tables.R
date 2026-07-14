## Deterministic downstream reproduction of Tables 1 & 2 from Hoogland et al. (2024)
## sim.10186 — reads the 500 shipped results/ite*.Rdata, computes RMSE tables.

## DescTools::Trim (verbatim algorithm) — symmetric trimming of proportion `trim` from each end.
Trim <- function(x, trim = 0.1, na.rm = FALSE){
  if(na.rm) x <- x[!is.na(x)]
  n <- length(x)
  lo <- floor(n * trim) + 1
  hi <- n + 1 - lo
  x <- sort.int(x, partial = unique(c(lo, hi)), na.last = TRUE)[lo:hi]
  return(x)
}

dir <- "results/"
files <- list.files(dir)
files <- grep("ite*", files, value = TRUE)
nsim <- length(files)
nss <- 3

numextract <- function(string){ as.numeric(regmatches(string, regexpr("-?[0-9]+", string))) }
files <- files[order(numextract(files))]

sr <- lapply(paste0(dir, files), function(x){ load(x); return(list=(r=results)) })
names(sr) <- paste0("sim", numextract(files))
sample.sizes <- c(500, 750, 1000)

cat("nsim =", nsim, "\n")

## augmentation loop (from replicate.R) so ext1/ext2 total have cforbenefit(.new)
for(i in 1:nsim){
  for(j in 1:length(sample.sizes)){
    sr[[i]][[j]]$ext1.total.discr$cforbenefit     <- sr[[i]][[j]]$ext1.app.discr$cforbenefit
    sr[[i]][[j]]$ext1.total.discr$cforbenefit.new <- sr[[i]][[j]]$ext1.app.discr$cforbenefit.new
    sr[[i]][[j]]$ext2.total.discr$cforbenefit     <- sr[[i]][[j]]$ext2.app.discr$cforbenefit
    sr[[i]][[j]]$ext2.total.discr$cforbenefit.new <- sr[[i]][[j]]$ext2.app.discr$cforbenefit.new
  }
}

######################## Discrimination RMSE (Table 1) ########################
discr.list <- c("apparent.discr", "ext1.app.discr", "ext2.app.discr",
                "boot0.632.discr", "boot.opt.discr", "ext1.total.discr",
                "ext2.total.discr")

rmse.discr <- function(sr, m, ref="sample", pl=FALSE, digits=NULL){
  rmse.data <- array(as.numeric(sapply(sr, function(x) sapply(x, function(xx) unlist(xx[m])))),
                     dim=c(5, nss, nsim))
  main <- c("cbendelta", "cbeny0hat", "mbcb", "cbennew")
  err <- lapply(1:4, function(x) rmse.data[x,,] - rmse.data[5,,])
  out <- t(sapply(err, function(x) apply(x, 1, function(xx) sqrt(mean(xx^2)))))
  colnames(out) <- paste0("n", sample.sizes)
  rownames(out) <- c("cbendelta", "cbeny0hat", "mbcb", "cbennew")
  if(!is.null(digits)) out <- round(out, digits)
  return(out)
}

table1 <- t(sapply(discr.list, function(m){
  xx <- t(rmse.discr(sr, m, ref="sample", pl=FALSE, digits=3))
  c(cben      = paste(xx[1], xx[2], xx[3], sep=","),   # cben-delta
    cben_new  = paste(xx[10], xx[11], xx[12], sep=","),# cben ppte (new)
    cben_y0hat= paste(xx[4], xx[5], xx[6], sep=","),   # cben-y0hat
    mbcm      = paste(xx[7], xx[8], xx[9], sep=","))   # mbcm
}))
cat("\n================= TABLE 1: Discrimination RMSE (n500,n750,n1000) =================\n")
df1 <- as.data.frame(table1)
df1 <- cbind(validation = rownames(df1), df1)
print(df1, row.names = FALSE)
write.csv(df1, "table1_discrimination.csv", row.names = FALSE)

######################## Calibration RMSE (Table 2) ########################
cal.list <- c("apparent.cal", "boot0.632.cal", "boot.opt.cal", "ext1.total.cal",
              "ext2.total.cal")

rmse.cal <- function(sr, m, pl=FALSE, digits=NULL, ...){
  empirical.both <- ifelse(!is.null(sr$sim1$n500[[m]]$empirical.both), TRUE, FALSE)
  true.both      <- ifelse(!is.null(sr$sim1$n500[[m]]$empirical.both), TRUE, FALSE)

  rmse.data <- cbind(
    if(empirical.both) t(array(as.numeric(sapply(sr, function(x) sapply(x, function(xx) unlist(xx[[m]]$empirical.both[1])))),
                               dim=c(nss, nsim))) else matrix(NA, nsim, nss),
    if(m != "boot0.632.cal") t(array(as.numeric(sapply(sr, function(x) sapply(x, function(xx) unlist(xx[[m]]$true.both[1])))),
                                     dim=c(nss, nsim))) else matrix(NA, nsim, nss),
    if(empirical.both) t(array(as.numeric(sapply(sr, function(x) sapply(x, function(xx) unlist(xx[[m]]$empirical.both[2])))),
                               dim=c(nss, nsim))) else matrix(NA, nsim, nss),
    if(true.both) t(array(as.numeric(sapply(sr, function(x) sapply(x, function(xx) unlist(xx[[m]]$true.both[2])))),
                          dim=c(nss, nsim))) else matrix(NA, nsim, nss))

  rmse.data <- rmse.data[ ,as.numeric(matrix(1:12, 4, 3, byrow = TRUE))]
  err <- rmse.data[ ,c(1,3,5,7,9,11)] - rmse.data[ ,c(1,3,5,7,9,11)+1]
  err <- err[ ,c(1,3,5,2,4,6)]
  err.list <- lapply(1:ncol(err), function(x) Trim(err[ ,x], trim=.1))
  err <- cbind(err.list[[1]], err.list[[2]], err.list[[3]], err.list[[4]], err.list[[5]], err.list[[6]])
  out <- apply(err, 2, function(x) sqrt(mean(x^2)))
  names(out) <- rep(paste0("n", sample.sizes), each=2)
  return(out)
}

table2 <- t(sapply(cal.list, function(m){ t(rmse.cal(sr, m, pl=F, digits=3)) }))
## After the c(1,3,5,2,4,6) reorder inside rmse.cal, columns are grouped:
## intercept (beta0) at n500/n750/n1000, then slope (beta1) at n500/n750/n1000.
colnames(table2) <- c("beta0_n500","beta0_n750","beta0_n1000","beta1_n500","beta1_n750","beta1_n1000")
cat("\n================= TABLE 2: Calibration RMSE =================\n")
df2 <- round(as.data.frame(table2), 4)
df2 <- cbind(validation = rownames(df2), df2)
print(df2, row.names = FALSE)
write.csv(df2, "table2_calibration.csv", row.names = FALSE)

cat("\n=== DONE ===\n")
