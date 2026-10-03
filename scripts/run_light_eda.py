#!/usr/bin/env python3
"""Validate the MVP dataset and produce the requested lightweight EDA outputs."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "inventory-decision-copilot-mpl")
)

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from PIL import Image  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "freshretail_mvp.parquet"
CSV_PATH = ROOT / "freshretail_mvp.csv"
EDA_DIR = ROOT / "reports" / "eda"
DOCS_DIR = ROOT / "docs"
STATS_PATH = EDA_DIR / "sku_eda_statistics.csv"
VALIDATION_PATH = EDA_DIR / "eda_validation.json"
SUMMARY_PATH = ROOT / "reports" / "eda_summary.md"
DICTIONARY_PATH = DOCS_DIR / "data_dictionary.md"

EXPECTED_COLUMNS = [
    "store_id",
    "product_id",
    "dt",
    "sale_amount",
    "stock_hour6_22_cnt",
]
EXPECTED_PRODUCTS = [44, 167, 316, 834, 851]
SEVERITY_ORDER = [851, 167, 316, 834, 44]

SALE_COLOR = "#2F6BFF"
STOCK_COLOR = "#E67E22"
GRID_COLOR = "#D7DEE8"
TEXT_COLOR = "#1F2937"
MUTED_COLOR = "#5F6B7A"


def markdown_table(frame: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    formats = formats or {}
    display = frame.copy()
    for column, fmt in formats.items():
        if column in display.columns:
            display[column] = display[column].map(lambda value: fmt.format(value))
    headers = [str(column) for column in display.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        values = [str(value).replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def longest_true_run(values: pd.Series) -> int:
    longest = current = 0
    for value in values.astype(bool):
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def validate_data(frame: pd.DataFrame) -> dict[str, object]:
    checks = {
        "row_count": int(len(frame)),
        "column_names": frame.columns.tolist(),
        "store_count": int(frame["store_id"].nunique()),
        "store_ids": [int(value) for value in sorted(frame["store_id"].unique())],
        "product_count": int(frame["product_id"].nunique()),
        "product_ids": [int(value) for value in sorted(frame["product_id"].unique())],
        "records_per_product": {
            str(int(key)): int(value)
            for key, value in frame.groupby("product_id").size().items()
        },
        "date_min": frame["dt"].min().strftime("%Y-%m-%d"),
        "date_max": frame["dt"].max().strftime("%Y-%m-%d"),
        "duplicate_key_rows": int(
            frame.duplicated(["store_id", "product_id", "dt"]).sum()
        ),
        "missing_values": {
            key: int(value) for key, value in frame[EXPECTED_COLUMNS].isna().sum().items()
        },
    }
    checks["passed"] = bool(
        checks["row_count"] == 450
        and checks["column_names"] == EXPECTED_COLUMNS
        and checks["store_ids"] == [837]
        and checks["product_ids"] == EXPECTED_PRODUCTS
        and set(checks["records_per_product"].values()) == {90}
        and checks["date_min"] == "2024-03-28"
        and checks["date_max"] == "2024-06-25"
        and checks["duplicate_key_rows"] == 0
        and sum(checks["missing_values"].values()) == 0
    )
    return checks


def build_statistics(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for product_id, group in frame.groupby("product_id", sort=True):
        group = group.sort_values("dt")
        stockout_mask = group["stock_hour6_22_cnt"] > 0
        stockout_sales = group.loc[stockout_mask, "sale_amount"]
        non_stockout_sales = group.loc[~stockout_mask, "sale_amount"]
        rows.append(
            {
                "product_id": int(product_id),
                "record_days": int(len(group)),
                "active_sales_days": int(group["sale_amount"].gt(0).sum()),
                "total_sales": float(group["sale_amount"].sum()),
                "mean_daily_sales": float(group["sale_amount"].mean()),
                "median_daily_sales": float(group["sale_amount"].median()),
                "stockout_days": int(stockout_mask.sum()),
                "stockout_day_ratio": float(stockout_mask.mean()),
                "total_stockout_hours": int(group["stock_hour6_22_cnt"].sum()),
                "full_stockout_days": int(group["stock_hour6_22_cnt"].eq(16).sum()),
                "longest_stockout_day_streak": longest_true_run(stockout_mask),
                "sale_stockout_pearson_r": float(
                    group["sale_amount"].corr(group["stock_hour6_22_cnt"])
                ),
                "mean_sales_stockout_days": float(stockout_sales.mean()),
                "mean_sales_non_stockout_days": float(non_stockout_sales.mean()),
                "mean_sales_difference_stockout_minus_non": float(
                    stockout_sales.mean() - non_stockout_sales.mean()
                ),
                "first_30d_stockout_hours": int(
                    group.head(30)["stock_hour6_22_cnt"].sum()
                ),
                "last_30d_stockout_hours": int(
                    group.tail(30)["stock_hour6_22_cnt"].sum()
                ),
                "first_30d_mean_sales": float(group.head(30)["sale_amount"].mean()),
                "last_30d_mean_sales": float(group.tail(30)["sale_amount"].mean()),
            }
        )
    return pd.DataFrame(rows)


def style_axis(axis: plt.Axes) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color(GRID_COLOR)
    axis.spines["bottom"].set_color(GRID_COLOR)
    axis.tick_params(colors=MUTED_COLOR, labelsize=10)
    axis.grid(axis="y", color=GRID_COLOR, linewidth=0.7, alpha=0.7)


def create_timeseries_chart(group: pd.DataFrame, stockout_ratio: float) -> Path:
    product_id = int(group["product_id"].iloc[0])
    group = group.sort_values("dt")
    figure, (sales_axis, stock_axis) = plt.subplots(
        2,
        1,
        figsize=(13.5, 8.5),
        dpi=140,
        sharex=True,
        gridspec_kw={"height_ratios": [1.25, 1], "hspace": 0.10},
    )
    figure.patch.set_facecolor("white")

    sales_axis.plot(
        group["dt"],
        group["sale_amount"],
        color=SALE_COLOR,
        linewidth=1.8,
        marker="o",
        markersize=2.8,
        markeredgewidth=0,
    )
    sales_axis.set_ylabel("sale_amount\n(processed unit)", color=TEXT_COLOR, fontsize=11)
    sales_axis.set_ylim(bottom=0)
    style_axis(sales_axis)

    stock_axis.bar(
        group["dt"],
        group["stock_hour6_22_cnt"],
        width=0.82,
        color=STOCK_COLOR,
        alpha=0.88,
    )
    stock_axis.set_ylabel("Out-of-stock hours\n(06:00–22:00)", color=TEXT_COLOR, fontsize=11)
    stock_axis.set_ylim(0, 16.8)
    stock_axis.set_yticks([0, 4, 8, 12, 16])
    stock_axis.set_xlabel("Date", color=TEXT_COLOR, fontsize=11)
    stock_axis.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    stock_axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    stock_axis.tick_params(axis="x", rotation=35)
    style_axis(stock_axis)

    figure.suptitle(
        f"Product {product_id} | stockout-day ratio: {stockout_ratio:.1%}",
        fontsize=15,
        fontweight="semibold",
        color=TEXT_COLOR,
        y=0.975,
    )
    figure.text(
        0.5,
        0.012,
        "Daily raw values; no smoothing or rescaling",
        ha="center",
        color=MUTED_COLOR,
        fontsize=9.5,
    )
    figure.subplots_adjust(left=0.10, right=0.98, top=0.91, bottom=0.12)
    output = EDA_DIR / f"sku_{product_id}_timeseries.png"
    figure.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return output


def create_comparison_chart(statistics: pd.DataFrame) -> Path:
    ordered = statistics.set_index("product_id").loc[SEVERITY_ORDER].reset_index()
    labels = [str(value) for value in ordered["product_id"]]
    y = np.arange(len(ordered))
    figure, (ratio_axis, hours_axis) = plt.subplots(
        1,
        2,
        figsize=(13.5, 5.8),
        dpi=140,
        gridspec_kw={"wspace": 0.28},
    )
    figure.patch.set_facecolor("white")

    ratio_values = ordered["stockout_day_ratio"].to_numpy()
    ratio_axis.barh(y, ratio_values, color=SALE_COLOR, height=0.62)
    ratio_axis.set_yticks(y, labels)
    ratio_axis.invert_yaxis()
    ratio_axis.set_xlim(0, 0.86)
    ratio_axis.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    ratio_axis.set_xlabel("Share of 90 days", color=TEXT_COLOR, fontsize=11)
    ratio_axis.set_title("Stockout-day ratio", color=TEXT_COLOR, fontsize=12)
    for index, value in enumerate(ratio_values):
        ratio_axis.text(
            value + 0.015,
            index,
            f"{value:.1%}",
            va="center",
            color=TEXT_COLOR,
            fontsize=10,
        )
    style_axis(ratio_axis)

    hours_values = ordered["total_stockout_hours"].to_numpy()
    hours_axis.barh(y, hours_values, color=STOCK_COLOR, height=0.62)
    hours_axis.set_yticks(y, labels)
    hours_axis.invert_yaxis()
    hours_axis.set_xlim(0, 1_040)
    hours_axis.set_xlabel("Hours over 90 days", color=TEXT_COLOR, fontsize=11)
    hours_axis.set_title("Total stockout hours", color=TEXT_COLOR, fontsize=12)
    for index, value in enumerate(hours_values):
        hours_axis.text(
            value + 18,
            index,
            f"{value:,}",
            va="center",
            color=TEXT_COLOR,
            fontsize=10,
        )
    style_axis(hours_axis)

    figure.suptitle(
        "Stockout severity across five SKUs",
        fontsize=15,
        fontweight="semibold",
        color=TEXT_COLOR,
        y=0.97,
    )
    figure.text(
        0.02,
        0.5,
        "product_id",
        rotation=90,
        va="center",
        color=MUTED_COLOR,
        fontsize=10,
    )
    figure.subplots_adjust(left=0.09, right=0.98, top=0.84, bottom=0.16)
    output = EDA_DIR / "sku_stockout_comparison.png"
    figure.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return output


def write_data_dictionary() -> None:
    content = """# FreshRetail MVP 数据字典

## 范围

本数据字典只记录 `freshretail_mvp.parquet` 和 `freshretail_mvp.csv` 中实际存在的五个字段。不定义或暗示源数据中不存在的库存数量、提前期、补货订单等业务字段。

| 字段 | 数据类型 | 含义 | 示例 | 使用限制 |
| --- | --- | --- | --- | --- |
| `store_id` | Parquet `int64` | 编码后的门店标识。当前 MVP 的所有记录均属于门店 `837`。 | `837` | 这是匿名化/编码标识，不是业务系统中的门店代码，也不包含位置或门店属性。 |
| `product_id` | Parquet `int64` | 编码后的商品/SKU 标识。 | `851` | 不包含商品名称、品类、价格、包装规格、保质期或计量单位。 |
| `dt` | Parquet `string`，格式为 `YYYY-MM-DD` | 每日观测对应的自然日期。 | `2024-03-28` | 表示日粒度日期，不是事件时间戳；时间序列分析前应显式解析为日期类型。 |
| `sale_amount` | Parquet `float64` | 官方处理后的日销售数值。本项目只把它作为相对的观察销量或需求/销售强度指标。 | `0.9` | 不是可以直接解释为商品件数或销售金额的原始业务单位。官方数据经过全局处理；缺货还可能截断观察销量，因此它不等于未经截断的潜在需求。 |
| `stock_hour6_22_cnt` | Parquet `int32` | 当天 06:00–22:00 期间的缺货小时数。 | `10` | 有效范围为 0–16。它不是实际库存数量、库存余额、补货数量，也不表示每次缺货发生的精确小时位置。 |

## 解释限制

缺货日观察到的 `sale_amount` 较低，并不能证明顾客需求较低。商品无货后，即使潜在需求仍然较高，实际成交销量也可能被截断。
"""
    DICTIONARY_PATH.write_text(content, encoding="utf-8")


def write_summary(statistics: pd.DataFrame) -> None:
    ordered = statistics.set_index("product_id").loc[SEVERITY_ORDER].reset_index()
    core = ordered[
        [
            "product_id",
            "total_sales",
            "mean_daily_sales",
            "active_sales_days",
            "stockout_days",
            "stockout_day_ratio",
            "total_stockout_hours",
        ]
    ].rename(
        columns={
            "product_id": "SKU",
            "total_sales": "sale_amount 总和",
            "mean_daily_sales": "日均 sale_amount",
            "active_sales_days": "有销量天数",
            "stockout_days": "缺货天数",
            "stockout_day_ratio": "缺货天比例",
            "total_stockout_hours": "缺货小时数",
        }
    )
    relation = ordered[
        [
            "product_id",
            "sale_stockout_pearson_r",
            "mean_sales_stockout_days",
            "mean_sales_non_stockout_days",
            "mean_sales_difference_stockout_minus_non",
        ]
    ].rename(
        columns={
            "product_id": "SKU",
            "sale_stockout_pearson_r": "Pearson r",
            "mean_sales_stockout_days": "缺货日日均 sale_amount",
            "mean_sales_non_stockout_days": "非缺货日日均 sale_amount",
            "mean_sales_difference_stockout_minus_non": "缺货日减非缺货日",
        }
    )

    all_first_heavier = bool(
        (ordered["first_30d_stockout_hours"] > ordered["last_30d_stockout_hours"]).all()
    )
    concentration_text = (
        "五个 SKU 在前 30 天的缺货小时数都高于最后 30 天。"
        if all_first_heavier
        else "五个 SKU 在 90 天窗口中的缺货时点分布不同。"
    )

    content = f"""# 轻量 EDA 总结

## 1. 五个 SKU 的缺货严重程度是否形成明显梯度？

是。按 851 → 167 → 316 → 834 → 44 排列时，缺货天比例从 5.6% 单调上升至 77.8%，累计缺货小时数也从 57 增至 937。缺货频率和持续时间都呈现清晰梯度。

{markdown_table(core, {'sale_amount 总和': '{:.2f}', '日均 sale_amount': '{:.3f}', '缺货天比例': '{:.1%}'})}

## 2. 各 SKU 的销量和缺货在时间上有什么明显现象？

{concentration_text} SKU 851 的 57 个缺货小时中有 56 个集中在前 30 天。SKU 834 和 44 多次出现长时或全天缺货，且前段更集中。五个 SKU 最后 30 天的平均观察销量都高于前 30 天，但当前数据无法区分这是缺货减少、季节性还是其他时间因素造成的。

## 3. 缺货日与非缺货日的观察销量是否有差异？

有描述性差异。五个 SKU 的日度 Pearson correlation 都为负，且缺货日平均观察 `sale_amount` 都低于非缺货日。SKU 851 只有 5 个缺货日，因此该 SKU 的相关系数稳定性较弱；缺货更严重的 SKU 负相关更强。

{markdown_table(relation, {'Pearson r': '{:.3f}', '缺货日日均 sale_amount': '{:.3f}', '非缺货日日均 sale_amount': '{:.3f}', '缺货日减非缺货日': '{:.3f}'})}

这些结果只用于描述，不能作因果解释。观察销量可能受缺货截断，因此缺货日销量较低不能证明潜在需求较低。

## 4. 哪些现象值得后续项目继续使用？

- 五个 SKU 位于同一门店和同一个 90 天窗口内，提供了清晰的低至高缺货梯度。
- 日粒度销量与缺货小时完全对齐，适合后续做可解释的库存风险展示。
- SKU 316、834 和 44 包含多次高缺货时段，可用于后续验证风险解释是否符合实际数据。

## 5. 哪些结论不能从当前数据推出？

- 如果没有额外假设或方法，当前字段不能识别损失销量或未经截断的潜在需求。
- 相关关系不能证明全部销量差异由缺货造成；时间趋势、促销、天气或其他未纳入变量也可能产生影响。
- 当前字段不能支持对现有库存、补货数量、提前期、服务水平或最优订货量的判断。
"""
    SUMMARY_PATH.write_text(content, encoding="utf-8")


def verify_images(paths: list[Path]) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for path in paths:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            results[path.name] = {
                "format": image.format,
                "size_pixels": list(image.size),
                "mode": image.mode,
                "file_bytes": path.stat().st_size,
            }
            if image.format != "PNG" or image.size[0] < 1_200 or image.size[1] < 600:
                raise ValueError(f"Image verification failed for {path}")
    return results


def main() -> None:
    EDA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    table = pq.read_table(INPUT_PATH, columns=EXPECTED_COLUMNS)
    frame = table.to_pandas()
    frame["dt"] = pd.to_datetime(frame["dt"], format="%Y-%m-%d", errors="raise")
    validation = validate_data(frame)
    if not validation["passed"]:
        raise ValueError(f"MVP validation failed: {validation}")

    # Confirm the two user-facing formats still contain the same five raw fields.
    csv_frame = pd.read_csv(CSV_PATH)
    csv_frame["dt"] = pd.to_datetime(csv_frame["dt"], format="%Y-%m-%d", errors="raise")
    pd.testing.assert_frame_equal(
        frame.sort_values(["product_id", "dt"]).reset_index(drop=True),
        csv_frame.sort_values(["product_id", "dt"]).reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        rtol=0,
        atol=5e-7,
    )
    validation["csv_matches_parquet"] = True

    statistics = build_statistics(frame)
    statistics.to_csv(STATS_PATH, index=False, float_format="%.6f")

    chart_paths: list[Path] = []
    ratio_lookup = statistics.set_index("product_id")["stockout_day_ratio"].to_dict()
    for product_id in EXPECTED_PRODUCTS:
        chart_paths.append(
            create_timeseries_chart(
                frame[frame["product_id"].eq(product_id)], ratio_lookup[product_id]
            )
        )
    chart_paths.append(create_comparison_chart(statistics))
    validation["image_checks"] = verify_images(chart_paths)

    write_data_dictionary()
    write_summary(statistics)

    validation["statistics_rows"] = int(len(statistics))
    validation["output_files"] = [
        str(path.relative_to(ROOT))
        for path in chart_paths
        + [STATS_PATH, DICTIONARY_PATH, SUMMARY_PATH]
    ]
    VALIDATION_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(validation, ensure_ascii=False, indent=2))
    print("\nSKU statistics:")
    print(statistics.set_index("product_id").loc[SEVERITY_ORDER].reset_index().to_string(index=False))


if __name__ == "__main__":
    main()
