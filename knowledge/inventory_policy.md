# 库存需求与补货决策规则

本文档记录当前 MVP 已冻结的需求估计、库存覆盖、风险分级与补货优先级规则。本文档用于解释 API 返回结果，不用于替代 API 进行计算。

## Demand Confidence：需求估计与置信度

`demand_confidence` 表示当前需求估计所依据的完整有货历史数据是否充分，不代表统计学置信区间，也不表示预测准确率或概率。

### 完整有货日口径

完整有货日的定义及数据使用限制见 `data_guardrails.md`。

需求估计仅使用所选时间窗口内完整有货日的 `sale_amount`，并取其中位数（median）。

### 最近 14 天规则

- 完整有货日不少于 10 天：
  - `estimated_daily_demand` = 最近 14 天完整有货日 `sale_amount` 的 median
  - `demand_confidence` = `High`
  - `demand_window_days` = `14`
- 完整有货日为 7–9 天：
  - `estimated_daily_demand` = 最近 14 天完整有货日 `sale_amount` 的 median
  - `demand_confidence` = `Medium`
  - `demand_window_days` = `14`
- 完整有货日少于 7 天：
  - 不使用 14 天窗口生成最终需求估计
  - 扩展检查最近 30 天

### 最近 30 天扩展窗口规则

- 完整有货日不少于 7 天：
  - `estimated_daily_demand` = 最近 30 天完整有货日 `sale_amount` 的 median
  - `demand_confidence` = `Low`
  - `demand_window_days` = `30`
  - 窗口类型标记为 `Extended window`
- 完整有货日少于 7 天：
  - `estimated_daily_demand` = `NULL`
  - `demand_confidence` = `Insufficient Data`
  - `demand_window_days` = `30`
  - `manual_review_required` = `True`

## Decision Formulas：决策公式

以下公式仅在 `estimated_daily_demand` 为有效正数时计算。

### Days of Supply

```text
days_of_supply = current_inventory / estimated_daily_demand
```

### Coverage Gap

```text
coverage_gap = max(lead_time_days - days_of_supply, 0)
```

### Coverage Ratio

```text
coverage_ratio = days_of_supply / lead_time_days
```

### 指标单位

- `days_of_supply`：单位为天。
- `coverage_gap`：单位为天。
- `coverage_ratio`：无量纲比例。

## Risk Rules：风险分级规则

`stockout_risk` 是基于库存覆盖程度的风险等级，不是统计模型预测的缺货概率。

| Coverage Ratio | Stockout Risk | Replenishment Priority |
|---|---|---|
| `coverage_ratio >= 1.0` | `Low` | `P3` |
| `0.5 <= coverage_ratio < 1.0` | `Medium` | `P2` |
| `coverage_ratio < 0.5` | `High` | `P1` |

## Replenishment Priority：补货优先级

- `P1`：对应 `High Risk`，为当前规则下最高补货优先级。
- `P2`：对应 `Medium Risk`，为中等补货优先级。
- `P3`：对应 `Low Risk`，为较低补货优先级。

当前 MVP 仅定义优先级顺序，不进一步规定“立即补货”“多少小时内处理”等具体运营动作。

## Manual Review：人工复核

如果 `estimated_daily_demand` 为 `NULL` 或小于等于 0：

- 不计算 `days_of_supply`、`coverage_gap` 和 `coverage_ratio`；
- `stockout_risk` 不生成自动风险等级；
- 不生成 `P1`、`P2` 或 `P3` 自动优先级；
- `replenishment_priority` = `Manual Review`；
- 需要人工复核。

## Rule Scope：规则适用范围

本项目中的 Demand Confidence、窗口扩展阈值、Risk 分级阈值和 Priority 映射均属于 MVP 阶段的 configurable business rules。

这些规则用于构造一致、透明、可复现的决策流程，不代表零售行业统一标准。

- `coverage_ratio = 1.0` 表示当前库存覆盖天数等于补货提前期，具有直接业务含义。
- `coverage_ratio = 0.5` 作为 `Medium Risk` 与 `High Risk` 的分界，是本项目设定的 heuristic。
- 14 天样本不足时扩展至 30 天，是为了在近期性与可用完整有货样本之间取得平衡。
- 7 天、10 天等样本阈值同样属于本项目 MVP 规则。
- 在真实企业环境中，这些阈值应通过历史回测、业务 SLA 或运营团队共同校准。

## API Source of Truth：唯一事实来源

API 返回结果是数值、需求置信度、风险等级、补货优先级和人工复核标记的唯一事实来源。

知识库内容仅用于解释这些结果和规则，不得重新计算、覆盖或修改 API 返回结果。

如果 API 返回结果与检索到的知识库规则存在明显冲突，LLM 不得自行重新计算或修改 API 结果。面向用户的当前决策结果仍以 API 为准，同时该冲突应被视为知识库或系统版本需要检查的信号。
