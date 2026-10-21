"""Column-level masking, applied on the way out.

Masking belongs at the response boundary, not in the prompt and not in the
model's judgement -- anything the model can see can be repeated.
"""

from __future__ import annotations

from typing import Any

SENSITIVE = {"phone", "id_card", "address", "email", "real_name", "name"}


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}****{digits[-4:]}"


def mask_id_card(value: str) -> str:
    text = str(value)
    if len(text) < 8:
        return "***"
    return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"


def mask_generic(value: Any) -> str:
    text = str(value)
    if len(text) <= 2:
        return "**"
    return f"{text[0]}{'*' * max(1, len(text) - 2)}{text[-1]}"


def mask_value(column: str, value: Any) -> Any:
    if value is None:
        return None
    key = column.lower()
    if key == "phone":
        return mask_phone(str(value))
    if key == "id_card":
        return mask_id_card(str(value))
    if key in SENSITIVE:
        return mask_generic(value)
    return value


def mask_rows(rows: list[dict], columns: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Return (masked_rows, masked_column_names)."""
    if not rows:
        return rows, []
    cols = columns or list(rows[0].keys())
    sensitive_hit = [c for c in cols if c.lower() in SENSITIVE]
    if not sensitive_hit:
        return rows, []
    out = []
    for row in rows:
        out.append({k: (mask_value(k, v) if k.lower() in SENSITIVE else v) for k, v in row.items()})
    return out, sensitive_hit
