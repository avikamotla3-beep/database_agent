import json
import re
import ollama

# ==============================
# CONFIGURATION
# ==============================
OLLAMA_MODEL = "llama3.2"
SCHEMA_FILE = "schema.json"
OUTPUT_FILE = "schema_enhanced.json"


def build_prompt(table_name, columns):
    """Build compact prompt. Limit columns to avoid token overflow."""
    display_cols = columns[:20]
    truncated = len(columns) > 20
    
    column_list = "\n".join([
        f"- {c['col_name']} ({c['data_type']})" 
        for c in display_cols
    ])
    if truncated:
        column_list += f"\n- ... ({len(columns) - 20} more columns)"
    
    # Infer FKs
    fk_lines = []
    for col in columns:
        cn = col['col_name']
        if cn.endswith('_id') and cn != 'id':
            fk_lines.append(f"- {cn}")
    fk_str = "\n".join(fk_lines) if fk_lines else "- None"
    
    # Infer PK
    pk = "- id (inferred)" if any(c['col_name'] == 'id' for c in columns) else "- None"
    
    prompt = f"""You are a Senior Data Architect. Generate descriptions.

Table: {table_name}
Columns:
{column_list}

Primary Keys:
{pk}

Foreign Keys:
{fk_str}

Return ONLY this exact JSON format. No markdown, no explanation, no code blocks:

{{"table_description":"concise business description","columns":[{{"column_name":"col1","description":"desc1"}},{{"column_name":"col2","description":"desc2"}}]}}

Generate descriptions for ALL {len(columns)} columns."""
    
    return prompt


def call_llama(prompt):
    """Call Llama via Ollama Python SDK."""
    try:
        response = ollama.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={
                'temperature': 0.1,
                'num_predict': 2048
            }
        )
        return response['response'].strip()
    except Exception as e:
        print(f"    ⚠️  SDK Error: {e}")
        return None


def extract_json(text):
    """Aggressively extract JSON from messy LLM output."""
    if not text:
        return None
    
    # Remove markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    
    # Method 1: Look for outermost braces
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    continue
    
    # Method 2: Try entire text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Method 3: Find anything that looks like JSON
    match = re.search(r'\{[\s\S]*?"table_description"[\s\S]*?\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    
    return None


def clean_output(schema):
    """Remove ALL non-standard fields from the entire schema."""
    for table in schema.get('tables', []):
        allowed_table = {'table_name', 'table_description', 'columns'}
        for key in list(table.keys()):
            if key not in allowed_table:
                del table[key]
        
        for col in table.get('columns', []):
            allowed_col = {'col_name', 'data_type', 'description'}
            for key in list(col.keys()):
                if key not in allowed_col:
                    del col[key]
    return schema


def generate_fallback(table_name, columns):
    """Generate fallback descriptions when LLM fails."""
    return {
        "table_description": f"{table_name.replace('_', ' ').title()} table.",
        "columns": [
            {
                "column_name": c['col_name'],
                "description": f"{c['col_name'].replace('_', ' ').title()} of type {c['data_type']}."
            }
            for c in columns
        ]
    }


def process_schema():
    """Main processing function."""
    
    print("=" * 70)
    print("  ENTERPRISE SCHEMA DESCRIPTION GENERATOR")
    print("  Model: Llama 3.2 | Role: Senior Data Architect")
    print("=" * 70)
    
    # Load schema
    with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    
    total_tables = len(schema.get('tables', []))
    print(f"\n📊 Found {total_tables} table(s) in {SCHEMA_FILE}\n")
    
    # Process each table
    for t_idx, table in enumerate(schema['tables']):
        table_name = table.get('table_name', f'table_{t_idx}')
        columns = table.get('columns', [])
        
        print("─" * 70)
        print(f"📋 [{t_idx+1}/{total_tables}] Processing: {table_name}")
        print(f"   Columns: {len(columns)}")
        print("─" * 70)
        
        # Build prompt
        prompt = build_prompt(table_name, columns)
        
        print("   ⏳ Calling Llama 3.2...")
        response = call_llama(prompt)
        
        # Extract JSON
        result = extract_json(response)
        
        if result:
            print("   ✅ JSON parsed successfully")
            
            table['table_description'] = result.get('table_description', 
                f"{table_name.replace('_', ' ').title()} table.")
            
            col_map = {c['column_name']: c['description'] 
                      for c in result.get('columns', [])}
            
            matched = 0
            for col in columns:
                cn = col['col_name']
                if cn in col_map:
                    col['description'] = col_map[cn]
                    matched += 1
                else:
                    col['description'] = f"{cn.replace('_', ' ').title()} of type {col['data_type']}."
            
            print(f"   📝 Matched {matched}/{len(columns)} columns")
        else:
            print("   ⚠️  Could not parse JSON, using fallback")
            fallback = generate_fallback(table_name, columns)
            table['table_description'] = fallback['table_description']
            for col in columns:
                col['description'] = f"{col['col_name'].replace('_', ' ').title()} of type {col['data_type']}."
        
        print()
    
    # Clean ALL metadata before saving
    print("🧹 Cleaning output...")
    schema = clean_output(schema)
    
    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    
    print("=" * 70)
    print(f"✅ COMPLETE — Saved to: {OUTPUT_FILE}")
    print("=" * 70)
    
    # Verify no metadata fields
    print("\n🔍 Verifying clean output...")
    dirty = False
    for table in schema['tables']:
        for key in table.keys():
            if key not in {'table_name', 'table_description', 'columns'}:
                print(f"   ❌ Dirty field found: {key}")
                dirty = True
        for col in table['columns']:
            for key in col.keys():
                if key not in {'col_name', 'data_type', 'description'}:
                    print(f"   ❌ Dirty field found: {key}")
                    dirty = True
    if not dirty:
        print("   ✅ Output is clean — no metadata fields")
    
    # Print sample
    print("\n📋 SAMPLE OUTPUT:")
    for table in schema['tables'][:2]:
        print(f"\n  Table: {table['table_name']}")
        print(f"  Desc:  {table.get('table_description', 'N/A')}")
        for col in table['columns'][:3]:
            print(f"    • {col['col_name']}: {col['description'][:55]}...")


if __name__ == '__main__':
    process_schema()