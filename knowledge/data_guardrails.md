# 数据口径与使用约束

本文档记录当前 MVP 数据的单位、来源、完整有货日定义和时间边界。所有需求估计均须遵守这些约束。

## Normalized Scale：归一化尺度

- FreshRetailNet 的 `sale_amount` 已经过归一化处理。
- `sale_amount` 不能解释成真实商品件数或销售金额。
- `estimated_daily_demand` 的单位为 `normalized demand units/day`。
- `current_inventory` 使用与需求一致的 normalized scale。
- `current_inventory` 不能解释成真实库存件数。

## Simulated Operational Parameters：模拟运营参数

- `lead_time_days` 和 `current_inventory` 是本项目构造的模拟运营参数。
- 它们不是 FreshRetailNet 的原始字段。
- `lead_time_days` 的单位为真实的“天”。
- `current_inventory` 表示 `simulated normalized inventory`。

## Complete In-Stock Day：完整有货日

完整有货日定义为：

```text
stock_hour6_22_cnt = 0
```

只有完整有货日的 `sale_amount` 才参与 `estimated_daily_demand` 的 median 计算。

## as_of_date Boundary：决策时间边界

任何需求估计只能使用：

```text
date < as_of_date
```

不得使用 `as_of_date` 当天或未来数据。

## Exact Time Windows：精确窗口范围

### 14-day window

```text
as_of_date - 14 days <= date < as_of_date
```

### 30-day window

```text
as_of_date - 30 days <= date < as_of_date
```

### 窗口示例

当：

```text
as_of_date = 2024-06-25
```

14-day window 为：

```text
2024-06-11 ～ 2024-06-24
```

该窗口严格不包含 `2024-06-25`。

## No Look-Ahead：禁止使用未来信息

- `as_of_date` 之后的数据只能用于后续 Evaluation 或 Backtest。
- 决策阶段不得读取未来数据。
- 该约束用于防止 data leakage 和 look-ahead bias。

## Dynamic Demand：动态需求估计

`estimated_daily_demand` 不是 SKU 的静态属性。

它必须根据以下组合动态重新计算：

```text
sku_id + as_of_date
```

不同的 `as_of_date` 可以得到不同的需求估计、需求置信度和窗口类型。
