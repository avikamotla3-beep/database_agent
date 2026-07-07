"""
Adapter for mysql_connection.py + mysql_security.py
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

tools_dir = Path(__file__).parent.parent / "tools"
if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

try:
    import mysql_connection as mc
    import mysql_security as ms
except ImportError:
    mc = None
    ms = None


class MySQLAdapter:
    def __init__(self):
        self.config = {
            "host": os.getenv("MYSQL_HOST", "localhost"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER", "root"),
            "password": os.getenv("MYSQL_PASSWORD", ""),
            "database": os.getenv("MYSQL_DATABASE", "")
        }
        self._connection = None

    def _get_connection(self):
        if self._connection is None:
            if mc is not None:
                self._connection = mc.connect(**self.config)
            else:
                raise RuntimeError("mysql_connection.py not found in tools/")
        return self._connection

    def validate_query(self, sql: str) -> Tuple[bool, Optional[str]]:
        if ms is not None:
            return ms.validate(sql)
        dangerous = ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT", "REVOKE"]
        upper = sql.upper()
        for keyword in dangerous:
            if keyword in upper and keyword + " TABLE" in upper:
                return False, f"Blocked dangerous operation: {keyword}"
        return True, None

    def execute(self, sql: str, params: tuple = None) -> Dict[str, Any]:
        is_safe, reason = self.validate_query(sql)
        if not is_safe:
            return {
                "success": False,
                "error": f"Security block: {reason}",
                "rows": [], "row_count": 0, "columns": []
            }
        conn = self._get_connection()
        try:
            if mc is not None:
                result = mc.execute_query(conn, sql, params)
            else:
                raise RuntimeError("mysql_connection.py not available")
            return {
                "success": True,
                "error": None,
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "columns": result.get("columns", [])
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "rows": [], "row_count": 0, "columns": []
            }

    def execute_raw(self, sql: str) -> List[Dict]:
        return self.execute(sql).get("rows", [])

    def close(self):
        if self._connection and mc is not None:
            mc.close(self._connection)
            self._connection = None


_adapter = None

def _get_adapter():
    global _adapter
    if _adapter is None:
        _adapter = MySQLAdapter()
    return _adapter

def validate_query(sql: str) -> Tuple[bool, Optional[str]]:
    return _get_adapter().validate_query(sql)

def execute(sql: str, params: tuple = None) -> Dict[str, Any]:
    return _get_adapter().execute(sql, params)

def execute_raw(sql: str) -> List[Dict]:
    return _get_adapter().execute_raw(sql)
