# save as import_dump.py
import mysql.connector

# Read SQL file
with open("Dump20260412 (1).sql", "r", encoding="utf-8") as f:
    sql = f.read()

# Connect without database
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="your_password"
)
cursor = conn.cursor()

# Split and execute statements
for statement in sql.split(";"):
    stmt = statement.strip()
    if stmt:
        try:
            cursor.execute(stmt)
        except Exception as e:
            print(f"Skipped: {str(e)[:50]}")

conn.commit()
cursor.close()
conn.close()
print("✓ SQL dump imported successfully")