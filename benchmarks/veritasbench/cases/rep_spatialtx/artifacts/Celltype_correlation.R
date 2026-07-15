################################################################################
# Cell type ranking based on correlation between the gene expression profiles
# of the cell types present in the single cell reference data
# 
# comments:
# Seurat donot calculate the corrected counts for integrated assays
# https://github.com/satijalab/seurat/issues/5686
# heatmap ref: http://www.sthda.com/english/wiki/ggplot2-quick-correlation-matrix-heatmap-r-software-and-data-visualization
#
# Implemented by Utkarsh Mahamune
# Bioinformatics Laboratory | Amsterdam UMC (Location AMC)
################################################################################


#### Initialize the environment ####
source("Init_env.R")

# reading the integrated scRNA-seq reference data
sc.combined <- readRDS(paste0("../../1_Generate_sc_ref_data/Results/",
                              "sc.combined.nor.rds"))
Idents(sc.combined) <- "blue.main"

sc.combined2 <- sc.combined[, !is.na(sc.combined@meta.data[, "blue.main"])]

# choosing idents with cells equal or more than Neutrophils
nr_cells_cutoff <- unname(sort(table(sc.combined2$blue.main))["Neutrophils"])

idents.use <- data.frame(sort(table(sc.combined2$blue.main))) %>%
  filter(Freq >= nr_cells_cutoff) %>%
  dplyr::select(Var1)

Idents(sc.combined2) <- "blue.main"
sc.combined3 <- subset(sc.combined2, idents = idents.use$Var1)
# sort(table(sc.combined3$blue.main))

cell.lists <- WhichCells(sc.combined3, downsample = 300, seed = 15)
# length(cell.lists)
sc.combined4 <- sc.combined3[, cell.lists]
# sort(table(sc.combined4$blue.main))

celltypes <- sort(unique(sc.combined4$blue.main))

# 1: RNA assay, 2: integrated assay
gene.exp.list <- list()
for (g in 1:2) {
  if (g == 1) {
    assay_ <- "RNA"
    num.features <- dim(sc.combined4@assays$RNA)[1]
    gene.exp <- matrix(nrow = num.features, ncol = length(celltypes)) %>% data.frame()
    colnames(gene.exp) <- celltypes
    rownames(gene.exp) <- rownames(sc.combined4@assays$RNA)
    
  } else {
    assay_ <- "integrated"
    num.features <- dim(sc.combined4@assays$integrated)[1]
    gene.exp <- matrix(nrow = num.features, ncol = length(celltypes)) %>% data.frame()
    colnames(gene.exp) <- celltypes
    rownames(gene.exp) <- rownames(sc.combined4@assays$integrated)
  }
  
  for (i in 1:length(celltypes)) {
    cellnames <- rownames(sc.combined4@meta.data[which(sc.combined4@meta.data$blue.main == celltypes[i]), ])
    gene.exp.celltype <- matrix(nrow = num.features, ncol = length(cellnames)) %>% data.frame()
    # dim(gene.exp.celltype)
    
    for (j in 1:length(cellnames)) {
      # collect the assay data from data slot from the assay for each sample
      gene.exp.celltype[, j] <-
        as.vector(GetAssayData(
          object = sc.combined4,
          assay = assay_,
          slot = "data"
        )[, cellnames][, j])
    }
    gene.exp[, i] <- rowMeans(as.matrix(gene.exp.celltype))
  }
  gene.exp.list[[g]] <- gene.exp
}

corr.plots <- lapply(1:2, function(pll) {
  if (pll == 1) {
    plot_title <- "with RNA assay"
  } else {
    plot_title <- "with integrated assay"
  }
  
  heatmap.corr <- cor((as.matrix(gene.exp.list[[pll]])), method = "pearson")
  head(heatmap.corr)
  write.csv(heatmap.corr, file = paste0(Results, "Correlation_matrix_", pll, ".csv"))
  
  heatmap.corr.mat <- reshape2::melt((heatmap.corr), na.rm = T)
  head(heatmap.corr.mat, 10)
  
  # limiting number of decimals
  heatmap.corr.mat <- heatmap.corr.mat %>%
    mutate(across(where(is.numeric), ~ round(., 2)))
  head(heatmap.corr.mat)
  
  # Create a diagonal mask
  heatmap.corr.mat$diagonal <- ifelse(heatmap.corr.mat$Var1 == heatmap.corr.mat$Var2, "diagonal", "non-diagonal")
  
  ggplot(heatmap.corr.mat, aes(x = Var2, y = forcats::fct_rev(Var1), fill = value)) +
    geom_tile(color = "white") +
    geom_text(aes(label = value), color = "black", size = 2) +
    geom_tile(data = subset(heatmap.corr.mat, diagonal == "diagonal"), fill = "gray40", color = "white") +
    scale_fill_gradient(low = "white", high = "deepskyblue4") +
    theme(
      legend.title = element_text(size = 6, color = "dodgerblue4"),
      legend.text = element_text(size = 5),
      legend.key.size = unit(0.5, "cm"),
      legend.box.margin = margin(2, 2, 2, 2),
      plot.title = element_text(size = 8, hjust = 0, color = "dodgerblue4"),
      panel.background = element_rect(fill = "white"),
      axis.text.x = element_text(size = 6.5, color = "black", angle = 45, hjust = 1, vjust = 1),
      axis.text.y = element_text(size = 6.5, color = "black"),
      axis.title.x = element_blank(),
      axis.title.y = element_blank(),
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(colour = "grey100", linewidth = 0.1)
    ) +
    labs(fill = " Correlation") + 
    guides(color = guide_legend(override.aes = list(size = 5))) +
    scale_x_discrete(labels = c("Adipocytes" = "Adipocytes",
                                "B-cells" = "B",
                                "CD4+ T-cells" = "CD4 T",
                                "CD8+ T-cells" = "CD8 T",
                                "Endothelial cells" = "Endothelial",
                                "Fibroblasts" = "Fibroblasts",
                                "HSC" = "HSC",
                                "Macrophages" = "Macrophages",
                                "Monocytes" = "Monocytes",
                                "Myocytes" = "Myocytes",
                                "Neutrophils" = "Neutrophils",
                                "NK cells" = "NK",
                                "Skeletal muscle" = "Skeletal muscle")) +
    scale_y_discrete(labels = c("Adipocytes" = "Adipocytes",
                                "B-cells" = "B",
                                "CD4+ T-cells" = "CD4 T",
                                "CD8+ T-cells" = "CD8 T",
                                "Endothelial cells" = "Endothelial",
                                "Fibroblasts" = "Fibroblasts",
                                "HSC" = "HSC",
                                "Macrophages" = "Macrophages",
                                "Monocytes" = "Monocytes",
                                "Myocytes" = "Myocytes",
                                "Neutrophils" = "Neutrophils",
                                "NK cells" = "NK",
                                "Skeletal muscle" = "Skeletal muscle"))
  
})


png(file = paste0(Results, "Fig_Celltype_corr_integrated_assay.png"),
    res = 450, width = 4.8, height = 3.6, units = "in")
plot_grid(corr.plots[[2]], nrow = 1, label_size = 12)
dev.off()

png(file = paste0(Results, "Fig_Celltype_corr_rna_assay.png"),
    res = 450, width = 4.8, height = 3.6, units = "in")
plot_grid(corr.plots[[1]], nrow = 1, label_size = 12)
dev.off()

