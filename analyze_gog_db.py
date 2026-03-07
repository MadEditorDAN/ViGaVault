import sqlite3
import os

def analyze_gog_db():
    """
    Connects to the local GOG Galaxy database and displays its structure.
    """
    try:
        gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')

        if not os.path.exists(gog_db_path):
            print(f"Error: GOG database file not found at the expected location:")
            print(gog_db_path)
            return

        print(f"Analyzing database: {gog_db_path}\n")

        # Connect in read-only mode for more safety
        con = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
        cursor = con.cursor()

        # 1. Get the list of all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = cursor.fetchall()
        
        print("--- TABLES FOUND IN DATABASE ---")
        table_names = [table[0] for table in tables]
        print("\n".join(table_names))
        print("\n" + "="*40 + "\n")

        # 2. For each table, get the structure (columns)
        print("--- DETAILED TABLE STRUCTURE ---")
        for table_name in table_names:
            print(f"\nTable: {table_name}")
            print("-" * (len(table_name) + 7))
            cursor.execute(f"PRAGMA table_info('{table_name}');")
            for column in cursor.fetchall():
                # cid, name, type, notnull, dflt_value, pk
                print(f"  - Column: {column[1]} (Type: {column[2]})")
        con.close()

    except Exception as e:
        print(f"\nAn error occurred during analysis: {e}")
        print("Please make sure GOG Galaxy is closed before running the script.")

if __name__ == "__main__":
    analyze_gog_db()
    