# WHY: Single Responsibility Principle - Isolates Galaxy SQLite parsing and game metadata mapping.
import os
import re
import json
import sqlite3
import logging
import difflib
import requests
import shutil
from datetime import datetime
from urllib.parse import urlparse

from ViGaVault_utils import BASE_DIR, get_safe_filename, normalize_genre
from .game import Game

def sync_galaxy_database(config, games_dict, worker_thread=None):
    logging.info(f"\n{' GALAXY SYNC ':=^80}")
    galaxy_db_path = config.get('galaxy_db_path', os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db'))

    if not os.path.exists(galaxy_db_path):
        logging.error(f"Galaxy database not found at: {galaxy_db_path}")
        return

    try:
        con = sqlite3.connect(f'file:{galaxy_db_path}?mode=ro', uri=True)
        cursor = con.cursor()
        query = """SELECT DISTINCT
 urp.releaseKey,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'meta' LIMIT 1) as meta_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'title' LIMIT 1) as title_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'originalTitle' LIMIT 1) as orig_title_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'summary' LIMIT 1) as summary_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'developers' LIMIT 1) as developers_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'publishers' LIMIT 1) as publishers_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'originalImages' LIMIT 1) as original_images_json,
 (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'allGameReleases' LIMIT 1) as all_releases_json,
 (SELECT name FROM Products p JOIN ReleaseProperties rp ON p.id = rp.gameId WHERE rp.releaseKey = urp.releaseKey LIMIT 1) as product_name,
 (SELECT title FROM LimitedDetails WHERE productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_title,
 (SELECT description FROM Details d JOIN LimitedDetails ld ON d.limitedDetailsId = ld.id WHERE ld.productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_summary,
 (SELECT releaseDate FROM Details d JOIN LimitedDetails ld ON d.limitedDetailsId = ld.id WHERE ld.productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_release_date,
 (SELECT images FROM LimitedDetails WHERE productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_images
 FROM
 UserReleaseProperties urp
 LEFT JOIN
 ReleaseProperties rp ON urp.releaseKey = rp.releaseKey
 WHERE
 (rp.isDlc IS NULL OR rp.isDlc = 0)"""
        cursor.execute(query)
    except Exception as e:
        logging.error(f"Error reading Galaxy database: {e}")
        if 'con' in locals() and con: con.close()
        return

    images_dir = config.get('image_path', os.path.join(BASE_DIR, 'images'))
    os.makedirs(images_dir, exist_ok=True)
    
    stats = {'total_found': 0, 'processed': 0, 'new': 0, 'matched_key': 0, 'matched_smart': 0, 'errors': 0, 'deleted_ghosts': 0, 'new_by_platform': {}}

    key_to_game_map = {}
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid: key_to_game_map[gid] = game
    
    found_galaxy_keys = set()
    processed_games_session = set()

    while True:
        if worker_thread and worker_thread.isInterruptionRequested(): break
        row = cursor.fetchone()
        if row is None: break

        stats['total_found'] += 1
        (releaseKey, meta_json, title_json, orig_title_json, summary_json, 
         developers_json, publishers_json, original_images_json, all_releases_json, 
         product_name, ld_title, ld_summary, ld_release_date, ld_images) = row

        found_galaxy_keys.add(releaseKey)

        def safe_json_load(json_str):
            if not json_str: return None
            try: return json.loads(json_str)
            except: return None

        all_releases_data = safe_json_load(all_releases_json)
        releases_list = all_releases_data.get('releases', []) if all_releases_data else []
        meta_data = safe_json_load(meta_json) or {}

        title = meta_data.get('title')
        if not title:
            def extract_title_from_json(json_str):
                if not json_str: return None
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict): return data.get('title') or data.get('value') or data.get('originalTitle')
                    return str(data)
                except: return json_str
            title = extract_title_from_json(title_json)
            if not title: title = extract_title_from_json(orig_title_json)
        if not title: title = product_name
        if not title: title = ld_title

        try:
            if not title:
                stats['errors'] += 1
                continue

            title = re.sub(r'\s*-\s*Amazon.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title)

            # WHY: Using an underscore leverages ASCII sorting to force it to the very top of the filter list.
            platform = '_UNKNOWN'
            if '_' in releaseKey:
                prefix = releaseKey.split('_', 1)[0].lower()
                platform_map = config.get('platform_map', {})
                ignored_prefixes = config.get('ignored_prefixes', [])
                if prefix not in ignored_prefixes:
                    platform = platform_map.get(prefix, prefix.title())
            elif releaseKey.isdigit(): platform = 'GOG'

            session_key = (re.sub(r'[^a-z0-9]', '', title.lower()), platform)
            if session_key in processed_games_session: continue
            processed_games_session.add(session_key)

            galaxy_dev = meta_data.get('developer')
            if not galaxy_dev:
                d_data = safe_json_load(developers_json)
                if isinstance(d_data, list): galaxy_dev = ", ".join(d_data)
            
            galaxy_pub = meta_data.get('publisher')
            if not galaxy_pub:
                p_data = safe_json_load(publishers_json)
                if isinstance(p_data, list): galaxy_pub = ", ".join(p_data)

            galaxy_year = None
            if release_ts := meta_data.get('releaseTimestamp'): galaxy_year = datetime.utcfromtimestamp(release_ts).strftime('%Y')
            elif ld_release_date:
                try: galaxy_year = ld_release_date[:4]
                except: pass

            act_str = ""
            game_obj = None
            if releaseKey in key_to_game_map:
                game_obj = key_to_game_map[releaseKey]
                stats['matched_key'] += 1
                act_str = "Updated"
            else:
                best_score = 0
                best_game = None
                norm_title = re.sub(r'[^a-z0-9]', '', title.lower())
                
                for game in games_dict.values():
                    local_title = game.data.get('Clean_Title', '')
                    local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
                    score = 0
                    if local_norm_title == norm_title: score += 60
                    else:
                        ratio = difflib.SequenceMatcher(None, title.lower(), local_title.lower()).ratio()
                        if ratio > 0.6: score += int(ratio * 60)
                        else: continue

                    local_platforms = game.data.get('Platforms', '').lower()
                    if platform.lower() in local_platforms: score += 20

                    local_dev = game.data.get('Developer', '').lower()
                    local_pub = game.data.get('Publisher', '').lower()
                    if galaxy_dev and galaxy_dev.lower() in local_dev: score += 10
                    elif galaxy_pub and galaxy_pub.lower() in local_pub: score += 10
                    
                    local_year = game.data.get('Year_Folder', '')
                    if not local_year and game.data.get('Original_Release_Date'):
                         try: local_year = game.data.get('Original_Release_Date')[-4:]
                         except: pass
                    
                    year_mismatch = False
                    if galaxy_year and local_year:
                        try:
                            if abs(int(galaxy_year) - int(local_year)) > 3: year_mismatch = True
                        except: pass
                    
                    if year_mismatch: score -= 50
                    elif galaxy_year and local_year and galaxy_year == local_year: score += 10

                    if local_norm_title == norm_title: score += 20
                    if score > best_score:
                        best_score, best_game = score, game
                
                threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
                if best_game and best_score >= threshold:
                    game_obj = best_game
                    stats['matched_smart'] += 1
                    act_str = "Merged"
            
            if not game_obj:
                folder_name = get_safe_filename(title)
                if not folder_name: folder_name = f"Unknown Game [{releaseKey}]"
                if folder_name in games_dict: folder_name = f"{title} [{releaseKey}]"
                game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='OK', Path_Root='')
                stats['new'] += 1
                stats['new_by_platform'][platform] = stats['new_by_platform'].get(platform, 0) + 1
                act_str = "Added"

            force_media_refresh = game_obj.data.get('Status_Flag') == 'NEW'
            if force_media_refresh:
                act_str = "Refresh"
            if game_obj.data.get('Status_Flag') == 'LOCKED':
                continue

            current_ids = set(x.strip() for x in game_obj.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(releaseKey)
            game_obj.data['game_ID'] = ", ".join(sorted(list(current_ids)))
            game_obj.data['Clean_Title'] = title
            
            current_platforms = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
            # WHY: Remove "Local Copy" tag if we have a real platform or if the game is a ghost (not installed locally).
            if platform != '_UNKNOWN' and 'Local Copy' in current_platforms: current_platforms.remove('Local Copy')
            if not game_obj.data.get('Path_Root') and 'Local Copy' in current_platforms: current_platforms.remove('Local Copy')
            if platform != '_UNKNOWN' or not current_platforms: current_platforms.add(platform)
            
            for i in range(50):
                col_name = f"platform_ID_{i+1:02d}"
                if i < len(releases_list): game_obj.data[col_name] = releases_list[i]
                else: game_obj.data[col_name] = ""
            game_obj.data['Platforms'] = ", ".join(sorted(list(current_platforms)))

            summary = meta_data.get('summary')
            if not summary:
                s_data = safe_json_load(summary_json)
                if isinstance(s_data, dict): summary = s_data.get('summary') or s_data.get('value')
            if not summary: summary = ld_summary
            if summary: game_obj.data['Summary'] = summary

            if galaxy_dev: game_obj.data['Developer'] = galaxy_dev
            if galaxy_pub: game_obj.data['Publisher'] = galaxy_pub

            genres = meta_data.get('genres')
            if genres:
                raw_genre = ""
                if isinstance(genres, list):
                    if len(genres) > 0 and isinstance(genres[0], dict): raw_genre = ", ".join([g.get('name', '') for g in genres if g.get('name')])
                    else: raw_genre = ", ".join([str(g) for g in genres])
                game_obj.data['Genre'] = normalize_genre(raw_genre)

            release_date = None
            release_ts = meta_data.get('releaseDate') or meta_data.get('releaseTimestamp')
            if release_ts:
                try: release_date = datetime.utcfromtimestamp(release_ts).strftime(config.get('date_format', '%d/%m/%Y'))
                except: pass
            elif ld_release_date:
                clean_date_str = ld_release_date.split('T')[0]
                try:
                    dt = datetime.strptime(clean_date_str, '%Y-%m-%d')
                    release_date = dt.strftime(config.get('date_format', '%d/%m/%Y'))
                except ValueError: release_date = ld_release_date
            if release_date: game_obj.data['Original_Release_Date'] = release_date

            folder_name_for_files = game_obj.data['Folder_Name']
            base_filename = game_obj.data.get('Clean_Title', folder_name_for_files)
            file_year = f" ({release_date[-4:]})" if release_date else ''
            safe_filename = get_safe_filename(f"{base_filename}{file_year}")

            # --- VIDEO MANAGEMENT (Trailer & Download) ---
            video_url = game_obj.data.get('Trailer_Link')
            existing_trailer = game_obj.data.get('Trailer_Link', '')
            
            steam_app_id = None
            if platform == 'Steam':
                steam_app_id = releaseKey.replace('steam_', '')
            else:
                for r in releases_list:
                    if r.startswith('steam_'):
                        steam_app_id = r.replace('steam_', '')
                        break

            if not existing_trailer and steam_app_id and steam_app_id.isdigit():
                try:
                    app_id = steam_app_id
                    steam_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
                    headers = {'User-Agent': 'ViGaVault/1.0'}
                    resp = requests.get(steam_url, timeout=5, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and data.get(app_id, {}).get('success'):
                            movies = data[app_id]['data'].get('movies', [])
                            if movies:
                                video_url = movies[0].get('mp4', {}).get('max')
                                if not video_url: video_url = movies[0].get('hls_h264')
                                if not video_url: video_url = 'Not_on_Steam'
                            else:
                                video_url = 'Not_on_Steam'
                        else:
                            video_url = 'Not_on_Steam'
                except Exception as e: pass

            if video_url: game_obj.data['Trailer_Link'] = video_url

            # --- D. Image URL Extraction ---
            cover_url = meta_data.get('image')
            if not cover_url:
                orig_imgs = safe_json_load(original_images_json)
                if orig_imgs:
                    cover_url = orig_imgs.get('verticalCover') or orig_imgs.get('boxart') or orig_imgs.get('poster') or orig_imgs.get('squareIcon') or orig_imgs.get('background')

            if not cover_url and ld_images:
                imgs = safe_json_load(ld_images)
                if isinstance(imgs, list) and len(imgs) > 0:
                    preferred_types = ['boxart', 'vertical_cover', 'packshot', 'poster']
                    cover_url = next((img.get('url') for img in imgs if img.get('type') in preferred_types), None)
                    if not cover_url:
                        cover_url = next((img.get('url') for img in imgs if img.get('type') != 'screenshot'), None)
            
            if cover_url:
                if cover_url.startswith('//'): cover_url = "https:" + cover_url
                
                # WHY: Always save the URL to the DB for asynchronous backfilling.
                game_obj.data['Cover_URL'] = cover_url
                
            if act_str in ["Added", "Merged", "Refresh"]:
                img_str = "Yes" if game_obj.data.get('Cover_URL') or game_obj.data.get('Image_Link') else "No "
                trl_str = "Yes" if game_obj.data.get('Trailer_Link') and game_obj.data.get('Trailer_Link') != 'Not_on_Steam' else "No "
                
                action_title = f"{act_str} : {title}"
                logging.info(f"|{action_title[:56]:<56}| Img: {img_str[:3]:<3} | Trl: {trl_str[:3]:<3} |")
                
            # End of loop assignment
            if force_media_refresh: game_obj.data['Status_Flag'] = 'OK'
            games_dict[game_obj.data['Folder_Name']] = game_obj
            stats['processed'] += 1
        except Exception as e:
            logging.error(f"    [GALAXY ERROR] Error processing game '{title}' (releaseKey: {releaseKey}): {e}")
            stats['errors'] += 1

    con.close()
    
    if not (worker_thread and worker_thread.isInterruptionRequested()):
        ghosts_to_delete = []
        for folder_name, game in games_dict.items():
            if not game.data.get('Path_Root'):
                
                # WHY: Jurisdiction Check - If the standalone GOG Web connector is active, 
                # it acts as the absolute master for GOG games. Galaxy is forbidden from deleting 
                # them just because they are Goodies or omitted from the Galaxy SQLite DB.
                platforms = [p.strip() for p in game.data.get('Platforms', '').split(',') if p.strip()]
                if 'GOG' in platforms and config.get('enable_gog_web', False):
                    continue

                game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
                is_valid = False
                for gid in game_ids:
                    if gid in found_galaxy_keys:
                        is_valid = True
                        break
                if not is_valid:
                    ghosts_to_delete.append(folder_name)

        for folder in ghosts_to_delete:
            action_title = f"Ghost Delete : {folder}"
            logging.info(f"|{action_title[:56]:<56}| Img: No  | Trl: No  |")
            del games_dict[folder]
            stats['deleted_ghosts'] += 1

    report = (
        f"{' REPORT ':=^80}\n"
        f"Games found in GALAXY: {stats['total_found']}\n"
        f"Games processed successfully: {stats['processed']}\n"
        f"New Added      : {stats['new']}\n"
        f"Smart Merged   : {stats['matched_smart']}\n"
        f"Ghosts Removed : {stats['deleted_ghosts']}\n"
        f"Errors / Ignored: {stats['errors']}\n"
        f"{'='*80}"
    )
    logging.info(report)