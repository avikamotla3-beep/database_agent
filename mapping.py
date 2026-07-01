import re
import json
import sys


def parse_sql_to_mapping(sql_file_path, output_path='mapping.json'):
    """
    Parse MySQL SQL dump and build a relational graph (tables + columns as nodes,
    FOREIGN KEY edges) for EVERY table in the dump.

    Output schema (matches the original 5-table format):
      {
        "database": "enveu_flow_db",
        "nodes": [
          {"id": "t1",  "properties": {"name": "<table>"}},
          {"id": "c1",  "properties": {"name": "<column>"}},
          ...
        ],
        "edges": [
          {"source": "t1", "target": "c1"},   # table -> its column
          {"source": "cX", "target": "cY"},   # FK column -> referenced column
          ...
        ]
      }
    """

    # Read SQL file (try multiple encodings)
    sql_content = None
    for enc in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            with open(sql_file_path, 'r', encoding=enc) as f:
                sql_content = f.read()
            print(f"[OK] Read SQL file with encoding: {enc}")
            break
        except Exception:
            continue

    if sql_content is None:
        with open(sql_file_path, 'rb') as f:
            sql_content = f.read().decode('utf-8', errors='replace')
        print("[OK] Read SQL file with fallback decoding")

    # Match every CREATE TABLE block (any ENGINE, not just InnoDB)
    pattern = r'CREATE TABLE `(\w+)` \((.*?)\) ENGINE=[^;]+;'
    matches = re.findall(pattern, sql_content, re.DOTALL)

    # Parse every table found in the dump
    tables = {}
    table_order = []

    for table_name, columns_block in matches:
        lines = [line.strip() for line in columns_block.split('\n') if line.strip()]
        columns = []
        constraints = []

        for line in lines:
            line = line.strip().rstrip(',')
            if not line:
                continue

            # Column definition line: `col_name` <type> ...
            if line.startswith('`') and not any(
                line.startswith(k) for k in ['KEY', 'PRIMARY', 'UNIQUE', 'CONSTRAINT']
            ):
                col_match = re.match(r'`(\w+)`\s+(.+)', line)
                if col_match:
                    columns.append({'name': col_match.group(1), 'definition': col_match.group(2)})

            # FOREIGN KEY constraint
            elif 'FOREIGN KEY' in line:
                fk_match = re.search(
                    r'CONSTRAINT `([^`]+)` FOREIGN KEY \(`([^`]+)`\) REFERENCES `(\w+)` \(`([^`]+)`\)',
                    line
                )
                if fk_match:
                    constraints.append({
                        'type': 'FOREIGN_KEY',
                        'column': fk_match.group(2),
                        'ref_table': fk_match.group(3),
                        'ref_column': fk_match.group(4)
                    })

        tables[table_name] = {'columns': columns, 'constraints': constraints}
        table_order.append(table_name)

    # Build nodes (tables + columns) and edges (table->column, column->column FKs)
    nodes = []
    edges = []

    t_id = 1
    c_id = 1

    table_id_map = {}
    column_id_map = {}

    # 1) Tables first, then all their columns (preserve original ordering)
    for table_name in table_order:
        table_data = tables[table_name]

        t_key = f"t{t_id}"
        table_id_map[table_name] = t_key
        nodes.append({"id": t_key, "properties": {"name": table_name}})
        t_id += 1

        for col in table_data['columns']:
            c_key = f"c{c_id}"
            column_id_map[f"{table_name}.{col['name']}"] = c_key
            nodes.append({"id": c_key, "properties": {"name": col['name']}})
            c_id += 1

    # 2) Edges: table -> column (containment) and FK column -> referenced column
    for table_name in table_order:
        table_data = tables[table_name]
        t_key = table_id_map[table_name]

        for col in table_data['columns']:
            c_key = column_id_map[f"{table_name}.{col['name']}"]
            edges.append({"source": t_key, "target": c_key})

        for constraint in table_data['constraints']:
            if constraint['type'] == 'FOREIGN_KEY' and constraint['ref_table'] in tables:
                src = column_id_map.get(f"{table_name}.{constraint['column']}")
                tgt = column_id_map.get(f"{constraint['ref_table']}.{constraint['ref_column']}")
                if src and tgt:
                    edges.append({"source": src, "target": tgt})

    mapping = {
        "database": "enveu_flow_db",
        "total_tables": len(table_order),
        "nodes": nodes,
        "edges": edges
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2)

    # Summary
    print("\n" + "=" * 60)
    print("MAPPING.JSON GENERATED SUCCESSFULLY (ALL TABLES)")
    print("=" * 60)
    print(f"\n[Output]       {output_path}")
    print(f"[Tables]       {len(table_order)}")
    print(f"[Table nodes]  {len(table_id_map)}")
    print(f"[Column nodes] {len(column_id_map)}")
    print(f"[Total nodes]  {len(nodes)}")
    print(f"[Total edges]  {len(edges)}")

    fk_edges = [e for e in edges if e['source'].startswith('c') and e['target'].startswith('c')]
    contain_edges = [e for e in edges if e['source'].startswith('t')]
    print(f"  - table->column (containment): {len(contain_edges)}")
    print(f"  - column->column (FK):         {len(fk_edges)}")

    print("\nTables processed:")
    for i, t in enumerate(table_order, 1):
        n_cols = len(tables[t]['columns'])
        n_fks = sum(1 for c in tables[t]['constraints'] if c['type'] == 'FOREIGN_KEY')
        print(f"   {i:>3}. {t} ({n_cols} cols, {n_fks} FKs)")
    print("=" * 60)

    return mapping


if __name__ == "__main__":
    sql_file = sys.argv[1] if len(sys.argv) > 1 else "Dump20260412 (1).sql"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "mapping.json"
    parse_sql_to_mapping(sql_file, output_file)
