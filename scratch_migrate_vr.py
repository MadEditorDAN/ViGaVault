import sys
import os
import time

# Append root to path
sys.path.append(os.getcwd())

from ViGaVault_utils import build_scanner_config, normalize_genre
from backend.library import LibraryManager
from backend.api_igdb import get_igdb_access_token, query_igdb_api

def migrate_vr_catalog():
    print("Starting VR migration script...")
    config = build_scanner_config()
    config['db_file'] = os.path.join(os.getcwd(), 'dan.dat')
    manager = LibraryManager(config)
    manager.load_db()

    token = get_igdb_access_token()
    if not token:
        print("Failed to get IGDB token!")
        return

    # Extract all valid IGDB IDs
    igdb_id_to_folders = {}
    for folder, game in manager.games.items():
        game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
        for gid in game_ids:
            if gid.startswith('igdb_'):
                numeric_id = gid.replace('igdb_', '')
                if numeric_id.isdigit():
                    igdb_id_to_folders.setdefault(int(numeric_id), []).append(folder)

    unique_ids = list(igdb_id_to_folders.keys())
    print(f"Found {len(unique_ids)} unique IGDB IDs in the library.")

    vr_platforms = {162, 163, 165, 384, 385, 386, 387, 388, 390, 471}
    vr_enabled_igdb_ids = set()

    # Batch query IGDB (50 at a time)
    batch_size = 50
    for i in range(0, len(unique_ids), batch_size):
        batch_ids = unique_ids[i:i+batch_size]
        ids_str = ",".join(map(str, batch_ids))
        
        query = f"fields id,platforms; where id = ({ids_str}); limit {batch_size};"
        print(f"Querying batch {i//batch_size + 1}/{(len(unique_ids) + batch_size - 1)//batch_size}...")
        
        try:
            results = query_igdb_api(token, custom_query=query)
            if results:
                for res in results:
                    platforms = res.get('platforms', [])
                    if any(p in vr_platforms for p in platforms):
                        vr_enabled_igdb_ids.add(res.get('id'))
        except Exception as e:
            print(f"Error querying batch: {e}")

    print(f"\nFound {len(vr_enabled_igdb_ids)} VR-enabled games from IGDB.")

    # Apply the VR tag to the database
    changes = 0
    for vr_id in vr_enabled_igdb_ids:
        folders = igdb_id_to_folders.get(vr_id, [])
        for folder in folders:
            game = manager.games.get(folder)
            if game:
                current_genre = game.data.get('Genre', '')
                # Ensure we don't duplicate the VR tag, but FORCE a normalization pass 
                # so that old "Vr" strings get caught by the new taxonomy rule.
                genre_list = [g.strip().upper() for g in current_genre.split(',') if g.strip()]
                
                if 'VR' not in genre_list:
                    new_genre_str = f"{current_genre}, VR" if current_genre else "VR"
                else:
                    new_genre_str = current_genre # We already have it, just push it through normalize
                    
                new_normalized = normalize_genre(new_genre_str)
                if game.data['Genre'] != new_normalized:
                    game.data['Genre'] = new_normalized
                    changes += 1
                    print(f"Updated VR casing in: {game.data.get('Clean_Title', folder)} ({game.data['Genre']})")

    if changes > 0:
        manager.save_db()
        print(f"\nMigration complete. Successfully updated {changes} games with the VR genre.")
    else:
        print("\nMigration complete. No games needed updating (VR already present or no VR games found).")

if __name__ == "__main__":
    migrate_vr_catalog()
