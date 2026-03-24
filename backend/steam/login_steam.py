# WHY: Single Responsibility Principle - Strictly manages Steam authentication states and secure local cookie storage.
import os
import json

STEAM_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(STEAM_DIR, "steam_session.json")

def is_steam_connected():
    """Checks if a valid session file exists for the Steam platform."""
    return os.path.exists(SESSION_FILE)

def disconnect_steam():
    """Safely removes the stored cookies, instantly logging the user out locally."""
    if os.path.exists(SESSION_FILE):
        try: os.remove(SESSION_FILE)
        except: pass

def save_steam_session(cookies_dict):
    """Securely dumps the intercepted browser cookies into a local JSON file."""
    os.makedirs(STEAM_DIR, exist_ok=True)
    with open(SESSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies_dict, f, indent=4)
        
def get_steam_session():
    """Returns the stored session cookies as a Python dictionary for the scanner to use."""
    if not is_steam_connected(): return {}
    try:
        with open(SESSION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}