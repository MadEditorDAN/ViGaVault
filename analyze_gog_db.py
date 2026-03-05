import sqlite3
import os

def analyze_gog_db():
    """
    Se connecte à la base de données locale de GOG Galaxy et affiche sa structure.
    """
    try:
        gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')

        if not os.path.exists(gog_db_path):
            print(f"Erreur : Le fichier de base de données GOG n'a pas été trouvé à l'emplacement attendu :")
            print(gog_db_path)
            return

        print(f"Analyse de la base de données : {gog_db_path}\n")

        # Se connecter en mode lecture seule pour plus de sécurité
        con = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
        cursor = con.cursor()

        # 1. Obtenir la liste de toutes les tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = cursor.fetchall()
        
        print("--- TABLES TROUVÉES DANS LA BASE DE DONNÉES ---")
        table_names = [table[0] for table in tables]
        print("\n".join(table_names))
        print("\n" + "="*40 + "\n")

        # 2. Pour chaque table, obtenir la structure (colonnes)
        print("--- STRUCTURE DÉTAILLÉE DES TABLES ---")
        for table_name in table_names:
            print(f"\nTable: {table_name}")
            print("-" * (len(table_name) + 7))
            cursor.execute(f"PRAGMA table_info('{table_name}');")
            for column in cursor.fetchall():
                # cid, name, type, notnull, dflt_value, pk
                print(f"  - Colonne: {column[1]} (Type: {column[2]})")
        con.close()

    except Exception as e:
        print(f"\nUne erreur est survenue lors de l'analyse : {e}")
        print("Veuillez vous assurer que GOG Galaxy est bien fermé avant de lancer le script.")

if __name__ == "__main__":
    analyze_gog_db()
    