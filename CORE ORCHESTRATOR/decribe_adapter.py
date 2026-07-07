"""
Adapter for describe_schema_tool.py with Llama 3.2 integration.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, Any

tools_dir = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_dir))

try:
    import describe_schema_tool as dst
except ImportError:
    dst = None


class SchemaDescriber:
    """
    Enriches schema with business-facing descriptions using Llama 3.2.
    """

    def __init__(self, base_url: str = None):
        # Llama 3.2 via Ollama (local) or compatible OpenAI-compatible endpoint
        self.base_url = base_url or os.getenv("LLAMA_BASE_URL", "http://localhost:11434/v1")
        self.model = os.getenv("LLAMA_MODEL", "llama3.2")
        self.api_key = os.getenv("LLAMA_API_KEY", "ollama")  # Ollama uses dummy key

        try:
            from openai import OpenAI
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        except ImportError:
            self.client = None

    def enrich_schema(self, schema: Dict[str, Any],
                      model: str = None,
                      max_tokens: int = 4096) -> Dict[str, Any]:
        """
        Populate empty description fields in schema using Llama 3.2.
        Falls back to your existing describe_schema_tool.py if available.
        """
        if dst is not None:
            # Your tool has generate_table_desc and generate_column_desc
            tables = schema.get("tables", [])
            if isinstance(tables, dict):
                tables = tables.items()
            else:
                tables = [(t.get("name", f"table_{i}"), t) for i, t in enumerate(tables)]

            for table_name, table in tables:
                if not table.get("description"):
                    table["description"] = dst.generate_table_desc(table)
                for col in table.get("columns", []):
                    if not col.get("description"):
                        col["description"] = dst.generate_column_desc(col, table_name)
            return schema

        # Fallback: direct Llama 3.2 integration via Ollama/OpenAI-compatible API
        enriched = json.loads(json.dumps(schema))  # Deep copy
        tables = enriched.get("tables", {})
        if isinstance(tables, list):
            tables = {t.get("name", f"table_{i}"): t for i, t in enumerate(tables)}

        for table_name, table in tables.items():
            if not table.get("description"):
                table["description"] = self._describe_table(table_name, table)

            for col in table.get("columns", []):
                if not col.get("description"):
                    col["description"] = self._describe_column(
                        table_name, table.get("description", ""), col
                    )

        return enriched

    def _describe_table(self, name: str, table: Dict) -> str:
        """Generate business description for a table using Llama 3.2."""
        cols = ", ".join(c["name"] for c in table.get("columns", []))
        pk = ", ".join(table.get("primary_key", []))
        fk = json.dumps(table.get("foreign_keys", []))
        prompt = f"""Describe this database table in 1-2 sentences for a business analyst:
Table: {name}
Columns: {cols}
Primary Key: {pk}
Foreign Keys: {fk}

Business description:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Table containing {len(table.get('columns', []))} columns"

    def _describe_column(self, table_name: str, table_desc: str, col: Dict) -> str:
        """Generate business description for a column using Llama 3.2."""
        prompt = f"""Describe this database column in 1 sentence:
Table: {table_name} ({table_desc})
Column: {col['name']}
Type: {col['type']}
Nullable: {col.get('nullable', True)}

Business description:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"{col['name']} column of type {col['type']}"


# Singleton instance
_describer = None

def get_describer() -> SchemaDescriber:
    global _describer
    if _describer is None:
        _describer = SchemaDescriber()
    return _describer


def enrich_schema(schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Convenience function matching expected interface."""
    return get_describer().enrich_schema(schema, **kwargs)