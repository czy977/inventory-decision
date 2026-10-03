#!/usr/bin/env python3
"""Build and validate the selected one-store, five-SKU FreshRetailNet MVP."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "raw" / "train.parquet"
SUMMARY_PATH = ROOT / "store_sku_summary.csv"
STORE_CANDIDATES_PATH = ROOT / "reports" / "store_candidates.csv"
MVP_CSV_PATH = ROOT / "freshretail_mvp.csv"
MVP_PARQUET_PATH = ROOT / "freshretail_mvp.parquet"
SELECTED_SKUS_PATH = ROOT / "reports" / "selected_skus.csv"
STORE_SELECTION_PATH = ROOT / "reports" / "store_selection.md"
VALIDATION_PATH = ROOT / "reports" / "final_validation.txt"
VALIDATION_JSON_PATH = ROOT / "reports" / "final_validation.json"

SELECTED_STORE = 837
SELECTIONS = [
    {
        "sku_label": "A",
        "product_id": 851,
        "stockout_profile": "基本不缺货（全数据最低档）",
        "selection_reason": "5/90 天发生缺货，为全量数据可见的最低缺货天比例之一；86 天有销量且销量充足。",
    },
    {
        "sku_label": "B",
        "product_id": 167,
        "stockout_profile": "轻微缺货",
        "selection_reason": "15/90 天发生缺货，处于全量分布低端；89 天有销量，避免把低销量误当作低风险。",
    },
    {
        "sku_label": "C",
        "product_id": 316,
        "stockout_profile": "偶尔/较低程度缺货",
        "selection_reason": "28/90 天发生缺货、累计 325 小时；81 天有销量，形成清晰的中低风险样本。",
    },
    {
        "sku_label": "D",
        "product_id": 834,
        "stockout_profile": "中等程度缺货",
        "selection_reason": "40/90 天发生缺货、累计 512 小时；总销量较高，适合观察缺货对已实现销量的截断。",
    },
    {
        "sku_label": "E",
        "product_id": 44,
        "stockout_profile": "缺货明显",
        "selection_reason": "70/90 天发生缺货、累计 937 小时；仍有 51 天产生销量，不是长期近零销量商品。",
    },
]

CORE_COLUMNS = [
    "store_id",
    "product_id",
    "dt",
    "sale_amount",
    "stock_hour6_22_cnt",
]


def describe_series(series: pd.Series) -> dict[str, float | int]:
    desc = series.describe(percentiles=[0.25, 0.5, 0.75])
    return {
        "count": int(desc["count"]),
        "mean": float(desc["mean"]),
        "std": float(desc["std"]),
        "min": float(desc["min"]),
        "25%": float(desc["25%"]),
        "50%": float(desc["50%"]),
        "75%": float(desc["75%"]),
        "max": float(desc["max"]),
        "zero_count": int(series.eq(0).sum()),
    }


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    """Render a small DataFrame as Markdown without optional dependencies."""
    display = frame.copy()
    for column in display.select_dtypes(include="float").columns:
        display[column] = display[column].map(lambda value: f"{value:.6f}")
    headers = [str(column) for column in display.columns]
    rows = [[str(value).replace("|", "\\|") for value in row] for row in display.itertuples(index=False, name=None)]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def main() -> None:
    selected_product_ids = [item["product_id"] for item in SELECTIONS]
    summary = pd.read_csv(SUMMARY_PATH)
    candidates = pd.read_csv(STORE_CANDIDATES_PATH)

    selected_summary = summary[
        summary["store_id"].eq(SELECTED_STORE)
        & summary["product_id"].isin(selected_product_ids)
    ].copy()
    if len(selected_summary) != 5:
        raise ValueError("The selected summary does not contain exactly five SKUs")

    selection_metadata = pd.DataFrame(SELECTIONS)
    selected_summary = selection_metadata.merge(
        selected_summary, on="product_id", how="left", validate="one_to_one"
    )
    selected_summary = selected_summary[
        [
            "sku_label",
            "store_id",
            "product_id",
            "record_days",
            "active_sales_days",
            "active_sales_day_ratio",
            "total_sales",
            "avg_daily_sales",
            "stockout_days",
            "total_stockout_hours",
            "avg_stockout_hours",
            "stockout_day_ratio",
            "stockout_profile",
            "selection_reason",
        ]
    ]
    selected_summary.to_csv(SELECTED_SKUS_PATH, index=False, float_format="%.6f")

    # Parquet predicate pushdown keeps only the five requested fields and selected
    # store/SKUs. The ISO date string is preserved exactly as released.
    table = pq.read_table(
        RAW_PATH,
        columns=CORE_COLUMNS,
        filters=[
            ("store_id", "=", SELECTED_STORE),
            ("product_id", "in", selected_product_ids),
        ],
    )
    mvp = table.to_pandas()
    mvp = mvp.sort_values(["product_id", "dt"], kind="stable").reset_index(drop=True)

    if list(mvp.columns) != CORE_COLUMNS:
        raise ValueError(f"Unexpected output columns: {mvp.columns.tolist()}")
    if len(mvp) != 450:
        raise ValueError(f"Expected 450 rows, found {len(mvp)}")
    if mvp["store_id"].nunique() != 1:
        raise ValueError("MVP does not contain exactly one store")
    if mvp["product_id"].nunique() != 5:
        raise ValueError("MVP does not contain exactly five products")
    if mvp.duplicated(["store_id", "product_id", "dt"]).any():
        raise ValueError("Duplicate store-product-date keys found")
    if mvp.isna().any().any():
        raise ValueError("Missing values found in MVP core fields")
    if not mvp["sale_amount"].ge(0).all():
        raise ValueError("Negative sale_amount values found")
    if not mvp["stock_hour6_22_cnt"].between(0, 16).all():
        raise ValueError("stock_hour6_22_cnt falls outside the documented 0-16 range")

    mvp.to_csv(MVP_CSV_PATH, index=False, float_format="%.6f")
    output_schema = pa.schema(
        [
            ("store_id", pa.int64()),
            ("product_id", pa.int64()),
            ("dt", pa.string()),
            ("sale_amount", pa.float64()),
            ("stock_hour6_22_cnt", pa.int32()),
        ]
    )
    output_table = pa.Table.from_pandas(
        mvp, schema=output_schema, preserve_index=False, safe=True
    )
    pq.write_table(output_table, MVP_PARQUET_PATH, compression="snappy")

    per_sku = (
        mvp.groupby("product_id", sort=True)
        .agg(
            record_count=("dt", "size"),
            unique_days=("dt", "nunique"),
            date_min=("dt", "min"),
            date_max=("dt", "max"),
            active_sales_days=("sale_amount", lambda x: int((x > 0).sum())),
            total_sales=("sale_amount", "sum"),
            stockout_days=("stock_hour6_22_cnt", lambda x: int((x > 0).sum())),
            total_stockout_hours=("stock_hour6_22_cnt", "sum"),
        )
        .reset_index()
    )
    per_sku["stockout_day_ratio"] = per_sku["stockout_days"] / per_sku["unique_days"]

    expected = selected_summary[
        [
            "product_id",
            "record_days",
            "active_sales_days",
            "total_sales",
            "stockout_days",
            "total_stockout_hours",
            "stockout_day_ratio",
        ]
    ].sort_values("product_id").reset_index(drop=True)
    actual = per_sku[
        [
            "product_id",
            "unique_days",
            "active_sales_days",
            "total_sales",
            "stockout_days",
            "total_stockout_hours",
            "stockout_day_ratio",
        ]
    ].sort_values("product_id").reset_index(drop=True)
    if not expected["product_id"].equals(actual["product_id"]):
        raise ValueError("Selected product IDs do not reconcile")
    if not expected["record_days"].astype(int).equals(actual["unique_days"].astype(int)):
        raise ValueError("Per-SKU day counts do not reconcile")
    for column in [
        "active_sales_days",
        "total_sales",
        "stockout_days",
        "total_stockout_hours",
        "stockout_day_ratio",
    ]:
        if not pd.Series(expected[column]).astype(float).round(6).equals(
            pd.Series(actual[column]).astype(float).round(6)
        ):
            raise ValueError(f"Selected summary mismatch for {column}")

    sale_distribution = describe_series(mvp["sale_amount"])
    stockout_distribution = describe_series(mvp["stock_hour6_22_cnt"])
    parquet_roundtrip = pq.read_table(MVP_PARQUET_PATH).to_pandas()
    csv_roundtrip = pd.read_csv(MVP_CSV_PATH, dtype={"dt": "string"})
    try:
        pd.testing.assert_frame_equal(mvp, parquet_roundtrip, check_dtype=True)
    except AssertionError as exc:
        raise ValueError("Parquet round-trip validation failed") from exc
    try:
        pd.testing.assert_frame_equal(
            mvp.reset_index(drop=True),
            csv_roundtrip.reset_index(drop=True),
            check_dtype=False,
            check_exact=False,
            rtol=0,
            atol=5e-7,
        )
    except AssertionError as exc:
        raise ValueError("CSV round-trip validation failed") from exc

    validation = {
        "row_count": int(len(mvp)),
        "store_count": int(mvp["store_id"].nunique()),
        "store_id": int(mvp["store_id"].iloc[0]),
        "product_count": int(mvp["product_id"].nunique()),
        "product_ids": [int(value) for value in sorted(mvp["product_id"].unique())],
        "date_range": [str(mvp["dt"].min()), str(mvp["dt"].max())],
        "duplicate_key_rows": int(
            mvp.duplicated(["store_id", "product_id", "dt"]).sum()
        ),
        "missing_values": {key: int(value) for key, value in mvp.isna().sum().items()},
        "per_sku": per_sku.to_dict(orient="records"),
        "sale_amount_distribution": sale_distribution,
        "stock_hour6_22_cnt_distribution": stockout_distribution,
        "csv_roundtrip_ok": True,
        "parquet_roundtrip_ok": True,
    }
    VALIDATION_JSON_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    validation_lines = [
        "FreshRetailNet MVP final validation",
        "",
        f"Rows: {len(mvp)}",
        f"Stores: {mvp['store_id'].nunique()} ({SELECTED_STORE})",
        f"Products: {mvp['product_id'].nunique()} ({', '.join(map(str, sorted(selected_product_ids)))})",
        f"Date range: {mvp['dt'].min()} to {mvp['dt'].max()}",
        f"Duplicate store_id + product_id + dt rows: {validation['duplicate_key_rows']}",
        f"Missing values: {validation['missing_values']}",
        "",
        "Per-SKU checks:",
        per_sku.to_string(index=False),
        "",
        "sale_amount distribution:",
        json.dumps(sale_distribution, ensure_ascii=False, indent=2),
        "",
        "stock_hour6_22_cnt distribution:",
        json.dumps(stockout_distribution, ensure_ascii=False, indent=2),
        "",
        "CSV round-trip: PASS",
        "Parquet round-trip: PASS",
    ]
    VALIDATION_PATH.write_text("\n".join(validation_lines) + "\n", encoding="utf-8")

    store_row = candidates[candidates["store_id"].eq(SELECTED_STORE)].iloc[0]
    store_report = f"""# Store selection: {SELECTED_STORE}

Store {SELECTED_STORE} contains {int(store_row['sku_count'])} SKUs, all with 90 daily records. Under the adaptive quality screen, {int(store_row['eligible_skus'])} SKUs have at least 50% active-sales days and total normalized sales at or above the full-data 20th-percentile floor.

The store spans stockout-day ratios from {store_row['min_stockout_ratio']:.1%} to {store_row['max_stockout_ratio']:.1%}, with a median of {store_row['median_stockout_ratio']:.1%}. It contains {int(store_row['low_stockout_skus'])} low-stockout, {int(store_row['middle_stockout_skus'])} middle-stockout, and {int(store_row['high_stockout_skus'])} high-stockout eligible SKUs under the full-data quantile bands recorded in `raw_data_profile.json`.

This combination gives a complete 90-day panel, sufficient sales activity, and strong within-store contrast. The released training data has no zero-stockout series: the global minimum is 5/90 days (5.6%), so SKU A represents the observed minimum rather than an artificial zero-stockout example.

## Selected SKU ladder

{dataframe_to_markdown(selected_summary)}
"""
    STORE_SELECTION_PATH.write_text(store_report, encoding="utf-8")

    print(f"Wrote {MVP_CSV_PATH} ({len(mvp)} rows)")
    print(f"Wrote {MVP_PARQUET_PATH} ({len(mvp)} rows)")
    print(f"Wrote {SELECTED_SKUS_PATH}")
    print(f"Wrote {VALIDATION_PATH}")
    print(f"Wrote {VALIDATION_JSON_PATH}")
    print(f"Wrote {STORE_SELECTION_PATH}")
    print("Selected SKUs:")
    print(selected_summary.to_string(index=False))


if __name__ == "__main__":
    main()
