"""
Adapter for neo4j_tool.py
"""

import os
from typing import Dict, Any, List
from neo4j import GraphDatabase

try:
    import neo4j_tool as nt
except ImportError:
    nt = None


class Neo4jAdapter:
    """Publishes schema as a graph and retrieves relationship context."""
    
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
    
    def publish_schema_graph(self, graph_id: str, schema: Dict[str, Any]) -> None:
        """Create nodes and relationships in Neo4j from schema."""
        if nt is not None:
            return nt.publish_graph(graph_id, schema)
        
        with self.driver.session() as session:
            # Clear existing graph for this ID
            session.run("MATCH (n {graph_id: $id}) DETACH DELETE n", id=graph_id)
            
            # Create table nodes
            for table_name, table in schema.get("tables", {}).items():
                session.run("""
                    CREATE (t:Table {
                        graph_id: $gid,
                        name: $name,
                        description: $desc,
                        column_count: $cc
                    })
                """, gid=graph_id, name=table_name, 
                    desc=table.get("description", ""),
                    cc=len(table.get("columns", [])))
                
                # Create column nodes and relationships
                for col in table.get("columns", []):
                    session.run("""
                        MATCH (t:Table {graph_id: $gid, name: $tname})
                        CREATE (c:Column {
                            graph_id: $gid,
                            name: $cname,
                            data_type: $dtype,
                            description: $desc,
                            nullable: $null
                        })
                        CREATE (t)-[:HAS_COLUMN]->(c)
                    """, gid=graph_id, tname=table_name,
                        cname=col["name"], dtype=col.get("type", "UNKNOWN"),
                        desc=col.get("description", ""),
                        null=col.get("nullable", True))
            
            # Create FK relationships
            for rel in schema.get("relationships", []):
                session.run("""
                    MATCH (from:Table {graph_id: $gid, name: $from_t})
                    MATCH (to:Table {graph_id: $gid, name: $to_t})
                    CREATE (from)-[:REFERENCES {
                        from_column: $from_c,
                        to_column: $to_c,
                        type: $rtype
                    }]->(to)
                """, gid=graph_id, from_t=rel["from_table"],
                    to_t=rel["to_table"], from_c=rel["from_column"],
                    to_c=rel["to_column"], rtype=rel.get("type", "unknown"))
            
            # Create inferred relationships (same-name columns across tables)
            self._create_inferred_relationships(session, graph_id, schema)
    
    def _create_inferred_relationships(self, session, graph_id: str, schema: Dict):
        """Infer relationships from column name patterns."""
        tables = list(schema.get("tables", {}).keys())
        for i, t1 in enumerate(tables):
            for t2 in tables[i+1:]:
                cols1 = {c["name"] for c in schema["tables"][t1].get("columns", [])}
                cols2 = {c["name"] for c in schema["tables"][t2].get("columns", [])}
                common = cols1 & cols2
                
                for col in common:
                    if col.endswith("_id") or col in ("id", "uuid", "guid"):
                        session.run("""
                            MATCH (t1:Table {graph_id: $gid, name: $t1})
                            MATCH (t2:Table {graph_id: $gid, name: $t2})
                            MERGE (t1)-[:POSSIBLY_RELATED {via: $col}]->(t2)
                        """, gid=graph_id, t1=t1, t2=t2, col=col)
    
    def get_query_context(self, graph_id: str, tables: List[str]) -> Dict[str, Any]:
        """Retrieve relationship graph for relevant tables."""
        if nt is not None:
            return nt.get_context(graph_id, tables)
        
        with self.driver.session() as session:
            # Get direct relationships between relevant tables
            result = session.run("""
                MATCH (t:Table {graph_id: $gid})-[:REFERENCES|POSSIBLY_RELATED*1..3]-(related:Table {graph_id: $gid})
                WHERE t.name IN $tables
                RETURN DISTINCT t.name as from_table, related.name as to_table,
                       type(r) as rel_type
            """, gid=graph_id, tables=tables)
            
            relationships = []
            for record in result:
                relationships.append({
                    "from": record["from_table"],
                    "to": record["to_table"],
                    "type": record["rel_type"]
                })
            
            # Get join paths
            join_paths = session.run("""
                MATCH path = (a:Table {graph_id: $gid})-[:REFERENCES*1..4]-(b:Table {graph_id: $gid})
                WHERE a.name IN $tables AND b.name IN $tables AND a <> b
                RETURN [n in nodes(path) | n.name] as path_tables,
                       length(path) as hops
                ORDER BY hops ASC
                LIMIT 10
            """, gid=graph_id, tables=tables)
            
            return {
                "relationships": relationships,
                "join_paths": [dict(r) for r in join_paths]
            }


# Module-level interface
_adapter = None

def _get_adapter():
    global _adapter
    if _adapter is None:
        _adapter = Neo4jAdapter()
    return _adapter

def publish_schema_graph(**kwargs):
    return _get_adapter().publish_schema_graph(**kwargs)

def get_query_context(**kwargs):
    return _get_adapter().get_query_context(**kwargs)