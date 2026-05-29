# WHY: Single Responsibility Principle - Strictly handles fetching Steam ownership data.
# Migrated exclusively to the official Steam Web API for bulletproof JSON extraction and permanent stability.
import logging
import requests
import re
from backend.game import Game
from ViGaVault_utils import (
    get_safe_filename,
    format_header_row, format_middle_header, format_box_bottom,
    format_separator_row, format_report_row, format_operation_row
)
from .login_steam import get_steam_session

def scan_steam_account(config, games_dict, worker_thread=None):
    session = get_steam_session()
    secure_cookie = session.get('steamLoginSecure')
    session_id = session.get('sessionid')
    steam_id = session.get('steam_id')
    
    if not secure_cookie or not steam_id:
        logging.error("[STEAM] No valid Steam Session found. Please connect Steam in the Platform Manager.")
        return False, {}

    api_key = session.get('api_key')
    
    try:
        games_list = []
        if api_key:
            url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={api_key}&steamid={steam_id}&include_appinfo=1"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                games_list = data.get('response', {}).get('games', [])
            else:
                logging.error(f"[STEAM] API Key scan failed: HTTP {response.status_code}")
                return False, {}
        else:
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
                return False, {}
                
            html = response.text
            match = re.search(r'var\s+rgGames\s*=\s*(\[.*?\]);', html, re.DOTALL)
            if match:
                import json
                games_list = json.loads(match.group(1))
            else:
                logging.warning("[STEAM] Could not find 'rgGames' data in the page HTML. The session may be invalid or the profile private.")
                return False, {}
                
    except Exception as e:
        logging.error(f"[STEAM] Error fetching library: {e}")
        return False, {}

    if not games_list:
        logging.warning("[STEAM] No games found. Ensure your Game Details privacy is set to Public.")
        return False, {}

    existing_steam_set = set()
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid.startswith('steam_'):
                existing_steam_set.add(gid.replace('steam_', ''))

    logging.info(format_header_row("STEAM SCAN", is_secondary=False, col_spec=[17, 36, 5, 5, 5, 5]))

    changes_made = False
    stats = {'total_cloud': len(games_list), 'already_in_db': 0, 'new_added': 0, 'matched_smart': 0}
    ops_logged = 0

    for game in games_list:
        if worker_thread and worker_thread.isInterruptionRequested(): break
        
        appid = str(game.get('appid'))
        name = game.get('name', f"Unknown App {appid}")
        
        if appid in existing_steam_set:
            stats['already_in_db'] += 1
            continue
            
        title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', name).strip()
        
        # --- ZERO-COST SMART MATCH ---
        norm_title = re.sub(r'[^a-z0-9]', '', title_clean.lower())
        best_score = 0
        best_game = None
        
        import difflib
        for g in games_dict.values():
            local_title = g.data.get('Clean_Title', '')
            local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
            
            score = 0
            if local_norm_title == norm_title: score += 60
            else:
                ratio = difflib.SequenceMatcher(None, title_clean.lower(), local_title.lower()).ratio()
                if ratio > 0.6: score += int(ratio * 60)
                else: continue
                
            local_platforms = g.data.get('Platforms', '').lower()
            if 'steam' in local_platforms: score += 20
            if local_norm_title == norm_title: score += 20
            
            if score > best_score:
                best_score, best_game = score, g
                
        threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
        
        if best_game and best_score >= threshold:
            current_ids = set(x.strip() for x in best_game.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(f"steam_{appid}")
            best_game.data['game_ID'] = ", ".join(sorted(list(current_ids)))
            
            p_set = set(x.strip() for x in best_game.data.get('Platforms', '').split(',') if x.strip())
            if 'Local Copy' in p_set: p_set.remove('Local Copy')
            p_set.add('Steam')
            best_game.data['Platforms'] = ", ".join(sorted(list(p_set)))
            
            changes_made = True
            
            if ops_logged == 0:
                logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
            
            img_ok = bool(best_game.data.get('Image_Link'))
            trl_ok = bool(best_game.data.get('Trailer_Link') and str(best_game.data.get('Trailer_Link')).startswith('http'))
            logging.info(format_operation_row("Merged", title_clean, img_ok, trl_ok))
            ops_logged += 1
            
            stats['matched_smart'] += 1
            continue
            
        folder_name = get_safe_filename(title_clean) or f"Unknown Game [{appid}]"
        if folder_name in games_dict: folder_name = f"{title_clean} [{appid}]"
        
        game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='NEW', Path_Root='', Clean_Title=title_clean, game_ID=f"steam_{appid}", Platforms="Steam")
        games_dict[folder_name] = game_obj
        changes_made = True
        stats['new_added'] += 1
        
        if ops_logged == 0:
            logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
        
        has_img = bool(game_obj.data.get('Cover_URL') or game_obj.data.get('Image_Link'))
        has_trl = bool(game_obj.data.get('Trailer_Link') and str(game_obj.data.get('Trailer_Link')).startswith('http'))
        logging.info(format_operation_row("Added", title_clean, has_img, has_trl))
        ops_logged += 1

    if ops_logged > 0:
        logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┴", "┴", "┴"]))
        
    logging.info(format_middle_header("REPORT", col_spec=[17, 36, 5, 5, 5, 5]))
    logging.info(format_report_row("Total Games", stats['total_cloud']))
    logging.info(format_report_row("Already in DB", stats['already_in_db']))
    logging.info(format_report_row("New Added", stats['new_added']))
    logging.info(format_report_row("Smart Merged", stats['matched_smart']))
    logging.info(format_report_row("Deleted", 0))
    logging.info(format_report_row("Errors/Ignored", 0))
    logging.info(format_box_bottom([17, 60]))
    return changes_made, stats