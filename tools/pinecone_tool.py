"""
tools/pinecone_tool.py

Production-ready Pinecone retrieval tool for the AI Database Agent.

Features
--------
- Loads configuration from .env
- Connects to an existing Pinecone index
- Uses Ollama (nomic-embed-text by default) for query embeddings
- Searches table vectors, column vectors, or both
- Filters low-confidence matches
- Returns structured results
- Health check
- Simple logging
"""

from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

import ollama
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[PineconeTool] %(message)s")


class PineconeTool:

    def __init__(
        self,
        index_name: Optional[str] = None,
        namespace: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:

        self.api_key = os.getenv("PINECONE_API_KEY")
        if not self.api_key:
            raise ValueError("PINECONE_API_KEY not found in .env")

        self.index_name = index_name or os.getenv("PINECONE_INDEX_NAME", "database-agent")
        self.namespace = namespace or os.getenv("PINECONE_NAMESPACE", "enveu_flow_db")
        self.model = model or os.getenv("OLLAMA_MODEL", "nomic-embed-text")

        self.pc = Pinecone(api_key=self.api_key)
        self.index = self.pc.Index(self.index_name)

        logging.info(f"Connected to index '{self.index_name}'")

    def _embed_query(self, query: str) -> List[float]:
        if not query.strip():
            raise ValueError("Query cannot be empty.")

        try:
            r = ollama.embed(model=self.model, input=query)
            if hasattr(r, "embeddings"):
                return r.embeddings[0]
            return r["embeddings"][0]
        except Exception as e:
            raise RuntimeError(f"Ollama embedding failed: {e}")

    def _query(self, query: str, top_k: int = 5,
               entity_type: Optional[str] = None,
               min_score: float = 0.0) -> Dict[str, Any]:

        vector = self._embed_query(query)

        kwargs = {
            "vector": vector,
            "top_k": top_k,
            "namespace": self.namespace,
            "include_metadata": True,
        }

        if entity_type:
            kwargs["filter"] = {"entity_type": {"$eq": entity_type}}

        result = self.index.query(**kwargs)

        matches = []

        for match in result.matches:
            if match.score < min_score:
                continue

            md = match.metadata or {}

            matches.append({
                "entity_type": md.get("entity_type"),
                "table": md.get("table_name"),
                "column": md.get("column_name"),
                "score": round(float(match.score), 3),
                "primary_key": md.get("primary_key"),
                "column_count": md.get("column_count"),
                "data_type": md.get("data_type"),
                "description": md.get("description"),
            })

        return {
            "query": query,
            "match_count": len(matches),
            "matches": matches,
        }

    def search_tables(self, query: str, top_k: int = 5,
                      min_score: float = 0.0) -> Dict[str, Any]:
        return self._query(query, top_k, "table", min_score)

    def search_columns(self, query: str, top_k: int = 5,
                       min_score: float = 0.0) -> Dict[str, Any]:
        return self._query(query, top_k, "column", min_score)

    def search_all(self, query: str, top_k: int = 10,
                   min_score: float = 0.0) -> Dict[str, Any]:
        return self._query(query, top_k, None, min_score)

    def get_best_match(self, query: str) -> Optional[Dict[str, Any]]:
        res = self.search_tables(query, top_k=1)
        return res["matches"][0] if res["matches"] else None

    def health_check(self) -> Dict[str, Any]:
        try:
            stats = self.index.describe_index_stats()
            return {
                "status": "healthy",
                "index": self.index_name,
                "namespace": self.namespace,
                "total_vectors": stats.total_vector_count,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    @staticmethod
    def pretty_print(result: Dict[str, Any]) -> None:
        print("=" * 70)
        print("Query:", result["query"])
        print("Matches:", result["match_count"])
        print("=" * 70)
        for i, m in enumerate(result["matches"], start=1):
            print(f"{i}. {m['table']}  (Score={m['score']})")
            if m["column"]:
                print(f"   Column : {m['column']}")
            if m["primary_key"]:
                print(f"   PK     : {m['primary_key']}")
            if m["column_count"] is not None:
                print(f"   Columns: {m['column_count']}")
            if m["description"]:
                print(f"   Desc   : {m['description'][:120]}...")
            print()

if __name__ == "__main__":
    tool = PineconeTool()

    print("\nHealth Check")
    print(tool.health_check())

    result = tool.search_tables(
        "show invoices",
        top_k=5,
        min_score=0.55,
    )

    tool.pretty_print(result)