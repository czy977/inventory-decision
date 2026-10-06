# Inventory Risk & Replenishment Decision Copilot

基于 FreshRetailNet-50K 构建的库存风险与补货决策 Copilot。

项目结合历史销售与缺货数据、模拟库存状态和补货提前期，通过确定性的 Python 决策后端计算库存覆盖、缺货风险和补货优先级；Dify 负责自然语言理解、意图路由、知识检索、What-if 场景编排和结果解释。

核心设计原则：

> LLM 负责理解和解释，核心业务决策由 deterministic Python backend 计算，避免由模型直接猜测风险和补货结果。

---

## 项目架构

```text
用户自然语言
      ↓
Dify Intent Classification
      ↓
 ┌───────────────┬───────────────┬───────────────┐
 ↓               ↓               ↓
Decision Query   Policy Query     Scenario Query
 ↓               ↓               ↓
参数提取          RAG              Scenario 参数提取
 ↓                               ↓
FastAPI                         Scenario API
 ↓                               ↓
Python Decision Backend         Baseline + Override
 ↓                               ↓
API Result ───────────────┐
                          ↓
                     RAG Policy
                          ↓
                     LLM 结果解释
                          ↓
                        用户
```

后端部署链路：

```text
GitHub
  ↓
Vercel
  ↓
FastAPI
  ↓
SQLite
  ↓
Python Decision Engine
```

---

## 核心能力

### 1. Decision Query

用户可以查询指定 SKU 在某个 `as_of_date` 下的库存风险，例如：

```text
帮我看看 SKU 851 在 2024 年 6 月 25 日有没有缺货风险。
```

系统返回：

- 需求估计与置信度
- 预计可供应天数
- 库存覆盖缺口
- 缺货风险等级
- 补货优先级
- 是否需要人工复核

支持：

```text
Low Risk    → P3
Medium Risk → P2
High Risk   → P1
Insufficient Data → Manual Review
```

---

### 2. Policy Query

用户可以直接询问系统中的业务规则，例如：

```text
P1、P2、P3 分别代表什么？
为什么 14 天数据不足时要扩展到 30 天？
什么情况下需要 Manual Review？
normalized scale 是什么意思？
为什么需求估计不能使用 as_of_date 当天的数据？
```

这类问题由 RAG Knowledge Base 提供规则说明，不需要调用库存决策 API。

---

### 3. What-if Scenario

支持在不修改 baseline 数据的情况下，临时调整：

```text
lead_time_days
current_inventory
```

例如：

```text
如果 SKU 851 在 2024-06-25 的 lead time
从 2 天变成 5 天，风险会怎样？
```

Scenario 会：

```text
读取 Baseline
      ↓
保持同一 sku_id + as_of_date 的历史需求估计
      ↓
临时覆盖运营参数
      ↓
复用同一个 deterministic decision engine
      ↓
返回 Baseline 与 Scenario 对比结果
```

Scenario 不写回 SQLite，也不会修改正式 baseline state。

---

## 核心决策逻辑

库存覆盖关系：

```text
days_of_supply =
current_inventory / estimated_daily_demand

coverage_ratio =
days_of_supply / lead_time_days
```

风险规则：

```text
coverage_ratio >= 1.0
→ Low / P3

0.5 <= coverage_ratio < 1.0
→ Medium / P2

coverage_ratio < 0.5
→ High / P1
```

如果历史数据不足以形成可靠需求估计：

```text
→ Manual Review
```

当前阈值属于项目 MVP 阶段的 configurable business rules，不代表零售行业统一标准。

---

## 数据说明

历史销售与缺货数据来源于 FreshRetailNet-50K。

当前 MVP 使用：

```text
1 个门店
5 个 SKU
90 天历史数据
450 条销售记录
```

原始数据中的 `sale_amount` 已经过归一化处理，因此项目中的需求和库存计算均运行在统一的 normalized scale 上，不解释为真实商品件数。

以下运营参数为项目中构造的模拟数据：

```text
lead_time_days
current_inventory
```

---

## RAG 与 LLM 设计原则

知识库主要包含：

```text
knowledge/
├── inventory_policy.md
└── data_guardrails.md
```

覆盖：

- Risk / Priority Rules
- Manual Review
- Demand Confidence
- normalized scale
- 时间窗口与 `as_of_date`
- no look-ahead
- 数据口径与业务边界

系统遵循：

> API 返回结果是数值、需求置信度、风险等级、补货优先级和人工复核标记的唯一事实来源。

RAG 仅用于解释规则和数据口径，LLM 不重新计算、修改或覆盖后端决策结果。

---

## Evaluation

### Python Backend

当前自动测试结果：

```text
49 / 49 Passed
```

覆盖：

- Demand estimation
- Decision rules
- API
- Scenario logic
- Risk boundary
- What-if monotonicity
- Manual Review
- Baseline regression
- Scenario 不修改 SQLite

---

### Dify End-to-End Evaluation

建立固定的 15-case End-to-End Evaluation Set，覆盖：

- Intent Classification
- Decision Query
- Policy Query
- Mixed Query
- Scenario Query
- Missing Parameters
- Manual Review
- RAG Retrieval
- normalized scale
- API Error Handling
- LLM Grounding

第一轮结果：

```text
10 / 15 Passed
End-to-End Pass Rate = 66.7%
```

主要问题包括：

```text
Routing Failure
RAG Grounding
Unsupported Inference
Factual Drift
Workflow Parameter Handling
```

针对真实 failure 调整 Intent Classification、Knowledge Base、Workflow Routing、参数处理和 LLM Guardrails 后，使用同一固定测试集进行回归测试：

```text
15 / 15 Passed
End-to-End Pass Rate = 100%
```

该 100% 仅代表当前固定 15-case Regression Evaluation Set，不代表系统在所有未知输入上的泛化准确率。

---

## API

Health Check：

```text
GET /health
```

Baseline Decision：

```text
GET /replenishment-decision?sku_id=851&as_of_date=2024-06-25
```

Scenario Decision：

```text
POST /scenario-decision
```

API 已部署至 Vercel。

---

## 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

构建 SQLite：

```bash
python scripts/build_inventory_db.py
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

启动 FastAPI：

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

---

## 技术栈

```text
Python
SQLite
FastAPI
Vercel
Dify
RAG
LLM Workflow
Unit / Regression Testing
```
