#Plotting Scripts
#Script for Boxplots (Fig 1 and 2) is all the way at the end of this script
#Script for Correlation Matrix (Fig 3) is half way through this script
#The rest of this script are explorations that didnt make the final paper

###########################################################################


LinkedData_21_5sec <- readRDS("linkedData.rds") #read datafile with Medlo and wearable data
MedloData <- readRDS("MedloData.rds")
Normalized_24hrs_Data <- readRDS("NormalizedAccelerometerData.rds")
library(ggplot2)



#############################
#instead of barcharts of the summed data, make boxplots of the percentage of time
#a resident spend in one movement category

#Medlo_2019$codebew

percentageActiveMedlo21<- MedloData [1:13 ,2:8] * 100/30 #
percentageActiveMedlo21[is.na(percentageActiveMedlo21)] <- 0 #clear NAs

percentageActiveSamsungCat<- t(Normalized_24hrs_Data) *100/30
percentageActiveSamsungCat[is.na(percentageActiveSamsungCat)] <- 0 #clear NAs

percentageActiveMedloLong21<- data.frame(
  percentage=unlist(c(percentageActiveMedlo21)),
  activity=c(rep("ML01", 13), rep("ML02", 13),
             rep("ML03", 13),
             rep("ML04", 13), rep("ML05", 13),
             rep("ML06", 13), rep("ML07", 13))
)

percentageActiveSamsungLong<- data.frame(
  percentage=unlist(c(percentageActiveSamsungCat)),
  activity=c(rep("Cycling", 16), rep("Inactive", 16), 
             rep("Light", 16), 
             rep("NotOnWrist", 16), rep("Sleeping", 16) )
)

# Opening the graphical device
pdf("BoxplotAllCatsMedloPercent.pdf")
#png("BoxplotAllCatsMedloPercent.png")

boxplot(percentageActiveMedloLong21$percentage ~ percentageActiveMedloLong21$activity,
        col='steelblue',
        main='Percentage of Time spent per activity',
        xlab='Activity',
        ylab='Percentage of Time') 

# Closing the graphical device
dev.off() 


# Opening the graphical device
pdf("BoxplotAllCatsSamsungPercent.pdf")
#png("BoxplotAllCatsSamsungPercent.png")
boxplot(percentageActiveSamsungLong$percentage ~ percentageActiveSamsungLong$activity,
        col='steelblue',
        main='Percentage of Time spent per activity',
        xlab='Activity',
        ylab='Percentage of Time') 

# Closing the graphical device
dev.off() 



###############################

library(corrplot)

# Opening the graphical device
#pdf("CorrelationMatrix_30min.pdf") #this is based on 30 min epochs, which we didnt use in the end
#corrplot.mixed(cor(LinkedData_21_30min),
#               lower = "number", 
#               upper = "circle",
#               tl.col = "black",
#               title = "30minEpochs",
#               mar=c(0,0,2,0))
# Closing the graphical device
#dev.off() 

#This is Figure 3
# Opening the graphical device
#pdf("CorrelationMatrix_5sec_hc.pdf",10,10)
tiff("CorrelationMatrix_5sec_hc.tif",units="in",7,7,res=300)
#png("CorrelationMatrix_5sec_hc.png") #no margins on png
corrplot(cor(LinkedData_21_5sec),
               method = 'square',
              type= 'lower',
               #lower = "number", 
               #upper = "circle",
         addCoef.col = 'black',
               tl.col = "black",
         cl.pos = 'n',
               title = "",
               mar=c(0,0,2,0),
               order = "hclust", 
              hclust.method = "complete",
               addrect = 2)
               
# Closing the graphical device
dev.off() 

#############################################

#The rest of the plots didnt make it to the paper. 

#############################################
# 
# # Opening the graphical device
# pdf("CorrelationMatrix_60sec.pdf")
# corrplot.mixed(cor(LinkedData_21_60sec),
#                lower = "number", 
#                upper = "circle",
#                tl.col = "black",
#                title = "60secEpochs",
#                mar=c(0,0,2,0))
# 
# # Closing the graphical device
# dev.off() 
# 
# ###########################
# 
# #Plot MAD data against time "Light Active"
# plot(LinkedData_21_60sec$MeanMAD, LinkedData_21_60sec$Light)
# plot(LinkedData_21_60sec$MeanMAD, LinkedData_21_60sec$Inactive)
# plot(LinkedData_21_60sec$Light, LinkedData_21_60sec$Inactive)
# 
# plot(LinkedData_21_60sec$MeanMAD, LinkedData_21_60sec$MLO2) #ceiling effect, 3 people with full 30 min on ML02
# plot(LinkedData_21_60sec$MeanMAD, LinkedData_21_60sec$MLO3) #floor effect, almost all people with full 0 ML 03
# plot(LinkedData_21_60sec$Inactive, LinkedData_21_60sec$MLO2)
# 
# pairs(LinkedData_21_60sec[,c(1,4,5,6,7)], pch = 19) #meanMAD/24hrs
# pairs(LinkedData_21_60sec[,c(1,8,9,10,11,12,13)], pch = 19) #meanMAD/Medlo
# pairs(LinkedData_21_60sec[,c(4,5,6,7,8,9,10,11,12,13)], pch = 19)
# 
# ###########################
# 
# MAD_AllEpochs5sec<-readRDS("epochsPerResident5sec.rds")
# allData<-numeric(length=3)
# allMeans<-numeric()
# 
# for (i in 1:length(MAD_AllEpochs5sec)){
# 
# dat<-data.frame(MAD=MAD_AllEpochs5sec[[i]][,1],
#                  measurement= seq (1:  length( MAD_AllEpochs5sec[[i]][,1])),
#                  resident=rep(i, length(MAD_AllEpochs5sec[[i]][,1])))
# 
# allData<-rbind(allData,dat)
# allMeans<-c(allMeans, mean(dat$MAD,na.rm=TRUE))
# }
# 
# allData<- allData [-1,] #remove empty first line
# var(allMeans)
# min(allMeans)
# max(allMeans)
# #########
# 
# 
# 
# 
# library(ggplot2)
# ###! This takes a long time to render!
# p<- ggplot(allData, aes(x=measurement, y=MAD)) +
#     geom_point()+
#     facet_wrap(~allData$resident, nrow=3)
# p
# ggsave(filename="PerResidentMAD.png")
# 
# #####This is more doable,saves plots individually
# for (j in 1:length(unique(allData$resident))) {
#   filename <- paste0("PerResidentMADResidentID",j,".png")
#   sampleResident <- allData[which(allData$resident == j),]
#   q<-ggplot(sampleResident, aes(x=measurement, y =MAD)) + geom_point()
#   q
#   ggsave(filename)
# }
# 
# lowvarianceResIDs<- c(6,2,15)
# highvarianceResIDs<- c(8,14,13)
# 
# p<- ggplot(allData [which(allData$resident %in%lowvarianceResIDs),], 
#            aes(x=measurement, y=MAD)) +
#   geom_point()+
#   ylim(0,420)+
#   facet_wrap(~allData [which(allData$resident %in%lowvarianceResIDs),]$resident, 
#              nrow=1)
# p
# ggsave("MADSpreadLowVariance0to420.pdf")
# 
# q<- ggplot(allData [which(allData$resident %in%highvarianceResIDs),], 
#            aes(x=measurement, y=MAD)) +
#   geom_point()+
#   ylim(0,420)+
#   facet_wrap(~allData [which(allData$resident %in%highvarianceResIDs),]$resident, 
#              nrow=1)
# q
# ggsave("MADSpreadHighVariance0to420.pdf")
# 
# #### violin plots of MAD data per resident
# p <- ggplot(allData [which(allData$resident %in%lowvarianceResIDs),], 
#             aes(x=as.factor(allData [which(allData$resident %in%lowvarianceResIDs),]$resident), 
#                 y=MAD)) + 
#   geom_violin()
# p
# 
# 
# 
# #####################################################3
# ##############################
# #Barcharts - MEDLO and 24hrs data
# 
# datMedlo <- data.frame(
#   
#   MovementCategoryMedlo = factor(c("1","2", "3", "4", "5", "6", "7"), 
#                                  levels    = c("1","2", "3", "4", "5", "6", "7"),
#                                  labels = c("Lying/No Movement","Sitting quietly", "Light to moderate sitting", 
#                                             "Standing", "Standing activity/walking around", "Walking Activity/Cycling", 
#                                             "Sports/Whole Body Movement")),
#   
#   TimeSumsMedlo = c(colSums(LinkedData_21_5sec [,8:13], na.rm = TRUE),0)
# )
# 
# p <- ggplot(data=datMedlo, aes(x=MovementCategoryMedlo, y=TimeSumsMedlo, fill=MovementCategoryMedlo)) +
#   
#   geom_bar(stat="identity")
# 
# p + scale_x_discrete(labels=c("Lying/No Movement" = "Lying", 
#                               "Sitting quietly" = "Sitting Quiet",
#                               "Light to moderate sitting" = "Sitting Moderate",
#                               "Standing" = "Standing",
#                               "Standing activity/walking around" = "Walking",
#                               "Walking Activity/Cycling" = "Active Walk",
#                               "Sports/Whole Body Movement" = "Sports")) +
#   theme_bw() +
#   theme(axis.text.x = element_text(size=14, angle=80)) +
#   theme(legend.position="none")

# ##########
# 
# dat24hrs <- data.frame(
#   MovementCategory = factor(c("1","2", "3","4"), 
#                             levels=c("1","2","3", "4"),
#                             labels = c( "Inactive","Light", "Not on wrist", "Sleeping") ),
#   
#   TimeSums = colSums(LinkedData_21_30min [,4:7], na.rm = TRUE)
# )
# q <- ggplot(data=dat24hrs, aes(x=MovementCategory, y=TimeSums, fill=MovementCategory)) +
#   
#   geom_bar(stat="identity")
# 
# q + scale_x_discrete(labels=c( "Inactive","Light", "Not on wrist", "Sleeping")) +
#   theme_bw() +
#   theme(axis.text.x = element_text(size=14, angle=80)) +
#   theme(legend.position="none")



