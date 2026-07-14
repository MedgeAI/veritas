.libPaths("/rlib")
suppressMessages({ library(readxl); library(dplyr); library(stringr); library(tidyr) })

OUT <- "/out"
df <- read_excel("/work/fulldata.xlsx")

## ---- discipline_figures.qmd reproduction ----
relevant_data <- df %>%
  filter(!is.na(item_id)) %>%
  mutate(publication_year = str_extract(author_year, "\\d+")) %>%
  select(article_id = item_id,
         frasc_top = `discipline_frascati_top-level`,
         frasc_2nd = `discipline_frascati_2nd-level`,
         publication_year)
n_studies <- nrow(relevant_data)
stopifnot(identical(n_studies, 104L))

relevant_fixed <- relevant_data %>%
  mutate(frasc_2nd = str_replace_all(frasc_2nd, "Sciences", "sciences") %>%
           str_replace_all(",", ";"))
frasc_top_long <- relevant_fixed %>%
  mutate(frasc_top_split = str_split(frasc_top, ";\\s")) %>%
  unnest(frasc_top_split)
disc <- frasc_top_long %>% count(frasc_top_split, name = "n_assignments") %>%
  arrange(desc(n_assignments)) %>% rename(frasc_top_level = frasc_top_split)
write.csv(disc, file.path(OUT, "discipline_counts.csv"), row.names = FALSE)

## ---- scope.qmd reproduction ----
fulldata <- df
fulldata[] <- lapply(fulldata, function(x) gsub("\n|\r", "", x))
fulldata[] <- lapply(fulldata, tolower)

mk <- function(var, x) {
  t <- as.data.frame(table(x), stringsAsFactors = FALSE)
  names(t) <- c("level", "n")
  t <- t[order(-t$n), ]
  rbind(data.frame(variable = var, level = t$level, n = t$n),
        data.frame(variable = var, level = "_n_levels", n = nrow(t)))
}
rows <- rbind(
  data.frame(variable = "n_included_studies", level = "total", n = n_studies),
  mk("intervention_class", fulldata$intervention_class),
  mk("outcomes_class",     fulldata$outcomes_class),
  data.frame(variable = "author_stated_effect",
             level = c("generally positive","null/neutral","generally negative"),
             n = as.integer(c(sum(fulldata$author_stated_effect=="generally positive", na.rm=TRUE),
                              sum(fulldata$author_stated_effect=="null/neutral", na.rm=TRUE),
                              sum(fulldata$author_stated_effect=="generally negative", na.rm=TRUE)))),
  data.frame(variable = "direct",
             level = c("direct outcomes","proxy outcomes"),
             n = as.integer(c(sum(df$direct==1, na.rm=TRUE), sum(df$direct==0, na.rm=TRUE))))
)
write.csv(rows, file.path(OUT, "scope_summary.csv"), row.names = FALSE)

cat("=== discipline_counts.csv ===\n"); print(disc)
cat("=== scope_summary.csv ===\n"); print(rows)
