#!/usr/bin/env python3
"""Audit rule-based daily demand estimates at fixed historical as-of dates."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PARQUET_PATH = ROOT / "freshretail_mvp.parquet"
CSV_PATH = ROOT / "freshretail_mvp.csv"
REPORTS_DIR = ROOT / "reports"
DETAIL_PATH = REPORTS_DIR / "demand_audit_detail.csv"
SUMMARY_PATH = REPORTS_DIR / "demand_audit_sku_summary.csv"
VALIDATION_PATH = REPORTS_DIR / "demand_audit_validation.json"

SKU_ORDER = [851, 167, 316, 834, 44]
AS_OF_DATES = pd.to_datetime(
    ["2024-05-01", "2024-05-15", "2024-05-29", "2024-06-12", "2024-06-25"]
)
CORE_COLUMNS = [
    "store_id",
    "product_id",
    "dt",
    "sale_amount",
    "stock_hour6_22_cnt",
]


def load_mvp() -> tuple[pd.DataFrame, Path]:
    """Prefer Parquet; use the equivalent MVP CSV when no Parquet engine is present."""
    try:
        frame = pd.read_parquet(PARQUET_PATH)
        source_path = PARQUET_PATH
    except ImportError:
        frame = pd.read_csv(CSV_PATH)
        source_path = CSV_PATH
    frame["dt"] = pd.to_datetime(frame["dt"])
    return frame, source_path


def validate_source(frame: pd.DataFrame) -> None:
    if frame.columns.tolist() != CORE_COLUMNS:
        raise ValueError(f"Unexpected columns: {frame.columns.tolist()}")
    if len(frame) != 450:
        raise ValueError(f"Expected 450 rows, found {len(frame)}")
    if frame["store_id"].nunique() != 1 or frame["store_id"].iloc[0] != 837:
        raise ValueError("Expected only store_id 837")
    if set(frame["product_id"].unique()) != set(SKU_ORDER):
        raise ValueError("Unexpected SKU set")
    if frame[CORE_COLUMNS].isna().any().any():
        raise ValueError("Core source fields contain missing values")
    if frame.duplicated(["store_id", "product_id", "dt"]).any():
        raise ValueError("Duplicate store_id + product_id + dt keys found")

    for sku_id, group in frame.groupby("product_id"):
        ordered = group.sort_values("dt")
        if len(ordered) != 90:
            raise ValueError(f"SKU {sku_id} does not have 90 observations")
        expected = pd.Series(
            pd.date_range(ordered["dt"].min(), periods=90, freq="D"),
            name="dt",
        )
        actual = ordered["dt"].reset_index(drop=True)
        if not actual.equals(expected):
            raise ValueError(f"SKU {sku_id} is not a contiguous daily series")


def trailing_window(group: pd.DataFrame, as_of_date: pd.Timestamp, days: int) -> pd.DataFrame:
    start_date = as_of_date - pd.Timedelta(days=days)
    return group.loc[group["dt"].ge(start_date) & group["dt"].lt(as_of_date)].copy()


def full_stock_sales(window: pd.DataFrame) -> pd.Series:
    return window.loc[window["stock_hour6_22_cnt"].eq(0), "sale_amount"]


def build_detail(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for sku_id in SKU_ORDER:
        group = frame.loc[frame["product_id"].eq(sku_id)].sort_values("dt")
        for as_of_date in AS_OF_DATES:
            window_14 = trailing_window(group, as_of_date, 14)
            window_30 = trailing_window(group, as_of_date, 30)
            sales_14 = full_stock_sales(window_14)
            sales_30 = full_stock_sales(window_30)
            in_stock_days_14 = len(sales_14)
            in_stock_days_30 = len(sales_30)
            median_14 = float(sales_14.median()) if in_stock_days_14 else np.nan
            median_30 = float(sales_30.median()) if in_stock_days_30 else np.nan

            if in_stock_days_14 >= 10:
                estimated_demand = median_14
                confidence = "High"
                demand_window_days: int | float = 14
                evaluated_window_days = 14
                in_stock_days_used = in_stock_days_14
                window_type = "Standard 14-day"
                manual_review = False
            elif in_stock_days_14 >= 7:
                estimated_demand = median_14
                confidence = "Medium"
                demand_window_days = 14
                evaluated_window_days = 14
                in_stock_days_used = in_stock_days_14
                window_type = "Standard 14-day"
                manual_review = False
            elif in_stock_days_30 >= 7:
                estimated_demand = median_30
                confidence = "Low"
                demand_window_days = 30
                evaluated_window_days = 30
                in_stock_days_used = in_stock_days_30
                window_type = "Extended window"
                manual_review = False
            else:
                estimated_demand = np.nan
                confidence = "Insufficient Data"
                demand_window_days = np.nan
                evaluated_window_days = 30
                in_stock_days_used = in_stock_days_30
                window_type = "Insufficient Data after 30-day check"
                manual_review = True

            history = group.loc[group["dt"].lt(as_of_date)]
            selected_window_start = as_of_date - pd.Timedelta(days=evaluated_window_days)
            rows.append(
                {
                    "sku_id": sku_id,
                    "as_of_date": as_of_date,
                    "history_max_date_used": history["dt"].max(),
                    "window_14_start_date": as_of_date - pd.Timedelta(days=14),
                    "window_14_end_date": as_of_date - pd.Timedelta(days=1),
                    "window_30_start_date": as_of_date - pd.Timedelta(days=30),
                    "window_30_end_date": as_of_date - pd.Timedelta(days=1),
                    "records_in_window_14": len(window_14),
                    "records_in_window_30": len(window_30),
                    "in_stock_days_14": in_stock_days_14,
                    "in_stock_days_30": in_stock_days_30,
                    "candidate_median_full_stock_14": median_14,
                    "candidate_median_full_stock_30": median_30,
                    "estimated_daily_demand": estimated_demand,
                    "demand_confidence": confidence,
                    "demand_window_days": demand_window_days,
                    "evaluated_window_days": evaluated_window_days,
                    "selected_window_start_date": selected_window_start,
                    "selected_window_end_date": as_of_date - pd.Timedelta(days=1),
                    "in_stock_days_used": in_stock_days_used,
                    "window_type": window_type,
                    "manual_review_required": manual_review,
                }
            )

    detail = pd.DataFrame(rows)
    detail["demand_window_days"] = detail["demand_window_days"].astype("Int64")
    return detail


def build_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sku_id in SKU_ORDER:
        group = detail.loc[detail["sku_id"].eq(sku_id)]
        valid = group["estimated_daily_demand"].dropna()
        minimum = float(valid.min()) if len(valid) else np.nan
        maximum = float(valid.max()) if len(valid) else np.nan
        rows.append(
            {
                "sku_id": sku_id,
                "as_of_points": len(group),
                "valid_estimate_count": len(valid),
                "insufficient_data_count": int(
                    group["demand_confidence"].eq("Insufficient Data").sum()
                ),
                "high_confidence_count": int(group["demand_confidence"].eq("High").sum()),
                "medium_confidence_count": int(
                    group["demand_confidence"].eq("Medium").sum()
                ),
                "low_confidence_count": int(group["demand_confidence"].eq("Low").sum()),
                "extended_window_count": int(group["window_type"].eq("Extended window").sum()),
                "min_estimated_daily_demand": minimum,
                "median_estimated_daily_demand": (
                    float(valid.median()) if len(valid) else np.nan
                ),
                "max_estimated_daily_demand": maximum,
                "range_estimated_daily_demand": (
                    maximum - minimum if len(valid) else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def validate_results(
    frame: pd.DataFrame, detail: pd.DataFrame, summary: pd.DataFrame, source_path: Path
) -> dict[str, object]:
    expected_pairs = {(sku, date) for sku in SKU_ORDER for date in AS_OF_DATES}
    actual_pairs = set(zip(detail["sku_id"], detail["as_of_date"]))

    no_as_of_or_future_data = bool(
        (detail["history_max_date_used"] < detail["as_of_date"]).all()
        and (detail["selected_window_end_date"] < detail["as_of_date"]).all()
    )
    window_boundaries_correct = bool(
        detail["records_in_window_14"].eq(14).all()
        and detail["records_in_window_30"].eq(30).all()
        and (
            detail["window_14_start_date"]
            == detail["as_of_date"] - pd.to_timedelta(14, unit="D")
        ).all()
        and (
            detail["window_30_start_date"]
            == detail["as_of_date"] - pd.to_timedelta(30, unit="D")
        ).all()
        and detail["window_14_end_date"].eq(
            detail["as_of_date"] - pd.to_timedelta(1, unit="D")
        ).all()
        and detail["window_30_end_date"].eq(
            detail["as_of_date"] - pd.to_timedelta(1, unit="D")
        ).all()
    )

    rule_matches: list[bool] = []
    estimate_matches: list[bool] = []
    for row in detail.itertuples(index=False):
        if row.in_stock_days_14 >= 10:
            expected_confidence = "High"
            expected_window = 14
            expected_manual = False
            expected_estimate = row.candidate_median_full_stock_14
        elif row.in_stock_days_14 >= 7:
            expected_confidence = "Medium"
            expected_window = 14
            expected_manual = False
            expected_estimate = row.candidate_median_full_stock_14
        elif row.in_stock_days_30 >= 7:
            expected_confidence = "Low"
            expected_window = 30
            expected_manual = False
            expected_estimate = row.candidate_median_full_stock_30
        else:
            expected_confidence = "Insufficient Data"
            expected_window = None
            expected_manual = True
            expected_estimate = np.nan

        actual_window = None if pd.isna(row.demand_window_days) else int(row.demand_window_days)
        rule_matches.append(
            row.demand_confidence == expected_confidence
            and actual_window == expected_window
            and bool(row.manual_review_required) == expected_manual
        )
        if pd.isna(expected_estimate):
            estimate_matches.append(pd.isna(row.estimated_daily_demand))
        else:
            estimate_matches.append(
                bool(np.isclose(row.estimated_daily_demand, expected_estimate, atol=1e-12))
            )

    insufficient = detail.loc[
        detail["demand_confidence"].eq("Insufficient Data"), ["sku_id", "as_of_date"]
    ]
    insufficient_records = [
        {"sku_id": int(row.sku_id), "as_of_date": row.as_of_date.strftime("%Y-%m-%d")}
        for row in insufficient.itertuples(index=False)
    ]

    summary_excludes_nulls = True
    for row in summary.itertuples(index=False):
        source = detail.loc[
            detail["sku_id"].eq(row.sku_id), "estimated_daily_demand"
        ].dropna()
        summary_excludes_nulls = summary_excludes_nulls and (
            row.valid_estimate_count == len(source)
            and np.isclose(row.min_estimated_daily_demand, source.min())
            and np.isclose(row.median_estimated_daily_demand, source.median())
            and np.isclose(row.max_estimated_daily_demand, source.max())
            and np.isclose(
                row.range_estimated_daily_demand, source.max() - source.min()
            )
        )

    checks = {
        "source_shape_is_450_by_5": frame.shape == (450, 5),
        "detail_has_25_rows": len(detail) == 25,
        "all_requested_sku_as_of_pairs_present_once": actual_pairs == expected_pairs
        and not detail.duplicated(["sku_id", "as_of_date"]).any(),
        "no_as_of_date_or_future_data_used": no_as_of_or_future_data,
        "all_14d_and_30d_boundaries_correct": window_boundaries_correct,
        "confidence_and_manual_review_match_rules": all(rule_matches),
        "estimated_demand_matches_selected_median": all(estimate_matches),
        "summary_excludes_null_estimates": bool(summary_excludes_nulls),
    }
    return {
        "passed": all(checks.values()),
        "source_file": str(source_path.relative_to(ROOT)),
        "checks": checks,
        "insufficient_data_exists": bool(len(insufficient)),
        "insufficient_data_count": int(len(insufficient)),
        "insufficient_data_records": insufficient_records,
        "extended_window_count": int(detail["window_type"].eq("Extended window").sum()),
        "extended_window_records": [
            {
                "sku_id": int(row.sku_id),
                "as_of_date": row.as_of_date.strftime("%Y-%m-%d"),
            }
            for row in detail.loc[
                detail["window_type"].eq("Extended window"), ["sku_id", "as_of_date"]
            ].itertuples(index=False)
        ],
    }


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    frame, source_path = load_mvp()
    validate_source(frame)
    detail = build_detail(frame)
    summary = build_summary(detail)
    validation = validate_results(frame, detail, summary, source_path)
    if not validation["passed"]:
        raise AssertionError(f"Demand audit validation failed: {validation['checks']}")

    date_columns = [
        "as_of_date",
        "history_max_date_used",
        "window_14_start_date",
        "window_14_end_date",
        "window_30_start_date",
        "window_30_end_date",
        "selected_window_start_date",
        "selected_window_end_date",
    ]
    output_detail = detail.copy()
    for column in date_columns:
        output_detail[column] = output_detail[column].dt.strftime("%Y-%m-%d")

    output_detail.to_csv(DETAIL_PATH, index=False, float_format="%.6f")
    summary.to_csv(SUMMARY_PATH, index=False, float_format="%.6f")
    VALIDATION_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Source: {source_path}")
    print(f"Detail: {len(detail)} rows -> {DETAIL_PATH}")
    print(f"Summary: {len(summary)} rows -> {SUMMARY_PATH}")
    print(f"Validation passed -> {VALIDATION_PATH}")


if __name__ == "__main__":
    main()
