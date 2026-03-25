# WHY: Single Responsibility Principle - Strictly manages IGDB configuration states and secure local storage.
import os
import json
import requests
from ViGaVault_utils import BASE_DIR

IGDB_DIR = os.path.join(BASE_DIR, "backend", "igdb")
SESSION_FILE = os.path.join(IGDB_DIR, "igdb_session.json")

def is_igdb_connected():
    return os.path.exists(SESSION_FILE)

def disconnect_igdb():
    if os.path.exists(SESSION_FILE):
        try: os.remove(SESSION_FILE)
        except: pass

def save_igdb_keys(client_id, client_secret):
    os.makedirs(IGDB_DIR, exist_ok=True)
    with open(SESSION_FILE, 'w', encoding='utf-8') as f:
        json.dump({"client_id": client_id, "client_secret": client_secret}, f, indent=4)

def get_igdb_keys():
    if not is_igdb_connected(): return None, None
    try:
        with open(SESSION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("client_id"), data.get("client_secret")
    except: return None, None

def validate_igdb_keys(client_id, client_secret):
    url = "https://id.twitch.tv/oauth2/token"
    params = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    try:
        response = requests.post(url, params=params, timeout=10)
        if response.status_code == 200:
            return True
    except: pass
    return False