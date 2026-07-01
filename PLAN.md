# Database Agent — Industry-Grade Build Plan

A terminal-first, LangGraph-based AI agent that answers natural-language questions and runs read-only SQL against `enveu_flow_db` using:

- **Vector KB** — `schema_enriched.json` upserted to **Pinecone**
- **Relational KB** — `mapping.json` loaded into **Neo4j**
- **LLM** — `MiniMax-M3` via the OpenAI-compatible endpoint in `.env`
- **Execution** — read-only **MySQL** connection (live DB)
- **Interface** — terminal REPL with `rich` + `typer`

---

## 0. Pre-flight — Resolve Two Setup Mismatches

These block everything downstream. Fix before Phase 1.

### 0.1 Embedding dimension alignment

You currently have a contradiction:

| Source                          | Model                  | Dim  |
|---------------------------------|------------------------|------|
| `.env`                          | `text-embedding-3-small` (OpenAI) | 1536 |
| `upsert_to_pinecone.py`         | `nomic-embed-text` (Ollama)       | 768  |

Pick one path and apply it everywhere (code, index, env):

- **Path A (recommended, OpenAI)**: keep `.env` value, delete `ollama` import in `upsert_to_pinecone.py`, set `EMBED_DIM=1536`, recreate Pinecone index at 1536-d, upsert via `openai.embeddings.create`.
- **Path B (local)**: change `.env` to `EMBEDDING_MODEL=nomic-embed-text`, `EMBED_DIM=768`, keep current upsert script.

Add `EMBED_DIM`, `PINECONE_INDEX_NAME`, `PINECONE_CLOUD`, `PINECONE_REGION`, `UPSERT_BATCH_SIZE` to `.env` (don't hardcode in script).

### 0.2 Neo4j provisioning

`mapping.json` is already in the right shape (`nodes` + `edges`). You need:

- Neo4j instance running (Aura free tier is fine).
- `.env` additions:
  ```
  NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
  NEO4J_USER=neo4j
  NEO4J_PASSWORD=...
  NEO4J_DATABASE=neo4j
  MYSQL_HOST=...
  MYSQL_PORT=3306
  MYSQL_USER=<read-only user>
  MYSQL_PASSWORD=...
  MYSQL_DATABASE=enveu_flow_db
  ```

- A one-shot loader script (`graph/load_neo4j.py`) that:
  1. Creates constraints: `(:Table {name})`, `(:Column {table, name})`.
  2. MERGEs all `t*` and `c*` nodes.
  3. Creates `(:Table)-[:HAS_COLUMN]->(:Column)` and `(:Column)-[:REFERENCES]->(:Column)` (FK edges only).
  4. Stores `name` as the business key for lookups (separate from `id`).

### 0.3 MySQL safety

Create a dedicated read-only DB user for the agent:

```sql
CREATE USER 'db_agent_ro'@'%' IDENTIFIED BY '...';
GRANT SELECT ON enveu_flow_db.* TO 'db_agent_ro'@'%';
FLUSH PRIVILEGES;
```

Hard-block all write keywords at the SQL validation layer (defence in depth).

---

## 1. Target Architecture

```
            ┌──────────────────────────────────────────────┐
            │                Terminal REPL                  │
            │   (rich + typer, slash cmds, streaming)      │
            └────────────────────┬─────────────────────────┘
                                 │
                                 ▼
            ┌──────────────────────────────────────────────┐
            │            LangGraph State Machine            │
            │                                              │
            │  router → retrieve_schema → expand_graph →   │
            │  generate_sql → validate_sql → execute_sql → │
            │  format_answer → END                         │
            │                                              │
            │  + memory (per-conversation_id checkpoint)   │
            │  + logging (every node writes to .log/)      │
            └──────┬──────────────┬───────────────┬────────┘
                   │              │               │
                   ▼              ▼               ▼
            ┌──────────┐   ┌────────────┐   ┌────────────┐
            │ Pinecone │   │   Neo4j    │   │  MySQL RO  │
            │  (vec)   │   │  (graph)   │   │ (executor) │
            └──────────┘   └────────────┘   └────────────┘
```

The agent answers three classes of intent:
1. **Schema questions** — "what tables store billing info?", "what does `flow_credentials.encrypted_data` hold?"
2. **Data questions** — "how many agent runs failed yesterday for tenant X?"
3. **Explanation of plan** — always returns the SQL it intends to run, awaits implicit confirmation by `auto_execute` flag.

---

## 2. Project Layout

```
database_agent/
├── .env                            # all secrets + config
├── schema_enriched.json            # KB input (already present)
├── mapping.json                    # Neo4j graph input (already present)
│
├── agent/
│   ├── __init__.py
│   ├── cli.py                      # typer entry: `python -m agent`
│   ├── repl.py                     # loop, slash commands, streaming
│   ├── state.py                    # AgentState (TypedDict)
│   ├── graph.py                    # StateGraph assembly + edges
│   ├── nodes/
│   │   ├── router.py               # intent classification
│   │   ├── retrieve_schema.py      # Pinecone vector search
│   │   ├── expand_graph.py         # Neo4j n-hop neighborhood
│   │   ├── generate_sql.py         # MiniMax-M3 → SQL
│   │   ├── validate_sql.py         # AST safety + allowlist
│   │   ├── execute_sql.py          # MySQL read-only exec
│   │   └── format_answer.py        # MiniMax-M3 → NL summary
│   ├── tools/
│   │   ├── pinecone_tool.py        # @tool search_schema
│   │   ├── neo4j_tool.py           # @tool get_relationships
│   │   ├── mysql_tool.py           # @tool execute_sql (RO)
│   │   └── local_schema_tool.py    # @tool get_table_info (fast)
│   ├── prompts/
│   │   ├── router.txt
│   │   ├── sql_generator.txt
│   │   ├── answer_formatter.txt
│   │   └── guardrails.txt
│   └── memory/
│       └── store.py                # SQLite-backed checkpoint store
│
├── graph/
│   ├── load_neo4j.py               # one-shot loader from mapping.json
│   └── cypher/
│       ├── neighborhood.cypher
│       └── join_paths.cypher
│
├── embeddings/
│   ├── upsert_to_pinecone.py       # rewrite after 0.1
│   └── chunk_builder.py            # turn schema_enriched into records
│
├── safety/
│   ├── sql_parser.py               # sqlglot parse + allowlist
│   └── policies.py                 # table/column allowlist config
│
├── tests/
│   ├── test_router.py
│   ├── test_sql_generator.py       # golden NL→SQL pairs
│   ├── test_validator.py           # injection attempts
│   ├── test_executor.py            # read-only enforcement
│   └── fixtures/
│       └── questions.jsonl
│
├── logs/                           # JSONL per-run traces
├── pyproject.toml                  # deps + tooling
├── README.md
└── PLAN.md                         # this file
```

---

## 3. Components in Detail

### 3.1 State (`agent/state.py`)

```python
class AgentState(TypedDict):
    user_query: str
    conversation_id: str
    intent: Literal["schema_q", "data_q", "clarify", "out_of_scope"]
    schema_hits: list[dict]          # from Pinecone
    graph_expansion: list[dict]      # from Neo4j
    candidate_sql: str
    validated_sql: str
    sql_rows: list[dict] | None
    final_answer: str
    errors: list[str]
    iteration: int                   # tool-call loop counter
```

### 3.2 Tools (LangChain `@tool`)

| Tool                  | Backend   | Purpose                                              | Returns                      |
|-----------------------|-----------|------------------------------------------------------|------------------------------|
| `search_schema`       | Pinecone  | semantic search over table+column docs               | top-k chunks with metadata   |
| `get_table_info`      | local JSON| exact lookup of one table (fast path)                | columns + descriptions       |
| `get_relationships`   | Neo4j     | n-hop FK neighborhood for a table                    | adjacent tables + joins      |
| `list_tables`         | local JSON| filtered listing                                     | table names + descriptions   |
| `execute_sql`         | MySQL RO  | runs validated SELECT, returns rows + EXPLAIN         | tabular result               |

`execute_sql` is **only** called from `execute_sql` node, not bound to the LLM directly. The LLM never has free rein to run SQL — it produces a candidate, the validator approves, the executor runs. This is the single most important safety boundary.

### 3.3 Nodes (LangGraph)

| Node              | Action                                                                              | Edge                                |
|-------------------|-------------------------------------------------------------------------------------|-------------------------------------|
| `router`          | MiniMax-M3 classifies `user_query` into intent. No tools.                           | intent → next                       |
| `retrieve_schema` | Pinecone search (`top_k=8`), merge with `local_schema_tool` hits.                   | → `expand_graph`                    |
| `expand_graph`    | For each candidate table, run Cypher 1-hop FK expansion. Returns join graph.        | → `generate_sql`                    |
| `generate_sql`    | MiniMax-M3 with system prompt that includes compressed schema + joins.              | → `validate_sql`                    |
| `validate_sql`    | `sqlglot.parse` → reject non-SELECT → check tables/cols against allowlist → reject destructive keywords. | retry (max 2) → `generate_sql` or → `execute_sql` |
| `execute_sql`     | Run on read-only conn with `MAX_EXECUTION_TIME(15000)` and `max_rows=1000`.         | → `format_answer`                   |
| `format_answer`   | MiniMax-M3 summarises rows into natural language.                                   | END                                 |

Loop limit: `iteration` capped at 3; on exceed, return "I couldn't confidently answer this — please refine."

### 3.4 Prompts (`agent/prompts/`)

- **`router.txt`** — strict intent classification, JSON output `{intent, reasoning}`.
- **`sql_generator.txt`** — system prompt template:

```
You are a senior data analyst writing MySQL SELECT queries.
You have a strict allowlist of tables and columns (below).
Never use INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/RENAME/GRANT.
Always alias tables when joining more than one.
Prefer explicit JOIN ... ON over comma joins.
Limit results to 1000 rows unless the question implies aggregation.
Use the provided FK relationships to join correctly.

# Allowed tables and columns
{schema_block}

# FK relationships (one-hop)
{graph_block}

# User question
{user_query}

Return JSON: {"sql": "...", "explanation": "..."}
```

- **`answer_formatter.txt`** — converts rows + question into a concise answer with optional markdown table.
- **`guardrails.txt`** — appended to every system prompt as a safety footer.

### 3.5 SQL validation (`safety/sql_parser.py`)

Use `sqlglot`:

```python
import sqlglot
from sqlglot import exp

DENY_STMT = (exp.Insert, exp.Update, exp.Delete, exp.Merge,
             exp.Drop, exp.Alter, exp.TruncateTable, exp.Grant)
DENY_FUNCTIONS = {"LOAD_FILE", "OUTFILE", "DUMPFILE"}

def validate(sql: str, allow_tables: set[str]) -> list[str]:
    errors = []
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except sqlglot.errors.ParseError as e:
        return [f"parse error: {e}"]
    if not isinstance(tree, exp.Select):
        errors.append(f"only SELECT allowed, got {type(tree).__name__}")
    for stmt in tree.find_all(*DENY_STMT):
        errors.append(f"disallowed statement: {type(stmt).__name__}")
    for f in tree.find_all(exp.Anonymous):
        if f.name.upper() in DENY_FUNCTIONS:
            errors.append(f"disallowed function: {f.name}")
    for t in tree.find_all(exp.Table):
        if t.name not in allow_tables:
            errors.append(f"table not in allowlist: {t.name}")
    return errors
```

`allow_tables` comes from `schema_enriched.json` and is regenerated on every upsert.

### 3.6 Terminal REPL (`agent/repl.py`)

Slash commands:

| Cmd                  | Action                                              |
|----------------------|-----------------------------------------------------|
| `/help`              | list commands                                       |
| `/tables [filter]`   | list tables matching filter                         |
| `/schema <table>`    | print full schema for a table                       |
| `/sql`               | show last SQL the agent ran                         |
| `/clear`             | clear screen + reset conversation                   |
| `/history`           | print last 20 turns                                 |
| `/exit`              | quit                                                |

Streaming: each token from `format_answer` printed via `rich.live.Live` with a `rich.markdown.Markdown` renderable. SQL shown in a `rich.panel.Panel` with `rich.syntax.Syntax(sql, "sql", theme="monokai")`.

Result rows rendered with `rich.table.Table`, capped at 50 visual rows with a `(showing first 50 of N)` footer.

### 3.7 Memory (`agent/memory/store.py`)

Use LangGraph's `SqliteSaver` from `langgraph.checkpoint.sqlite` for per-`conversation_id` state. Path: `./.conversations.db`. Each terminal session auto-creates a `conversation_id` (uuid4) unless `--resume <id>` is passed.

### 3.8 Logging (`logs/`)

Structured JSONL per turn, fields:

```json
{"ts":"...","conv_id":"...","intent":"data_q","tables":["..."],"sql":"...",
 "validation_errors":[],"rows":42,"tokens_in":312,"tokens_out":128,
 "duration_ms":1840,"model":"MiniMax-M3"}
```

Use a small helper around `logging` + `json.dumps` — no extra dep needed.

---

## 4. Step-by-Step Phases

Realistic timing for an engineer who already knows the stack. This is one focused build session (~5–6 hours total), not a multi-day plan.

### Phase 0 — Setup & secrets (10 min)

1. Decide Path A (OpenAI 1536-d) or Path B (Ollama 768-d) per §0.1 and align `.env` + script.
2. Fill in Neo4j + MySQL creds in `.env`.
3. `pip install langchain langgraph langgraph-checkpoint-sqlite neo4j sqlglot`.
4. Quick smoke: `python -c "import langchain, langgraph, neo4j, pinecone, sqlglot"`.

### Phase 1 — Re-upsert KB to Pinecone (15 min)

1. Edit `embeddings/upsert_to_pinecone.py`: drop the `ollama` import, use `openai.embeddings.create`, set `EMBED_DIM` from env. Keep the chunk-builder logic — it's already correct.
2. If dim changed, `pc.delete_index` then recreate.
3. Run, confirm ~750 vectors in `enveu_flow_db` namespace.

### Phase 2 — Load Neo4j (20 min)

1. Write `graph/load_neo4j.py` (constraints + MERGE nodes/edges from `mapping.json`, ~80 lines).
2. Run once. Verify counts with a `MATCH (n) RETURN count(n)` and a 1-hop expansion query on `flow_credentials`.

### Phase 3 — Tools (40 min)

Four small wrappers, each ~30–50 lines:

1. `pinecone_tool.py` — `query(index, text, top_k=8, entity_type_filter=...)`.
2. `neo4j_tool.py` — `expand(table, hops=1)` and `path_between(t1, t2)`.
3. `mysql_tool.py` — read-only conn, `MAX_EXECUTION_TIME(15000)`, row cap.
4. `local_schema_tool.py` — `schema_enriched.json` loaded once into a dict at startup.

Test each with a hardcoded call and a print.

### Phase 4 — State machine (60 min)

1. Define `AgentState` in `agent/state.py`.
2. Implement 7 nodes, each a 10–20 line function: `router` → `retrieve_schema` → `expand_graph` → `generate_sql` → `validate_sql` → `execute_sql` → `format_answer`.
3. Wire `StateGraph` with the conditional edges from §3.3.
4. Compile with `SqliteSaver`.
5. Smoke: `graph.invoke({"user_query": "how many tables are there?"})` returns something sane.

### Phase 5 — Safety layer (30 min)

1. `safety/sql_parser.py` with `validate()` from §3.5 (~40 lines).
2. Build allowlist set from `schema_enriched.json` at startup.
3. Hand-craft ~10 injection fixtures in `tests/test_validator.py` (DROP, DELETE, UNION, comment bypass, INTO OUTFILE, multi-statement). Run, confirm all rejected.

### Phase 6 — Terminal UI (60 min)

1. `cli.py` — `typer` entry with `--resume`, `--no-color`, `--debug` flags.
2. `repl.py` — input loop + slash cmds + `rich.live.Live` streaming + `rich.syntax.Syntax` for SQL + `rich.table.Table` for results.
3. Wire it to the compiled graph.

### Phase 7 — Memory & logging (20 min)

1. `SqliteSaver` is already attached at compile time — just confirm `--resume` works.
2. Tiny JSONL logger (~15 lines) writing to `logs/<conv_id>.jsonl` per turn.
3. `/history` reads from checkpoint state.

### Phase 8 — Tests & eval (45 min)

1. 15–20 golden questions in `tests/fixtures/questions.jsonl` (good enough for a v1; expand later).
2. `scripts/eval.py` (~40 lines) runs the JSONL through the graph, asserts SQL parses, executes, returns rows.
3. Aim for ≥80% pass on first run — refine prompts based on failures.

### Phase 9 — Hardening (later)

- `--dry-run` flag.
- Per-`conversation_id` rate limit (token bucket).
- `--max-turns` cap.
- Log rotation.
- Optional: audit row per query in local SQLite.

### Total budget

| Phase | Time    | Cumulative |
|-------|---------|------------|
| 0     | 10 min  | 10 min     |
| 1     | 15 min  | 25 min     |
| 2     | 20 min  | 45 min     |
| 3     | 40 min  | 1h 25m     |
| 4     | 60 min  | 2h 25m     |
| 5     | 30 min  | 2h 55m     |
| 6     | 60 min  | 3h 55m     |
| 7     | 20 min  | 4h 15m     |
| 8     | 45 min  | **5h**     |

Phases 0–6 get you a working terminal agent. 7–8 turn it from "works on my machine" to "verifiable + persistent." Phase 9 is when the FE / multi-DB / RBAC scope lands.

---

## 5. Configuration (final `.env`)

```ini
# LLM
MINIMAX_API_KEY=sk-cp-...
MINIMAX_BASE_URL=https://api.minimax.io/v1
LLM_MODEL=MiniMax-M3
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2000

# Embeddings (choose one path)
EMBEDDING_PROVIDER=openai            # or "ollama"
EMBEDDING_MODEL=text-embedding-3-small
EMBED_DIM=1536

# Pinecone
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=database-agent
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
PINECONE_NAMESPACE=enveu_flow_db

# Neo4j
NEO4J_URI=neo4j+s://...
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j

# MySQL (read-only user)
MYSQL_HOST=...
MYSQL_PORT=3306
MYSQL_USER=db_agent_ro
MYSQL_PASSWORD=...
MYSQL_DATABASE=enveu_flow_db

# Agent limits
AGENT_MAX_ITERATIONS=3
SQL_MAX_ROWS=1000
SQL_TIMEOUT_SECONDS=15
```

---

## 6. Run Commands (final)

```bash
# One-time KB setup
python -m embeddings.upsert_to_pinecone
python -m graph.load_neo4j

# Terminal agent
python -m agent
python -m agent --resume <conv_id>
python -m agent --dry-run      # prints SQL, never executes

# Evaluation
pytest -q
python scripts/eval.py --fixtures tests/fixtures/questions.jsonl
```

---

## 7. Non-Goals (this phase)

- Frontend / web UI — explicitly deferred per your scope.
- Multi-DB routing (one DB at a time).
- Fine-grained RBAC (single read-only DB user).
- Vector store other than Pinecone.
- Streaming partial SQL — only final SQL + final answer are streamed.

---

## 8. Risks & Mitigations

| Risk                                          | Mitigation                                                                 |
|-----------------------------------------------|----------------------------------------------------------------------------|
| LLM hallucinates table/column names           | Allowlist check in validator; on miss, retry with explicit error in prompt |
| Prompt injection via user input               | System prompts + guardrails footer; no tool is LLM-callable except retrieve/expand which are read-only |
| SQL injection via crafted user input          | `sqlglot` AST validation + read-only DB user + `MAX_EXECUTION_TIME`         |
| Embedding dim drift                           | Validate at startup; refuse to run if Pinecone `dim != EMBED_DIM`          |
| MiniMax rate limits / 529s                    | Retry with exponential backoff (already in your `minimax_descriptions.py`); surface friendly "try again" to user |
| Neo4j cold start (Aura)                       | Lazy connection; first query may be slow — surface latency in `/debug`     |
| PII in logs                                   | Never log row contents in JSONL; log column names + counts only            |
| Secret leakage                                | `.env` gitignored; `.env.example` ships placeholder values only            |

---

## 9. Definition of Done

The agent is "industry grade for terminal" when:

1. `python -m agent` boots in <5s.
2. Answers golden questions with ≥80% success on first attempt (valid SQL + non-empty result where expected); refines to ≥90% after one round of prompt tuning.
3. Blocks 100% of injection test fixtures.
4. Streams final answer token-by-token in the terminal.
5. Persists conversation across restarts via `--resume`.
6. JSONL logs written for every turn.
7. README documents `.env`, setup, run, and eval.