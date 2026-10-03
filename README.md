# Inventory Risk & Replenishment Decision Copilot — Phase 1

本目录保存 FreshRetailNet-50K 的原始训练数据、全量门店-SKU 汇总、候选门店分析、最终 1 店 × 5 SKU 数据集及验证报告。

## 数据来源

- Dataset: `Dingdong-Inc/FreshRetailNet-50K`
- Official file: `data/train.parquet`
- Source page: https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K
- Local raw file: `data/raw/train.parquet`
- Verified SHA-256: `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d`

## 主要输出

- `store_sku_summary.csv`: 全部 50,000 条门店-SKU 序列的汇总统计。
- `freshretail_mvp.csv`: 最终 450 行 MVP 数据。
- `freshretail_mvp.parquet`: 与 CSV 内容一致的 Parquet 版本。
- `reports/raw_data_profile.txt`: 原始 shape、字段、dtype、前 10 行、缺失和选择阈值。
- `reports/store_candidates.csv`: 898 家门店的候选统计和排序。
- `reports/selected_skus.csv`: 最终 5 个 SKU 的汇总与选择理由。
- `reports/final_validation.txt`: 最终数据质量与分布检查。

## 复现

项目内的 `.python-deps` 可保存本地分析所需的 Parquet 引擎：

```bash
PYTHONPATH=.python-deps python scripts/analyze_freshretail.py
PYTHONPATH=.python-deps python scripts/build_freshretail_mvp.py
```

第二个脚本会重新生成 CSV/Parquet，并执行键唯一性、缺失值、数值范围、汇总对账和格式回读检查。

## API 与部署构建

API 运行和测试所需依赖由 `requirements.txt` 管理。SQLite 数据库是部署时生成文件，不提交到 Git：

```bash
pip install -r requirements.txt
python scripts/build_inventory_db.py
python -m unittest discover -s tests -v
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Render Build Command：

```bash
pip install -r requirements.txt && python scripts/build_inventory_db.py
```

Render Start Command：

```bash
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```
