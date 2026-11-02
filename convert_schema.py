
import re
from pathlib import Path

source = Path("create_tables.sql")
output = Path("create_tables_nullable.sql")

sql = source.read_text(encoding="utf-8-sig")

# Match the column definitions used in our TPC-DS schema.
column_pattern = re.compile(
    r"^(\s*[A-Za-z_]\w*\s+)"
    r"(UInt32|Int64|Decimal\(\d+,\s*\d+\)|FixedString\(\d+\)|String|Date)"
    r"(\s+NOT\s+NULL)?"
    r"(\s*,\s*)$",
    re.MULTILINE | re.IGNORECASE,
)

converted = 0

def convert_column(match):
    global converted

    prefix, data_type, not_null, ending = match.groups()

    # Keep required columns unchanged.
    if not_null:
        return match.group(0)

    converted += 1
    return f"{prefix}Nullable({data_type}){ending}"

updated_sql = column_pattern.sub(convert_column, sql)

if converted == 0:
    raise RuntimeError("No columns converted. Check the source SQL format.")

output.write_text(updated_sql, encoding="utf-8")

print(f"Converted {converted} optional columns.")
print(f"Created: {output}")
print("Existing database tables were not modified.")
