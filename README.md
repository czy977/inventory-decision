# Inventory Risk & Replenishment Decision Copilot

基于 FreshRetailNet-50K 数据集构建的库存缺货风险与补货决策项目。

项目利用历史销售与缺货数据动态估计近期需求，并结合模拟的当前库存与补货提前期，计算库存覆盖情况、缺货风险和补货优先级。

## 项目流程

```text

FreshRetailNet 历史数据

        ↓

SQLite

        ↓

需求估计

        ↓

库存覆盖计算

        ↓

缺货风险与补货优先级判断

        ↓

FastAPI

        ↓

Render

        ↓

Dify

        ↓

自然语言库存决策 Copilot

```

## 技术栈

- Python

- SQLite

- FastAPI

- Unit Test

- Render

- Dify

## 项目结构

```text

api/        FastAPI 接口

src/        核心业务逻辑

scripts/    数据处理与数据库构建

tests/      自动测试

reports/    数据分析与验证结果

docs/       数据字段与口径说明

```

## 本地运行

安装依赖：

```bash

pip install -r requirements.txt

```

构建 SQLite 数据库：

```bash

python scripts/build_inventory_[db.py](http://db.py)

```

运行测试：

```bash

python -m unittest discover -s tests -v

```

启动 API：

```bash

uvicorn api.main:app --host 0.0.0.0 --port 8000

```

## API

```text

GET /health

GET /replenishment-decision?sku_id=851&as_of_date=2024-06-25

```

## 数据说明

历史销售与缺货数据来源于 FreshRetailNet-50K。

`lead_time_days` 和 `current_inventory` 为项目中构造的模拟运营参数，不属于原始数据集。

由于原始数据中的销量经过归一化处理，因此项目中的需求和库存计算均基于统一的 normalized scale，不解释为真实商品件数。

