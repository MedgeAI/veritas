
# Color Category Mini Study -----------------------------------------------
library(ggplot2)

# Open Processed Dataset
ds <- read.csv("https://osf.io/download/jcmt9/") # dataset

nrow(ds) # number of participants

co <- matrix(data = NA, nrow = length(ds$CASE), ncol = 20) # create empty matrix
c1c <- which(colnames(ds) == "CO01_01" ) # estimate: get column numbers for loop
r1c <- which(colnames(ds) == "RA01x01" ) # stimulus number

for (i in 1:length(ds$CASE)) { # for each participant
  for (j in 1:20) { # for 20 estimates
    # i <- j <- 1
    estimateno <- ds[i, r1c-1+j]
    co[i, estimateno] <- ds[i, c1c-1+j]
  }
}

cocol <- apply(co, 2, FUN = "mean")
cocolsd <- apply(co, 2, FUN = "sd")
cocol <- data.frame(cbind(cocol, cocolsd))
names(cocol) <- c("m", "sd")

cocol$n <- length(ds$CASE)
cocol$ucb <- cocol$m + (qnorm(.975)*cocol$sd/sqrt(cocol$n))
cocol$lcb <- cocol$m - (qnorm(.975)*cocol$sd/sqrt(cocol$n))
plot(cocol$m, type = "b", xlab = "presented", ylab = "perceived", ylim = c(0, 100))
lines(cocol$lcb, type = "l", col = "blue", lty = 3)
lines(cocol$ucb, type = "l", col = "blue", lty = 3)
abline(a = 0, b = 5, col = "red", lty = 2)

# Individual results
plot(cocol$m, type = "n", xlab = "presented", ylab = "perceived", ylim = c(0, 100))
for (i in 1:length(ds$CASE)) {
  lines(co[i,], type = "l", col = rgb(0, 0, i/length(ds$CASE), .1), lwd = 5)
}
abline(a = 0, b = 5, col = "red", lty = 2, lwd = 5)

# look at individual participants
# for (i in 1:length(ds$CASE)) {
#   plot(co[i,], type = "l", ylim = c(0, 100), main = i, xlab = "presented", ylab = "perceived")
#   abline(a = 0, b = 5, col = "red", lty = 2)
#   Sys.sleep(1)
# }

ggplot(cocol, aes(x = as.numeric(rownames(cocol))*5, y = m)) + geom_point() +
  geom_errorbar(aes(ymax = ucb, ymin = lcb)) +
  theme_classic() + geom_abline(yintercept = 0, slope = 1) + ylim(c(0, 100)) + xlim(c(0,105)) +
  xlab("Stimulus redness in %") + ylab("Estimated redness in %")
ggsave("pilot.jpg", height = 800, width = 800, units = "px", scale = 1.5)
