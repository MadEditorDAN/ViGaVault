import sys
import os

sys.path.append(os.getcwd())

from ViGaVault_utils import build_scanner_config
from backend.library import LibraryManager
from backend.api_igdb import get_igdb_access_token, query_igdb_api

def check_steam_vr_games():
    test_games = [
        "ADR1FT", "Budget Cuts Ultimate", "DiRT Rally 2.0", "DOOM VFR",
        "Elite Dangerous", "Fruit Ninja VR", "The Lab", "Prison Boss VR",
        "Project CARS", "Trover Saves the Universe", "Wolfenstein: Cyberpilot"
    ]
    
    config = build_scanner_config()
    manager = LibraryManager(config)
    manager.load_db()

    token = get_igdb_access_token()

    print("Checking local database for these games...")
    found_in_db = 0
    vr_platforms = {162, 163, 165, 384, 385, 386, 387, 388, 390, 471}
    
    for game_name in test_games:
        # Fuzzy find in DB
        local_match = None
        for folder, game in manager.games.items():
            if game_name.lower() in game.data.get('Clean_Title', '').lower():
                local_match = game
                break
                
        if local_match:
            found_in_db += 1
            ids = local_match.data.get('game_ID', '')
            status = local_match.data.get('Status_Flag', '')
            genre = local_match.data.get('Genre', '')
            print(f"\n[LOCAL DB] Found '{game_name}' -> Title: '{local_match.data.get('Clean_Title')}', Status: {status}, Genres: {genre}, IDs: {ids}")
            
            # Check IGDB for this specific ID if it has one
            igdb_ids = [x.replace('igdb_', '') for x in ids.split(',') if x.strip().startswith('igdb_')]
            if igdb_ids:
                query = f"fields id,name,platforms.name,themes.name,game_modes.name,player_perspectives.name; where id = ({','.join(igdb_ids)}); limit 1;"
                res = query_igdb_api(token, custom_query=query)
                if res:
                    g = res[0]
                    platforms = g.get('platforms', [])
                    p_ids = [p['id'] for p in platforms if isinstance(p, dict)]
                    p_names = [p['name'] for p in platforms if isinstance(p, dict)]
                    is_vr_platform = any(pid in vr_platforms for pid in p_ids)
                    
                    themes = [t['name'] for t in g.get('themes', [])]
                    modes = [m['name'] for m in g.get('game_modes', [])]
                    persps = [p['name'] for p in g.get('player_perspectives', [])]
                    
                    print(f"  -> IGDB Match: {g.get('name')}")
                    print(f"  -> Has VR Platform ID? {is_vr_platform} | Platforms: {p_names}")
                    print(f"  -> Themes: {themes}")
                    print(f"  -> Modes: {modes}")
                    print(f"  -> Perspectives: {persps}")
                else:
                    print(f"  -> Failed to fetch from IGDB by ID.")
            else:
                print("  -> No IGDB ID in database. Needs metadata scrape.")
                # Fallback to search
                res = query_igdb_api(token, search_term=game_name, limit=1)
                if res:
                    g = res[0]
                    print(f"  -> Text Search IGDB Match: {g.get('name')}")
        else:
            print(f"\n[LOCAL DB] '{game_name}' NOT FOUND in local ViGaVault database!")

if __name__ == "__main__":
    check_steam_vr_games()
