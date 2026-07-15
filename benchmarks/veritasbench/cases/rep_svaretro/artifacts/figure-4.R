library(frictionless)
library(tidyverse)
library(plotly)

data_package <- read_package("https://ftp.cngb.org/pub/gigadb/pub/10.5524/102001_103000/102318/datapackage.json")

df <- read_resource(data_package, "figure4")

figure4 <-
  df |>
  unite("set", group:caller, remove = FALSE) |>
  ggplot(aes(set, count, fill=reorder(category, count))) +
  geom_bar(stat="identity", width=0.5) +
  scale_fill_brewer(palette="Pastel1") +
  coord_flip() +
  labs(x="", y="", fill="category") +
  theme_minimal()

figure4 |>
  ggplotly(tooltip="count") |>
  config(
    toImageButtonOptions = list(
      format = "svg",
      filename = "figure-4",
      width = 400,
      height = 300
    )
  ) |>
  layout() |>
  htmlwidgets::saveWidget(
    "figure-4.html",
    title = 'Figure 4',
    selfcontained = TRUE
  )
