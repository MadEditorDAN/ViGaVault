# WHY: Single Responsibility Principle - Strictly queries the SteamGridDB API.
import requests
import logging
from urllib.parse import quote
from .login_steamgriddb import get_steamgriddb_key, is_steamgriddb_connected

def fetch_steamgriddb_covers_list(search_term):
    """
    Queries SteamGridDB for the given game search term.
    Returns a list of cover URLs.
    """
    if not is_steamgriddb_connected():
        return []

    api_key = get_steamgriddb_key()
    if not api_key:
        return []

    headers = {"Authorization": f"Bearer {api_key}"}
    
    # 1. Autocomplete Search to get Game ID
    search_url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{quote(search_term)}"
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code != 200:
            logging.warning(f"[SteamGridDB] Search failed: HTTP {response.status_code}")
            return []
        
        search_data = response.json()
        if not search_data.get("success") or not search_data.get("data"):
            logging.info(f"[SteamGridDB] No games found for: {search_term}")
            return []
        
        game_id = search_data["data"][0].get("id")
        if not game_id:
            return []
        
        # 2. Get Grids for the Game
        # We explicitly request dimensions=600x900 so that the API returns vertical posters matching ViGaVault cards.
        grids_url = f"https://www.steamgriddb.com/api/v2/grids/game/{game_id}"
        params = {"dimensions": "600x900", "nsfw": "false", "humor": "false"}
        grids_resp = requests.get(grids_url, headers=headers, params=params, timeout=10)
        
        if grids_resp.status_code == 200:
            grids_data = grids_resp.json()
            if grids_data.get("success") and grids_data.get("data"):
                return [{"url": g.get("url"), "thumb": g.get("thumb", g.get("url"))} for g in grids_data["data"] if g.get("url")]
    except Exception as e:
        logging.error(f"[SteamGridDB] Error fetching covers for {search_term}: {e}")
        
    return []
