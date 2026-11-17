"""Minimal dialect changes used by the verified M2 reference check."""
import re

def portable_sql(number, sql):
    sql = re.sub(r"(?m)^\s*--.*$", "", sql).strip()
    changes = []
    if number == 31:
        sql = sql.replace("AS Float64", "AS DOUBLE")
        changes.append("Float64 -> DOUBLE; retain floating-point division")
    if number == 47:
        # In standard SQL the outer query sees v2, not v1 inside its CTE.
        head, tail = sql.rsplit("FROM v2", 1)
        sql = head + "FROM v2" + tail.replace("v1.", "v2.")
        changes.append("Outer-query v1 qualifiers -> v2; no predicate changes")
    if number == 82:
        sql = re.sub(r"CAST\('([^']+)',\s*'date'\)", r"CAST('\1' AS DATE)", sql)
        changes.append("ClickHouse CAST(value, 'date') -> SQL CAST(value AS DATE)")
    return sql, changes
