"""
neo4j_tool.py

Neo4j Tool for AI Database Agent

Purpose
-------
This tool queries the graph stored in Neo4j.

Compatible Graph:

(Table)-[:HAS_COLUMN]->(Column)
(Column)-[:REFERENCES]->(Column)

Author : ChatGPT
"""

from __future__ import annotations

import os
import logging
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

load_dotenv()

# ============================================================
# Configuration
# ============================================================

NEO4J_URI = os.getenv(
    "NEO4J_URI",
    "neo4j://127.0.0.1:7687"
)

NEO4J_USERNAME = os.getenv(
    "NEO4J_USERNAME",
    "neo4j"
)

NEO4J_PASSWORD = os.getenv(
    "NEO4J_PASSWORD",
    "AVK@1234"
)

NEO4J_DATABASE = os.getenv(
    "NEO4J_DATABASE",
    "neo4j"
)

logging.basicConfig(
    level=logging.INFO,
    format="[Neo4jTool] %(message)s"
)


# ============================================================
# Neo4j Tool
# ============================================================

class Neo4jTool:

    """
    Helper class for querying Neo4j.
    """

    ###########################################################

    def __init__(self):

        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(
                NEO4J_USERNAME,
                NEO4J_PASSWORD
            )
        )

        logging.info("Connected to Neo4j.")

    ###########################################################

    def close(self):

        """
        Close driver.
        """

        if self.driver:

            self.driver.close()

            logging.info("Neo4j connection closed.")

    ###########################################################

    def _run_query(
        self,
        query: str,
        **params
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query and return
        list of dictionaries.
        """

        try:

            with self.driver.session(
                database=NEO4J_DATABASE
            ) as session:

                result = session.run(
                    query,
                    **params
                )

                return [
                    dict(record)
                    for record in result
                ]

        except Neo4jError as e:

            logging.error(e)

            return []

    ###########################################################

    def health_check(
        self
    ) -> Dict[str, Any]:

        """
        Verify connection.
        """

        query = """
        MATCH (n)

        RETURN count(n) AS total_nodes
        """

        result = self._run_query(query)

        if not result:

            return {

                "status": "unhealthy"

            }

        return {

            "status": "healthy",

            "database": NEO4J_DATABASE,

            "total_nodes": result[0]["total_nodes"]

        }

    ###########################################################

    def get_graph_statistics(
        self
    ) -> Dict[str, int]:

        query = """
        MATCH (t:Table)

        WITH count(t) AS tables

        MATCH (c:Column)

        WITH tables,count(c) AS columns

        MATCH ()-[r]->()

        RETURN

        tables,

        columns,

        count(r) AS relationships
        """

        result = self._run_query(query)

        if not result:

            return {}

        return result[0]

    ###########################################################

    def table_exists(
        self,
        table_name: str
    ) -> bool:

        query = """
        MATCH (t:Table)

        WHERE t.name=$table

        RETURN count(t) AS total
        """

        result = self._run_query(

            query,

            table=table_name

        )

        return bool(result and result[0]["total"] > 0)

    ###########################################################

    def get_columns(
        self,
        table_name: str
    ) -> List[Dict]:

        """
        Get all columns of a table.
        """

        query = """
        MATCH (t:Table)-[:HAS_COLUMN]->(c:Column)

        WHERE t.name=$table

        RETURN

        c.name AS column_name

        ORDER BY c.name
        """

        result = self._run_query(

            query,

            table=table_name

        )

        return result

    ###########################################################

    def get_table(
        self,
        table_name: str
    ) -> Optional[Dict]:

        query = """
        MATCH (t:Table)

        WHERE t.name=$table

        RETURN

        t.id AS id,

        t.name AS name
        """

        result = self._run_query(

            query,

            table=table_name

        )

        if not result:

            return None

        return result[0]
        ###########################################################
    # Get Neighbor Tables
    ###########################################################

    def get_neighbors(
        self,
        table_name: str
    ) -> List[Dict]:
        """
        Find all tables connected to the given table.

        Traverses:

        Table
            ↓
        HAS_COLUMN
            ↓
        Column
            ↓
        REFERENCES
            ↓
        Column
            ↓
        HAS_COLUMN
            ↓
        Table
        """

        query = """
        MATCH (t1:Table)-[:HAS_COLUMN]->(c1:Column)
              -[:REFERENCES]->
              (c2:Column)<-[:HAS_COLUMN]-
              (t2:Table)

        WHERE t1.name=$table

        RETURN DISTINCT

            t2.name AS related_table,

            c1.name AS source_column,

            c2.name AS target_column

        ORDER BY related_table
        """

        return self._run_query(
            query,
            table=table_name
        )

    ###########################################################
    # Alias
    ###########################################################

    def get_relationships(
        self,
        table_name: str
    ) -> List[Dict]:

        return self.get_neighbors(table_name)

    ###########################################################
    # Shortest Path
    ###########################################################

    def find_shortest_path(
        self,
        source_table: str,
        target_table: str
    ) -> Dict:

        """
        Find shortest path between two tables.
        """

        query = """
        MATCH (start:Table {name:$source}),
              (end:Table {name:$target})

        MATCH p = shortestPath(

            (start)-[:HAS_COLUMN|REFERENCES*..20]-(end)

        )

        RETURN p
        """

        try:

            with self.driver.session(
                database=NEO4J_DATABASE
            ) as session:

                record = session.run(
                    query,
                    source=source_table,
                    target=target_table
                ).single()

                if record is None:

                    return {
                        "found": False,
                        "path": []
                    }

                path = record["p"]

                nodes = []

                for node in path.nodes:

                    if "Table" in node.labels:

                        nodes.append({
                            "type": "Table",
                            "name": node["name"]
                        })

                    elif "Column" in node.labels:

                        nodes.append({
                            "type": "Column",
                            "name": node["name"]
                        })

                return {

                    "found": True,

                    "length": len(path.relationships),

                    "path": nodes

                }

        except Exception as e:

            logging.error(e)

            return {

                "found": False,

                "path": []

            }

    ###########################################################
    # Join Path
    ###########################################################

    def find_join_path(
        self,
        tables: List[str]
    ) -> Dict:

        """
        Build join path for multiple tables.
        """

        joins = []

        if len(tables) < 2:

            return {

                "tables": tables,

                "joins": []

            }

        for i in range(len(tables) - 1):

            joins.append(

                self.find_shortest_path(

                    tables[i],

                    tables[i + 1]

                )

            )

        return {

            "tables": tables,

            "joins": joins

        }

    ###########################################################
    # Pretty Print
    ###########################################################

    def pretty_print(
        self,
        data
    ):

        from pprint import pprint

        pprint(data)

    ###########################################################
    # Destructor
    ###########################################################

    def __del__(self):

        try:

            self.close()

        except Exception:

            pass


###############################################################
# Demo
###############################################################

if __name__ == "__main__":

    tool = Neo4jTool()

    print("\n" + "=" * 60)
    print("Neo4j Tool Demo")
    print("=" * 60)

    print("\nHealth Check\n")
    tool.pretty_print(
        tool.health_check()
    )

    print("\nGraph Statistics\n")
    tool.pretty_print(
        tool.get_graph_statistics()
    )

    sample_table = "tenant_invoices"

    print("\nTable Exists\n")
    print(
        tool.table_exists(
            sample_table
        )
    )

    print("\nColumns\n")
    tool.pretty_print(
        tool.get_columns(
            sample_table
        )
    )

    print("\nNeighbors\n")
    tool.pretty_print(
        tool.get_neighbors(
            sample_table
        )
    )

    print("\nShortest Path\n")
    tool.pretty_print(

        tool.find_shortest_path(

            "tenant_invoices",

            "plans"

        )

    )

    print("\nJoin Path\n")
    tool.pretty_print(

        tool.find_join_path(

            [

                "tenant_invoices",

                "plans"

            ]

        )

    )

    tool.close()