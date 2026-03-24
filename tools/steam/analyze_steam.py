# WHY: Single Responsibility Principle - A standalone script exclusively dedicated to Data Discovery. 
# It safely assesses exactly what data the Steam API returns without risking corruption to the main VGVDB library.
import os
import sys
import json
import time
import re
import requests
import shutil

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
    session = get_steam_session()
    secure_cookie = session.get('steamLoginSecure')
    
    if not secure_cookie:
        print("ERROR: No Steam session found. Please connect Steam in the ViGaVault Platform Manager first.")
        sys.exit(1)
        
    # WHY: The cookie format is SteamID64%7C... or SteamID64||... We extract the first part.
    steam_id = secure_cookie.split('%7C')[0].split('||')[0]
    print(f"Extracted SteamID64: {steam_id}")
    
    # 2. Fetch the user's game library HTML page
    url = f"https://steamcommunity.com/profiles/{steam_id}/games/?tab=all"
    
    # WHY: Recycle the stealth User-Agent to masquerade as organic browser traffic
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
    }
    
    print("Fetching Steam Library page...")
    response = requests.get(url, cookies=session, headers=headers)
    
    if response.status_code != 200:
        print(f"ERROR: Failed to fetch library. HTTP {response.status_code}")
        sys.exit(1)
        
    # 3. Parse the embedded JSON array (rgGames) using regex
    # WHY: Steam embeds the entire library as a Javascript array variable in the page source. 
    # Extracting it saves us from making hundreds of individual pagination requests.
    match = re.search(r'var rgGames = (\[.*?\]);\r?\n', response.text, re.DOTALL)
    if not match:
        print("ERROR: Could not find rgGames array in the page source. Is the profile Private?")
        sys.exit(1)
        
    rg_games = json.loads(match.group(1))
    print(f"Successfully extracted {len(rg_games)} games from library.")
    
    # Limit to the first 20 games for discovery
    games_to_process = rg_games[:20]
    api_dump = {}
    
    # 4. Deep Fetching from the Steam Store API
    for index, game in enumerate(games_to_process):
        appid = game['appid']
        name = game.get('name', 'Unknown')
        safe_name = get_safe_filename(name)
        print(f"\n[{index+1}/20] Fetching data for: {name} (AppID: {appid})")
        
        app_url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        try:
            app_resp = requests.get(app_url, headers=headers, timeout=10)
            app_data = app_resp.json()
            
            if app_data and str(appid) in app_data and app_data[str(appid)].get('success'):
                data = app_data[str(appid)]['data']
                api_dump[str(appid)] = data
                
                # 5. Download Images into organized subfolders
                # WHY: Isolating images per game prevents a massive unreadable folder dump.
                img_dir = os.path.join(TOOLS_STEAM_DIR, "images", f"{appid}_{safe_name}")
                os.makedirs(img_dir, exist_ok=True)
                
                def download_img(img_url, filename):
                    if not img_url: return
                    # Remove trailing query params for clean extension extraction
                    clean_url = img_url.split('?')[0]
                    ext = os.path.splitext(clean_url)[1]
                    if not ext: ext = '.jpg'
                    filepath = os.path.join(img_dir, f"{filename}{ext}")
                    print(f"  -> Downloading {filename}{ext}")
                    try:
                        r = requests.get(img_url, stream=True, headers=headers, timeout=5)
                        if r.status_code == 200:
                            with open(filepath, 'wb') as f:
                                shutil.copyfileobj(r.raw, f)
                        else:
                            print(f"     Failed HTTP {r.status_code}")
                    except Exception as e:
                        print(f"     Failed: {e}")

                # Download standard hero/capsule artwork
                download_img(data.get('header_image'), "header_image")
                download_img(data.get('capsule_image'), "capsule_image")
                download_img(data.get('capsule_imagev5'), "capsule_imagev5")
                download_img(data.get('library_hero'), "library_hero") # Sometimes present
                download_img(data.get('background'), "background")
                download_img(data.get('background_raw'), "background_raw")
                
                # Download screenshots
                for i, screenshot in enumerate(data.get('screenshots', [])):
                    download_img(screenshot.get('path_full'), f"screenshot_{i+1}")
                    
                # Download movie thumbnails (Trailers themselves are mapped in JSON, we only download their poster)
                for i, movie in enumerate(data.get('movies', [])):
                    download_img(movie.get('thumbnail'), f"movie_thumbnail_{i+1}")
                    
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
    print(f"Images saved to  : {os.path.join(TOOLS_STEAM_DIR, 'images')}")

if __name__ == "__main__":
    analyze_steam_data()