"""
Adapter for pinecone_tool.py
"""

import os
import json
from typing import Dict, Any, List
from pinecone import Pinecone, ServerlessSpec

try:
    import pinecone_tool as pt
except ImportError:
    pt = None


class PineconeAdapter:
    """Manages schema embeddings in Pinecone."""
    
    def __init__(self):
        self.api_key = os.getenv("PINECONE_API_KEY")
        self.pc = Pinecone(api_key=self.api_key)
    
    def upsert_schema_vectors(self, 
                            index_name: str,
                            schema: Dict[str, Any],
                            namespace: str = "schema-metadata",
                            dimension: int = 1536) -> None:
        """
        Create embeddings for each table/column and upsert to Pinecone.
        Uses text-embedding-3-large or similar for 1536-dim vectors.
        """
        if pt is not None:
            return pt.upsert_schema(index_name, schema, namespace)
        
        # Ensure index exists
        try:
            self.pc.describe_index(index_name)
        except Exception:
            self.pc.create_index(
                name=index_name,
                dimension=dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
        
        index = self.pc.Index(index_name)
        vectors = []
        
        # Embed each table as a document
        for table_name, table in schema.get("tables", {}).items():
            text = self._table_to_text(table_name, table)
            embedding = self._get_embedding(text)
            
            vectors.append({
                "id": f"table:{table_name}",
                "values": embedding,
                "metadata": {
                    "type": "table",
                    "name": table_name,
                    "description": table.get("description", ""),
                    "column_count": len(table.get("columns", [])),
                    "columns": json.dumps([c["name"] for c in table.get("columns", [])])
                }
            })
            
            # Embed each column
            for col in table.get("columns", []):
                col_text = self._column_to_text(table_name, table, col)
                col_embedding = self._get_embedding(col_text)
                
                vectors.append({
                    "id": f"column:{table_name}.{col['name']}",
                    "values": col_embedding,
                    "metadata": {
                        "type": "column",
                        "table": table_name,
                        "name": col["name"],
                        "data_type": col.get("type", "UNKNOWN"),
                        "description": col.get("description", ""),
                        "nullable": col.get("nullable", True)
                    }
                })
        
        # Batch upsert
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            index.upsert(vectors=batch, namespace=namespace)
    
    def query_similar_schema(self,
                             index_name: str,
                             query: str,
                             top_k: int = 5,
                             namespace: str = "schema-metadata") -> Dict:
        """Retrieve relevant schema elements for a natural language query."""
        if pt is not None:
            return pt.query_schema(index_name, query, top_k)
        
        index = self.pc.Index(index_name)
        embedding = self._get_embedding(query)
        
        return index.query(
            vector=embedding,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True
        )
    
    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding vector. Replace with your embedding model."""
        # Placeholder: return zero vector
        # In production: use OpenAI text-embedding-3-large or similar
        import random
        random.seed(hash(text) % 10000)
        return [random.uniform(-1, 1) for _ in range(1536)]
    
    def _table_to_text(self, name: str, table: Dict) -> str:
        cols = ", ".join(f"{c['name']}({c.get('type','')})" 
                        for c in table.get("columns", []))
        return f"Table {name}: {table.get('description','')}. Columns: {cols}"
    
    def _column_to_text(self, table_name: str, table: Dict, col: Dict) -> str:
        return (f"Column {col['name']} in table {table_name}. "
                f"Type: {col.get('type','')}. "
                f"Description: {col.get('description','')}")


# Module-level functions for adapter interface
_adapter = None

def _get_adapter():
    global _adapter
    if _adapter is None:
        _adapter = PineconeAdapter()
    return _adapter

def upsert_schema_vectors(**kwargs):
    return _get_adapter().upsert_schema_vectors(**kwargs)

def query_similar_schema(**kwargs):
    return _get_adapter().query_similar_schema(**kwargs)