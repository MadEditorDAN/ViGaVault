# WHY: Single Responsibility Principle - Strictly manages Steam API key storage and validation.
import os
import requests
import re
from ViGaVault_utils import BASE_DIR, save_encrypted_json, load_encrypted_json

STEAM_DIR = os.path.join(BASE_DIR, "backend", "steam")
SESSION_FILE = os.path.join(STEAM_DIR, "steam_session.dat")

def is_steam_connected():
    """Checks if a valid API Key file exists for the Steam platform."""
    return os.path.exists(SESSION_FILE)

def disconnect_steam():
    if os.path.exists(SESSION_FILE):
        try: os.remove(SESSION_FILE)
        except: pass

def save_steam_session(data_dict):
    """Securely dumps the Steam API key and SteamID into a local JSON file."""
    os.makedirs(STEAM_DIR, exist_ok=True)
    save_encrypted_json(SESSION_FILE, data_dict)
        
def get_steam_session():
    return load_encrypted_json(SESSION_FILE)

def validate_steam_keys(api_key, steam_input):
    """WHY: Resolves the SteamID if a URL/Username was provided, then strictly validates it against the user's Privacy Settings."""
    steam_id = None
    
    # Step 1: Use regex to instantly catch a raw 17-digit SteamID64 if provided directly in the text or URL.
    match = re.search(r'(7656119[0-9]{10})', steam_input)
    if match:
        steam_id = match.group(1)
    else:
        # Step 2: Fallback to Vanity URL Resolution. Extract the vanity name cleanly from raw input or a full profile link.
        vanity_name = steam_input.strip().strip('/')
        if 'steamcommunity.com/id/' in vanity_name:
            vanity_name = vanity_name.split('steamcommunity.com/id/')[-1].split('/')[0]
            
        url = f"http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={api_key}&vanityurl={vanity_name}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('response', {}).get('success') == 1:
                    steam_id = data['response']['steamid']
        except: pass
        
    if not steam_id:
        return None
        
    # Step 3: Validate the resolved steam_id can actually fetch public games.
    url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={api_key}&steamid={steam_id}&format=json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "response" in data and "game_count" in data["response"]:
                return steam_id
    except: pass
    return False