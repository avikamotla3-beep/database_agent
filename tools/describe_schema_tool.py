#!/usr/bin/env python3
"""
describe_ollama.py

Generate business-facing descriptions using local Llama 3.2 via Ollama.
No API key needed. Runs entirely locally.
"""

import json
import requests
import argparse


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"


def generate_with_ollama(prompt):
    """Call local Ollama API."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"    [ERROR] {e}")
        return ""


def generate_table_desc(table):
    cols = ", ".join([f"{c['col_name']} ({c['data_type']})" for c in table['columns'][:8]])
    if len(table['columns']) > 8:
        cols += f", ... and {len(table['columns']) - 8} more"

    prompt = f"""Generate a single-paragraph business-facing description (2-3 sentences) for this database table.

Table: {table['table_name']}
Columns: {cols}
Primary Key: {table.get('primary_key', 'N/A')}

Describe what business purpose this table serves, what data it stores, and how it relates to the overall system. Be specific and professional."""

    return generate_with_ollama(prompt)


def generate_column_desc(col, table_name):
    prompt = f"""Generate a single concise sentence describing this database column in business terms.

Table: {table_name}
Column: {col['col_name']}
Data Type: {col['data_type']}

Explain what this column represents and its business significance. Be specific and professional."""

    return generate_with_ollama(prompt)


def main():
    parser = argparse.ArgumentParser(description='Enrich schema with Llama 3.2 descriptions via Ollama')
    parser.add_argument('--input', '-i', required=True, help='Input schema_enriched.json')
    parser.add_argument('--output', '-o', default=None, help='Output file')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    print(f"[✓] Loaded: {schema['database_name']} ({schema['total_tables']} tables)")
    print(f"[✓] Using local model: {MODEL}")
    print(f"[✓] Make sure Ollama is running: ollama run {MODEL}")

    output_path = args.output or args.input
    total_tables = len(schema['tables'])
    total_cols = sum(len(t['columns']) for t in schema['tables'])

    print(f"[...] Enriching {total_tables} tables, {total_cols} columns...")

    for i, table in enumerate(schema['tables']):
        print(f"\n  [{i+1}/{total_tables}] {table['table_name']}")

        if not table.get('description'):
            print("    Table desc: generating...")
            table['description'] = generate_table_desc(table)
            print(f"    [✓] {table['description'][:80]}..." if table['description'] else "    [!] Failed")
        else:
            print("    [SKIP] Table has description")

        for col in table['columns']:
            if not col.get('description'):
                print(f"    Col '{col['col_name']}': generating...")
                col['description'] = generate_column_desc(col, table['table_name'])
                print(f"      [✓] {col['description'][:60]}..." if col['description'] else "      [!] Failed")
            else:
                print(f"    Col '{col['col_name']}': [SKIP]")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] Saved to: {output_path}")


if __name__ == '__main__':
    main()