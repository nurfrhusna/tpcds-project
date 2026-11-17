"""Typed, duplicate-preserving comparisons copied from the verified M2 checks."""
import datetime
import decimal
import math

def cells_equal(left, right):
    if left is None or right is None:
        return left is right
    numeric = (int, float, decimal.Decimal)
    if isinstance(left, numeric) and isinstance(right, numeric):
        if isinstance(left, float) or isinstance(right, float):
            return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)
        return decimal.Decimal(left) == decimal.Decimal(right)
    return left == right

def rows_equal(left, right):
    return len(left) == len(right) and all(cells_equal(a, b) for a, b in zip(left, right))

def compare_bags(left, right):
    # Results are small; retain duplicates and compare numeric cells with tolerance.
    remaining = list(right)
    missing = []
    for row in left:
        match = next((i for i, other in enumerate(remaining) if rows_equal(row, other)), None)
        if match is None:
            missing.append(row)
        else:
            remaining.pop(match)
    return {"equal": not missing and not remaining,
            "missing_count": len(missing), "extra_count": len(remaining),
            "first_missing": missing[:1], "first_extra": remaining[:1]}

def decode_value(value, dtype):
    if value is None:
        return None
    if "DECIMAL" in dtype:
        return decimal.Decimal(str(value))
    if dtype in ("DOUBLE", "FLOAT", "REAL"):
        return float(value)
    if "INT" in dtype:
        return int(value)
    if dtype == "DATE":
        return datetime.date.fromisoformat(value)
    # FixedString pads ClickHouse values with NUL; generated text has no NULs.
    return value.rstrip("\x00") if isinstance(value, str) else value

