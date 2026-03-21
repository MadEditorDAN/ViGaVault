# WHY: Single Responsibility Principle - Strictly manages GOG authentication states and secure local cookie storage.
import os
import json
import requests

GOG_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(GOG_DIR, "gog_session.json")

def is_gog_connected():
    """Checks if a valid session file exists for the GOG platform."""
    return os.path.exists(SESSION_FILE)

def disconnect_gog():
    """Safely removes the stored cookies, instantly logging the user out locally."""
    if os.path.exists(SESSION_FILE):
        try: os.remove(SESSION_FILE)
        except: pass

def save_gog_session(cookies_dict):
    """Securely dumps the intercepted browser cookies into a local JSON file."""
    os.makedirs(GOG_DIR, exist_ok=True)
    with open(SESSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies_dict, f, indent=4)
        
def get_gog_cookies():
    """Returns the stored session cookies as a Python dictionary for the scanner to use."""
    if not is_gog_connected(): return {}
    try:
        with open(SESSION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def exchange_code_for_token(auth_code):
    """WHY: Exchanges the temporary browser code for a persistent OAuth Bearer Token."""
    url = "https://auth.gog.com/token"
    payload = {
        'client_id': '46899977096215655',
        'client_secret': '9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9',
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': 'https://embed.gog.com/on_login_success?origin=client'
    }
    try:
        resp = requests.get(url, params=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except: pass
    return None

def refresh_gog_token():
    """WHY: Automatically requests a fresh access token before scanning to prevent 401 Unauthorized errors."""
    session_data = get_gog_cookies()
    refresh_token = session_data.get('refresh_token')
    if not refresh_token: return None
    
    url = "https://auth.gog.com/token"
    payload = {
        'client_id': '46899977096215655',
        'client_secret': '9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9',
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    try:
        resp = requests.get(url, params=payload, timeout=10)
        if resp.status_code == 200:
            new_data = resp.json()
            save_gog_session(new_data)
            return new_data.get('access_token')
    except: pass
    return None