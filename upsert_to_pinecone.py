"""
Upsert database schema metadata to Pinecone using Ollama local embeddings.
Model: nomic-embed-text (768-dim)

Reads PINECONE_API_KEY from .env, validates/creates the target index, generates
768-dim embeddings via Ollama in batches, and upserts to a per-database namespace.
"""

import os
import sys
import json
import hashlib
import time
from typing import List, Dict, Any

from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
import ollama

load_dotenv()

# ─── Configuration ───────────────────────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME       = os.getenv("PINECONE_INDEX_NAME", "database-agent")
EMBED_DIM        = 768
METRIC           = "cosine"
CLOUD            = os.getenv("PINECONE_CLOUD", "aws")
REGION           = os.getenv("PINECONE_REGION", "us-east-1")
BATCH_SIZE       = int(os.getenv("UPSERT_BATCH_SIZE", "100"))
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "nomic-embed-text")
SCHEMA_FILE      = os.getenv("SCHEMA_FILE", "schema_enriched.json")
MAX_RETRIES      = 3

if not PINECONE_API_KEY:
    raise ValueError("PINECONE_API_KEY not set. Add it to your .env file.")


# ─── Pinecone setup (validate or create index) ───────────────────────────────
def init_pinecone() -> Pinecone.Index:
    pc = Pinecone(api_key=PINECONE_API_KEY)
    existing = {i.name for i in pc.list_indexes()}

    if INDEX_NAME not in existing:
        print(f"[setup] Index '{INDEX_NAME}' not found. Creating serverless "
              f"({EMBED_DIM}d, {METRIC}, {CLOUD}/{REGION})...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=EMBED_DIM,
            metric=METRIC,
            spec=ServerlessSpec(cloud=CLOUD, region=REGION),
        )
        # Wait until the index is ready
        while not pc.describe_index(INDEX_NAME).status["ready"]:
            time.sleep(1)
        print(f"[setup] Index '{INDEX_NAME}' created.")

    desc = pc.describe_index(INDEX_NAME)
    if desc.dimension != EMBED_DIM:
        raise RuntimeError(
            f"Index '{INDEX_NAME}' has dim={desc.dimension}, "
            f"but {OLLAMA_MODEL} produces {EMBED_DIM}d. "
            f"Recreate the index with dimension={EMBED_DIM}."
        )
    print(f"[setup] Index '{INDEX_NAME}' ready (dim={desc.dimension}, metric={desc.metric}).")
    return pc.Index(INDEX_NAME)


# ─── Embeddings via Ollama with retry ────────────────────────────────────────
def get_embeddings(texts: List[str]) -> List[List[float]]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = ollama.embed(model=OLLAMA_MODEL, input=texts)
            return response.embeddings
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Ollama embed failed after {MAX_RETRIES} attempts: {e}")
            print(f"[embed] attempt {attempt} failed ({e}); retrying...")
            time.sleep(2 ** attempt)


# ─── Record builders ─────────────────────────────────────────────────────────
def make_id(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()

def clean_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Strip None values -- Pinecone rejects null metadata fields."""
    return {k: v for k, v in meta.items() if v is not None}

def build_records(schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = []
    db_name = schema.get("database_name", "unknown_db")

    for table in schema.get("tables", []):
        table_name = table["table_name"]
        table_desc = table.get("description", "")
        pk = table.get("primary_key")
        cols = table.get("columns", [])

        records.append({
            "id": make_id(f"{db_name}:{table_name}"),
            "text": f"Table: {table_name}. {table_desc}",
            "metadata": clean_metadata({
                "database_name": db_name,
                "entity_type": "table",
                "table_name": table_name,
                "primary_key": pk,
                "description": table_desc,
                "column_count": len(cols),
                "columns": [c["col_name"] for c in cols],
            }),
        })

        for col in cols:
            col_name = col["col_name"]
            records.append({
                "id": make_id(f"{db_name}:{table_name}:{col_name}"),
                "text": (f"Column: {table_name}.{col_name} "
                         f"({col.get('data_type','')}). {col.get('description','')}"),
                "metadata": clean_metadata({
                    "database_name": db_name,
                    "entity_type": "column",
                    "table_name": table_name,
                    "column_name": col_name,
                    "data_type": col.get("data_type", ""),
                    "description": col.get("description", ""),
                    "primary_key": pk,
                    "table_description": table_desc,
                }),
            })
    return records


# ─── Batched upsert ──────────────────────────────────────────────────────────
def upsert_records(index: Pinecone.Index, records: List[Dict[str, Any]],
                   namespace: str) -> None:
    total = len(records)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, total, BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        texts = [r["text"] for r in batch]
        batch_no = i // BATCH_SIZE + 1

        print(f"[embed] batch {batch_no}/{total_batches} ({len(batch)} records)...")
        embeddings = get_embeddings(texts)

        vectors = [{"id": r["id"], "values": emb, "metadata": r["metadata"]}
                   for r, emb in zip(batch, embeddings)]

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                index.upsert(vectors=vectors, namespace=namespace)
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise RuntimeError(f"Upsert failed after {MAX_RETRIES} attempts: {e}")
                print(f"[upsert] attempt {attempt} failed ({e}); retrying...")
                time.sleep(2 ** attempt)

        print(f"[upsert] batch {batch_no}/{total_batches} done "
              f"({(i + len(batch))/total*100:.1f}%)")


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    if not os.path.isfile(SCHEMA_FILE):
        print(f"[error] {SCHEMA_FILE} not found.")
        return 1

    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = json.load(f)

    db_name = schema.get("database_name", "unknown_db")
    namespace = db_name  # isolate by database name

    print("=" * 60)
    print(f"  Database : {db_name}")
    print(f"  Tables   : {schema.get('total_tables', len(schema.get('tables', [])))}")
    print(f"  Index    : {INDEX_NAME}")
    print(f"  Namespace: {namespace}")
    print(f"  Model    : {OLLAMA_MODEL} ({EMBED_DIM}d)")
    print("=" * 60)

    index = init_pinecone()
    records = build_records(schema)
    print(f"\n[build] {len(records)} records "
          f"({sum(1 for r in records if r['metadata']['entity_type']=='table')} tables, "
          f"{sum(1 for r in records if r['metadata']['entity_type']=='column')} columns)")

    t0 = time.time()
    upsert_records(index, records, namespace)
    elapsed = time.time() - t0

    # Wait for indexing then report stats
    print("\n[verify] waiting for index to refresh...")
    time.sleep(5)
    stats = index.describe_index_stats()
    ns_count = stats.namespaces.get(namespace, None)
    ns_vector_count = ns_count.vector_count if ns_count else 0

    print("=" * 60)
    print(f"  Upserted    : {len(records)} vectors in {elapsed:.1f}s")
    print(f"  In namespace: {namespace}")
    print(f"  Index total : {stats.total_vector_count} vectors")
    print(f"  Namespace   : {ns_vector_count} vectors")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[abort] interrupted.")
        sys.exit(130)