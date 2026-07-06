#!/usr/bin/env python3
"""
schema_extractor.py

Self-contained tool that parses a MySQL dump file and generates
schema_enriched.json in the EXACT format expected by local_schema_tool.py.

Format:
{
  "database_name": "enveu_flow_db",
  "total_tables": 47,
  "tables": [
    {
      "table_name": "agent_conversation_messages",
      "description": "",
      "primary_key": "id",
      "columns": [
        {
          "col_name": "id",
          "data_type": "BIGINT",
          "description": ""
        }
      ]
    }
  ]
}

Usage:
    python schema_extractor.py --input dump.sql --output schema_enriched.json
"""

import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any


class MySQLSchemaExtractor:
    def __init__(self, dump_path: str):
        self.dump_path = Path(dump_path)
        self.raw_sql = ""
        self.database_name = ""
        self.tables: List[Dict[str, Any]] = []
        
    def load_dump(self) -> None:
        if not self.dump_path.exists():
            raise FileNotFoundError(f"Dump file not found: {self.dump_path}")
        with open(self.dump_path, 'r', encoding='utf-8', errors='ignore') as f:
            self.raw_sql = f.read()
        print(f"[✓] Loaded dump file: {self.dump_path} ({len(self.raw_sql):,} chars)")
    
    def extract_database_name(self) -> str:
        use_match = re.search(r'USE\s+`?([^`;\s]+)`?\s*;', self.raw_sql, re.IGNORECASE)
        if use_match:
            return use_match.group(1)
        db_match = re.search(r'CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`;\s]+)`?', self.raw_sql, re.IGNORECASE)
        if db_match:
            return db_match.group(1)
        return self.dump_path.stem
    
    def _clean_identifier(self, identifier: str) -> str:
        return identifier.strip().strip('`').strip()
    
    def _extract_create_table_blocks(self) -> List[tuple]:
        blocks = []
        create_pattern = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s(]+)`?\s*\(', re.IGNORECASE)
        
        for match in create_pattern.finditer(self.raw_sql):
            table_name = self._clean_identifier(match.group(1))
            start_idx = match.end()
            depth = 1
            pos = start_idx
            while pos < len(self.raw_sql) and depth > 0:
                if self.raw_sql[pos] == '(':
                    depth += 1
                elif self.raw_sql[pos] == ')':
                    depth -= 1
                pos += 1
            body = self.raw_sql[start_idx:pos-1]
            stmt_start = match.start()
            trailing = self.raw_sql[stmt_start:]
            semi_idx = trailing.find(';')
            full_stmt = trailing[:semi_idx + 1] if semi_idx != -1 else trailing
            blocks.append((table_name, body, full_stmt))
        return blocks
    
    def _parse_column_definition(self, col_def: str) -> Optional[Dict[str, Any]]:
        col_def = col_def.strip()
        if not col_def:
            return None
        col_pattern = r'^`?([^`\s]+)`?\s+([A-Za-z0-9_]+(?:\s*\([^)]*\))?)'
        match = re.match(col_pattern, col_def)
        if not match:
            return None
        col_name = self._clean_identifier(match.group(1))
        data_type = match.group(2).strip().upper()
        return {
            'col_name': col_name,
            'data_type': data_type,
            'description': ''
        }
    
    def _parse_table_body(self, table_name: str, body: str, full_stmt: str) -> Dict[str, Any]:
        table_schema = {
            'table_name': table_name,
            'description': '',
            'primary_key': None,
            'columns': []
        }
        lines = self._smart_split(body)
        for line in lines:
            line = line.strip()
            if not line:
                continue
            upper_line = line.upper()
            if upper_line.startswith('PRIMARY KEY'):
                pk_match = re.search(r'PRIMARY\s+KEY\s*\(([^)]+)\)', line, re.IGNORECASE)
                if pk_match:
                    pk_cols = [self._clean_identifier(c.strip()) for c in pk_match.group(1).split(',')]
                    table_schema['primary_key'] = pk_cols[0] if len(pk_cols) == 1 else pk_cols
                continue
            if upper_line.startswith('CONSTRAINT') and 'FOREIGN KEY' in upper_line:
                continue
            if any(upper_line.startswith(kw) for kw in ['UNIQUE KEY', 'UNIQUE INDEX', 'KEY', 'INDEX', 'FULLTEXT KEY', 'FULLTEXT INDEX', 'SPATIAL KEY', 'SPATIAL INDEX']):
                continue
            if upper_line.startswith('CONSTRAINT'):
                continue
            col = self._parse_column_definition(line)
            if col:
                table_schema['columns'].append(col)
        if table_schema['primary_key'] is None:
            inline_pk = re.findall(r'`?([^`\s]+)`?\s+[^,]+\s+PRIMARY\s+KEY', body, re.IGNORECASE)
            if inline_pk:
                table_schema['primary_key'] = inline_pk[0]
        return table_schema
    
    def _smart_split(self, body: str) -> List[str]:
        parts = []
        current = ""
        depth = 0
        in_quote = False
        quote_char = None
        for char in body:
            if not in_quote and char in "'\"":
                in_quote = True
                quote_char = char
                current += char
            elif in_quote and char == quote_char:
                if current and current[-1] == '\\':
                    current += char
                else:
                    in_quote = False
                    quote_char = None
                    current += char
            elif not in_quote:
                if char == '(':
                    depth += 1
                    current += char
                elif char == ')':
                    depth -= 1
                    current += char
                elif char == ',' and depth == 0:
                    parts.append(current)
                    current = ""
                else:
                    current += char
            else:
                current += char
        if current.strip():
            parts.append(current)
        return parts
    
    def extract_schema(self) -> Dict[str, Any]:
        self.load_dump()
        self.database_name = self.extract_database_name()
        print(f"[✓] Database name: {self.database_name}")
        blocks = self._extract_create_table_blocks()
        print(f"[✓] Found {len(blocks)} CREATE TABLE blocks")
        for table_name, body, full_stmt in blocks:
            try:
                table_schema = self._parse_table_body(table_name, body, full_stmt)
                self.tables.append(table_schema)
            except Exception as e:
                print(f"[!] Warning: Failed to parse table '{table_name}': {e}")
                continue
        schema = {
            'database_name': self.database_name,
            'total_tables': len(self.tables),
            'tables': self.tables
        }
        print(f"[✓] Successfully parsed {len(self.tables)} tables")
        return schema
    
    def save_schema(self, output_path: str, schema: Dict[str, Any]) -> None:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        print(f"[✓] Schema saved to: {output_file.absolute()}")
        print(f"    Database: {schema['database_name']}")
        print(f"    Tables: {schema['total_tables']}")
        print(f"    File size: {output_file.stat().st_size:,} bytes")


def main():
    parser = argparse.ArgumentParser(description='Extract schema from MySQL dump and generate schema_enriched.json')
    parser.add_argument('--input', '-i', required=True, help='Path to MySQL dump file (.sql)')
    parser.add_argument('--output', '-o', default='schema_enriched.json', help='Output JSON file path')
    args = parser.parse_args()
    extractor = MySQLSchemaExtractor(args.input)
    schema = extractor.extract_schema()
    extractor.save_schema(args.output, schema)
    print("\n[✓] Done! You can now load this with local_schema_tool.py")


if __name__ == '__main__':
    main()