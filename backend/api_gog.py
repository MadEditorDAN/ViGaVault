# WHY: Single Responsibility Principle - Isolates GOG SQLite parsing and game metadata mapping.
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

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.webm')
_yt_dlp_warning_logged = False

def sync_gog_database(config, games_dict, worker_thread=None):
    global _yt_dlp_warning_logged
    logging.info("--- START OF GOG SYNC ---")
    gog_db_path = config.get('gog_db_path', os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db'))

    if not os.path.exists(gog_db_path):
        logging.error(f"GOG Galaxy database not found at: {gog_db_path}")
        return

    try:
        con = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
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
        logging.error(f"Error reading GOG database: {e}")
        if 'con' in locals() and con: con.close()
        return

    images_dir = config.get('image_path', os.path.join(BASE_DIR, 'images'))
    os.makedirs(images_dir, exist_ok=True)
    video_dir = config.get('video_path', os.path.join(BASE_DIR, 'videos'))
    os.makedirs(video_dir, exist_ok=True)
    
    stats = {'total_found': 0, 'processed': 0, 'new': 0, 'matched_key': 0, 'matched_smart': 0, 'errors': 0, 'deleted_ghosts': 0, 'images_found_existing': 0, 'images_downloaded': 0, 'videos_found_existing': 0, 'videos_downloaded': 0, 'videos_download_fail': 0, 'new_by_platform': {}}

    key_to_game_map = {}
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid: key_to_game_map[gid] = game
    
    found_gog_keys = set()
    processed_games_session = set()

    while True:
        if worker_thread and worker_thread.isInterruptionRequested(): break
        row = cursor.fetchone()
        if row is None: break

        stats['total_found'] += 1
        (releaseKey, meta_json, title_json, orig_title_json, summary_json, 
         developers_json, publishers_json, original_images_json, all_releases_json, 
         product_name, ld_title, ld_summary, ld_release_date, ld_images) = row

        found_gog_keys.add(releaseKey)

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

            platform = 'Unknown'
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

            gog_dev = meta_data.get('developer')
            if not gog_dev:
                d_data = safe_json_load(developers_json)
                if isinstance(d_data, list): gog_dev = ", ".join(d_data)
            
            gog_pub = meta_data.get('publisher')
            if not gog_pub:
                p_data = safe_json_load(publishers_json)
                if isinstance(p_data, list): gog_pub = ", ".join(p_data)

            gog_year = None
            if release_ts := meta_data.get('releaseTimestamp'): gog_year = datetime.utcfromtimestamp(release_ts).strftime('%Y')
            elif ld_release_date:
                try: gog_year = ld_release_date[:4]
                except: pass

            game_obj = None
            if releaseKey in key_to_game_map:
                game_obj = key_to_game_map[releaseKey]
                stats['matched_key'] += 1
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
                    if gog_dev and gog_dev.lower() in local_dev: score += 10
                    elif gog_pub and gog_pub.lower() in local_pub: score += 10
                    
                    local_year = game.data.get('Year_Folder', '')
                    if not local_year and game.data.get('Original_Release_Date'):
                         try: local_year = game.data.get('Original_Release_Date')[-4:]
                         except: pass
                    
                    year_mismatch = False
                    if gog_year and local_year:
                        try:
                            if abs(int(gog_year) - int(local_year)) > 3: year_mismatch = True
                        except: pass
                    
                    if year_mismatch: score -= 50
                    elif gog_year and local_year and gog_year == local_year: score += 10

                    if local_norm_title == norm_title: score += 20
                    if score > best_score:
                        best_score, best_game = score, game
                
                threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
                if best_game and best_score >= threshold:
                    game_obj = best_game
                    logging.info(f"    [GOG MATCH SMART] Game recognized by title (Score: {best_score}): '{title}' -> '{best_game.data.get('Clean_Title')}'")
                    stats['matched_smart'] += 1
            
            if not game_obj:
                folder_name = get_safe_filename(title)
                if not folder_name: folder_name = f"Unknown Game [{releaseKey}]"
                if folder_name in games_dict: folder_name = f"{title} [{releaseKey}]"
                logging.info(f"    [GOG NEW] Adding game: '{title}' ({platform})")
                game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='OK', Path_Root='')
                stats['new'] += 1
                stats['new_by_platform'][platform] = stats['new_by_platform'].get(platform, 0) + 1

            force_media_refresh = game_obj.data.get('Status_Flag') == 'NEW'
            if force_media_refresh:
                logging.info(f"    [GOG REFRESH] 'NEW' status detected for '{title}'. Checking for missing media.")
            if game_obj.data.get('Status_Flag') == 'LOCKED':
                logging.info(f"    [LOCKED] Skipping metadata update for protected game: {title}")
                continue

            current_ids = set(x.strip() for x in game_obj.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(releaseKey)
            game_obj.data['game_ID'] = ", ".join(sorted(list(current_ids)))
            game_obj.data['Clean_Title'] = title
            
            current_platforms = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
            if 'Unknown' in current_platforms: current_platforms.remove('Unknown')
            # WHY: Remove "Local Copy" tag if we have a real platform or if the game is a ghost (not installed locally).
            if platform != 'Unknown' and 'Local Copy' in current_platforms: current_platforms.remove('Local Copy')
            if not game_obj.data.get('Path_Root') and 'Local Copy' in current_platforms: current_platforms.remove('Local Copy')
            if platform != 'Unknown' or not current_platforms: current_platforms.add(platform)
            
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

            if gog_dev: game_obj.data['Developer'] = gog_dev
            if gog_pub: game_obj.data['Publisher'] = gog_pub

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
                try: release_date = datetime.utcfromtimestamp(release_ts).strftime('%d/%m/%Y')
                except: pass
            elif ld_release_date:
                clean_date_str = ld_release_date.split('T')[0]
                try:
                    dt = datetime.strptime(clean_date_str, '%Y-%m-%d')
                    release_date = dt.strftime('%d/%m/%Y')
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

            # --- C. Video Download (yt-dlp) & Physical Check ---
            existing_video_name = game_obj.data.get('Path_Video')
            existing_video_path = os.path.join(video_dir, os.path.basename(existing_video_name)) if existing_video_name else ''
            video_exists_on_disk = bool(existing_video_name and os.path.exists(existing_video_path))
            
            if video_exists_on_disk: stats['videos_found_existing'] += 1

            if not video_exists_on_disk:
                for ext in VIDEO_EXTS:
                    potential_path = os.path.join(video_dir, f"{safe_filename}{ext}")
                    if os.path.exists(potential_path):
                        game_obj.data['Path_Video'] = f"{safe_filename}{ext}"
                        video_exists_on_disk = True
                        stats['videos_found_existing'] += 1
                        break

            if worker_thread and worker_thread.isInterruptionRequested(): break

            is_youtube = video_url and ('youtube.com' in video_url or 'youtu.be' in video_url)
            is_downloadable_url = video_url and video_url.startswith('http') and not is_youtube

            if is_downloadable_url and not video_exists_on_disk:
                # WHY: Respect the Media Download config
                if config.get('download_videos', False):
                    if YT_DLP_AVAILABLE:
                        try:
                            logging.info(f"    [VIDEO] Found video URL, downloading with yt-dlp: {safe_filename} ...")
                            def progress_hook(d):
                                if worker_thread and worker_thread.isInterruptionRequested():
                                    raise Exception("Download interrupted by user")
                            ydl_opts = {
                                'outtmpl': os.path.join(video_dir, f"{safe_filename}.%(ext)s"),
                                'quiet': True,
                                'no_warnings': True,
                                'format': 'bestvideo+bestaudio/best', 
                                'progress_hooks': [progress_hook],
                            }
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                info = ydl.extract_info(video_url, download=True)
                                filename = ydl.prepare_filename(info)
                                if os.path.exists(filename):
                                    game_obj.data['Path_Video'] = os.path.basename(filename)
                                    stats['videos_downloaded'] += 1
                        except Exception as e:
                            if "Download interrupted" in str(e): break
                            stats['videos_download_fail'] += 1
                    else:
                        if not getattr(LibraryManager, '_yt_dlp_warning_logged', False):
                            logging.warning("    [VIDEO] yt-dlp module not installed, skipping video downloads.")
                            LibraryManager._yt_dlp_warning_logged = True

            # --- D. Image Download & Physical Check ---
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
                
                existing_image_name = game_obj.data.get('Image_Link')
                existing_image_path = os.path.join(images_dir, os.path.basename(existing_image_name)) if existing_image_name else ''
                image_exists_on_disk = bool(existing_image_name and os.path.exists(existing_image_path))

                if image_exists_on_disk: stats['images_found_existing'] += 1

                if not image_exists_on_disk:
                    for check_ext in ['.jpg', '.png', '.jpeg', '.webp']:
                        check_path = os.path.join(images_dir, f"{safe_filename}{check_ext}")
                        if os.path.exists(check_path):
                            game_obj.data['Image_Link'] = f"{safe_filename}{check_ext}"
                            image_exists_on_disk = True
                            stats['images_found_existing'] += 1
                            break

                if not image_exists_on_disk:
                    try:
                        path = urlparse(cover_url).path
                        ext = os.path.splitext(path)[1]
                        if not ext and 'gog.com' in cover_url: ext = '.webp'
                        elif not ext: ext = '.jpg'
                    except: ext = '.jpg'
                    
                    save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
                    
                    # WHY: Respect the Media Download config
                    if config.get('download_images', True):
                        try:
                            response = requests.get(cover_url, timeout=5)
                            if response.status_code == 200:
                                with open(save_path, 'wb') as f: f.write(response.content)
                                game_obj.data['Image_Link'] = f"{safe_filename}{ext}"
                                logging.info(f"    [IMAGE] Downloaded missing image: {safe_filename}{ext}")
                                stats['images_downloaded'] += 1
                        except Exception as e: pass

            # End of loop assignment
            if force_media_refresh: game_obj.data['Status_Flag'] = 'OK'
            games_dict[game_obj.data['Folder_Name']] = game_obj
            stats['processed'] += 1
        except Exception as e:
            logging.error(f"    [GOG ERROR] Error processing game '{title}' (releaseKey: {releaseKey}): {e}")
            stats['errors'] += 1

    con.close()
    
    if not (worker_thread and worker_thread.isInterruptionRequested()):
        ghosts_to_delete = []
        for folder_name, game in games_dict.items():
            if not game.data.get('Path_Root'):
                game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
                is_valid = False
                for gid in game_ids:
                    if gid in found_gog_keys:
                        is_valid = True
                        break
                if not is_valid:
                    ghosts_to_delete.append(folder_name)

        for folder in ghosts_to_delete:
            logging.info(f"    [GOG CLEANUP] Removing obsolete platform entry: {folder}")
            del games_dict[folder]
            stats['deleted_ghosts'] += 1

    sorted_platforms = sorted(stats['new_by_platform'].items())
    platform_stats = "\n".join([f"  - {p}: {c}" for p, c in sorted_platforms])
    if not platform_stats: platform_stats = "  (None)"

    report = (
        "\n=== GOG SYNC REPORT ===\n"
        f"Games found in GOG: {stats['total_found']}\n"
        f"Games processed successfully: {stats['processed']}\n"
        f"-----------------------------------\n"
        f"New games added: {stats['new']}\n"
        f"{platform_stats}\n"
        f"Updates (Unique Key): {stats['matched_key']}\n"
        f"Updates (Smart): {stats['matched_smart']}\n"
        f"Removed (Obsolete Ghosts): {stats['deleted_ghosts']}\n"
        f"Errors / Ignored: {stats['errors']}\n"
        f"==================================="
    )
    logging.info(report)