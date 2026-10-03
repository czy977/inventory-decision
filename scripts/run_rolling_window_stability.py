#!/usr/bin/env python3
"""Run no-lookahead 14-day versus 30-day rolling median stability checks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "freshretail_mvp.parquet"
REPORTS_DIR = ROOT / "reports"
DETAIL_PATH = REPORTS_DIR / "rolling_window_stability_detail.csv"
SUMMARY_CSV_PATH = REPORTS_DIR / "rolling_window_stability_summary.csv"
SUMMARY_MD_PATH = REPORTS_DIR / "rolling_window_stability.md"

EXPECTED_COLUMNS = {
    "store_id",
    "product_id",
    "dt",
    "sale_amount",
    "stock_hour6_22_cnt",
}
EXPECTED_PRODUCTS = {44, 167, 316, 834, 851}
WINDOW_14 = 14
WINDOW_30 = 30
MIN_FULL_STOCK_DAYS_14 = 7
MIN_FULL_STOCK_DAYS_30 = 15


def validate_input(frame: pd.DataFrame) -> None:
    """Fail loudly if the checked MVP input is not the expected 5 × 90 panel."""
    missing = EXPECTED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if len(frame) != 450:
        raise ValueError(f"Expected 450 rows, found {len(frame)}")
    if frame["store_id"].nunique() != 1:
        raise ValueError("Expected exactly one store")
    products = set(frame["product_id"].unique())
    if products != EXPECTED_PRODUCTS:
        raise ValueError(f"Unexpected product IDs: {sorted(products)}")
    if frame[list(EXPECTED_COLUMNS)].isna().any().any():
        raise ValueError("Core fields contain missing values")
    if frame.duplicated(["store_id", "product_id", "dt"]).any():
        raise ValueError("Duplicate store_id + product_id + dt keys found")

    for product_id, group in frame.groupby("product_id"):
        group = group.sort_values("dt")
        if len(group) != 90:
            raise ValueError(f"SKU {product_id} does not have 90 rows")
        expected_dates = pd.date_range(group["dt"].min(), periods=90, freq="D")
        if not group["dt"].reset_index(drop=True).equals(pd.Series(expected_dates)):
            raise ValueError(f"SKU {product_id} does not have a contiguous daily series")


def build_detail(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate Day 31–90 cutoffs using only observations before each cutoff."""
    rows: list[dict[str, object]] = []
    ordered = frame.sort_values(["product_id", "dt"])

    for product_id, group in ordered.groupby("product_id", sort=True):
        group = group.reset_index(drop=True)
        store_id = int(group.loc[0, "store_id"])

        # At cutoff Day 31 (index 30), use Day 1–30 for the 30-day window
        # and Day 17–30 for the 14-day window. The cutoff day itself is excluded.
        for cutoff_index in range(WINDOW_30, len(group)):
            window_14 = group.iloc[cutoff_index - WINDOW_14 : cutoff_index]
            window_30 = group.iloc[cutoff_index - WINDOW_30 : cutoff_index]
            full_stock_14 = window_14.loc[
                window_14["stock_hour6_22_cnt"].eq(0), "sale_amount"
            ]
            full_stock_30 = window_30.loc[
                window_30["stock_hour6_22_cnt"].eq(0), "sale_amount"
            ]

            median_14 = float(full_stock_14.median()) if len(full_stock_14) else np.nan
            median_30 = float(full_stock_30.median()) if len(full_stock_30) else np.nan

            if pd.isna(median_14) and pd.isna(median_30):
                difference = np.nan
                status = "no_full_stock_days_in_either_window"
            elif pd.isna(median_14):
                difference = np.nan
                status = "no_full_stock_days_in_14d_window"
            elif pd.isna(median_30):
                difference = np.nan
                status = "no_full_stock_days_in_30d_window"
            elif median_30 == 0:
                difference = np.nan
                status = "median_30_is_zero"
            else:
                difference = abs(median_14 - median_30) / median_30
                status = "comparable"

            if pd.isna(difference):
                difference_band = "unavailable"
            elif difference < 0.15:
                difference_band = "<15%"
            elif difference > 0.25:
                difference_band = ">25%"
            else:
                difference_band = "15%-25%"

            rows.append(
                {
                    "store_id": store_id,
                    "product_id": int(product_id),
                    "cutoff_day": cutoff_index + 1,
                    "cutoff_date": group.loc[cutoff_index, "dt"],
                    "history_end_date": group.loc[cutoff_index - 1, "dt"],
                    "window_14_start_date": window_14["dt"].iloc[0],
                    "window_30_start_date": window_30["dt"].iloc[0],
                    "full_stock_days_14": int(len(full_stock_14)),
                    "full_stock_days_30": int(len(full_stock_30)),
                    "full_stock_days_14_sufficient": bool(
                        len(full_stock_14) >= MIN_FULL_STOCK_DAYS_14
                    ),
                    "full_stock_days_30_sufficient": bool(
                        len(full_stock_30) >= MIN_FULL_STOCK_DAYS_30
                    ),
                    "median_sale_full_stock_14": median_14,
                    "median_sale_full_stock_30": median_30,
                    "difference": difference,
                    "difference_pct": difference * 100 if pd.notna(difference) else np.nan,
                    "difference_band": difference_band,
                    "calculation_status": status,
                }
            )

    return pd.DataFrame(rows)


def build_summary(detail: pd.DataFrame) -> pd.DataFrame:
    """Summarize stability and sample availability separately for each SKU."""
    rows: list[dict[str, object]] = []
    for product_id, group in detail.groupby("product_id", sort=True):
        comparable = group.loc[group["calculation_status"].eq("comparable")]
        difference = comparable["difference"]
        total = len(group)
        comparable_count = len(comparable)

        rows.append(
            {
                "product_id": int(product_id),
                "total_cutoffs": total,
                "comparable_cutoffs": comparable_count,
                "undefined_cutoffs": total - comparable_count,
                "full_stock_days_14_sufficient_cutoffs": int(
                    group["full_stock_days_14_sufficient"].sum()
                ),
                "full_stock_days_14_sufficient_rate": float(
                    group["full_stock_days_14_sufficient"].mean()
                ),
                "full_stock_days_30_sufficient_cutoffs": int(
                    group["full_stock_days_30_sufficient"].sum()
                ),
                "full_stock_days_30_sufficient_rate": float(
                    group["full_stock_days_30_sufficient"].mean()
                ),
                "median_full_stock_days_14": float(group["full_stock_days_14"].median()),
                "median_full_stock_days_30": float(group["full_stock_days_30"].median()),
                "median_difference": float(difference.median()),
                "mean_difference": float(difference.mean()),
                "p75_difference": float(difference.quantile(0.75)),
                "p90_difference": float(difference.quantile(0.90)),
                "max_difference": float(difference.max()),
                "difference_lt_15_count": int(difference.lt(0.15).sum()),
                "difference_lt_15_rate": float(difference.lt(0.15).mean()),
                "difference_15_to_25_count": int(
                    difference.between(0.15, 0.25, inclusive="both").sum()
                ),
                "difference_15_to_25_rate": float(
                    difference.between(0.15, 0.25, inclusive="both").mean()
                ),
                "difference_gt_25_count": int(difference.gt(0.25).sum()),
                "difference_gt_25_rate": float(difference.gt(0.25).mean()),
            }
        )
    return pd.DataFrame(rows)


def pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}%}"


def build_markdown(summary: pd.DataFrame) -> str:
    table_lines = [
        "| SKU | 可比窗口 | 通常差异（中位数） | 平均差异 | <15% | >25% | P90差异 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.itertuples(index=False):
        table_lines.append(
            "| "
            f"{row.product_id} | {row.comparable_cutoffs}/{row.total_cutoffs} | "
            f"{pct(row.median_difference)} | {pct(row.mean_difference)} | "
            f"{row.difference_lt_15_count}/{row.comparable_cutoffs} "
            f"({pct(row.difference_lt_15_rate)}) | "
            f"{row.difference_gt_25_count}/{row.comparable_cutoffs} "
            f"({pct(row.difference_gt_25_rate)}) | {pct(row.p90_difference)} |"
        )

    availability_lines = [
        "| SKU | 14天充足（≥7天） | 14天充足比例 | 30天充足（≥15天） | 30天充足比例 | 14天完整有货日中位数 | 无法比较窗口 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.itertuples(index=False):
        availability_lines.append(
            "| "
            f"{row.product_id} | "
            f"{row.full_stock_days_14_sufficient_cutoffs}/{row.total_cutoffs} | "
            f"{pct(row.full_stock_days_14_sufficient_rate)} | "
            f"{row.full_stock_days_30_sufficient_cutoffs}/{row.total_cutoffs} | "
            f"{pct(row.full_stock_days_30_sufficient_rate)} | "
            f"{row.median_full_stock_days_14:.1f} | {row.undefined_cutoffs} |"
        )

    return "\n".join(
        [
            "# 14 天 vs 30 天滚动窗口稳定性检查",
            "",
            "## 口径",
            "",
            "- 对每个 SKU 设置 Day 31–Day 90 共 60 个截止点。",
            "- 严格只使用截止日之前的数据：Day 31 使用 Day 1–30 作为 30 天窗口、Day 17–30 作为 14 天窗口；截止日当天不进入计算。",
            "- “完整有货日”定义为 `stock_hour6_22_cnt = 0`，中位数只基于这些日期的原始 `sale_amount`。",
            "- 差异按 `abs(median_14 - median_30) / median_30` 计算；当任一窗口无完整有货日，或 30 天中位数为 0 时，不计算差异。",
            "- 沿用轻量可用性口径：14 天窗口至少有 7 个完整有货日才记为“样本充足”。该门槛只用于数据可用性检查，不用于剔除主稳定性统计。",
            "- `<15%` 和 `>25%` 的比例分母均为“可比窗口”数量，不包含无法计算的窗口。",
            "",
            "## 数值稳定性",
            "",
            *table_lines,
            "",
            "## 完整有货日样本可用性",
            "",
            *availability_lines,
            "",
            "## 结论",
            "",
            "- SKU 167 最稳定：78.3% 的可比窗口差异低于 15%，只有 1.7% 高于 25%。SKU 834 的典型差异最低（中位数 4.2%），但尾部偶有较大偏离。",
            "- SKU 316 和 851 居中；SKU 851 有 16.7% 的窗口差异高于 25%，说明短窗口对其近期水平变化更敏感。",
            "- SKU 44 在全部可比窗口中的典型差异最高（中位数 16.7%），且 22.6% 的窗口差异高于 25%，数值稳定性最弱。",
            "- 更重要的是，SKU 44 的 60 个滚动截止点中只有 4 个满足“14 天至少 7 个完整有货日”，没有任何截止点满足“30 天至少 15 个完整有货日”，另有 7 个窗口完全无法计算。它并非只是波动较大，而是完整有货样本经常不足，因此不能把其窗口中位数当作可靠基线。",
            "- 对 SKU 44，满足样本充足条件的窗口只有 4 个，样本过少，不应据此反向宣称其在“充足窗口内”稳定或不稳定。",
            "",
            "本检查只评估两个历史窗口估计值的一致性，不解释需求变化原因，也不构成预测或补货规则。",
            "",
        ]
    )


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    frame = pd.read_parquet(INPUT_PATH)
    frame["dt"] = pd.to_datetime(frame["dt"])
    validate_input(frame)

    detail = build_detail(frame)
    summary = build_summary(detail)

    if len(detail) != 300 or not detail.groupby("product_id").size().eq(60).all():
        raise AssertionError("Expected exactly 60 rolling cutoffs for each of 5 SKUs")
    if not detail["cutoff_day"].between(31, 90).all():
        raise AssertionError("Rolling cutoffs must span Day 31 through Day 90")
    if not (detail["history_end_date"] < detail["cutoff_date"]).all():
        raise AssertionError("Look-ahead detected: history must end before cutoff")

    detail.to_csv(DETAIL_PATH, index=False, float_format="%.6f", date_format="%Y-%m-%d")
    summary.to_csv(
        SUMMARY_CSV_PATH, index=False, float_format="%.6f", date_format="%Y-%m-%d"
    )
    SUMMARY_MD_PATH.write_text(build_markdown(summary), encoding="utf-8")

    print(f"Input validated: {len(frame)} rows, {frame['product_id'].nunique()} SKUs")
    print(f"Rolling detail: {len(detail)} rows -> {DETAIL_PATH}")
    print(f"Summary: {len(summary)} rows -> {SUMMARY_CSV_PATH}")
    print(f"Report -> {SUMMARY_MD_PATH}")


if __name__ == "__main__":
    main()
