import re
import json
from pathlib import Path


def parse_sql_to_schema_json(sql_content, db_name="enveu_flow_db"):
    """
    Parse MySQL SQL dump and extract schemas for ALL tables into handwritten JSON format.

    Args:
        sql_content: Raw SQL dump string
        db_name: Database name for description

    Returns:
        dict: Schema JSON in handwritten format containing every CREATE TABLE
    """

    # Match every CREATE TABLE ... ENGINE=...;
    create_table_pattern = re.compile(
        r'CREATE TABLE `([^`]+)`\s*\((.*?)\)\s*ENGINE=([^;]+);',
        re.DOTALL | re.IGNORECASE
    )

    all_tables = []

    for match in create_table_pattern.finditer(sql_content):
        table_name = match.group(1)
        columns_block = match.group(2)
        engine_info = match.group(3).strip()

        lines = [line.strip() for line in columns_block.split('\n') if line.strip()]

        columns = []
        primary_key = None

        for line in lines:
            line = line.rstrip(',').strip()

            if not line:
                continue

            # PRIMARY KEY detection
            pk_match = re.match(r'PRIMARY KEY\s*\(([^)]+)\)', line, re.IGNORECASE)
            if pk_match:
                pk_cols = pk_match.group(1).replace('`', '').split(',')
                primary_key = [c.strip() for c in pk_cols]
                continue

            # Skip indexes, constraints, foreign keys
            if re.match(r'(UNIQUE KEY|KEY|CONSTRAINT|INDEX|FULLTEXT|SPATIAL)', line, re.IGNORECASE):
                continue

            # Column definition: `col_name` datatype [constraints]
            col_match = re.match(r'`([^`]+)`\s+(\w+(?:\s*\(.*?\))?)\s*(.*)', line, re.DOTALL)
            if not col_match:
                continue

            col_name = col_match.group(1)
            data_type = col_match.group(2).upper().replace('  ', ' ').strip()

            data_type = re.sub(r'\s+', ' ', data_type)

            columns.append({
                "col_name": col_name,
                "data_type": data_type,
                "description": ""
            })

        # Handle primary key format
        if primary_key and len(primary_key) == 1:
            pk = primary_key[0]
        else:
            pk = primary_key  # None or list for composite

        all_tables.append({
            "table_name": table_name,
            "description": "",
            "primary_key": pk,
            "columns": columns
        })

    schema_json = {
        "database_name": db_name,
        "total_tables": len(all_tables),
        "tables": all_tables
    }

    return schema_json


# ─── MAIN EXECUTION ───

# CONFIG
SQL_FILE_PATH = 'Dump20260412 (1).sql'   # <-- Change to your .sql file path
DB_NAME = "enveu_flow_db"                  # <-- Your database name
OUTPUT_FILE = "schema.json"                # <-- Output JSON filename

# Read SQL file (try multiple encodings)
sql_content = None
for enc in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
    try:
        with open(SQL_FILE_PATH, 'r', encoding=enc) as f:
            sql_content = f.read()
        print(f"[OK] Read SQL file with encoding: {enc}")
        break
    except Exception:
        continue

if sql_content is None:
    with open(SQL_FILE_PATH, 'rb') as f:
        sql_content = f.read().decode('utf-8', errors='replace')
    print("[OK] Read SQL file with fallback decoding")

# Parse and generate schema JSON (ALL tables)
schema_json = parse_sql_to_schema_json(sql_content, db_name=DB_NAME)

# Save to JSON file
output_path = Path(OUTPUT_FILE)
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(schema_json, f, indent=2, ensure_ascii=False)

# Print summary
print("\n" + "=" * 60)
print("SCHEMA.JSON GENERATED SUCCESSFULLY (ALL TABLES)")
print("=" * 60)
print(f"\n[Output] {output_path.absolute()}")
print(f"[Tables in dump] {schema_json['total_tables']}")
print(f"[Tables extracted] {len(schema_json['tables'])}")

print("\nExtracted Tables:")
for i, t in enumerate(schema_json['tables'], 1):
    pk = t['primary_key'] if t['primary_key'] else 'None'
    print(f"   {i:>3}. {t['table_name']} ({len(t['columns'])} columns, PK: {pk})")

print(f"\n[Total columns] {sum(len(t['columns']) for t in schema_json['tables'])}")
print("=" * 60)
