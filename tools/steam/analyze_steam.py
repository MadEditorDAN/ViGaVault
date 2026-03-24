# WHY: Single Responsibility Principle - A standalone script exclusively dedicated to Data Discovery. 
# It safely assesses exactly what data the Steam API returns without risking corruption to the main VGVDB library.
import os
import sys
import json
import time
import re
import requests
import shutil
import html
import urllib.parse

# WHY: Setup paths to import the cookie parser and utilities from ViGaVault natively.
TOOLS_STEAM_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(TOOLS_STEAM_DIR)
BASE_DIR = os.path.dirname(TOOLS_DIR)
sys.path.append(BASE_DIR)

from ViGaVault_utils import get_safe_filename
from backend.steam.login_steam import get_steam_session

def analyze_steam_data():
    print(f"{' STEAM DATA DISCOVERY DUMP ':=^80}")
    
    # 1. Extract SteamID64 from the intercepted cookie
    raw_session = get_steam_session()
    
    secure_cookie = None
    for k, v in raw_session.items():
        if 'steamcommunity.com' in k and k.endswith('steamLoginSecure'):
            secure_cookie = v
            break
            
    if not secure_cookie:
        secure_cookie = raw_session.get('steamLoginSecure')
    
    if not secure_cookie:
        print("ERROR: No Steam session found. Please connect Steam in the ViGaVault Platform Manager first.")
        sys.exit(1)
        
    # WHY: We strictly decode the cookie purely to extract the SteamID64 for our URL.
    # We do NOT save the decoded version, to preserve the exact cryptographic signature for the HTTP request.
    steam_id = urllib.parse.unquote(secure_cookie).split('||')[0]
    print(f"Extracted SteamID64: {steam_id}")
    
    # 2. Fetch the user's game library HTML page
    url = f"https://steamcommunity.com/profiles/{steam_id}/games/?tab=all"
    
    # WHY: We MUST send the ENTIRE cookie jar (browserid, steamCountry, steamRefresh_steam).
    # Stripping these out caused the Community server to reject the session as a bot forgery and redirect to /login/.
    clean_session = {k: v for k, v in raw_session.items() if not k.startswith('.')}
    
    # WHY: Explicitly override the generic 'steamLoginSecure' (which is the Store token) 
    # with the domain-specific Community token we extracted earlier. 
    # This fixes the bug where we successfully found the token but forgot to actually inject it!
    clean_session['steamLoginSecure'] = secure_cookie
    
    raw_cookie_string = "; ".join([f"{k}={v}" for k, v in clean_session.items()])
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cookie': raw_cookie_string
    }
    
    print("Fetching Steam Library page...")
    
    # WHY: Diagnostic Logging. Prove exactly what we are sending so we never fly blind again.
    print(f"DEBUG OUTGOING COOKIE STRING: {raw_cookie_string}")
    
    # WHY: Removed the cookies= parameter. The raw cookie string is now injected directly into the headers.
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"ERROR: Failed to fetch library. HTTP {response.status_code}")
        sys.exit(1)

    html_text = response.text
    print(f"DEBUG: Fetched HTML length: {len(html_text)} characters")
        
    # 3. Indestructible Extraction Logic
    # WHY: Steam migrated to React and SSR state injection. 
    # The JSON is now safely embedded within window.SSR.renderContext.
    rg_games = []
    
    # Attempt A: Parse the React-Query SSR state directly
    ssr_match = re.search(r'window\.SSR\.renderContext\s*=\s*JSON\.parse\("(.*?)"\)\s*;?\s*</script>', html_text)
    if ssr_match:
        try:
            print("DEBUG: Found window.SSR.renderContext, decoding JSON...")
            json_str = json.loads('"' + ssr_match.group(1) + '"')
            render_context = json.loads(json_str)
            query_data_str = render_context.get("queryData", "{}")
            query_data = json.loads(query_data_str)
            
            for query in query_data.get("queries", []):
                q_key = query.get("queryKey", [])
                if isinstance(q_key, list) and len(q_key) > 0 and q_key[0] == "OwnedGames":
                    games_list = query.get("state", {}).get("data", [])
                    if games_list:
                        rg_games = games_list
                        print(f"Successfully extracted {len(rg_games)} games from SSR renderContext.")
                    break
        except Exception as e:
            print(f"DEBUG: Failed to parse SSR renderContext: {e}")
            
    # Attempt B: Universal Regex for deeply escaped JSON fragments (Fallback)
    if not rg_games:
        print("DEBUG: Falling back to regex extraction...")
        matches = re.finditer(r'(?:\\*)"appid(?:\\*)"\s*:\s*(\d+)\s*,\s*(?:\\*)"name(?:\\*)"\s*:\s*(?:\\*)"([^"\\]*(?:\\.[^"\\]*)*)(?:\\*)"', html_text)
        for match in matches:
            appid = match.group(1)
            raw_name = match.group(2)
            try:
                clean_name = json.loads(f'"{raw_name}"')
            except:
                clean_name = raw_name
            rg_games.append({"appid": int(appid), "name": clean_name})
            
        if rg_games:
            print(f"Successfully extracted {len(rg_games)} AppIDs using Regex.")
        
    if not rg_games:
        print("ERROR: Could not extract any AppIDs from the page.")
        sys.exit(1)
    
    # WHY: Process ALL games for the full metadata dump, removing the previous 20-game test limit.
    games_to_process = rg_games
    api_dump = {}
    
    # 4. Deep Fetching from the Steam Store API
    for index, game in enumerate(games_to_process):
        appid = game['appid']
        name = game.get('name', 'Unknown')
        safe_name = get_safe_filename(name)
        print(f"\n[{index+1}/{len(games_to_process)}] Fetching data for: {name} (AppID: {appid})")
        
        app_url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        try:
            app_resp = requests.get(app_url, headers=headers, timeout=10)
            app_data = app_resp.json()
            
            if app_data and str(appid) in app_data and app_data[str(appid)].get('success'):
                data = app_data[str(appid)]['data']
                api_dump[str(appid)] = data
                
            else:
                print("  -> Failed: API returned success=false (Game might be delisted or region locked)")
                api_dump[str(appid)] = {"error": "Failed to fetch or success=false", "library_data": game}
                
        except Exception as e:
            print(f"  -> Error during API request: {e}")
            api_dump[str(appid)] = {"error": str(e), "library_data": game}
            
        # WHY: Strict Rate Limiting. The public Steam API blocks rapid sequential requests without an API Key.
        print("  [Waiting 1.5s to respect rate limits...]")
        time.sleep(1.5)

    # 6. Save the final JSON Dump
    dump_path = os.path.join(TOOLS_STEAM_DIR, "steam_api_dump.json")
    with open(dump_path, 'w', encoding='utf-8') as f:
        json.dump(api_dump, f, indent=4)
        
    print(f"\n{' DISCOVERY FINISHED ':=^80}")
    print(f"API Dump saved to: {dump_path}")

if __name__ == "__main__":
    analyze_steam_data()