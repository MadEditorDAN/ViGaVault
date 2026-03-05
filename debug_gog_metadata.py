import sqlite3
import os
import json
import sys
import io
import csv
from collections import defaultdict

# Force l'encodage UTF-8 pour la console Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def debug_gog_metadata():
    gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')
    output_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_gog_metadata.csv")
    
    if not os.path.exists(gog_db_path):
        print(f"ERREUR: Base de données introuvable à : {gog_db_path}")
        return

    print(f"--- ANALYSE APPROFONDIE DES MÉTADONNÉES GOG ---\n")
    print(f"Base de données : {gog_db_path}\n")

    try:
        conn = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row # Permet d'accéder aux colonnes par nom
        cursor = conn.cursor()

        # 1. Récupération des clés et groupement par plateforme
        print("Récupération des clés de jeux...")
        cursor.execute("SELECT releaseKey FROM UserReleaseProperties")
        all_keys = [row['releaseKey'] for row in cursor.fetchall()]
        
        if not all_keys:
             print("UserReleaseProperties vide, essai avec GamePieces...")
             cursor.execute("SELECT DISTINCT releaseKey FROM GamePieces")
             all_keys = [row['releaseKey'] for row in cursor.fetchall()]

        platforms = defaultdict(list)
        for key in all_keys:
            parts = key.split('_', 1)
            platform = parts[0] if len(parts) > 1 else 'unknown'
            platforms[platform].append(key)

        selected_keys = []
        print("\nSélection des jeux par plateforme :")
        for platform, keys in platforms.items():
            subset = keys[:3]
            selected_keys.extend(subset)
            print(f"  - {platform}: {len(keys)} trouvés -> {len(subset)} sélectionnés")

        print(f"\nAnalyse de {len(selected_keys)} jeux au total...\n")
        
        results = []

        for key in selected_keys:
            game_data = {'ReleaseKey': key, 'Platform': key.split('_')[0] if '_' in key else 'unknown'}
            
            # 1. GamePieces (Métadonnées brutes JSON)

            cursor.execute("""
                SELECT gpt.type, gp.value 
                FROM GamePieces gp 
                JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id 
                WHERE gp.releaseKey = ?
            """, (key,))
            rows = cursor.fetchall()
            for row in rows:
                # Capture large des types intéressants
                if row['type'] in ['meta', 'title', 'originalTitle', 'summary', 'developers', 'publishers', 'originalImages', 'videos']:
                     game_data[f"GP_{row['type']}"] = row['value']

            # 2. Identification de l'ID Produit (Game ID)
            game_id = None
            
            # Via ReleaseProperties
            cursor.execute("SELECT gameId FROM ReleaseProperties WHERE releaseKey = ?", (key,))
            rp = cursor.fetchone()
            if rp: game_id = rp['gameId']
            
            # Via ProductsToReleaseKeys (si pas trouvé avant)
            if not game_id:
                cursor.execute("SELECT gogId FROM ProductsToReleaseKeys WHERE releaseKey = ?", (key,))
                p2rk = cursor.fetchone()
                if p2rk: game_id = p2rk['gogId']
            
            game_data['GameID'] = game_id

            if game_id:
            # 3. LimitedDetails & Details
                # On retire releaseDate de LimitedDetails car elle n'y est pas toujours
                # On la cherche dans Details
                try:
                    cursor.execute("""
                        SELECT ld.languageId, ld.title, ld.images, 
                               d.description, d.videos, d.releaseDate
                        FROM LimitedDetails ld
                        LEFT JOIN Details d ON d.limitedDetailsId = ld.id
                        WHERE ld.productId = ?
                        ORDER BY CASE WHEN ld.languageId = 1 THEN 0 ELSE 1 END
                        LIMIT 1
                    """, (game_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        game_data['LD_Title'] = row['title']
                        game_data['LD_Images'] = row['images']
                        game_data['Det_Description'] = row['description']
                        game_data['Det_Videos'] = row['videos']
                        game_data['Det_ReleaseDate'] = row['releaseDate']
                except sqlite3.Error as e:
                    game_data['DB_Error'] = str(e)

            results.append(game_data)

        # Écriture CSV
        fieldnames = ['Platform', 'ReleaseKey', 'GameID', 
                      'GP_title', 'GP_originalTitle', 'GP_meta', 'GP_summary', 'GP_developers', 'GP_publishers', 'GP_originalImages', 'GP_videos',
                      'LD_Title', 'LD_Images', 
                      'Det_Description', 'Det_ReleaseDate', 'Det_Videos', 'DB_Error']
        
        with open(output_csv, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            for data in results:
                clean_data = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        clean_data[k] = v.replace('\n', ' ').replace('\r', '').replace(';', ',')
                    else:
                        clean_data[k] = v
                row = {field: clean_data.get(field, '') for field in fieldnames}
                writer.writerow(row)

        print(f"Terminé ! Résultats exportés dans : {output_csv}")                
    except Exception as e:
        print(f"\nERREUR CRITIQUE : {e}")

if __name__ == "__main__":
    debug_gog_metadata()
