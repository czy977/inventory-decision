# Store selection: 837

Store 837 contains 64 SKUs, all with 90 daily records. Under the adaptive quality screen, 55 SKUs have at least 50% active-sales days and total normalized sales at or above the full-data 20th-percentile floor.

The store spans stockout-day ratios from 5.6% to 96.7%, with a median of 41.1%. It contains 17 low-stockout, 16 middle-stockout, and 9 high-stockout eligible SKUs under the full-data quantile bands recorded in `raw_data_profile.json`.

This combination gives a complete 90-day panel, sufficient sales activity, and strong within-store contrast. The released training data has no zero-stockout series: the global minimum is 5/90 days (5.6%), so SKU A represents the observed minimum rather than an artificial zero-stockout example.

## Selected SKU ladder

| sku_label | store_id | product_id | record_days | active_sales_days | active_sales_day_ratio | total_sales | avg_daily_sales | stockout_days | total_stockout_hours | avg_stockout_hours | stockout_day_ratio | stockout_profile | selection_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 837 | 851 | 90 | 86 | 0.955556 | 144.500000 | 1.605556 | 5 | 57 | 0.633333 | 0.055556 | 基本不缺货（全数据最低档） | 5/90 天发生缺货，为全量数据可见的最低缺货天比例之一；86 天有销量且销量充足。 |
| B | 837 | 167 | 90 | 89 | 0.988889 | 92.000000 | 1.022222 | 15 | 122 | 1.355556 | 0.166667 | 轻微缺货 | 15/90 天发生缺货，处于全量分布低端；89 天有销量，避免把低销量误当作低风险。 |
| C | 837 | 316 | 90 | 81 | 0.900000 | 118.670000 | 1.318556 | 28 | 325 | 3.611111 | 0.311111 | 偶尔/较低程度缺货 | 28/90 天发生缺货、累计 325 小时；81 天有销量，形成清晰的中低风险样本。 |
| D | 837 | 834 | 90 | 71 | 0.788889 | 138.400000 | 1.537778 | 40 | 512 | 5.688889 | 0.444444 | 中等程度缺货 | 40/90 天发生缺货、累计 512 小时；总销量较高，适合观察缺货对已实现销量的截断。 |
| E | 837 | 44 | 90 | 51 | 0.566667 | 60.100000 | 0.667778 | 70 | 937 | 10.411111 | 0.777778 | 缺货明显 | 70/90 天发生缺货、累计 937 小时；仍有 51 天产生销量，不是长期近零销量商品。 |
