#!/usr/bin/env python3
"""Enrich schema.json with business-facing descriptions via MiniMax.

One LLM call per table; the model returns batch JSON for the table description
plus all column descriptions. Reads relational_mapping.json for accurate FK
targets. Retries on 529 overload with exponential backoff.
"""

import json
import re
import sys
import time
from pathlib import Path

from openai import OpenAI

API_KEY = "sk-cp-MROGqoQmQHUaooqkGNBZRUpsCXwjc9w2zSWPLW9JFZ5hAROk13S35faan4bWqAN7r-HaVc-NzKFX4Ebwq8HDZKjNPCDDuaFm6JCE--NhKWfqFJPqPC7SjGQ"
client = OpenAI(base_url="https://api.minimax.io/v1", api_key=API_KEY)

MODEL = "MiniMax-M3"
MAX_TOKENS = 4000
MAX_RETRIES = 5

PLACEHOLDERS = [
    "table in ", "database", "required", "auto-increment", "primary key",
    "foreign key", "index", "unique", "not null", "default", "constraint",
    "bigint", "varchar", "char", "int", "text", "datetime", "timestamp",
    "enum", "boolean", "float", "double", "decimal", " column",
]


def is_placeholder(text: str) -> bool:
    if not text or not text.strip():
        return True
    return any(p in text.lower() for p in PLACEHOLDERS)


def strip_think(text: str) -> str:
    return re.sub(r"ThinkTag.*?CloseTag", "", text, flags=re.DOTALL).strip()


def call_llm(prompt: str) -> str:
    delay = 3.0
    for attempt in range(MAX_RETRIES):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                temperature=0.2,
            )
            return strip_think(r.choices[0].message.content or "")
        except Exception as e:
            msg = str(e)
            overloaded = "529" in msg or "overloaded" in msg.lower()
            if overloaded and attempt < MAX_RETRIES - 1:
                print(f"    overload (try {attempt + 1}/{MAX_RETRIES}), wait {delay:.0f}s", file=sys.stderr)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            print(f"    API error: {e}", file=sys.stderr)
            return ""
    return ""


def extract_json(text: str):
    if not text:
        return None
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```", "", text).strip()

    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*?\"table_description\"[\s\S]*?\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def load_relationships(path: str = "relational_mapping.json") -> dict[str, list[dict]]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, list[dict]] = {}
    for rel in data.get("relationships", []):
        out.setdefault(rel["from_table"], []).append(rel)
    return out


def build_fk_map(table: dict, rels: list[dict]) -> dict[str, tuple[str, str]]:
    fk_map: dict[str, tuple[str, str]] = {}
    for rel in rels:
        to_table = rel["to_table"]
        to_cols = rel.get("to_columns") or ["id"]
        for i, col in enumerate(rel.get("from_columns", [])):
            target = to_cols[i] if i < len(to_cols) else to_cols[0]
            fk_map[col] = (to_table, target)
    pk = table.get("primary_key")
    for c in table.get("columns", []):
        cn = c["col_name"]
        if cn not in fk_map and cn.endswith("_id") and cn != pk and cn != "id":
            fk_map[cn] = (cn[:-3], "id")
    return fk_map


def build_table_prompt(table: dict, fk_map: dict[str, tuple[str, str]]) -> str:
    cols = table.get("columns", [])
    pk = table.get("primary_key") or "unknown"

    col_lines = []
    for c in cols:
        cn = c["col_name"]
        dt = c.get("data_type", "unknown")
        if cn == pk:
            col_lines.append(f"  - {cn} ({dt}) [PRIMARY KEY]")
        elif cn in fk_map:
            tgt, tgt_col = fk_map[cn]
            col_lines.append(f"  - {cn} ({dt}) [FOREIGN KEY -> {tgt}.{tgt_col}]")
        else:
            col_lines.append(f"  - {cn} ({dt})")

    fk_summary = "; ".join(f"{c} -> {t}.{tc}" for c, (t, tc) in fk_map.items()) or "none"

    return f"""You are a Senior Data Architect writing business-facing documentation.

Table: {table['table_name']}
Primary key: {pk}
Relationships (foreign keys): {fk_summary}

All columns:
{chr(10).join(col_lines)}

Write business-facing descriptions for this table and ALL {len(cols)} columns. Be specific to the business domain implied by the column names (e.g. AI agents, billing, conversations). Avoid technical jargon (no data types, indexes, constraints, primary/foreign key terms).

Return ONLY this exact JSON format. No markdown, no code blocks, no commentary:

{{"table_description":"<2-3 sentence business description>","columns":[{{"col_name":"<EXACT column name from list above>","description":"<1-2 sentence business description>"}},...]}}

You MUST include one entry for EACH of the {len(cols)} columns listed above. Use the EXACT col_name strings as they appear.
"""


def fallback_descriptions(table: dict) -> tuple[str, dict[str, str]]:
    name = table["table_name"]
    pk = table.get("primary_key")
    fk_hints = [
        c["col_name"][:-3]
        for c in table.get("columns", [])
        if c["col_name"].endswith("_id") and c["col_name"] != pk and c["col_name"] != "id"
    ]
    table_desc = f"Stores {name.replace('_', ' ')} records for the platform."
    if fk_hints:
        table_desc += f" Links to: {', '.join(fk_hints)}."
    col_desc = {
        c["col_name"]: c.get("description") or f"{c['col_name'].replace('_', ' ').title()} field."
        for c in table.get("columns", [])
    }
    return table_desc, col_desc


def main(input_path: str = "schema.json", output_path: str = "schema_enriched.json") -> None:
    with open(input_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    tables = schema.get("tables", [])
    rels_map = load_relationships()

    print(f"Processing {len(tables)} table(s) one at a time\n")

    for i, table in enumerate(tables):
        tname = table["table_name"]
        cols = table.get("columns", [])

        needs_table = is_placeholder(table.get("description", ""))
        needs_cols = [c for c in cols if is_placeholder(c.get("description", ""))]

        if not needs_table and not needs_cols:
            print(f"[{i + 1}/{len(tables)}] {tname}: already complete, skipping")
            continue

        print(f"[{i + 1}/{len(tables)}] {tname} ({len(cols)} cols, {len(needs_cols)} need desc)")

        rels = rels_map.get(tname, [])
        fk_map = build_fk_map(table, rels)
        prompt = build_table_prompt(table, fk_map)
        response = call_llm(prompt)
        result = extract_json(response)

        if result:
            if needs_table:
                td = (result.get("table_description") or "").strip()
                if td:
                    table["description"] = td
                    print(f"  table: {td[:80]}...")

            col_map = {
                (c.get("col_name") or ""): (c.get("description") or "").strip()
                for c in result.get("columns", [])
            }
            matched = 0
            for col in cols:
                cn = col["col_name"]
                if cn in col_map and col_map[cn]:
                    col["description"] = col_map[cn]
                    matched += 1
            print(f"  columns: {matched}/{len(cols)} updated")
        else:
            print("  parse failed, using fallback")
            td, col_desc = fallback_descriptions(table)
            if needs_table:
                table["description"] = td
            for col in cols:
                if is_placeholder(col.get("description", "")):
                    col["description"] = col_desc.get(col["col_name"], col.get("description", ""))

        time.sleep(1.5)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
