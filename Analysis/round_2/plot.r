library(dplyr)
library(ggplot2)

files <- c(
  "prices_round_2_day_-1.csv",
  "prices_round_2_day_0.csv",
  "prices_round_2_day_1.csv"
)

df <- do.call(rbind, lapply(files, function(f) {
  read.csv(f, sep=";")
}))

# Create continuous time
df$global_time <- df$day * 1000000 + df$timestamp

df <- df %>% arrange(global_time)

ggplot(df, aes(x = global_time, y = mid_price)) +
  geom_line() +
  facet_wrap(~product, ncol = 1, scales = "free_y") +
  geom_vline(xintercept = unique(df$day) * 1000000,
             linetype = "dashed", alpha = 0.4) +
  labs(title = "Mid Price Across Days",
       x = "Time", y = "Mid Price") +
  theme_minimal()

