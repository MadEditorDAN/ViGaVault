# WHY: Single Responsibility Principle - Strictly handles interacting with the Epic Games API 
# to fetch owned items, query the catalog metadata, and safely merge the results.
import logging
import requests
import difflib
import re
from datetime import datetime

from .login_epic import get_epic_session, refresh_epic_token
from backend.api_igdb import get_igdb_access_token
from backend.game import Game
from ViGaVault_utils import get_safe_filename, normalize_genre

def scan_epic_account(config, games_dict, worker_thread=None):
    session = get_epic_session()
    access_token = session.get("access_token")
    
    # WHY: Always refresh the token at the start of a scan to guarantee it hasn't expired.
    fresh_token = refresh_epic_token()
    if fresh_token:
        access_token = fresh_token
    else:
        logging.warning("[EPIC GAMES] Could not refresh token. Attempting to use the existing one.")
    
    if not access_token:
        logging.error("[EPIC GAMES] No valid OAuth token found. Please connect your account in the Platform Manager.")
        return False
        
    logging.info(f"\n{' EPIC GAMES SCAN ':=^80}")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # WHY: Epic caps the library response at 100 items. We loop the cursor to guarantee we retrieve the entire 400+ library.
    records = []
    cursor = ""
    
    while True:
        if worker_thread and worker_thread.isInterruptionRequested(): return False
        # WHY: includeMetadata=true is strictly required for the Epic Library API to return the responseMetadata block containing the pagination cursor!
        url = "https://library-service.live.use1a.on.epicgames.com/library/api/public/items?includeMetadata=true"
        if cursor: url += f"&cursor={cursor}"

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logging.error(f"[EPIC GAMES] Failed to fetch library page: HTTP {resp.status_code}")
            break
            
        data = resp.json()
        page_records = data.get("records", [])
        records.extend(page_records)
        
        # WHY: The pagination token is nested inside the 'responseMetadata' key (with a lowercase 'm').
        meta = data.get("responseMetadata", {})
        new_cursor = meta.get("nextCursor")
        if not new_cursor: break
        
        cursor = new_cursor

    # WHY: Pre-calculate existing Epic games to rapidly skip known entries, avoiding heavy per-game API requests.
    existing_epic_set = set()
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid.startswith('epic_'):
                existing_epic_set.add(gid.replace('epic_', ''))

    changes_made = False
    igdb_token = None

    stats = {
        'total_cloud': len(records),
        'already_in_db': 0,
        'processed': 0,
        'new_added': 0,
        'matched_smart': 0,
        'errors': 0,
        'skipped': 0,
        'merged_titles': [],
        'ignored_titles': []
    }

    for item in records:
        if worker_thread and worker_thread.isInterruptionRequested(): break
        
        namespace = item.get("namespace")
        catalog_item_id = item.get("catalogItemId")
        app_name = item.get("appName")
        
        if not namespace or not catalog_item_id:
            stats['skipped'] += 1
            stats['ignored_titles'].append(str(app_name))
            continue
            
        # WHY: Fast-path skip. If the game already has this exact Epic ID attached in the database, 
        # strictly skip it regardless of Status_Flag to prevent infinite merge loops on DLCs/Unscrappable games.
        if catalog_item_id in existing_epic_set:
            stats['already_in_db'] += 1
            continue
            
        # WHY: Skip known developer tools and Engine components inherently polluting the library.
        if namespace == "ue":
            stats['skipped'] += 1
            stats['ignored_titles'].append(str(app_name))
            continue
            
        cat_url = f"https://catalog-public-service-prod06.ol.epicgames.com/catalog/api/shared/namespace/{namespace}/bulk/items?id={catalog_item_id}&includeDLCDetails=true&includeMainGameDetails=true&country=US&locale=en-US"
        
        try:
            c_resp = requests.get(cat_url, headers=headers, timeout=10)
            if c_resp.status_code != 200:
                stats['errors'] += 1
                stats['ignored_titles'].append(str(app_name))
                continue
                
            c_data = c_resp.json()
            if not c_data or not isinstance(c_data, dict):
                stats['skipped'] += 1
                stats['ignored_titles'].append(str(app_name))
                continue
                
            # Epic dynamically remaps keys based on versioning, so we extract the first available payload.
            game_meta = list(c_data.values())[0]
            
            # WHY: Protection against unexpected API responses (like string-based error messages) 
            # masquerading as game metadata. If it's not a dictionary, we cannot safely extract data from it.
            if not isinstance(game_meta, dict):
                stats['skipped'] += 1
                stats['ignored_titles'].append(str(app_name))
                continue
            
            title_raw = game_meta.get("title", app_name or "Unknown Epic Game")
            
            # WHY: DLC Filtering. Exclude expansions and consumables from cluttering the game list.
            categories = game_meta.get("categories", [])
            cat_paths = []
            for c in categories:
                # WHY: Protection against corrupted metadata where Epic returns raw strings instead of dictionaries.
                if isinstance(c, dict): cat_paths.append(c.get("path", "").lower())
                elif isinstance(c, str): cat_paths.append(c.lower())
                
            is_dlc = any("addon" in p or "dlc" in p or "consumable" in p for p in cat_paths)
            if is_dlc:
                stats['skipped'] += 1
                stats['ignored_titles'].append(title_raw)
                continue
                
            title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title_raw).strip()
            
            # --- ZERO-COST SMART MATCH ---
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
                if 'epic' in local_platforms: score += 20
                if local_norm_title == norm_title: score += 20
                
                if score > best_score:
                    best_score, best_game = score, game
                    
            threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
            
            if best_game and best_score >= threshold:
                current_ids = set(x.strip() for x in best_game.data.get('game_ID', '').split(',') if x.strip())
                current_ids.add(f"epic_{catalog_item_id}")
                best_game.data['game_ID'] = ", ".join(sorted(list(current_ids)))
                
                p_set = set(x.strip() for x in best_game.data.get('Platforms', '').split(',') if x.strip())
                if 'Local Copy' in p_set: p_set.remove('Local Copy')
                p_set.add('Epic Games Store')
                best_game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                
                img_str = "Yes" if best_game.data.get('Image_Link') else "No "
                trl_str = "Yes" if best_game.data.get('Trailer_Link') else "No "
                action_title = f"Merged : {title_clean}"
                logging.info(f"|{action_title[:56]:<56}| Img: {img_str[:3]:<3} | Trl: {trl_str[:3]:<3} |")
                
                stats['matched_smart'] += 1
                stats['merged_titles'].append(title_clean)
                changes_made = True
                continue
                
            # --- NEW GAME LOGIC ---
            folder_name = get_safe_filename(title_clean) or f"Unknown Game [{catalog_item_id}]"
            if folder_name in games_dict: folder_name = f"{title_clean} [{catalog_item_id}]"
            
            game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='NEW', Path_Root='')
            game_obj.data['Clean_Title'] = title_clean
            game_obj.data['game_ID'] = f"epic_{catalog_item_id}"
            game_obj.data['Platforms'] = "Epic Games Store"
            
            desc = game_meta.get('description', '')
            game_obj.data['Summary'] = desc
            
            # WHY: Epic stores Dev/Pub in a generic array of Key/Value pairs. We extract them via matching keys.
            custom_attrs = game_meta.get("customAttributes")
            if isinstance(custom_attrs, list):
                for attr in custom_attrs:
                    if isinstance(attr, dict):
                        if attr.get("key") == "developerName": game_obj.data["Developer"] = attr.get("value", "")
                        elif attr.get("key") == "publisherName": game_obj.data["Publisher"] = attr.get("value", "")
                        elif "video" in attr.get("key", "").lower(): game_obj.data["Trailer_Link"] = attr.get("value", "")
            elif isinstance(custom_attrs, dict):
                # WHY: The newer bulk catalog API returns customAttributes as a nested dictionary instead of a list.
                dev = custom_attrs.get("developerName", {}).get("value", "")
                if dev: game_obj.data["Developer"] = dev
                
                pub = custom_attrs.get("publisherName", {}).get("value", "")
                if pub: game_obj.data["Publisher"] = pub
                
                for k, v in custom_attrs.items():
                    if isinstance(v, dict) and "video" in k.lower():
                        game_obj.data["Trailer_Link"] = v.get("value", "")
                
            # WHY: If Epic didn't provide a direct video attribute, we scan the raw description text for hidden MP4s or YouTube links.
            if not game_obj.data.get('Trailer_Link'):
                yt_match = re.search(r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+|https?://youtu\.be/[\w-]+|https?://[^\s\"\']+\.mp4)', desc)
                if yt_match: game_obj.data['Trailer_Link'] = yt_match.group(1)
            
            # WHY: As requested, we completely ignore Epic's unstandardized images. 
            # By deliberately leaving Cover_URL blank, we guarantee the IGDB engine will fetch a high-quality vertical poster.
                
            # WHY: Check if any core metadata is missing, and scan with IGDB to backfill.
            # We added Trailer_Link to the requirements so IGDB will fetch a YouTube trailer if Epic didn't provide an MP4.
            missing_meta = not all([game_obj.data.get(f) for f in ['Developer', 'Publisher', 'Genre', 'Summary', 'Original_Release_Date', 'Trailer_Link']])
            if (missing_meta or not game_obj.data.get('Cover_URL')):
                # WHY: Lazy load the IGDB token only when actually needed to minimize unneeded auth requests.
                if not igdb_token:
                    igdb_token = get_igdb_access_token()
                if igdb_token:
                    game_obj.fill_missing_metadata(igdb_token)
                
            game_obj.data['Status_Flag'] = 'OK'
            img_ok = "Yes" if game_obj.data.get('Cover_URL') or game_obj.data.get('Image_Link') else "No "
            
            games_dict[folder_name] = game_obj
            changes_made = True
            stats['new_added'] += 1
            
            action_title = f"Added : {title_clean}"
            logging.info(f"|{action_title[:56]:<56}| Img: {img_ok[:3]:<3} | Trl: No  |")
            
        except Exception as e:
            logging.error(f"    [EPIC ERROR] Failed processing {app_name}: {e}")
            stats['errors'] += 1
            stats['ignored_titles'].append(str(app_name))
            
    # WHY: Dynamically append captured titles using exact space formatting so they cleanly indent under the colons.
    report = f"{' REPORT ':=^80}\n"
    report += f"Total Cloud    : {stats['total_cloud']}\n"
    report += f"Already in DB  : {stats['already_in_db']}\n"
    report += f"New Added      : {stats['new_added']}\n"
    report += f"Smart Merged   : {stats['matched_smart']}\n"
    for t in stats['merged_titles']: report += f"                 {t}\n"
    report += f"DLCs/Ignored   : {stats['errors'] + stats['skipped']}\n"
    for t in stats['ignored_titles']: report += f"                 {t}\n"
    report += f"{'='*80}"
    
    logging.info(report)
    return changes_made