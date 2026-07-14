
# Color Category Mini Study -----------------------------------------------
library(ggplot2)
library(reshape)
library(dplyr)
library(psych)

# 100ms GIF study
redblue <- c(
   rgb(9  /255, 0,  1)
  ,rgb(35 /255, 0,  1)
  ,rgb(63 /255, 0,  1)
  ,rgb(86 /255, 0,  1)
  ,rgb(111/255, 0,  1)
  ,rgb(139/255, 0,  1)
  ,rgb(165/255, 0,  1)
  ,rgb(189/255, 0,  1)
  ,rgb(216/255, 0,  1)
  ,rgb(241/255, 0,  1)
  ,rgb(255/255, 0,  244/255)
  ,rgb(1   , 0,     216/255)
  ,rgb(1   , 0,     191/255)
  ,rgb(1   , 0,     165/255)
  ,rgb(1   , 0,     139/255)
  ,rgb(1   , 0,     113/255)
  ,rgb(1   , 0,     87/255)
  ,rgb(1   , 0,     61/255)
  ,rgb(1   , 0,     36/255)
  ,rgb(1   , 0,     11/255))

rb <- data.frame("hex" = redblue
                 , "red" = c(
                   9/255,
                  35/255,
                 63/255,
                 86/255,
                 111/255,
                 139/255,
                 165/255,
                 189/255,
                 216/255,
                 241/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255,
                 255/255)
                 , "blue" = c(
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   255/255, 
                   244/255, 
                   216/255, 
                   191/255, 
                   165/255, 
                   139/255, 
                   113/255, 
                   87/255, 
                   61/255, 
                   36/255, 
                   11/255
                 )
                   )

rb$scalepoint <- rb$red - rb$blue
rb$scalepoint100 <- (rb$scalepoint+1)*50 # convert values to 0-100 scale

# Open Dataset
ds <- read.csv("https://osf.io/download/bksxg/") # processed dataset

# Descriptives ------------------------------------------------------------

table(ds$DE01, useNA = "always") # 1 = male, 2 = female, 3 = diverse, -9 = no response
psych::describe(as.numeric(ds$DE02_01)) # age
psych::describe(ds$dis) # number of correctly solved arithmetic tasks (distractors)

# Distractor tasks times
# (1:20)*3 # pages, for which TIME needs to be summed
hist(ds$rechenzeit)


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

co <- co[!is.na(co[, 1]), ]

cods <- as.data.frame(co)
cods$id <- ds$CASE

colong <- melt(cods, id = "id")
colong$color <- rep(redblue, each = nrow(co))
colong <- merge(colong, rb, by.x = "color", by.y = "hex")

# scatterplot -------------------------------------------------------------

set.seed(123)
ggplot(colong, aes(x = scalepoint100, y = value)) + 
  # geom_point(aes(y = scalepoint100, col = color), size = 3) +
  scale_color_manual(values = unique(colong$color)) +
  guides(col = "none") +
  geom_jitter(width = .5, col = rgb(0,0,0,.2)) +
  # geom_smooth(col = "black") +
  # geom_violin(colong, aes(x = as.factor(scalepoint100, y = value)), draw_quantiles = .5, fill = rgb(0,0,0,0)) +
  theme_classic() +
  ylab("Rated color") + xlab("Presented color")
ggsave("colors_scatterplot.jpg", width = 800, height = 800, units = "px", scale = 2)



# Violin plot -------------------------------------------------------------

set.seed(123)
ggplot(colong, aes(x = variable, y = value, fill = color)) + 
  geom_violin(draw_quantiles = .5) +
  scale_fill_manual(values = unique(colong$color)) +
  # scale_color_manual(values = unique(colong$color)) +
  scale_x_discrete(name = "Stimulus", labels = rb$hex) +
  guides(col = "none", fill = "none") +
  # geom_jitter(width = 0.1, col = rgb(0,0,0,.2)) +
  theme_classic() +
  ylab("Rated color") + xlab("Presented color") +
  theme(axis.text.x = element_text(angle = 45, vjust = .5))
ggsave("colors_violinplot.jpg", width = 800, height = 800, units = "px", scale = 2)





# With confidence intervals -----------------------------------------------

cocol <- apply(cods[, 1:20], 2, FUN = "mean")
cocolsd <- apply(cods[, 1:20], 2, FUN = "sd")
cocol <- data.frame(cbind(cocol, cocolsd))
names(cocol) <- c("m", "sd")

cocol$n <- length(ds$CASE)
cocol$ucb <- cocol$m+qnorm(.975)*(cocol$sd/sqrt(cocol$n))
cocol$lcb <- cocol$m-qnorm(.975)*(cocol$sd/sqrt(cocol$n))
cocol$variable <- as.factor(11:30)
cocol$color <- rb$hex

ggplot(cocol, aes(x = variable, y = m, color = color)) + 
  geom_point() + 
  geom_errorbar(aes(ymax = ucb, ymin = lcb)) +
  scale_color_manual(values = unique(colong$color)) +
  scale_x_discrete(name = "Stimulus", labels = rb$hex) +
  guides(col = "none", fill = "none") +
  # geom_jitter(width = 0.1, col = rgb(0,0,0,.2)) +
  theme_classic() + 
  ylab("Rated color") + xlab("Presented color") +
  theme(axis.text.x = element_text(angle = 45, vjust = .5))
ggsave("colors_means.jpg", width = 800, height = 800, units = "px", scale = 2)







# CORRELATIONS ------------------------------------------------------------

cor(co[, 1:20])
psych::alpha(co[, 1:20])



# Standardized Values -----------------------------------------------------

coz <- cods
for (i in 1:nrow(coz)) {
  coz[i, 1:20] <- scale(unlist(as.vector(coz[i, 1:20])))
}
cozlong <- melt(coz, id = "id")
cozlong$color <- rep(redblue, each = nrow(co))
cozlong <- merge(cozlong, rb, by.x = "color", by.y = "hex")

ggplot(cozlong, aes(x = variable, y = value, fill = color)) + 
  geom_violin(draw_quantiles = .5) +
  scale_fill_manual(values = unique(colong$color)) +
  # scale_color_manual(values = unique(colong$color)) +
  scale_x_discrete(name = "Stimulus", labels = rb$hex) +
  guides(col = "none", fill = "none") +
  # geom_jitter(width = 0.1, col = rgb(0,0,0,.2)) +
  theme_classic() +
  ylab("Rated color (standardized)") + xlab("Presented color") +
  theme(axis.text.x = element_text(angle = 45, vjust = .5))
ggsave("colors_violinplot_standardized.jpg", width = 800, height = 800, units = "px", scale = 2)






# Cluster Analysis of variables -------------------------------------------

# SIMULATED DATA
n_ds <- length(unique(colong$id))
repetitions <- 1000
set.seed(04062024)
scree <- matrix(NA, nrow = repetitions, ncol = 19)
for (i in 1:repetitions) {
  
  cotsim <- rbind(  rnorm(n = n_ds, m = rb$scalepoint100[ 1], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 2], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 3], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 4], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 5], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 6], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 7], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 8], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[ 9], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[10], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[11], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[12], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[13], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[14], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[15], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[16], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[17], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[18], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[19], sd = 20)
                    , rnorm(n = n_ds, m = rb$scalepoint100[20], sd = 20)
  )
  
  dsim <- dist(cotsim, method = "euclidean") # distance matrix
  fitsim <- hclust(dsim, method = "ward.D")
  scree[i, ] <- fitsim$height
}
scree <- as.data.frame(scree)
scree$run <- 1:repetitions
screelong <- melt(scree, id = "run")
screelong$variable <- as.numeric(screelong$variable)



# ACTUAL DATA
cot <- t(co[, 1:20]) # transposed matrix to cluster variables

d <- dist(cot, method = "euclidean") # distance matrix
fit <- hclust(d, method = "ward.D")
fit$order <- sort(fit$order)
plot(fit, main = "Actual Data") # display dendogram
points(y = rep(1000, 20), x = 1:20, col = redblue, pch = 15, cex = 3)
groups <- cutree(fit, k=5)
# draw dendogram with red borders around the clusters
# rect.hclust(fit, k=3, border="red")


# PLOT SIMULATED AND ACTUAL DATA TOGETHER
dc <- data.frame("variable" = 1:19
                 , "value" = fit$height
                 , "run" = 0)

ggplot(screelong, aes(x = variable, y = value, group = as.factor(run))) + geom_line(col = rgb(0,0,0,.05)) +
  guides(col = "none") +
  geom_line(data = dc, color = "red", linewidth = 1) +
  theme_classic()

