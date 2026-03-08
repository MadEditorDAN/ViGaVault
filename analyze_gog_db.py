import sqlite3
import os

def analyze_gog_db():
    """
    Connects to the local GOG Galaxy database and displays its structure.
    """
    output_filename = "analyze_gog_db.txt"
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')

            if not os.path.exists(gog_db_path):
                f.write(f"Error: GOG database file not found at the expected location:\n")
                f.write(gog_db_path)
                print(f"Error: GOG database file not found. See {output_filename} for details.")
                return

            f.write(f"Analyzing database: {gog_db_path}\n\n")

            # Connect in read-only mode for more safety
            con = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
            cursor = con.cursor()

            # 1. Get the list of all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
            tables = cursor.fetchall()
            
            f.write("--- TABLES FOUND IN DATABASE ---\n")
            table_names = [table[0] for table in tables]
            f.write("\n".join(table_names))
            f.write("\n\n" + "="*40 + "\n\n")

            # 2. For each table, get the structure (columns)
            f.write("--- DETAILED TABLE STRUCTURE ---\n")
            for table_name in table_names:
                f.write(f"\nTable: {table_name}\n")
                f.write("-" * (len(table_name) + 7) + "\n")
                cursor.execute(f"PRAGMA table_info('{table_name}');")
                for column in cursor.fetchall():
                    # cid, name, type, notnull, dflt_value, pk
                    f.write(f"  - Column: {column[1]} (Type: {column[2]})\n")
            con.close()
        
        print(f"Analysis complete. Results saved to {output_filename}")

    except Exception as e:
        print(f"\nAn error occurred during analysis. See {output_filename} for details.")
        with open(output_filename, 'a', encoding='utf-8') as f:
            f.write(f"\nAn error occurred during analysis: {e}\n")
            f.write("Please make sure GOG Galaxy is closed before running the script.\n")

if __name__ == "__main__":
    analyze_gog_db()
    