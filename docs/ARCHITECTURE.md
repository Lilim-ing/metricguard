# 架构

## 请求生命周期

```
QueryRequest
   │
   ├─ strict ──────► matcher ──► MetricSpec ──► builders(编译 SQL)
   │                    │                          │
   │                    └─ 未命中 ──► 拒绝          │
   │                                               │
   └─ exploratory ──► 调用方提供 SQL ──────────────┤
                                                   ▼
                                          AST policy review
                                                   │
                                     ┌─────────────┴─────────────┐
                                     │ 不通过                     │ 通过
                                     ▼                            ▼
                              可修复？→ 补 LIMIT            definition check
                                     │                            │
                                     └─ 仍不通过 → 拒绝            ▼
                                                            DuckDB 执行
                                                                  │
                                                            返回层掩码
                                                                  │
                                                            审计落盘
                                                                  │
                                                             QueryResult
```

## 模块

| 模块 | 职责 | 不做 |
|---|---|---|
| `catalog/models.py` | 契约模型 + 请求/响应 | 不碰数据库 |
| `catalog/loader.py` | 加载 YAML、校验必填与重复 | 不生成 SQL |
| `catalog/builders.py` | 12 个指标 → SQL | 不执行 |
| `policy/ast_rules.py` | 语法树审查 | 不改写 SQL |
| `policy/pii.py` | 返回层掩码 | 不拦截 |
| `nl2sql/matcher.py` | 问题 → (指标, 维度, 窗口) | 不保证匹配正确 |
| `nl2sql/verifier.py` | 生成 SQL 与契约的弱核对 | 不证明等价 |
| `nl2sql/repair.py` | 错误分类 + 唯一自动修复 | 不改语义 |
| `exec/engine.py` | 只读执行 + 行数上限 | 不审批 |
| `audit/log.py` | 追加写审计 | 不防篡改 |
| `gateway.py` | 串起全链路 | 不含业务口径 |

## 关键不变量

| 不变量 | 位置 |
|---|---|
| 未注册指标在 strict 模式必须拒绝 | `gateway.ask` |
| 任何 SQL 在执行前必须过 AST | `gateway.ask` |
| 分组结果的整体值必须单独计算 | `gateway.ask` |
| 敏感列在返回前必须掩码 | `gateway.ask` |
| 每个请求必须落一条审计 | `gateway._finish` |
| YAML 与 builder 必须一一对应 | `Gateway.__init__` |

## 接入真实模型

当前 exploratory 模式的 SQL 由调用方提供，没有接模型。接入点很明确：

```python
# nl2sql/generator.py（未实现）
def generate(question: str, catalog_summary: list[dict], schema: dict) -> str:
    ...
```

生成的 SQL 走同一条 `gateway.ask(..., mode="exploratory", sql=...)`，因此 AST 策略、口径核对、脱敏、审计全部复用。这是刻意的：**模型是可选组件，治理是必选组件。**

## 接入真实数据

替换 `data/fixtures/*.parquet`，保持表结构；或替换 `exec/engine.py` 的连接方式。`policy/ast_rules.ALLOWED_TABLES` 需要同步调整。
