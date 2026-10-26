# round_2_analysis.R
# Analyze Round 2 market data (prices + trades)
# Works with files in: Analysis/round_2/

suppressPackageStartupMessages({
  library(tidyverse)
  library(broom)
})

# ---------------------------
# 1) Paths + file discovery
# ---------------------------
base_dir <- "Analysis/round_2"
out_dir  <- file.path(base_dir, "analysis_outputs")
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

price_files <- list.files(base_dir, pattern = "^prices_round_2_day_.*\\.csv$", full.names = TRUE)
trade_files <- list.files(base_dir, pattern = "^trades_round_2_day_.*\\.csv$", full.names = TRUE)

if (length(price_files) == 0) stop("No Round 2 price files found in Analysis/round_2")
message("Found ", length(price_files), " price files")
message("Found ", length(trade_files), " trade files")

# ---------------------------
# 2) Load helpers
# ---------------------------
safe_read <- function(path) {
  # Most IMC exports are semicolon separated
  suppressWarnings(readr::read_delim(path, delim = ";", show_col_types = FALSE))
}

extract_day <- function(filename) {
  # from "...day_-1.csv" etc.
  as.numeric(stringr::str_match(basename(filename), "day_(-?\\d+)")[,2])
}

# ---------------------------
# 3) Load + clean prices
# ---------------------------
prices <- purrr::map_dfr(price_files, function(f) {
  df <- safe_read(f)
  df$source_file <- basename(f)
  df$day_file <- extract_day(f)
  df
})

numeric_candidates <- c(
  "day", "timestamp",
  "bid_price_1","bid_volume_1","bid_price_2","bid_volume_2","bid_price_3","bid_volume_3",
  "ask_price_1","ask_volume_1","ask_price_2","ask_volume_2","ask_price_3","ask_volume_3",
  "mid_price","profit_and_loss"
)

for (col in intersect(names(prices), numeric_candidates)) {
  prices[[col]] <- suppressWarnings(as.numeric(prices[[col]]))
}

# Normalize product column name
if (!"product" %in% names(prices) && "symbol" %in% names(prices)) {
  prices$product <- prices$symbol
}

prices <- prices %>%
  arrange(product, day, timestamp)

# ---------------------------
# 4) Feature engineering
# ---------------------------
prices_feat <- prices %>%
  mutate(
    spread_1 = ask_price_1 - bid_price_1,
    top_bid_vol = coalesce(bid_volume_1, 0) + coalesce(bid_volume_2, 0) + coalesce(bid_volume_3, 0),
    top_ask_vol = coalesce(ask_volume_1, 0) + coalesce(ask_volume_2, 0) + coalesce(ask_volume_3, 0),
    depth_top = top_bid_vol + top_ask_vol,
    obi_top = if_else(depth_top > 0, (top_bid_vol - top_ask_vol) / depth_top, 0),
    microprice = if_else(
      coalesce(bid_volume_1,0) + coalesce(ask_volume_1,0) > 0,
      (ask_price_1 * coalesce(bid_volume_1,0) + bid_price_1 * coalesce(ask_volume_1,0)) /
        (coalesce(bid_volume_1,0) + coalesce(ask_volume_1,0)),
      mid_price
    )
  ) %>%
  group_by(product, day) %>%
  arrange(timestamp, .by_group = TRUE) %>%
  mutate(
    mid_return = (mid_price / lag(mid_price) - 1),
    next_mid_return = lead(mid_return),
    mid_diff = mid_price - lag(mid_price),
    rolling_vol_20 = zoo::rollapply(mid_return, width = 20, FUN = sd, fill = NA, align = "right")
  ) %>%
  ungroup()

# ---------------------------
# 5) Load + aggregate trades (if available)
# ---------------------------
if (length(trade_files) > 0) {
  trades <- purrr::map_dfr(trade_files, function(f) {
    df <- safe_read(f)
    df$source_file <- basename(f)
    df$day_file <- extract_day(f)
    df
  })

  for (col in intersect(names(trades), c("timestamp","price","quantity"))) {
    trades[[col]] <- suppressWarnings(as.numeric(trades[[col]]))
  }

  if (!"product" %in% names(trades) && "symbol" %in% names(trades)) {
    trades$product <- trades$symbol
  }

  # Join nearest mid_price for trade direction proxy
  px_for_join <- prices_feat %>%
    select(product, timestamp, day, mid_price) %>%
    distinct()

  trades_joined <- trades %>%
    filter(!is.na(product), !is.na(timestamp), !is.na(price), !is.na(quantity)) %>%
    left_join(px_for_join, by = c("product", "timestamp")) %>%
    mutate(
      direction = sign(price - mid_price),
      signed_qty = direction * quantity
    )

  trade_agg <- trades_joined %>%
    group_by(product, timestamp) %>%
    summarise(
      trade_count = n(),
      trade_qty = sum(quantity, na.rm = TRUE),
      signed_trade_qty = sum(signed_qty, na.rm = TRUE),
      .groups = "drop"
    )

  prices_feat <- prices_feat %>%
    left_join(trade_agg, by = c("product", "timestamp")) %>%
    mutate(
      trade_count = replace_na(trade_count, 0),
      trade_qty = replace_na(trade_qty, 0),
      signed_trade_qty = replace_na(signed_trade_qty, 0)
    )
} else {
  prices_feat <- prices_feat %>%
    mutate(trade_count = 0, trade_qty = 0, signed_trade_qty = 0)
}

# ---------------------------
# 6) Summary tables
# ---------------------------
summary_by_product_day <- prices_feat %>%
  group_by(product, day) %>%
  summarise(
    n_obs = n(),
    mid_mean = mean(mid_price, na.rm = TRUE),
    mid_sd = sd(mid_price, na.rm = TRUE),
    spread_mean = mean(spread_1, na.rm = TRUE),
    spread_p95 = quantile(spread_1, 0.95, na.rm = TRUE),
    obi_mean = mean(obi_top, na.rm = TRUE),
    abs_ret_mean = mean(abs(mid_return), na.rm = TRUE),
    vol20_mean = mean(rolling_vol_20, na.rm = TRUE),
    pnl_last = dplyr::last(profit_and_loss[!is.na(profit_and_loss)]),
    .groups = "drop"
  )

readr::write_csv(summary_by_product_day, file.path(out_dir, "round2_summary_by_product_day.csv"))

# ---------------------------
# 7) Simple signal regression
# next_mid_return ~ obi_top + spread_1 + mid_diff + signed_trade_qty
# ---------------------------
reg_data <- prices_feat %>%
  select(product, day, next_mid_return, obi_top, spread_1, mid_diff, signed_trade_qty) %>%
  drop_na()

reg_results <- reg_data %>%
  group_by(product) %>%
  group_modify(~{
    m <- lm(next_mid_return ~ obi_top + spread_1 + mid_diff + signed_trade_qty, data = .x)
    tidy_m <- broom::tidy(m)
    glance_m <- broom::glance(m)
    tidy_m %>% mutate(r.squared = glance_m$r.squared, n = nrow(.x))
  }) %>%
  ungroup()

readr::write_csv(reg_results, file.path(out_dir, "round2_microstructure_regression.csv"))

# ---------------------------
# 8) Plots
# ---------------------------
# Mid price over time by day
p_mid <- ggplot(prices_feat, aes(x = timestamp, y = mid_price, color = factor(day))) +
  geom_line(alpha = 0.9) +
  facet_wrap(~product, scales = "free_y") +
  labs(title = "Round 2 Mid Price by Product/Day", color = "day") +
  theme_minimal()

ggsave(file.path(out_dir, "round2_midprice.png"), p_mid, width = 12, height = 6, dpi = 150)

# Spread and OBI distributions
p_spread <- ggplot(prices_feat, aes(x = spread_1, fill = product)) +
  geom_histogram(bins = 60, alpha = 0.55, position = "identity") +
  facet_wrap(~product, scales = "free_y") +
  theme_minimal() +
  labs(title = "Spread Distribution (Level 1)")

ggsave(file.path(out_dir, "round2_spread_hist.png"), p_spread, width = 12, height = 6, dpi = 150)

p_obi_ret <- ggplot(prices_feat, aes(x = obi_top, y = next_mid_return, color = product)) +
  geom_point(alpha = 0.15, size = 0.7) +
  geom_smooth(method = "lm", se = FALSE) +
  facet_wrap(~product, scales = "free") +
  theme_minimal() +
  labs(title = "OBI vs Next Mid Return")

ggsave(file.path(out_dir, "round2_obi_vs_next_return.png"), p_obi_ret, width = 12, height = 6, dpi = 150)

# ---------------------------
# 9) Save enriched dataset
# ---------------------------
readr::write_csv(prices_feat, file.path(out_dir, "round2_enriched_prices.csv"))

message("Analysis complete. Outputs written to: ", out_dir)

