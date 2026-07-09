"""
Tool Adapters — wraps existing tool classes without modifying them.
Provides uniform schema + run() interface for the orchestrator.
"""

import json
import os
from typing import Optional

from .mysql_tool import MySQLTool
from .neo4j_tool import Neo4jTool
from .pinecone_tool import PineconeTool


class MySQLToolAdapter:
    """Adapter for MySQLTool — wraps execute_query()"""
    
    def __init__(self):
        self._tool = MySQLTool()
    
    @property
    def schema(self):
        return {
            "name": "mysql_query",
            "description": "Execute SQL queries (SELECT, SHOW, DESCRIBE, EXPLAIN) against MySQL database. Returns structured results with rows, columns, execution time, and warnings.",
            "capability": "sql",
            "parameters": {
                "query": {"type": "string", "description": "SQL query string"}
            }
        }
    
    def run(self, query: str) -> str:
        result = self._tool.execute_query(query)
        return json.dumps(result, indent=2, default=str)


class Neo4jToolAdapter:
    """Adapter for Neo4jTool — wraps various query methods"""
    
    def __init__(self):
        self._tool = Neo4jTool()
    
    @property
    def schema(self):
        return {
            "name": "neo4j_query",
            "description": "Query Neo4j graph database for table relationships, column references, shortest paths between tables, and join paths. Use when user asks about how tables connect or relate.",
            "capability": "graph",
            "parameters": {
                "query_type": {"type": "string", "enum": ["neighbors", "shortest_path", "join_path", "columns", "statistics"], "description": "Type of graph query"},
                "table": {"type": "string", "description": "Primary table name"},
                "target_table": {"type": "string", "description": "Target table for path queries"}
            }
        }
    
    def run(self, query_type: str, table: str, target_table: str = None) -> str:
        if query_type == "neighbors":
            result = self._tool.get_neighbors(table)
        elif query_type == "shortest_path":
            if not target_table:
                return json.dumps({"error": "target_table required for shortest_path"})
            result = self._tool.find_shortest_path(table, target_table)
        elif query_type == "join_path":
            tables = [t.strip() for t in table.split(",")]
            result = self._tool.find_join_path(tables)
        elif query_type == "columns":
            result = self._tool.get_columns(table)
        elif query_type == "statistics":
            result = self._tool.get_graph_statistics()
        else:
            return json.dumps({"error": f"Unknown query_type: {query_type}"})
        
        return json.dumps(result, indent=2, default=str)


class PineconeToolAdapter:
    """Adapter for PineconeTool — wraps search methods"""
    
    def __init__(self):
        self._tool = PineconeTool()
    
    @property
    def schema(self):
        return {
            "name": "pinecone_query",
            "description": "Semantic vector search on database schema (tables/columns). Use when user asks in natural language without specific table names, or wants to find relevant tables/columns by meaning.",
            "capability": "vector",
            "parameters": {
                "query": {"type": "string", "description": "Natural language search text"},
                "search_type": {"type": "string", "enum": ["tables", "columns", "all"], "default": "all"},
                "top_k": {"type": "integer", "default": 5}
            }
        }
    
    def run(self, query: str, search_type: str = "all", top_k: int = 5) -> str:
        if search_type == "tables":
            result = self._tool.search_tables(query, top_k)
        elif search_type == "columns":
            result = self._tool.search_columns(query, top_k)
        else:
            result = self._tool.search_all(query, top_k)
        
        return json.dumps(result, indent=2, default=str)


class DescribeSchemaTool:
    """
    Standalone tool — reads schema_enriched.json.
    (No existing tool to wrap, this is new)
    """
    
    def __init__(self, schema_path: str = "schema_enriched.json"):
        self.schema_path = schema_path
        self._schema = None
    
    def _load(self):
        if self._schema is not None:
            return
        if not os.path.exists(self.schema_path):
            self._schema = {"error": f"Schema file not found: {self.schema_path}"}
            return
        with open(self.schema_path, 'r', encoding='utf-8') as f:
            self._schema = json.load(f)
    
    @property
    def schema(self):
        return {
            "name": "describe_schema",
            "description": "Get database schema information — table names, column names, data types, primary keys, descriptions. Use BEFORE writing SQL to understand available tables.",
            "capability": "schema",
            "parameters": {
                "table_name": {"type": "string", "description": "Specific table to describe (omit for all tables)", "default": None}
            }
        }
    
    def run(self, table_name: Optional[str] = None) -> str:
        self._load()
        
        if "error" in self._schema:
            return json.dumps(self._schema)
        
        if table_name:
            for table in self._schema.get("tables", []):
                if table["table_name"] == table_name:
                    return json.dumps(table, indent=2)
            return json.dumps({"error": f"Table '{table_name}' not found"})
        
        overview = {
            "database_name": self._schema.get("database_name"),
            "total_tables": self._schema.get("total_tables"),
            "tables": [
                {
                    "table_name": t["table_name"],
                    "description": t.get("description", "")[:100],
                    "primary_key": t.get("primary_key"),
                    "column_count": len(t.get("columns", []))
                }
                for t in self._schema.get("tables", [])
            ]
        }
        return json.dumps(overview, indent=2)