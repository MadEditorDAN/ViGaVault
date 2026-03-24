# WHY: Single Responsibility Principle - Strictly handles extracting Steam ownership data via fast HTML scraping.
# Completely drops the slow Store API to guarantee scan times remain under 2 seconds.
import logging
import requests
import re
import json
import urllib.parse
from backend.game import Game
from ViGaVault_utils import get_safe_filename
from .login_steam import get_steam_session

def scan_steam_account(config, games_dict, worker_thread=None):
    raw_session = get_steam_session()
    
    secure_cookie = None
    for k, v in raw_session.items():
        if 'steamcommunity.com' in k and k.endswith('steamLoginSecure'):
            secure_cookie = v
            break
            
    if not secure_cookie:
        secure_cookie = raw_session.get('steamLoginSecure')
    
    if not secure_cookie:
        logging.error("[STEAM] No valid session found. Please connect Steam in the Platform Manager.")
        return False

    steam_id = urllib.parse.unquote(secure_cookie).split('||')[0]
    
    url = f"https://steamcommunity.com/profiles/{steam_id}/games/?tab=all"
    clean_session = {k: v for k, v in raw_session.items() if not k.startswith('.')}
    clean_session['steamLoginSecure'] = secure_cookie
    raw_cookie_string = "; ".join([f"{k}={v}" for k, v in clean_session.items()])
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cookie': raw_cookie_string
    }
    
    logging.info(f"\n{' STEAM SCAN ':=^80}")
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            logging.error(f"[STEAM] Failed to fetch library page: HTTP {response.status_code}")
            return False
        html_text = response.text
    except Exception as e:
        logging.error(f"[STEAM] Error fetching library: {e}")
        return False

    # WHY: Steam migrated to React-Query SSR state injection.
    # The JSON is now safely embedded within window.SSR.renderContext.
    extracted_games = {}
    
    # Attempt 1: Parse the modern React-Query SSR state (window.SSR.renderContext)
    ssr_match = re.search(r'window\.SSR\.renderContext\s*=\s*JSON\.parse\("(.*?)"\)\s*;?\s*</script>', html_text)
    if ssr_match:
        try:
            # Safely unescape the outer JSON string literal natively
            json_str = json.loads('"' + ssr_match.group(1) + '"')
            render_context = json.loads(json_str)
            query_data_str = render_context.get("queryData", "{}")
            query_data = json.loads(query_data_str)
            
            for query in query_data.get("queries", []):
                q_key = query.get("queryKey", [])
                if isinstance(q_key, list) and len(q_key) > 0 and q_key[0] == "OwnedGames":
                    games_list = query.get("state", {}).get("data", [])
                    for g in games_list:
                        if "appid" in g and "name" in g:
                            extracted_games[str(g["appid"])] = g["name"]
                    break
        except Exception as e:
            logging.error(f"    [STEAM] Failed to parse SSR renderContext: {e}")

    # Attempt 2: Universal Regex for deeply escaped JSON fragments (Fallback)
    if not extracted_games:
        # WHY: Fallback regex tolerating any level of backslash escaping (\", \\\", etc.)
        matches = re.finditer(r'(?:\\*)"appid(?:\\*)"\s*:\s*(\d+)\s*,\s*(?:\\*)"name(?:\\*)"\s*:\s*(?:\\*)"([^"\\]*(?:\\.[^"\\]*)*)(?:\\*)"', html_text)
        for match in matches:
            appid = match.group(1)
            raw_name = match.group(2)
            try: 
                clean_name = json.loads(f'"{raw_name}"')
            except: 
                clean_name = raw_name
            extracted_games[appid] = clean_name

    if not extracted_games:
        logging.warning("[STEAM] No games found in the HTML response. The profile might be private or the layout changed.")
        return False

    existing_steam_set = set()
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid.startswith('steam_'):
                existing_steam_set.add(gid.replace('steam_', ''))

    new_ids = [aid for aid in extracted_games.keys() if aid not in existing_steam_set]
    
    changes_made = False
    stats = {'total_cloud': len(extracted_games), 'already_in_db': len(extracted_games) - len(new_ids), 'new_added': 0}

    for app_id in new_ids:
        if worker_thread and worker_thread.isInterruptionRequested(): break
        
        title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', extracted_games[app_id]).strip()
        folder_name = get_safe_filename(title_clean) or f"Unknown Game [{app_id}]"
        if folder_name in games_dict: folder_name = f"{title_clean} [{app_id}]"
        
        game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='NEW', Path_Root='', Clean_Title=title_clean, game_ID=f"steam_{app_id}", Platforms="Steam")
        games_dict[folder_name] = game_obj
        changes_made = True
        stats['new_added'] += 1
        logging.info(f"|{'Added : ' + title_clean[:48]:<56}| Img: No  | Trl: No  |")

    report = f"{' REPORT ':=^80}\nTotal Cloud    : {stats['total_cloud']}\nAlready in DB  : {stats['already_in_db']}\nNew Added      : {stats['new_added']}\n{'='*80}"
    logging.info(report)
    return changes_made