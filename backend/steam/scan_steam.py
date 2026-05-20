# WHY: Single Responsibility Principle - Strictly handles fetching Steam ownership data.
# Migrated exclusively to the official Steam Web API for bulletproof JSON extraction and permanent stability.
import logging
import requests
import re
from backend.game import Game
from ViGaVault_utils import get_safe_filename
from .login_steam import get_steam_session

def scan_steam_account(config, games_dict, worker_thread=None):
    session = get_steam_session()
    secure_cookie = session.get('steamLoginSecure')
    session_id = session.get('sessionid')
    steam_id = session.get('steam_id')
    
    if not secure_cookie or not steam_id:
        logging.error("[STEAM] No valid Steam Session found. Please connect Steam in the Platform Manager.")
        return False

    api_key = session.get('api_key')
    
    try:
        games_list = []
        if api_key:
            logging.info("[STEAM] Using Legacy API Key for scan...")
            url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={api_key}&steamid={steam_id}&include_appinfo=1"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                games_list = data.get('response', {}).get('games', [])
            else:
                logging.error(f"[STEAM] API Key scan failed: HTTP {response.status_code}")
                return False
        else:
            logging.info("[STEAM] Using Web Scraper for scan...")
            url = f"https://steamcommunity.com/profiles/{steam_id}/games/?tab=all"
            
            import urllib.parse
            cookies = {}
            for k, v in session.items():
                if k == 'steam_id': continue
                if k == 'steamLoginSecure':
                    clean_secure = urllib.parse.unquote(v)
                    cookies[k] = urllib.parse.quote(clean_secure)
                else:
                    cookies[k] = v
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': f'https://steamcommunity.com/profiles/{steam_id}/'
            }
            response = requests.get(url, cookies=cookies, headers=headers, timeout=15)
            if response.status_code != 200:
                logging.error(f"[STEAM] Failed to fetch library: HTTP {response.status_code}")
                return False
                
            html = response.text
            match = re.search(r'var\s+rgGames\s*=\s*(\[.*?\]);', html, re.DOTALL)
            if match:
                import json
                games_list = json.loads(match.group(1))
            else:
                logging.warning("[STEAM] Could not find 'rgGames' data in the page HTML. The session may be invalid or the profile private.")
                return False
                
    except Exception as e:
        logging.error(f"[STEAM] Error fetching library: {e}")
        return False

    if not games_list:
        logging.warning("[STEAM] No games found. Ensure your Game Details privacy is set to Public.")
        return False

    existing_steam_set = set()
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid.startswith('steam_'):
                existing_steam_set.add(gid.replace('steam_', ''))

    changes_made = False
    stats = {'total_cloud': len(games_list), 'already_in_db': 0, 'new_added': 0}

    for game in games_list:
        if worker_thread and worker_thread.isInterruptionRequested(): break
        
        appid = str(game.get('appid'))
        name = game.get('name', f"Unknown App {appid}")
        
        if appid in existing_steam_set:
            stats['already_in_db'] += 1
            continue
            
        title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', name).strip()
        folder_name = get_safe_filename(title_clean) or f"Unknown Game [{appid}]"
        if folder_name in games_dict: folder_name = f"{title_clean} [{appid}]"
        
        game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='NEW', Path_Root='', Clean_Title=title_clean, game_ID=f"steam_{appid}", Platforms="Steam")
        games_dict[folder_name] = game_obj
        changes_made = True
        stats['new_added'] += 1
        logging.info(f"|{'Added : ' + title_clean[:48]:<56}| Img: No  | Trl: No  |")

    report = f"{' REPORT ':=^80}\nTotal Cloud    : {stats['total_cloud']}\nAlready in DB  : {stats['already_in_db']}\nNew Added      : {stats['new_added']}\n{'='*80}"
    logging.info(report)
    return changes_made