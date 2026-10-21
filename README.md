# metricguard

指标口径校验和问数网关。把自然语言查数拆成固定的几步：

```
问题 → 语义层匹配 → SQL 编译 → AST 策略审查 → 口径核对 → 沙箱执行 → 脱敏 → 审计
```

```bash
pip install -e ".[dev]"
metricguard ask "9月复购率按渠道"
```

不需要模型，也不需要 API key。严格模式下的 SQL 由指标编译器生成，结果确定、可复算。

---

## 背景

企业不敢把自助取数开放给业务，常见的原因有这几个：

| 事故 | 常见做法 | metricguard |
|---|---|---|
| 同一个"复购率"每次算法不同 | 在 prompt 里描述口径 | 指标写进 YAML 契约，SQL 由编译器生成；自由 SQL 也要过口径核对 |
| 一句"导出会员手机号"就把 PII 带走 | 让模型"注意隐私" | AST 检测敏感列，执行前拒绝；返回层再做一次掩码 |
| 结果错了不知道哪一步错 | 打日志 | 每个请求一条审计：SQL、AST 判定、行数、耗时、脱敏列、调用者 |

---

## 两种模式

### strict：不让模型写 SQL

```bash
metricguard ask "9月复购率按渠道"
```

```
通过 repurchase_rate_90d · strict · pass
整体值：0.1310
┌────────┬────────┐
│ k      │ v      │
├────────┼────────┤
│ 门店   │ 0.1374 │
│ 天猫   │ 0.1370 │
│ 京东   │ 0.1291 │
└────────┴────────┘
维度 channel 不适用于 repurchase_rate_90d，改用 register_channel
```

- 问题先匹配已注册的指标，匹配不到就拒绝，不做猜测
- 维度不支持时先找同义候选（渠道 → 注册渠道），仍不支持则回退并说明
- 分组结果会额外计算一次整体值，不会拿某个分组冒充总数

### exploratory：允许写 SQL，但要过审查

```bash
metricguard ask "导出手机号" --mode exploratory \
  --sql "SELECT member_id, phone FROM members WHERE ..."
```

```
拒绝 policy_blocked:pii_column,unbounded_scan
  hint: pii_column: 列 phone 属于敏感字段
```

---

## AST 策略

| 规则 | 拦截什么 |
|---|---|
| `not_read_only` | INSERT / UPDATE / DELETE / DROP / ALTER / CREATE |
| `multi_statement` | 分号拼接的第二条语句 |
| `table_not_allowed` | 表白名单之外的表（CTE 别名不算表） |
| `select_star` | `SELECT *`（`COUNT(*)` 不算） |
| `pii_column` | phone / id_card / address / email / real_name |
| `join_without_condition` | 缺 ON/USING 的 JOIN、CROSS JOIN |
| `missing_time_filter` | 没有时间谓词的查询 |
| `unbounded_scan` | 既无 LIMIT 又无聚合 |

其中 `unbounded_scan` 会自动修复（追加 `LIMIT 1000`）并记入审计。其余规则一律拒绝。

---

## 评测

```bash
python evals/run.py
```

40 个用例（2026-10-21 实跑）：

| 指标 | 值 |
|---|---|
| 用例通过率 | 40/40 (100%) |
| 严格模式通过 | 22/22 |
| 对抗拦截率 | 10/10 |
| 合法查询误拒 | 0 |
| PII 泄露 | 0 |
| 自动修复触发 | 1 |

对抗集覆盖手机号、身份证、`SELECT *`、DELETE、UPDATE、DROP、多语句、缺时间过滤、越权表、无 ON 的 JOIN。

```bash
python -m pytest    # 40 passed
```

---

## 快速开始

```bash
pip install -e ".[dev]"

metricguard catalog                  # 12 个已注册指标
metricguard ask "9月客单价按渠道"
metricguard ask "9月退货率按品类"
metricguard ask "预测明年增长"        # 拒绝：未注册指标
metricguard audit --tail 5           # 审计日志

metricguard serve --port 8134        # Web 界面
```

也可以直接调 API：

```bash
curl -X POST http://127.0.0.1:8134/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"9月客单价按渠道","mode":"strict"}'
```

---

## 设计取舍

strict 模式不让模型写 SQL，是因为口径一致性靠结构保证更稳。模板编译的结果不会漂移。模型生成即使做到 99%，剩下 1% 的口径偏差在企业里也是事故。

exploratory 模式保留下来，是因为真实分析有大量探索性需求，全都塞进指标目录不现实。折中方案是：探索可以自由写 SQL，但必须过同一套 AST 策略和口径核对，结果标注"非注册指标"。

口径核对不做 SQL 等价性证明。等价性在一般情况下不可判定，假装能做只会给人虚假的安全感。这里只核对聚合函数集合和必需过滤条件（比如剔除退款），文档里也写明这是弱核对。

PII 在执行前就拦，是因为提示词管不住 `SELECT phone`。执行前的 AST 拒绝是唯一可靠的位置，返回层掩码只是第二道。

---

## 目录

```
metricguard/
├── catalog/metrics/*.yml      # 12 个指标契约（分子/分母/维度/版本）
├── src/metricguard/
│   ├── catalog/               # 契约模型 + 加载器 + SQL 编译器
│   ├── policy/                # AST 策略 + PII 掩码
│   ├── nl2sql/                # 问题匹配 / 口径核对 / 错误分类
│   ├── exec/                  # 只读 DuckDB + 行数上限
│   ├── audit/                 # JSONL 审计
│   ├── gateway.py             # 主链路
│   ├── api.py  cli.py
│   └── web/index.html
├── data/fixtures/             # 合成数据（8,000 会员 / 23,697 订单）
├── evals/                     # 40 个用例 + 报告
├── tests/                     # 40 个测试
└── docs/                      # 口径 / 安全 / 决策记录
```

---

## 边界

- 数据全部为合成数据（见 `docs/DATA_ASSUMPTIONS.md`），含虚构的手机号和证件号，仅用于演示 PII 拦截
- 严格模式的指标编译是确定性的；exploratory 模式不接模型，SQL 由调用方提供（接入点见 `docs/ARCHITECTURE.md`）
- 口径核对是弱核对，不能证明任意两条 SQL 等价
- 单进程、无并发控制；DuckDB 内存模式，不适合生产规模

## License

MIT
