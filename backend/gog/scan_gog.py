# WHY: Single Responsibility Principle - Strictly handles interacting with the GOG API using stored credentials.
import logging
import requests
import difflib
import difflib
import re
from datetime import datetime
from .login_gog import get_gog_cookies, refresh_gog_token
from backend.api_igdb import get_igdb_access_token, query_igdb_api
from backend.game import Game
from ViGaVault_utils import get_safe_filename, normalize_genre

def scan_gog_account(config, games_dict, worker_thread=None):
    """Fetches user data from GOG.com via browser cookies and safely merges metadata."""
    session_data = get_gog_cookies()
    access_token = session_data.get('access_token')
    
    if not access_token:
        logging.error("[GOG.COM] No valid OAuth token found. Please reconnect your account in the Platform Manager.")
        return False
    
    # WHY: Always refresh the token at the start of a scan to guarantee it hasn't expired.
    fresh_token = refresh_gog_token()
    if fresh_token:
        access_token = fresh_token
    else:
        logging.warning("[GOG.COM] Could not refresh token. Attempting to use the existing one.")

    logging.info(f"\n{' GOG SCAN ':=^80}")

    try:
        # WHY: Use the official Bearer token authorization instead of flaky web cookies to bypass Cloudflare.
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        cloud_games = {}
        current_page = 1
        total_pages = 1
        
        # WHY: Use the standard web library endpoint. It natively respects the gog-al session cookie and returns paginated data.
        while current_page <= total_pages:
            if worker_thread and worker_thread.isInterruptionRequested(): return False
            
            url = f"https://www.gog.com/account/getFilteredProducts?mediaType=1&sortBy=title&page={current_page}"
            resp = requests.get(url, headers=headers, timeout=10)
            
            content_type = resp.headers.get('Content-Type', '')
            if resp.status_code != 200 or 'application/json' not in content_type:
                logging.error(f"[GOG.COM] Failed to fetch page {current_page}. Session might be expired.")
                return False
                
            data = resp.json()
            total_pages = data.get("totalPages", 1)
            for item in data.get("products", []):
                cloud_games[item["id"]] = item
                
            current_page += 1
            
    except Exception as e:
        logging.error(f"[GOG.COM] Error connecting to GOG: {e}")
        return False

    # WHY: Pre-fetch the IGDB token once for the session to avoid requesting it repeatedly for every new game.
    igdb_token = get_igdb_access_token()

    # WHY: Pre-emptive Diffing. We isolate strictly new purchases to save API bandwidth and time.
    # We also keep a reference to existing games to patch missing URLs using the bulk data.
    existing_gog_map = {}
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid.isdigit():
                existing_gog_map[int(gid)] = game
            elif gid.startswith('gog_') and gid[4:].isdigit():
                existing_gog_map[int(gid[4:])] = game

    cloud_ids = set(cloud_games.keys())
    new_ids = cloud_ids - set(existing_gog_map.keys())

    changes_made = False

    stats = {
        'total_cloud': len(cloud_ids),
        'already_in_db': len(set(existing_gog_map.keys()) & cloud_ids),
        'new_to_fetch': len(new_ids),
        'matched_smart': 0,
        'new_added': 0,
        'failed': 0
    }

    def print_report():
        stats['failed'] = stats['new_to_fetch'] - stats['matched_smart'] - stats['new_added']
        report = (
            f"{' REPORT ':=^80}\n"
            f"Total Cloud    : {stats['total_cloud']}\n"
            f"Already in DB  : {stats['already_in_db']}\n"
            f"New Added      : {stats['new_added']}\n"
            f"Smart Merged   : {stats['matched_smart']}\n"
            f"Errors / Skips : {stats['failed']}\n"
            f"{'='*80}"
        )
        logging.info(report)

    if not new_ids:
        print_report()
        return changes_made

    for gog_id in new_ids:
        if worker_thread and worker_thread.isInterruptionRequested():
            break

        # WHY: Use .get() to prevent KeyError if the License DB was used (which leaves cloud_games empty).
        base_item = cloud_games.get(gog_id, {})
        title_raw = base_item.get("title", "")
        
        if not title_raw:
            title_raw = f"Unknown GOG Game {gog_id}"
            
        title_clean = re.sub(r'\s*-\s*Amazon.*$', '', title_raw, flags=re.IGNORECASE)
        title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title_clean)
        
        # --- PASS 2: ZERO-COST SMART MATCH ---
        # WHY: GOG frequently uses different IDs for the Galaxy Client (releaseKey) vs the Web Store (Store ID).
        # We use the bulk RAM titles to catch these mismatches before firing any expensive API calls.
        norm_title = re.sub(r'[^a-z0-9]', '', title_clean.lower())
        best_score = 0
        best_game = None
        
        for game in games_dict.values():
            local_title = game.data.get('Clean_Title', '')
            local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
            
            score = 0
            if local_norm_title == norm_title: score += 60
            else:
                ratio = difflib.SequenceMatcher(None, title_clean.lower(), local_title.lower()).ratio()
                if ratio > 0.6: score += int(ratio * 60)
                else: continue
                
            local_platforms = game.data.get('Platforms', '').lower()
            if 'gog' in local_platforms: score += 20
            if local_norm_title == norm_title: score += 20
            
            if score > best_score:
                best_score, best_game = score, game
                
        threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
        
        if best_game and best_score >= threshold:
            
            current_ids = set(x.strip() for x in best_game.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(str(gog_id))
            best_game.data['game_ID'] = ", ".join(sorted(list(current_ids)))
            
            p_set = set(x.strip() for x in best_game.data.get('Platforms', '').split(',') if x.strip())
            if 'Local Copy' in p_set: p_set.remove('Local Copy')
            p_set.add('GOG')
            best_game.data['Platforms'] = ", ".join(sorted(list(p_set)))
            
            img_str = "Yes" if best_game.data.get('Image_Link') else "No "
            trl_str = "Yes" if best_game.data.get('Trailer_Link') else "No "
            action_title = f"Merged : {title_clean}"
            logging.info(f"|{action_title[:56]:<56}| Img: {img_str[:3]:<3} | Trl: {trl_str[:3]:<3} |")
            
            stats['matched_smart'] += 1
            changes_made = True
            continue
            
        # --- PASS 3: FULL API FETCH (GENUINE NEW GAMES) ---
        p_data = {}
        try:
            # Try to fetch rich metadata (Dev, Pub, Summary) from the public catalog API FIRST.
            p_resp = requests.get(f"https://api.gog.com/products/{gog_id}?expand=description", headers=headers, timeout=10)
            if p_resp.status_code == 200:
                p_data = p_resp.json()
        except Exception: pass

        fetched_title = p_data.get("title", "")
        if fetched_title:
            title_raw = fetched_title
            title_clean = re.sub(r'\s*-\s*Amazon.*$', '', title_raw, flags=re.IGNORECASE)
            title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title_clean)
            
        folder_name = get_safe_filename(title_clean) or f"Unknown Game [{gog_id}]"
        if folder_name in games_dict: folder_name = f"{title_clean} [{gog_id}]"
        
        game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='OK', Path_Root='')
        game_obj.data['Clean_Title'] = title_clean
        game_obj.data['game_ID'] = str(gog_id)
        game_obj.data['Platforms'] = "GOG"
        
        # WHY: Apply basic fallback data immediately in case the rich API fails.
        cat = base_item.get("category", "")
        if cat: game_obj.data['Genre'] = normalize_genre(cat)
        
        base_img = base_item.get("image", "")
        cover_url = ""
        img_ok = "No "

        urls_to_try = []
        cover_hash_source = base_img

        if p_data:
                
                devs = [d.get("name") for d in p_data.get("developers", [])]
                if devs: game_obj.data['Developer'] = ", ".join(devs)
                
                pubs = [p.get("name") for p in p_data.get("publishers", [])]
                if pubs: game_obj.data['Publisher'] = ", ".join(pubs)
                
                genres = [g.get("name") for g in p_data.get("genres", [])]
                if genres: game_obj.data['Genre'] = normalize_genre(", ".join(genres))
                
                desc = p_data.get("description", {}).get("full", "")
                if desc: game_obj.data['Summary'] = re.sub('<[^<]+?>', '', desc).strip()
                
                # WHY: Extract and parse the strict ISO-8601 release date provided by the Catalog API 
                # into ViGaVault's standard DD/MM/YYYY string format.
                release_date_raw = p_data.get("release_date")
                if release_date_raw:
                    try:
                        dt_str = release_date_raw.split('T')[0]
                        dt = datetime.strptime(dt_str, "%Y-%m-%d")
                        game_obj.data['Original_Release_Date'] = dt.strftime(config.get('date_format', '%d/%m/%Y'))
                    except Exception: pass
        
        # WHY: GOG image CDN is highly unreliable for vertical 3:4 posters.
        # We leverage the Single Responsibility Principle: Use GOG for perfect text metadata, 
        # but query IGDB strictly to harvest their standardized high-quality covers.
        if igdb_token:
            igdb_res = query_igdb_api(igdb_token, search_term=title_clean, limit=3)
            if igdb_res:
                best_match, best_score = None, -1
                for g in igdb_res:
                    score = int(difflib.SequenceMatcher(None, title_clean.lower(), g.get('name', '').lower()).ratio() * 100)
                    if g.get('category', 0) == 0: score += 15
                    elif g.get('category', 0) in [1, 2]: score -= 30
                    if score > best_score and 'cover' in g and 'url' in g['cover']:
                        best_score, best_match = score, g
                
                if best_match:
                    cover_url = "https:" + best_match['cover']['url'].replace('t_thumb', 't_cover_big')

        if cover_url:
            game_obj.data['Cover_URL'] = cover_url
            img_ok = "Yes"

        games_dict[folder_name] = game_obj
        changes_made = True

        action_title = f"Added : {title_clean}"
        logging.info(f"|{action_title[:56]:<56}| Img: {img_ok[:3]:<3} | Trl: No  |")
        
        stats['new_added'] += 1

    print_report()
    return changes_made