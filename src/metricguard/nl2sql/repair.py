"""Turn engine errors into structured, actionable feedback.

Only one class of issue is auto-fixed (missing LIMIT). Anything that would
change the meaning of the query -- missing time filter, wrong column -- is
returned as a hint for the caller to decide.
"""

from __future__ import annotations

import re

MAX_ROWS = 1000


def classify(error: str) -> tuple[str, str]:
    text = error.lower()

    if "parser error" in text:
        return "syntax_error", "SQL 语法错误：检查括号、关键字与引号配对"
    if "does not exist" in text:
        match = re.search(r'"([^"]+)" does not exist', error)
        name = match.group(1) if match else "?"
        return "unknown_identifier", f"标识符 {name} 不存在：可用表 members/orders/order_items/products/behaviors"
    if "binder error" in text:
        return "binding_error", "字段类型或引用不匹配：检查 JOIN 条件与列名"
    if "conversion error" in text:
        return "type_error", "类型转换失败：时间字段需 CAST(... AS DATE)"
    if "out of memory" in text:
        return "resource_limit", "查询超出内存限制：缩小时间范围或先聚合"
    return "execution_error", "执行失败：检查 SQL 语义"


def auto_fix(sql: str, finding_codes: list[str]) -> tuple[str, list[str]]:
    fixes: list[str] = []
    if "unbounded_scan" in finding_codes:
        sql = sql.rstrip().rstrip(";") + f" LIMIT {MAX_ROWS}"
        fixes.append(f"appended LIMIT {MAX_ROWS}")
    return sql, fixes
