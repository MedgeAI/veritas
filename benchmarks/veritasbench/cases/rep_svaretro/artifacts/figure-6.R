library(frictionless)
library(tidyverse)
library(plotly)

data_package <- read_package("https://ftp.cngb.org/pub/gigadb/pub/10.5524/102001_103000/102318/datapackage.json")

df <- read_resource(data_package, "figure6")

figure6 <-
  df |>
  ggplot(aes(x = reorder(repClass, n), y = n)) +
  geom_bar(stat = "identity", fill="lightblue3") +
  coord_flip() +
  labs(y="count", x="repClass") +
  ylim(0, 300) +
  theme_minimal()

figure6 |>
  ggplotly(tooltip="n") |>
  config(
    toImageButtonOptions = list(
      format = "svg",
      filename = "figure-6",
      width = 400,
      height = 300
    )
  ) |>
  layout() |>
  htmlwidgets::saveWidget(
    "figure-6.html",
    title = 'Figure 6',
    selfcontained = TRUE
  )
