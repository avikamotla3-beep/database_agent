"""
Adapter for your schema_extractor.py
Ensures output matches the expected schema format.
"""

import sys
from pathlib import Path
tools_dir = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_dir))

try:
    import schema_extractor as se
except ImportError:
    se = None


def extract_from_dump(dump_path: str) -> Dict[str, Any]:
    if se is None:
        raise ImportError("schema_extractor.py not found in Python path")
    
    extractor = se.MySQLSchemaExtractor(dump_path)
    raw_schema = extractor.extract_schema()
    
    # If already in correct format, return as-is
    if isinstance(raw_schema, dict) and "tables" in raw_schema:
        raw_schema["source"] = dump_path
        return raw_schema
    
    # If it's a flat dict of table names -> strings, wrap it
    normalized = {
        "source": dump_path,
        "extracted_at": None,
        "tables": {},
        "relationships": []
    }
    
    for table_name, table_data in raw_schema.items():
        if isinstance(table_data, dict):
            # Already parsed properly
            normalized["tables"][table_name] = {
                "name": table_name,
                "description": table_data.get("description", ""),
                "columns": [
                    {
                        "name": col["name"] if isinstance(col, dict) else str(col),
                        "type": col.get("type", "UNKNOWN") if isinstance(col, dict) else "UNKNOWN",
                        "nullable": col.get("nullable", True) if isinstance(col, dict) else True,
                        "description": col.get("description", "") if isinstance(col, dict) else "",
                    }
                    for col in table_data.get("columns", [])
                ],
                "primary_key": table_data.get("primary_key", []),
                "foreign_keys": table_data.get("foreign_keys", []),
            }
            for fk in table_data.get("foreign_keys", []):
                normalized["relationships"].append({
                    "from_table": table_name,
                    "from_column": fk["column"] if isinstance(fk, dict) else fk,
                    "to_table": (fk["references"].split(".")[0] if isinstance(fk, dict) and "." in fk.get("references", "") else "unknown"),
                    "to_column": (fk["references"].split(".")[1] if isinstance(fk, dict) and "." in fk.get("references", "") else "id"),
                    "type": "many-to-one"
                })
        else:
            # Fallback: table_data is a string or simple value
            normalized["tables"][table_name] = {
                "name": table_name,
                "description": str(table_data) if not isinstance(table_data, dict) else "",
                "columns": [],
                "primary_key": [],
                "foreign_keys": [],
            }
    
    return normalized