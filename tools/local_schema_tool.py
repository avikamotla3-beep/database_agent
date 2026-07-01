import json
from pathlib import Path


class LocalSchemaTool:
    """
    Loads schema_enriched.json into memory and provides
    helper methods for querying database schema metadata.
    """

    def __init__(self, schema_file="schema_enriched.json"):

        self.schema_path = Path(schema_file)

        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")

        with open(self.schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

        self.database_name = self.schema.get("database_name")
        self.total_tables = self.schema.get("total_tables", 0)

        tables = self.schema.get("tables", [])

        # ==========================================================
        # FAST LOOKUP INDEXES
        # ==========================================================

        # table_name -> complete table object
        self.table_index = {}

        # column_name -> list of tables containing that column
        self.column_index = {}

        # datatype -> list of (table,column)
        self.datatype_index = {}

        # lowercase description -> table_name
        self.description_index = {}

        # Build all indexes only once
        for table in tables:

            table_name = table["table_name"]

            self.table_index[table_name] = table

            self.description_index[table_name] = (
                table.get("description", "").lower()
            )

            for column in table.get("columns", []):

                col_name = column["col_name"]

                self.column_index.setdefault(col_name.lower(), []).append(table_name)

                datatype = column.get("data_type", "").upper()

                self.datatype_index.setdefault(datatype, []).append(
                    {
                        "table": table_name,
                        "column": col_name
                    }
                )

    # ==========================================================
    # DATABASE INFORMATION
    # ==========================================================

    def get_database_name(self):
        return self.database_name

    def get_total_tables(self):
        return self.total_tables

    def summary(self):

        return {
            "database": self.database_name,
            "total_tables": self.total_tables
        }

    # ==========================================================
    # TABLE METHODS
    # ==========================================================

    def list_tables(self):
        return sorted(self.table_index.keys())

    def table_exists(self, table_name):
        return table_name in self.table_index

    def get_table(self, table_name):
        return self.table_index.get(table_name)

    def get_table_description(self, table_name):

        table = self.get_table(table_name)

        if table:
            return table.get("description")

        return None

    def get_primary_key(self, table_name):

        table = self.get_table(table_name)

        if table:
            return table.get("primary_key")

        return None

    # ==========================================================
    # COLUMN METHODS
    # ==========================================================

    def get_columns(self, table_name):

        table = self.get_table(table_name)

        if table:
            return table.get("columns", [])

        return []

    def get_column_names(self, table_name):

        return [
            column["col_name"]
            for column in self.get_columns(table_name)
        ]

    def get_column(self, table_name, column_name):

        for column in self.get_columns(table_name):

            if column["col_name"].lower() == column_name.lower():
                return column

        return None

    # ==========================================================
    # SEARCH METHODS
    # ==========================================================

    def search_tables(self, keyword):

        keyword = keyword.lower()

        matches = []

        for table in self.table_index:

            if keyword in table.lower():
                matches.append(table)

        return matches

    def search_tables_by_description(self, keyword):

        keyword = keyword.lower()

        matches = []

        for table, description in self.description_index.items():

            if keyword in description:
                matches.append(table)

        return matches

    def search_columns(self, keyword):

        keyword = keyword.lower()

        matches = []

        for table_name, table in self.table_index.items():

            for column in table.get("columns", []):

                if keyword in column["col_name"].lower():

                    matches.append({
                        "table": table_name,
                        "column": column["col_name"],
                        "datatype": column["data_type"]
                    })

        return matches

    def search_datatype(self, datatype):

        datatype = datatype.upper()

        return self.datatype_index.get(datatype, [])

    def find_tables_with_column(self, column_name):

        return self.column_index.get(column_name.lower(), [])

    # ==========================================================
    # CONTEXT METHODS
    # ==========================================================

    def get_table_context(self, table_name):

        table = self.get_table(table_name)

        if not table:
            return None

        return {
            "table_name": table["table_name"],
            "description": table.get("description"),
            "primary_key": table.get("primary_key"),
            "columns": table.get("columns", [])
        }


# ==========================================================
# TEST
# ==========================================================

if __name__ == "__main__":

    schema = LocalSchemaTool()

    print("=" * 70)

    print("Database")
    print(schema.get_database_name())

    print("\nTotal Tables")
    print(schema.get_total_tables())

    print("\nFirst 5 Tables")
    print(schema.list_tables()[:5])

    print("\nDescription")
    print(schema.get_table_description("agent_conversation_messages"))

    print("\nPrimary Key")
    print(schema.get_primary_key("agent_conversation_messages"))

    print("\nColumn Names")
    print(schema.get_column_names("agent_conversation_messages"))

    print("\nFind Tables Having tenant_id")
    print(schema.find_tables_with_column("tenant_id"))

    print("\nSearch Table Name 'conversation'")
    print(schema.search_tables("conversation"))

    print("\nSearch Description 'billing'")
    print(schema.search_tables_by_description("billing"))

    print("\nSearch Column 'created_at'")
    print(schema.search_columns("created_at"))

    print("\nAll BIGINT Columns")
    print(schema.search_datatype("BIGINT"))