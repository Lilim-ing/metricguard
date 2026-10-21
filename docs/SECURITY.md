# 安全模型

## 威胁模型

| 威胁 | 举例 | 防线 |
|---|---|---|
| 数据外带 | `SELECT phone FROM members` | AST 敏感列检测，执行前拒绝 |
| 破坏性操作 | `DELETE FROM orders` | 语句类型白名单 |
| 越权访问 | `SELECT * FROM secret_table` | 表白名单 |
| 全表拉取 | 无 WHERE、无 LIMIT | 时间过滤 + LIMIT/聚合强制 |
| 注入拼接 | 多语句、异常 JOIN | 单语句限制 + JOIN 条件检查 |
| 结果泄露 | 合法查询但返回敏感列 | 返回层掩码（第二道防线） |
| 事后抵赖 | "我没查过这个" | 每请求一条审计，含 SQL hash 与调用者 |

## 规则清单

| code | 级别 | 触发条件 |
|---|---|---|
| `not_read_only` | block | 出现 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/Command |
| `multi_statement` | block | 解析出多于一条语句 |
| `table_not_allowed` | block | 表名不在白名单（CTE 别名除外） |
| `select_star` | block | SELECT 列表出现 `*` 或 `alias.*` |
| `pii_column` | block | 引用 phone/id_card/address/email/real_name/name |
| `cartesian_join` | block | CROSS / OUTER JOIN |
| `join_without_condition` | block | JOIN 无 ON/USING |
| `missing_time_filter` | block | 无 order_time/register_date/event_time 谓词 |
| `unbounded_scan` | 可修复 | 无 LIMIT 且无聚合 → 自动追加 `LIMIT 1000` |
| `parse_error` | block | SQL 无法解析 |

## 已知局限（诚实列出）

1. **列名别名可以绕过 PII 检测**：`SELECT phone AS p FROM members` —— 当前规则检查 AST 列引用，别名不影响检测，仍然会命中 `phone`。但 `SELECT CONCAT(phone) FROM ...` 这类函数包裹也能被 `find_all(exp.Column)` 找到，暂未发现直接绕过。
2. **子查询里的敏感列**同样会被检出（`find_all` 递归遍历整棵树）。
3. **不做数据脱敏后的可用性保证**：掩码会破坏 `GROUP BY phone` 这类查询的语义，正确做法是禁止对敏感列分组，当前未实现。
4. **审计日志可被运行者删除**：本地文件没有防篡改机制。生产环境应写入不可变存储。
5. **不防 SQL 层面的资源耗尽**：只限制了返回行数，没有查询超时与扫描量预估。DuckDB 内存上限设为 512MB，属于粗粒度保护。

## 掩码规则

| 列 | 规则 | 示例 |
|---|---|---|
| phone | 前 3 + `****` + 后 4 | `138****5678` |
| id_card | 前 4 + `*` + 后 4 | `1101**********1234` |
| 其他敏感列 | 首尾字符 + 星号 | `张*三` |

掩码发生在**返回层**，数据库里仍是原值。这是刻意的：拦截靠 AST，脱敏靠返回层，两层独立，任何一层失效另一层仍在。
