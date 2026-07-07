"""
mysql_tool.py
=============
Main orchestrator. Uses mysql_connection for the wire,
uses mysql_security for validation and cost analysis.
"""

import time
from typing import Dict, Any, List, Tuple, Optional

import mysql.connector
from mysql.connector import Error

from mysql_connection import MySQLConnection
from mysql_security import MySQLSecurity


class MySQLTool:
    """
    Read-only MySQL execution engine for LLM-generated SQL.
    """

    DEFAULT_ROW_LIMIT = 10_000

    def __init__(self):
        self.conn = MySQLConnection()
        self.conn.connect()
        self.security = MySQLSecurity()

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------
    # Internal runner
    # ---------------------------------------------------------

    def _run(self, sql: str) -> Tuple[List[Dict], List[str]]:
        """Execute and fetch. Returns (rows, column_names)."""
        self.conn.ensure_alive()
        self.conn.cursor.execute(sql)
        rows = self.conn.cursor.fetchall()
        columns = [col[0] for col in self.conn.cursor.description] if self.conn.cursor.description else []
        return rows, columns

    def _format_result(
        self,
        statement: str,
        rows: List[Dict],
        columns: List[str],
        execution_time: float,
        warnings: Optional[List[str]] = None,
        plan: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Uniform JSON output."""
        return {
            "success": True,
            "statement": statement,
            "row_count": len(rows),
            "columns": columns,
            "rows": rows[: self.DEFAULT_ROW_LIMIT],
            "execution_time_ms": round(execution_time * 1000, 2),
            "warnings": warnings or [],
            "execution_plan": plan or [],
        }

    # ---------------------------------------------------------
    # Pretty-print (human-readable)
    # ---------------------------------------------------------

    @staticmethod
    def _pretty_print(result: Dict[str, Any], table_name: Optional[str] = None) -> None:
        """Print results in clean format."""
        if not result.get("success"):
            print(f"[ERROR] {result.get('error', 'Unknown error')}")
            return

        statement = result.get("statement", "UNKNOWN")
        rows = result.get("rows", [])
        columns = result.get("columns", [])
        row_count = result.get("row_count", 0)
        exec_time = result.get("execution_time_ms", 0)
        warnings = result.get("warnings", [])
        plan = result.get("execution_plan", [])

        # DESCRIBE → compact schema card
        if statement in ("DESCRIBE", "DESC"):
            name = table_name or "table"
            pk = next((r["Field"] for r in rows if r.get("Key") == "PRI"), "(none)")
            col_names = [r.get("Field", "") for r in rows]
            relevant = ", ".join(col_names[:8])
            if len(col_names) > 8:
                relevant += f", ... ({len(col_names) - 8} more)"

            print(f"\n{name}  (Score=0.000)")
            print(f"   PK     : {pk}")
            print(f"   Columns: {len(rows)}")
            print(f"   Desc   : Schema for {name}.")
            print(f"   Relevant Columns: {relevant}")
            return

        # EXPLAIN / Cost Analysis
        if statement == "EXPLAIN" or (plan and not rows):
            print(f"\nExecution Plan ({len(plan)} steps):")
            for step in plan:
                print(f"   {step.get('table','—'):<20} {step.get('type','—'):<10} ~{step.get('rows','—')} rows")
            if warnings:
                print("Warnings:")
                for w in warnings:
                    print(f"   ⚠ {w}")
            return

        # SELECT / WITH
        print(f"\nResult: {statement} | {row_count} rows | {exec_time} ms")

        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"   ⚠ {w}")

        if plan:
            print("Plan:")
            for step in plan:
                print(f"   {step.get('table','—')}: {step.get('type','—')} (~{step.get('rows','—')} rows)")

        if not rows:
            print("(no rows)")
            return

        print(f"\nRelevant Columns: {', '.join(columns)}")

        print("\nSample rows:")
        for i, row in enumerate(rows[:5]):
            vals = [str(row.get(c, "NULL"))[:25] for c in columns]
            print(f"   Row {i+1}: {' | '.join(vals)}")

        if row_count > 5:
            print(f"   ... and {row_count - 5} more rows")

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def execute_query(self, sql: str) -> Dict[str, Any]:
        """Validate, execute, return structured result."""
        validation = self.security.validate(sql)
        if not validation["success"]:
            return validation

        statement = validation["statement"]

        try:
            if statement in ("SELECT", "WITH"):
                return self._execute_select(sql)
            elif statement == "SHOW":
                return self._execute_show(sql)
            elif statement in ("DESCRIBE", "DESC"):
                return self._execute_describe(sql)
            elif statement == "EXPLAIN":
                return self._execute_explain(sql)
            else:
                return {"success": False, "error": f"Unsupported: {statement}"}
        except Error as e:
            return {"success": False, "error": str(e)}

    def explain_query(self, sql: str) -> Dict[str, Any]:
        """Run EXPLAIN on SELECT/WITH."""
        validation = self.security.validate(sql)
        if not validation["success"]:
            return validation
        if validation["statement"] not in ("SELECT", "WITH"):
            return {"success": False, "error": "EXPLAIN only for SELECT/WITH"}

        try:
            self.conn.ensure_alive()
            self.conn.cursor.execute(f"EXPLAIN {sql}")
            plan = self.conn.cursor.fetchall()
            return {
                "success": True,
                "statement": "EXPLAIN",
                "row_count": len(plan),
                "columns": ["table", "type", "rows"],
                "rows": plan,
                "execution_time_ms": 0,
                "warnings": [],
                "execution_plan": plan,
            }
        except Error as e:
            return {"success": False, "error": str(e)}

    def analyze_cost(self, sql: str) -> Dict[str, Any]:
        """EXPLAIN + cost warnings."""
        explain = self.explain_query(sql)
        if not explain["success"]:
            return explain

        warnings = self.security.analyze_cost(explain["execution_plan"])
        return {
            "success": True,
            "statement": "EXPLAIN",
            "row_count": len(explain["execution_plan"]),
            "columns": ["table", "type", "rows"],
            "rows": explain["execution_plan"],
            "execution_time_ms": 0,
            "warnings": warnings,
            "execution_plan": explain["execution_plan"],
        }

    # ---------------------------------------------------------
    # Statement executors (private)
    # ---------------------------------------------------------

    def _execute_select(self, sql: str) -> Dict[str, Any]:
        cost = self.analyze_cost(sql)
        if not cost["success"]:
            return cost

        sql = self.security.inject_max_execution_time(sql, 5000)

        start = time.perf_counter()
        rows, columns = self._run(sql)
        end = time.perf_counter()

        return self._format_result(
            statement="SELECT",
            rows=rows,
            columns=columns,
            execution_time=end - start,
            warnings=cost["warnings"],
            plan=cost["execution_plan"],
        )

    def _execute_show(self, sql: str) -> Dict[str, Any]:
        start = time.perf_counter()
        rows, columns = self._run(sql)
        end = time.perf_counter()
        return self._format_result("SHOW", rows, columns, end - start)

    def _execute_describe(self, sql: str) -> Dict[str, Any]:
        start = time.perf_counter()
        rows, columns = self._run(sql)
        end = time.perf_counter()
        return self._format_result("DESCRIBE", rows, columns, end - start)

    def _execute_explain(self, sql: str) -> Dict[str, Any]:
        start = time.perf_counter()
        rows, columns = self._run(sql)
        end = time.perf_counter()
        return self._format_result("EXPLAIN", rows, columns, end - start)

    # ---------------------------------------------------------
    # Demo
    # ---------------------------------------------------------

    def demo(self) -> None:
        print("\n" + "=" * 60)
        print("MySQL Tool Demo")
        print("=" * 60)

        print("\n--- Health Check ---")
        r = self.conn.health_check()
        print(f"  Status : {r.get('status')}")
        print(f"  DB     : {r.get('database')}")

        print("\n--- DESCRIBE tenants ---")
        r = self.execute_query("DESCRIBE tenants")
        self._pretty_print(r, table_name="tenants")

        print("\n--- SELECT * FROM tenants LIMIT 3 ---")
        r = self.execute_query("SELECT * FROM tenants LIMIT 3")
        self._pretty_print(r)

        print("\n--- EXPLAIN ---")
        r = self.explain_query("SELECT * FROM tenants LIMIT 5")
        self._pretty_print(r)

        print("\n--- Cost Analysis ---")
        r = self.analyze_cost("SELECT * FROM tenants LIMIT 5")
        self._pretty_print(r)

        print("\n--- Security (DELETE) ---")
        r = self.execute_query("DELETE FROM tenants")
        self._pretty_print(r)

        print("\n--- Security (DROP) ---")
        r = self.execute_query("DROP TABLE tenants")
        self._pretty_print(r)


if __name__ == "__main__":
    tool = MySQLTool()
    try:
        tool.demo()
    finally:
        tool.close()