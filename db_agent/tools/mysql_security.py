"""
mysql_security.py
=================
Validates SQL, runs EXPLAIN, analyzes cost.
"""

import re
from typing import Dict, Any, List


class MySQLSecurity:
    """Read-only SQL validator and cost analyzer."""

    ALLOWED_STATEMENTS = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}
    FORBIDDEN_KEYWORDS = {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
        "TRUNCATE", "REPLACE", "RENAME", "GRANT", "REVOKE",
        "LOCK", "UNLOCK", "CALL", "EXECUTE", "LOAD", "LOAD_FILE",
    }

    FULL_SCAN_ROW_THRESHOLD = 100_000
    LARGE_ROW_THRESHOLD = 500_000

    @staticmethod
    def strip_comments(sql: str) -> str:
        """Remove /* */ and -- comments."""
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
        sql = re.sub(r"--[^\n]*", " ", sql)
        sql = re.sub(r"#[^\n]*", " ", sql)
        return sql

    def get_statement_type(self, sql: str) -> str:
        """First keyword after stripping comments."""
        clean = self.strip_comments(sql).strip()
        if not clean:
            return "UNKNOWN"
        return clean.split()[0].upper()

    def validate(self, sql: str) -> Dict[str, Any]:
        """Two-layer validation: allow-list + forbidden keyword scan."""
        stripped = sql.strip()
        if not stripped:
            return {"success": False, "error": "Empty SQL query."}

        statement = self.get_statement_type(stripped)
        if statement not in self.ALLOWED_STATEMENTS:
            return {"success": False, "error": f"{statement} statements are not allowed."}

        upper = self.strip_comments(stripped).upper()
        for keyword in self.FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper):
                return {"success": False, "error": f"Forbidden keyword detected: {keyword}"}

        return {"success": True, "statement": statement}

    def inject_max_execution_time(self, sql: str, timeout_ms: int = 5000) -> str:
        """Insert MAX_EXECUTION_TIME hint after SELECT or WITH."""
        match = re.search(
            r"^(\s*/\*.*?\*/\s*)?(\s*)(SELECT|WITH)\b",
            sql,
            re.IGNORECASE,
        )
        if not match:
            return sql
        return sql[:match.end()] + f" /*+ MAX_EXECUTION_TIME({timeout_ms}) */" + sql[match.end():]

    def analyze_cost(self, plan_rows: List[Dict]) -> List[str]:
        """Inspect EXPLAIN plan for expensive scans."""
        warnings: List[str] = []
        for row in plan_rows:
            access_type = row.get("type", "")
            est_rows = row.get("rows", 0) or 0
            table = row.get("table", "Unknown")

            if access_type == "ALL" and est_rows > self.FULL_SCAN_ROW_THRESHOLD:
                warnings.append(
                    f"Large full table scan on '{table}' (est. {est_rows:,} rows)."
                )
            elif est_rows > self.LARGE_ROW_THRESHOLD:
                warnings.append(
                    f"Query may process ~{est_rows:,} rows."
                )
        return warnings