#!/usr/bin/env python3
"""Profile FreshRetailNet-50K and create store-SKU and store candidate summaries."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "raw" / "train.parquet"
SUMMARY_PATH = ROOT / "store_sku_summary.csv"
PROFILE_PATH = ROOT / "reports" / "raw_data_profile.txt"
PROFILE_JSON_PATH = ROOT / "reports" / "raw_data_profile.json"
STORE_CANDIDATES_PATH = ROOT / "reports" / "store_candidates.csv"

CORE_COLUMNS = [
    "store_id",
    "product_id",
    "dt",
    "sale_amount",
    "stock_hour6_22_cnt",
]


def fmt_head(table: pa.Table) -> str:
    """Return a readable ten-row preview without truncating columns."""
    return table.to_pandas().to_string(index=False)


def main() -> None:
    if not RAW_PATH.exists():
        raise FileNotFoundError(RAW_PATH)

    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    parquet_file = pq.ParquetFile(RAW_PATH)
    schema = parquet_file.schema_arrow
    missing_required = [column for column in CORE_COLUMNS if column not in schema.names]
    if missing_required:
        raise ValueError(f"Missing required official fields: {missing_required}")

    null_counts = {name: 0 for name in schema.names}
    core_batches: list[pa.RecordBatch] = []
    first_ten: pa.Table | None = None

    # Scan once. All columns are visited for exact top-level null counts, while only
    # the five core columns are retained for aggregation.
    for batch in parquet_file.iter_batches(batch_size=131_072):
        if first_ten is None:
            first_ten = pa.Table.from_batches([batch.slice(0, 10)])
        for index, name in enumerate(schema.names):
            null_counts[name] += batch.column(index).null_count
        core_batches.append(batch.select(CORE_COLUMNS))

    if first_ten is None:
        raise ValueError("The training Parquet contains no rows")

    core_table = pa.Table.from_batches(core_batches)
    del core_batches

    sale = core_table["sale_amount"]
    stockout_hours = core_table["stock_hour6_22_cnt"]
    core_table = core_table.append_column(
        "active_sales_day",
        pc.cast(pc.greater(sale, pa.scalar(0.0)), pa.int8()),
    )
    core_table = core_table.append_column(
        "stockout_day",
        pc.cast(pc.greater(stockout_hours, pa.scalar(0)), pa.int8()),
    )

    grouped = core_table.group_by(["store_id", "product_id"]).aggregate(
        [
            ("dt", "count_distinct"),
            ("active_sales_day", "sum"),
            ("sale_amount", "sum"),
            ("stockout_day", "sum"),
            ("stock_hour6_22_cnt", "sum"),
        ]
    )
    summary = grouped.to_pandas().rename(
        columns={
            "dt_count_distinct": "record_days",
            "active_sales_day_sum": "active_sales_days",
            "sale_amount_sum": "total_sales",
            "stockout_day_sum": "stockout_days",
            "stock_hour6_22_cnt_sum": "total_stockout_hours",
        }
    )
    integer_columns = [
        "store_id",
        "product_id",
        "record_days",
        "active_sales_days",
        "stockout_days",
        "total_stockout_hours",
    ]
    summary[integer_columns] = summary[integer_columns].astype("int64")
    summary["avg_daily_sales"] = summary["total_sales"] / summary["record_days"]
    summary["avg_stockout_hours"] = (
        summary["total_stockout_hours"] / summary["record_days"]
    )
    summary["stockout_day_ratio"] = summary["stockout_days"] / summary["record_days"]
    summary["active_sales_day_ratio"] = (
        summary["active_sales_days"] / summary["record_days"]
    )
    summary = summary.sort_values(["store_id", "product_id"]).reset_index(drop=True)
    summary.to_csv(SUMMARY_PATH, index=False, float_format="%.6f")

    max_days = int(summary["record_days"].max())
    near_complete_days = int(np.ceil(max_days * 0.9))
    near_complete = summary[summary["record_days"] >= near_complete_days]
    positive_sales = near_complete.loc[near_complete["total_sales"] > 0, "total_sales"]
    sales_floor = float(positive_sales.quantile(0.20))
    eligible = near_complete[
        (near_complete["active_sales_day_ratio"] >= 0.50)
        & (near_complete["total_sales"] >= sales_floor)
    ].copy()

    stockout_quantiles = eligible["stockout_day_ratio"].quantile(
        [0.20, 0.40, 0.60, 0.80]
    )
    q20, q40, q60, q80 = [float(stockout_quantiles.loc[q]) for q in stockout_quantiles.index]

    def summarize_store(group: pd.DataFrame) -> pd.Series:
        ratios = group["stockout_day_ratio"]
        return pd.Series(
            {
                "eligible_skus": len(group),
                "low_stockout_skus": int((ratios <= q20).sum()),
                "middle_stockout_skus": int(((ratios >= q40) & (ratios <= q60)).sum()),
                "high_stockout_skus": int((ratios >= q80).sum()),
                "min_stockout_ratio": ratios.min(),
                "q25_stockout_ratio": ratios.quantile(0.25),
                "median_stockout_ratio": ratios.median(),
                "q75_stockout_ratio": ratios.quantile(0.75),
                "max_stockout_ratio": ratios.max(),
                "median_active_sales_ratio": group["active_sales_day_ratio"].median(),
                "median_total_sales": group["total_sales"].median(),
            }
        )

    store_all = summary.groupby("store_id").agg(
        sku_count=("product_id", "nunique"),
        near_complete_skus=("record_days", lambda x: int((x >= near_complete_days).sum())),
    )
    store_eligible = eligible.groupby("store_id", sort=True).apply(
        summarize_store, include_groups=False
    )
    stores = store_all.join(store_eligible, how="left").fillna(0).reset_index()

    # Transparent ranking: coverage and within-store contrast matter most; sales
    # sufficiency is already enforced in the eligible subset.
    stores["coverage_score"] = (
        np.log1p(stores["eligible_skus"])
        + np.minimum(stores["low_stockout_skus"], 3)
        + np.minimum(stores["middle_stockout_skus"], 3)
        + np.minimum(stores["high_stockout_skus"], 3)
        + 5
        * np.maximum(
            0,
            stores["max_stockout_ratio"] - stores["min_stockout_ratio"],
        )
    )
    stores = stores.sort_values(
        ["coverage_score", "eligible_skus", "sku_count"], ascending=False
    ).reset_index(drop=True)
    stores.to_csv(STORE_CANDIDATES_PATH, index=False, float_format="%.6f")

    dates = core_table["dt"]
    min_date = pc.min(dates).as_py()
    max_date = pc.max(dates).as_py()
    store_count = pc.count_distinct(core_table["store_id"]).as_py()
    product_count = pc.count_distinct(core_table["product_id"]).as_py()
    duplicate_keys = int(parquet_file.metadata.num_rows - summary["record_days"].sum())

    profile = {
        "shape": [parquet_file.metadata.num_rows, len(schema.names)],
        "row_groups": parquet_file.metadata.num_row_groups,
        "columns": schema.names,
        "dtypes": {field.name: str(field.type) for field in schema},
        "missing_values": null_counts,
        "date_range": [min_date, max_date],
        "store_count": int(store_count),
        "product_count": int(product_count),
        "store_sku_series_count": int(len(summary)),
        "duplicate_store_product_date_rows": duplicate_keys,
        "selection_thresholds": {
            "max_record_days": max_days,
            "near_complete_days": near_complete_days,
            "minimum_active_sales_day_ratio": 0.50,
            "total_sales_20th_percentile_floor": sales_floor,
            "eligible_stockout_ratio_quantiles": {
                "q20": q20,
                "q40": q40,
                "q60": q60,
                "q80": q80,
            },
        },
    }
    PROFILE_JSON_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    profile_lines = [
        "FreshRetailNet-50K train.parquet profile",
        "",
        f"Shape: {tuple(profile['shape'])}",
        f"Row groups: {profile['row_groups']}",
        f"Date range: {min_date} to {max_date}",
        f"Unique stores: {store_count}",
        f"Unique products: {product_count}",
        f"Store-SKU series: {len(summary)}",
        f"Duplicate store_id + product_id + dt rows: {duplicate_keys}",
        "",
        "Fields and Arrow dtypes:",
    ]
    profile_lines.extend(f"- {field.name}: {field.type}" for field in schema)
    profile_lines.extend(["", "First 10 rows:", fmt_head(first_ten), "", "Missing values:"])
    profile_lines.extend(f"- {name}: {count}" for name, count in null_counts.items())
    profile_lines.extend(
        [
            "",
            "Adaptive candidate-selection thresholds:",
            f"- Near-complete series: record_days >= {near_complete_days} (90% of max {max_days})",
            "- Active sales sufficiency: active_sales_day_ratio >= 0.50",
            f"- Sales sufficiency: total_sales >= {sales_floor:.6f} (20th percentile among positive, near-complete series)",
            f"- Eligible stockout ratio quantiles: q20={q20:.6f}, q40={q40:.6f}, q60={q60:.6f}, q80={q80:.6f}",
        ]
    )
    PROFILE_PATH.write_text("\n".join(profile_lines) + "\n", encoding="utf-8")

    print(f"Wrote {SUMMARY_PATH} ({len(summary):,} rows)")
    print(f"Wrote {STORE_CANDIDATES_PATH} ({len(stores):,} rows)")
    print(f"Wrote {PROFILE_PATH}")
    print(f"Wrote {PROFILE_JSON_PATH}")
    print("Top 10 store candidates:")
    print(stores.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
