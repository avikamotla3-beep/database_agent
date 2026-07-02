"""
mysql_connection.py
===================
Handles the physical MySQL connection only.
"""

import os
from typing import Optional

import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()


class MySQLConnection:
    """Manages the MySQL connection lifecycle."""

    def __init__(self):
        self.host = os.getenv("MYSQL_HOST", "localhost")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.user = os.getenv("MYSQL_USER")
        self.password = os.getenv("MYSQL_PASSWORD")
        self.database = os.getenv("MYSQL_DATABASE")

        self.connection: Optional[mysql.connector.MySQLConnection] = None
        self.cursor: Optional[mysql.connector.cursor.MySQLCursorDict] = None

    def connect(self) -> None:
        """Open a new dictionary-cursor connection."""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                autocommit=True,
                connection_timeout=10,
                use_pure=True,
            )
            self.cursor = self.connection.cursor(dictionary=True)
            print("[MySQLConnection] Connected.")
        except Error as e:
            raise RuntimeError(f"MySQL Connection Error: {e}")

    def ensure_alive(self) -> None:
        """Ping server; reconnect if dead."""
        try:
            if self.connection is None or not self.connection.is_connected():
                self.connect()
            else:
                self.connection.ping(reconnect=True, attempts=2, delay=1)
        except Error:
            self.close()
            self.connect()

    def close(self) -> None:
        """Gracefully close connection."""
        if self.cursor:
            try:
                self.cursor.close()
            except Error:
                pass
            self.cursor = None
        if self.connection:
            try:
                self.connection.close()
            except Error:
                pass
            self.connection = None
        print("[MySQLConnection] Closed.")

    def health_check(self) -> dict:
        """Verify connection is alive."""
        try:
            self.ensure_alive()
            self.cursor.execute("SELECT DATABASE() AS db")
            db = self.cursor.fetchone()["db"]
            return {"status": "healthy", "database": db}
        except Error as e:
            return {"status": "unhealthy", "error": str(e)}