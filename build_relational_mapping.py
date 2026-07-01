"""
Build relational_mapping.json for ALL tables in the SQL dump.

Reuses the same JSON shape as the original 5-table file:
- schema_version
- database
- tables_analyzed
- total_tables_in_dump
- entity_relationship_diagram (nodes + edges)
- relationships (explicit FK + implicit _id matches)
- table_details (per-table columns + in/out relationships)
"""

import json
import re
from pathlib import Path

SQL_FILE = "Dump20260412 (1).sql"
OUTPUT_FILE = "relational_mapping.json"
DB_NAME = "enveu_flow_db"


def read_sql(path: str) -> str:
    for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def parse_dump(sql: str):
    create_re = re.compile(
        r"CREATE TABLE `([^`]+)`\s*\((.*?)\)\s*ENGINE=[^;]+;",
        re.DOTALL | re.IGNORECASE,
    )
    fk_re = re.compile(
        r"CONSTRAINT `([^`]+)`\s+FOREIGN KEY\s*\(`([^`]+)`\)\s+"
        r"REFERENCES\s+`([^`]+)`\s*\(`([^`]+)`\)",
        re.IGNORECASE,
    )
    pk_re = re.compile(r"PRIMARY KEY\s*\(([^)]+)\)", re.IGNORECASE)
    col_re = re.compile(r"^`([^`]+)`\s+([^,]+)", re.IGNORECASE)

    tables: dict[str, dict] = {}
    order: list[str] = []

    for tbl_match in create_re.finditer(sql):
        name = tbl_match.group(1)
        body = tbl_match.group(2)
        order.append(name)

        columns = []
        explicit_fks: list[dict] = []
        pk_cols: list[str] | None = None

        for raw_line in body.split("\n"):
            line = raw_line.strip().rstrip(",").strip()
            if not line:
                continue

            # PK
            pk_match = pk_re.match(line)
            if pk_match:
                pk_cols = [c.strip().strip("`") for c in pk_match.group(1).split(",")]
                continue

            # FK constraint
            fk_match = fk_re.search(line)
            if fk_match:
                explicit_fks.append({
                    "constraint_name": fk_match.group(1),
                    "from_columns": [fk_match.group(2)],
                    "to_table": fk_match.group(3),
                    "to_columns": [fk_match.group(4)],
                })
                continue

            # Skip non-column lines
            if line.upper().startswith(("KEY ", "UNIQUE KEY", "INDEX", "FULLTEXT", "SPATIAL", "CONSTRAINT")):
                continue

            # Column definition
            col_match = col_re.match(line)
            if col_match:
                columns.append({
                    "col_name": col_match.group(1),
                    "data_type": col_match.group(2).strip(),
                })

        if pk_cols and len(pk_cols) == 1:
            pk = pk_cols[0]
        else:
            pk = pk_cols  # None or composite list

        tables[name] = {
            "table_name": name,
            "primary_key": pk,
            "columns": columns,
            "explicit_fks": explicit_fks,
        }

    return tables, order


def infer_implicit_fks(tables: dict[str, dict]) -> list[dict]:
    """
    Infer relationships from column naming patterns:

    1. `<singular>_id` -> `<table_name>` (e.g. `user_id` -> `users` not found;
       works when the singular form exists as a table name)
    2. Column whose name matches a target table's primary key column name
       (e.g. `tenant_id` -> `tenants.tenant_id`, `plugin_id` -> `plugins.plugin_id`)
    """
    inferred: list[dict] = []
    table_names = set(tables.keys())
    pk_by_name: dict[str, tuple[str, str]] = {}
    for tname, src in tables.items():
        pk = src.get("primary_key")
        if isinstance(pk, str):
            pk_by_name[pk] = (tname, pk)

    for src_name, src in tables.items():
        pk = src.get("primary_key")
        for col in src["columns"]:
            cn = col["col_name"]
            if cn == pk or cn == "id":
                continue

            target = None
            target_col = "id"

            # Pattern 1: column endswith `_id` and singular table exists
            if cn.endswith("_id"):
                singular = cn[:-3]
                if singular in table_names and singular != src_name:
                    target = singular

            # Pattern 2: column name exactly matches a PK column of some table
            if not target and cn in pk_by_name:
                t, c = pk_by_name[cn]
                if t != src_name:
                    target = t
                    target_col = c

            if not target:
                continue

            inferred.append({
                "from_table": src_name,
                "from_columns": [cn],
                "to_table": target,
                "to_columns": [target_col],
                "constraint_name": None,
                "via": "COLUMN NAMING PATTERN",
            })
    return inferred


def build_edges(relationships: list[dict]) -> list[dict]:
    edges = []
    for i, rel in enumerate(relationships, 1):
        rel_type = "N:1" if rel["via"] == "FOREIGN KEY" else "N:1 (implicit)"
        edges.append({
            "id": f"edge_{i}",
            "source": rel["from_table"],
            "target": rel["to_table"],
            "label": rel_type,
            "source_columns": rel["from_columns"],
            "target_columns": rel["to_columns"],
            "relationship_type": rel_type,
            "description": (
                f"Each row in '{rel['from_table']}' references one row in '{rel['to_table']}'"
                if rel["via"] == "FOREIGN KEY"
                else f"Column '{rel['from_columns'][0]}' suggests relationship to '{rel['to_table']}'"
            ),
        })
    return edges


def build_table_details(tables: dict[str, dict], relationships: list[dict]) -> list[dict]:
    out: list[dict] = []
    outgoing_by_table: dict[str, list[dict]] = {}
    incoming_by_table: dict[str, list[dict]] = {}

    for rel in relationships:
        outgoing_by_table.setdefault(rel["from_table"], []).append(rel)
        incoming_by_table.setdefault(rel["to_table"], []).append(rel)

    for name, src in tables.items():
        out.append({
            "table_name": name,
            "primary_key": src["primary_key"],
            "column_count": len(src["columns"]),
            "columns": [
                {"col_name": c["col_name"], "data_type": c["data_type"], "description": ""}
                for c in src["columns"]
            ],
            "outgoing_relationships": [
                {
                    "to_table": r["to_table"],
                    "via_columns": r["from_columns"],
                    "relationship_type": "N:1" if r["via"] == "FOREIGN KEY" else "N:1 (implicit)",
                    "description": (
                        f"Each row in '{r['from_table']}' references one row in '{r['to_table']}'"
                        if r["via"] == "FOREIGN KEY"
                        else f"Column '{r['from_columns'][0]}' suggests relationship to '{r['to_table']}'"
                    ),
                }
                for r in outgoing_by_table.get(name, [])
            ],
            "incoming_relationships": [
                {
                    "from_table": r["from_table"],
                    "via_columns": r["from_columns"],
                    "relationship_type": "N:1" if r["via"] == "FOREIGN KEY" else "N:1 (implicit)",
                    "description": (
                        f"Each row in '{r['from_table']}' references one row in '{r['to_table']}'"
                        if r["via"] == "FOREIGN KEY"
                        else f"Column '{r['from_columns'][0]}' suggests relationship to '{r['to_table']}'"
                    ),
                }
                for r in incoming_by_table.get(name, [])
            ],
        })
    return out


def main() -> None:
    sql = read_sql(SQL_FILE)
    tables, order = parse_dump(sql)

    # 1. Explicit FKs
    relationships: list[dict] = []
    for name, src in tables.items():
        for fk in src["explicit_fks"]:
            relationships.append({
                "from_table": name,
                "from_columns": fk["from_columns"],
                "to_table": fk["to_table"],
                "to_columns": fk["to_columns"],
                "constraint_name": fk["constraint_name"],
                "relationship_type": "N:1",
                "cardinality": f"Many {name} rows -> One {fk['to_table']}",
                "via": "FOREIGN KEY",
                "description": f"Each row in '{name}' references one row in '{fk['to_table']}'",
            })

    # 2. Implicit _id relationships
    explicit_keys = {
        (r["from_table"], tuple(r["from_columns"])) for r in relationships
    }
    for inf in infer_implicit_fks(tables):
        key = (inf["from_table"], tuple(inf["from_columns"]))
        if key in explicit_keys:
            continue
        relationships.append({
            "from_table": inf["from_table"],
            "from_columns": inf["from_columns"],
            "to_table": inf["to_table"],
            "to_columns": inf["to_columns"],
            "constraint_name": None,
            "relationship_type": "N:1 (implicit)",
            "cardinality": f"Many {inf['from_table']} rows -> One {inf['to_table']}",
            "via": "COLUMN NAMING PATTERN",
            "description": f"Column '{inf['from_columns'][0]}' suggests relationship to '{inf['to_table']}'",
        })

    # 3. Build final structure
    erd_nodes = [
        {
            "id": name,
            "label": name,
            "column_count": len(tables[name]["columns"]),
            "primary_key": tables[name]["primary_key"],
        }
        for name in order
    ]
    erd_edges = build_edges(relationships)
    table_details = build_table_details(tables, relationships)

    result = {
        "schema_version": "1.0",
        "database": DB_NAME,
        "tables_analyzed": order,
        "total_tables_in_dump": len(order),
        "entity_relationship_diagram": {
            "nodes": erd_nodes,
            "edges": erd_edges,
        },
        "relationships": relationships,
        "table_details": table_details,
    }

    Path(OUTPUT_FILE).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    explicit_count = sum(1 for r in relationships if r["via"] == "FOREIGN KEY")
    implicit_count = sum(1 for r in relationships if r["via"] == "COLUMN NAMING PATTERN")

    print("=" * 60)
    print(f"RELATIONAL MAPPING GENERATED: {OUTPUT_FILE}")
    print("=" * 60)
    print(f"[Tables]          {len(order)}")
    print(f"[Relationships]   {len(relationships)}")
    print(f"  - Explicit FKs: {explicit_count}")
    print(f"  - Implicit _id: {implicit_count}")
    print(f"[ERD nodes]       {len(erd_nodes)}")
    print(f"[ERD edges]       {len(erd_edges)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
