# WHY: Single Responsibility Principle - Strictly manages SteamGridDB API key states and secure local storage.
import os
import requests
from ViGaVault_utils import BASE_DIR, save_encrypted_json, load_encrypted_json

STEAMGRIDDB_DIR = os.path.join(BASE_DIR, "backend", "steamgriddb")
SESSION_FILE = os.path.join(STEAMGRIDDB_DIR, "steamgriddb_session.dat")

def is_steamgriddb_connected():
    return os.path.exists(SESSION_FILE)

def disconnect_steamgriddb():
    if os.path.exists(SESSION_FILE):
        try: os.remove(SESSION_FILE)
        except: pass

def save_steamgriddb_key(api_key):
    os.makedirs(STEAMGRIDDB_DIR, exist_ok=True)
    save_encrypted_json(SESSION_FILE, {"api_key": api_key})

def get_steamgriddb_key():
    data = load_encrypted_json(SESSION_FILE)
    return data.get("api_key")

def validate_steamgriddb_key(api_key):
    url = "https://www.steamgriddb.com/api/v2/search/autocomplete/a"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return True
    except: pass
    return False
