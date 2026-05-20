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
