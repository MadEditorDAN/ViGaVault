# WHY: Single Responsibility Principle - Strictly queries the SteamGridDB API.
import requests
import logging
from urllib.parse import quote
from .login_steamgriddb import get_steamgriddb_key, is_steamgriddb_connected

def fetch_steamgriddb_covers_list(search_term):
    """
    Queries SteamGridDB for the given game search term.
    Returns a list of cover URLs or raises RuntimeError/ValueError with specific reasons.
    """
    if not is_steamgriddb_connected():
        raise RuntimeError("SteamGridDB platform is not connected. Please connect it in the platforms settings first.")

    api_key = get_steamgriddb_key()
    if not api_key:
        raise RuntimeError("API key is missing or corrupted. Try disconnecting and reconnecting SteamGridDB in Platforms settings.")

    headers = {"Authorization": f"Bearer {api_key}"}
    
    # 1. Autocomplete Search to get Game ID
    search_url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{quote(search_term)}"
    
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network request failed: Could not connect to SteamGridDB server.\n\nDetails: {e}")
        
    if response.status_code == 401:
        raise RuntimeError("Authentication failed (HTTP 401). Your SteamGridDB API key is invalid or has been revoked.")
    elif response.status_code == 403:
        raise RuntimeError("Access forbidden (HTTP 403). SteamGridDB blocked the request. Verify your API key.")
    elif response.status_code == 429:
        raise RuntimeError("Rate limited (HTTP 429). Too many requests sent to SteamGridDB. Wait a few seconds and try again.")
    elif response.status_code != 200:
        raise RuntimeError(f"Search request failed: SteamGridDB returned HTTP status {response.status_code}.")
    
    try:
        search_data = response.json()
    except Exception as e:
        raise RuntimeError(f"Invalid API response: Failed to parse search JSON.\n\nDetails: {e}")
        
    if not search_data.get("success") or not search_data.get("data"):
        raise ValueError(f"No matching games found for '{search_term}' on SteamGridDB. Check the game title spelling.")
    
    game = search_data["data"][0]
    game_id = game.get("id")
    game_name = game.get("name", search_term)
    if not game_id:
        raise ValueError(f"Found game search record for '{search_term}', but it lacks a valid SteamGridDB ID.")
    
    all_covers = []
    was_fallback = False
    
    grids_url = f"https://www.steamgriddb.com/api/v2/grids/game/{game_id}"
    params = {"dimensions": "600x900", "nsfw": "false", "humor": "false"}
    
    try:
        grids_resp = requests.get(grids_url, headers=headers, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network request failed while fetching covers.\n\nDetails: {e}")
        
    if grids_resp.status_code == 401:
        raise RuntimeError("Authentication failed (HTTP 401) during covers retrieval. Your API key is invalid.")
    elif grids_resp.status_code != 200:
        raise RuntimeError(f"Covers request failed: SteamGridDB returned HTTP status {grids_resp.status_code}.")
        
    try:
        grids_data = grids_resp.json()
    except Exception as e:
        raise RuntimeError(f"Invalid response format: Failed to parse covers JSON.\n\nDetails: {e}")
        
    if grids_data.get("success") and grids_data.get("data"):
        for g in grids_data["data"]:
            if g.get("url"):
                all_covers.append({"url": g.get("url"), "thumb": g.get("thumb", g.get("url")), "is_fallback": False})
                
    # Fallback 1: if no 600x900 vertical covers found for this game, try all grid dimensions
    if not all_covers:
        try:
            grids_resp_any = requests.get(grids_url, headers=headers, params={"nsfw": "false", "humor": "false"}, timeout=10)
            if grids_resp_any.status_code == 200:
                grids_data_any = grids_resp_any.json()
                if grids_data_any.get("success") and grids_data_any.get("data"):
                    for g in grids_data_any["data"]:
                        if g.get("url"):
                            all_covers.append({"url": g.get("url"), "thumb": g.get("thumb", g.get("url")), "is_fallback": True})
                            was_fallback = True
        except Exception:
            pass
            
    if not all_covers:
        raise ValueError(f"No vertical covers or alternative dimension covers were found for '{game_name}' on SteamGridDB.")
        
    return all_covers
