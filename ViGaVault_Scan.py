import os
import re
import pandas as pd
import logging
import shutil
import ctypes
import requests
import sqlite3
import json
import argparse
from datetime import datetime
from urllib.parse import urlparse
import difflib


# --- CONFIGURATION ---
ROOT_PATH = r"\\madhdd02\Software\GAMES"
DB_FILE = "VGVDB.csv"
LOG_DIR = "./logs"
BACKUP_DIR = "./backups"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.webm')
MAX_FILES = 10 

# --- API CONFIGURATION ---
IGDB_CLIENT_ID = "a6q5htw1uxkye5kta223vwjs2qlace"
IGDB_CLIENT_SECRET = "psmi013osf0leudnb0jlyzpr8xz9fq"

# --- LOGGING SETUP ---
def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logs = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.startswith("scan_")]
    logs.sort(key=os.path.getctime)
    while len(logs) >= MAX_FILES:
        os.remove(logs.pop(0))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"scan_{timestamp}.log")
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s [%(levelname)s] %(message)s', 
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'), 
            logging.StreamHandler() # This one sends everything to the console
        ]
    )
setup_logging()

def get_safe_filename(name):
    """Cleans a name to make it safe for a filename."""
    # Replace colons with a space
    safe_name = name.replace(':', ' ')
    # Remove anything that is not alphanumeric, space, dash, dot, parentheses, etc.
    safe_name = re.sub(r'[^\w\s\-\.\(\)\[\]]', '', safe_name).strip()
    # Replace multiple spaces with a single one
    safe_name = re.sub(r'\s{2,}', ' ', safe_name).strip()
    # Remove trailing dot (problematic on Windows)
    safe_name = safe_name.rstrip('. ')
    return safe_name


def is_hidden(filepath):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
        return attrs != -1 and (attrs & 2)
    except:
        return False

class Game:
    def __init__(self, **kwargs):
        self.data = kwargs
        self.data.setdefault('Folder_Name', 'Unknown')
        self.data.setdefault('Path_Root', '')
        self.data.setdefault('Status_Flag', 'NEW')
        self.data.setdefault('Platforms', '')
        if not self.data.get('Clean_Title'):
            self._parse_folder_name()
        self._find_video()
        self._find_image()

    def _parse_folder_name(self):
        name = self.data['Folder_Name']
        
        # Platform detection
        tag_match = re.search(r'\(([^)]+)\)$', name)
        if tag_match:
            tag_content = tag_match.group(1)
            
            # Map for platform name canonicalization
            platform_map = {
                'gog': 'GOG',
                'steam': 'Steam',
                'epic games store': 'Epic Games Store',
                'uplay': 'Uplay',
                'origin': 'Origin',
                'amazon': 'Amazon'
            }
            platform_pattern = r'|'.join(platform_map.keys())
            found_platforms_raw = re.findall(platform_pattern, tag_content, re.IGNORECASE)
            
            if found_platforms_raw:
                canonical_platforms = {platform_map[p.lower()] for p in found_platforms_raw}
                self.data['Platforms'] = ", ".join(sorted(list(canonical_platforms)))

        if not self.data.get('Platforms'):
            self.data['Platforms'] = 'Warez'

        # Clean up the name for the title
        clean_name = re.sub(r'\s*\([^)]*\)$', '', name).strip() # Remove the last parenthesis
        year_match = re.match(r'^(\d{4})\s*-\s*', clean_name)
        if year_match:
            self.data['Year_Folder'] = year_match.group(1)
            clean_name = clean_name[len(year_match.group(0)):]
            
        self.data['Clean_Title'] = clean_name
        self.data['Search_Title'] = clean_name

    def _find_video(self):
        folder = self.data.get('Path_Root', '')
        name = self.data.get('Folder_Name', '')
        if not folder or not os.path.exists(folder):
            return
            
        # Search in the parent folder (next to the game folder)
        parent_dir = os.path.dirname(folder)
            
        for ext in VIDEO_EXTS:
            v_path = os.path.join(parent_dir, f"{name}{ext}")
            if os.path.exists(v_path):
                # Update only if it's new or different
                current_video_path = self.data.get('Path_Video', '')
                
                # Robust normalization (Absolute + Normalized + Case) to avoid false positives
                try:
                    p1 = os.path.normcase(os.path.abspath(os.path.normpath(current_video_path))) if current_video_path else ""
                    p2 = os.path.normcase(os.path.abspath(os.path.normpath(v_path)))
                except:
                    p1 = os.path.normcase(current_video_path) if current_video_path else ""
                    p2 = os.path.normcase(v_path)

                if p1 != p2:
                    self.data['Path_Video'] = v_path
                    logging.info(f"    [VIDEO] Found: {name}{ext}")
                return

    def _find_image(self):
        # If the link already exists and is valid, do nothing
        current_path = self.data.get('Image_Link', '')
        if current_path and os.path.exists(current_path):
            return

        # Otherwise, check if an image already exists in the images folder
        safe_name = get_safe_filename(self.data.get('Folder_Name', ''))
        for ext in ['.jpg', '.png', '.jpeg', '.webp']:
            potential_path = os.path.join("images", f"{safe_name}{ext}")
            if os.path.exists(potential_path):
                self.data['Image_Link'] = potential_path
                logging.info(f"    [IMAGE] Found locally: {safe_name}{ext}")
                return

    def _ensure_cover(self, game_info, force_download=False):
        existing_path = self.data.get('Image_Link', '')
        
        # If not forcing, check for existence as before
        if not force_download and existing_path and os.path.exists(existing_path):
            return existing_path

        # If we get here, it means we must (re)download
        if 'cover' in game_info:
            os.makedirs("images", exist_ok=True)
            # IGDB provides a relative URL starting with //, we add https:
            cover_url = "https:" + game_info['cover']['url'].replace('t_thumb', 't_cover_big')
            
            # Strict cleanup for the filename on disk
            safe_filename = get_safe_filename(self.data.get('Folder_Name', ''))

            # Determine the extension
            try:
                path = urlparse(cover_url).path
                ext = os.path.splitext(path)[1]
                if not ext: ext = '.jpg' # IGDB is almost always .jpg
            except:
                ext = '.jpg'

            save_path = os.path.join("images", f"{safe_filename}{ext}")
            
            try:
                response = requests.get(cover_url, stream=True)
                if response.status_code == 200:
                    with open(save_path, 'wb') as f: shutil.copyfileobj(response.raw, f)
                    logging.info(f"    [IMAGE OK] Downloaded (forced={force_download}): {save_path}")
                    return save_path
            except Exception as e:
                logging.error(f"    [IMAGE ERROR] {e}")
        return ""

    def refetch_cover(self, token):
        """Fetches only the cover URL from IGDB and downloads the image if missing."""
        game_id = self.data.get('game_ID', '')
        if not game_id or not game_id.startswith('igdb_'):
            logging.warning(f"    [COVER FETCH] Cannot fetch image for '{self.data['Clean_Title']}', missing IGDB ID.")
            return False

        igdb_id = game_id.replace('igdb_', '')
        logging.info(f"    [COVER FETCH] Fetching image URL for '{self.data['Clean_Title']}' (ID: {igdb_id})")

        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        query = f'fields cover.url; where id = {igdb_id};'

        try:
            response = requests.post(api_url, headers=headers, data=query, timeout=10)
            if response.status_code == 200 and response.json():
                game_info = response.json()[0]
                # Forcing download because we are here due to a missing image
                new_path = self._ensure_cover(game_info, force_download=True)
                if new_path:
                    self.data['Image_Link'] = new_path
                    return True
            else:
                logging.error(f"    [COVER FETCH ERROR] Could not find info for ID {igdb_id}.")
                return False
        except Exception as e:
            logging.error(f"    [COVER FETCH CRITICAL] Network error: {e}")
            return False

    def fetch_metadata(self, token):
        # Prioritize Search_Title for the API request
        search_term = self.data.get('Search_Title') or self.data.get('Clean_Title') or self.data.get('Folder_Name')
        
        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        # Note: 'release_dates.date' is essential here to get the Unix timestamp
        query = (f'search "{search_term}"; fields id, name, summary, genres.name, '
                 'involved_companies.company.name, involved_companies.developer, '
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13); limit 1;')
        
        try:
            response = requests.post(api_url, headers=headers, data=query, timeout=10)
            if response.status_code == 200 and response.json():
                g = response.json()[0]
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = ", ".join([ge['name'] for ge in g.get('genres', [])])
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
                self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                # Updated Logic for Release Date
                dates = g.get('release_dates', [])
                if dates:
                    # Filter valid dates and extract the earliest timestamp
                    valid_dates = [d['date'] for d in dates if 'date' in d]
                    if valid_dates:
                        orig_ts = min(valid_dates)
                        # Explicitly use utcfromtimestamp to format as DD/MM/YYYY
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
                
                # If the game has no platform defined (it's a "Warez"), store its IGDB ID.
                if self.data.get('Platforms') == 'Warez':
                    if 'id' in g:
                        self.data['game_ID'] = f"igdb_{g.get('id')}"
                        logging.info(f"    [ID UPDATE] IGDB ID {g.get('id')} assigned to game.")

                self.data['Image_Link'] = self._ensure_cover(g)
                self.data['Status_Flag'] = 'OK'
                logging.info(f"    [API SUCCESS] found: {self.data['Clean_Title']}")
                return True
            else:
                logging.warning(f"    [API WARNING] No results for '{search_term}'")
                self.data['Status_Flag'] = 'NEEDS_ATTENTION'
                return False
        except Exception as e:
            logging.error(f"    [API CRITICAL] Network error: {e}")
            return False

    def fetch_smart_metadata(self, token, search_override=None):
        # 1. Define search term
        search_term = search_override or self.data.get('Search_Title') or self.data.get('Folder_Name')
        logging.info(f"    [SMART SCAN] searching for: {search_term}")
        
        local_dev = self.data.get('Developer', '').lower()
        local_year = self.data.get('Year_Folder', '')

        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        
        # 2. Request with a limit of 5 for scoring
        query = (f'search "{search_term}"; fields name, summary, genres.name, '
                 'involved_companies.company.name, involved_companies.developer, '
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13, 14, 3); limit 5;')
        
        try:
            response = requests.post(api_url, headers=headers, data=query, timeout=10)
            if response.status_code == 200 and response.json():
                results = response.json()
                best_match = None
                best_score = -1

                # 3. SCORING LOGIC (The "brain")
                for g in results:
                    score = 0
                    # Score on title
                    if search_term.lower() in g.get('name', '').lower(): score += 10
                    
                    # Score on developer
                    devs = [c['company']['name'].lower() for c in g.get('involved_companies', []) if c.get('developer')]
                    if local_dev and any(local_dev in d for d in devs): score += 5
                    
                    # Score on year
                    dates = g.get('release_dates', [])
                    if local_year and dates:
                        try:
                            api_year = datetime.utcfromtimestamp(min([d['date'] for d in dates if 'date' in d])).strftime('%Y')
                            if local_year == api_year: score += 5
                        except:
                            pass
                    
                    logging.info(f"    [CANDIDATE] '{g.get('name')}' - Score: {score}")
                    
                    # Keep the best result
                    if score > best_score:
                        best_score = score
                        best_match = g

                # 4. APPLYING THE BEST MATCH
                if best_match:
                    g = best_match
                    self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                    self.data['Summary'] = g.get('summary', '')
                    self.data['Genre'] = ", ".join([ge['name'] for ge in g.get('genres', [])])
                    
                    companies = g.get('involved_companies', [])
                    self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
                    self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
                    
                    videos = g.get('videos', [])
                    self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                    
                    dates = g.get('release_dates', [])
                    if dates:
                        orig_ts = min([d['date'] for d in dates if 'date' in d])
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
                    
                    self.data['Image_Link'] = self._ensure_cover(g)
                    self.data['Status_Flag'] = 'OK'
                    logging.info(f"    [SMART SCAN] Match found: {self.data['Clean_Title']} (Score: {best_score})")
                    return True
            return False
        except Exception as e:
            logging.error(f"    [SMART SCAN CRITICAL] {e}")
            return False

    def apply_candidate_data(self, g):
        logging.info(f"    [MANUAL APPLY] Application des données pour '{self.data.get('Clean_Title')}' -> '{g.get('name')}'")
        self.data['Clean_Title'] = g.get('name', self.data.get('Clean_Title'))
        self.data['Summary'] = g.get('summary', '')
        self.data['Genre'] = ", ".join([ge['name'] for ge in g.get('genres', [])])
        
        companies = g.get('involved_companies', [])
        self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
        self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
        
        videos = g.get('videos', [])
        self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
        
        dates = g.get('release_dates', [])
        if dates:
            orig_ts = min([d['date'] for d in dates if 'date' in d])
            self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
        
        # If the game has no platform defined (it's a "Warez"), store its IGDB ID.
        # This will make future updates much more reliable.
        if self.data.get('Platforms') == 'Warez':
            if 'id' in g:
                self.data['game_ID'] = f"igdb_{g.get('id')}"
                logging.info(f"    [ID UPDATE] IGDB ID {g.get('id')} assigned to game.")

        # Forced image download
        self.data['Image_Link'] = self._ensure_cover(g, force_download=True)
        self.data['Status_Flag'] = 'OK'
        return True

    def to_dict(self):
        return self.data

class LibraryManager:
    def __init__(self, root_path, db_file):
        self.root_path = root_path
        self.db_file = db_file
        self.games = {} 

    def sync_gog(self, worker_thread=None):
        logging.info("--- START OF GOG SYNC ---")
        token = self.get_access_token()
        gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')

        if not os.path.exists(gog_db_path):
            logging.error(f"GOG Galaxy database not found at: {gog_db_path}")
            return

        try:
            con = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
            query = """
                SELECT DISTINCT
                    urp.releaseKey,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'meta' LIMIT 1) as meta_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'title' LIMIT 1) as title_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'originalTitle' LIMIT 1) as orig_title_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'summary' LIMIT 1) as summary_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'developers' LIMIT 1) as developers_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'publishers' LIMIT 1) as publishers_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'originalImages' LIMIT 1) as original_images_json,
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
                    (rp.isDlc IS NULL OR rp.isDlc = 0)
            """
            gog_games = con.execute(query).fetchall()
            con.close()
            logging.info(f"{len(gog_games)} games found in your GOG library.")
        except Exception as e:
            logging.error(f"Error reading GOG database: {e}")
            return

        os.makedirs("images", exist_ok=True)
        os.makedirs("videos", exist_ok=True)
        
        # Stats for the report
        stats = {
            'total_found': len(gog_games),
            'processed': 0,
            'new': 0,
            'matched_key': 0,
            'matched_smart': 0,
            'errors': 0,
            'fetched_success': 0,
            'fetched_fail': 0
        }

        # Create a map for ultra-fast search by releaseKey
        key_to_game_map = {game.data.get('game_ID'): game for game in self.games.values() if game.data.get('game_ID')}

        for releaseKey, meta_json, title_json, orig_title_json, summary_json, developers_json, publishers_json, original_images_json, product_name, ld_title, ld_summary, ld_release_date, ld_images in gog_games:
            # Check for interruption request from the UI thread
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("GOG Sync interrupted by user.")
                break

            title = "Unknown"
            metadata = {}
            
            # Helper to safely extract from JSON
            def safe_json_load(json_str):
                if not json_str: return None
                try: return json.loads(json_str)
                except: return None

            meta_data = safe_json_load(meta_json) or {}

            # 1. Try via full metadata (meta)
            title = meta_data.get('title')
            
            # 2. Try via GamePieces 'title' or 'originalTitle'
            if not title:
                def extract_title_from_json(json_str):
                    if not json_str: return None
                    try:
                        data = json.loads(json_str)
                        if isinstance(data, dict):
                            return data.get('title') or data.get('value') or data.get('originalTitle')
                        return str(data)
                    except:
                        return json_str # If it's not JSON, it might be the raw title
                
                title = extract_title_from_json(title_json)
                if not title: title = extract_title_from_json(orig_title_json)
            
            # 3. Try via Products table (ultimate fallback)
            if not title: title = product_name
            if not title: title = ld_title

            try:
                if not title:
                    logging.warning(f"    [GOG WARNING] Game with releaseKey {releaseKey} ignored (no title).")
                    stats['errors'] += 1
                    continue

                # Clean Amazon suffixes (Prime/Luna) to avoid duplicates
                # Ex: "A Plague Tale - Amazon Prime" -> "A Plague Tale"
                title = re.sub(r'\s*-\s*Amazon.*$', '', title, flags=re.IGNORECASE)

                # Clean special characters (anything not a letter, number, or basic punctuation)
                title = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title)

                platform = 'Unknown'
                if releaseKey.startswith('gog_'): platform = 'GOG'
                elif releaseKey.startswith('steam_'): platform = 'Steam'
                elif releaseKey.startswith('epic_'): platform = 'Epic Games Store'
                elif releaseKey.startswith('xboxone_') or releaseKey.startswith('xbox_'): platform = 'Xbox'
                elif releaseKey.startswith('ps_') or releaseKey.startswith('ps4_') or releaseKey.startswith('ps5_'): platform = 'PlayStation'
                elif releaseKey.startswith('amazon_'): platform = 'Amazon'
                elif releaseKey.startswith('uplay_'): platform = 'Uplay'
                elif releaseKey.startswith('origin_'): platform = 'Origin'
                elif releaseKey.startswith('battle.net_'): platform = 'Battle.net'
                elif releaseKey.startswith('humble_'): platform = 'Humble Bundle'

                # --- METADATA EXTRACTION FOR COMPARISON ---
                gog_dev = meta_data.get('developer')
                if not gog_dev:
                    d_data = safe_json_load(developers_json)
                    if isinstance(d_data, list): gog_dev = ", ".join(d_data)
                
                gog_pub = meta_data.get('publisher')
                if not gog_pub:
                    p_data = safe_json_load(publishers_json)
                    if isinstance(p_data, list): gog_pub = ", ".join(p_data)

                gog_year = None
                if release_ts := meta_data.get('releaseTimestamp'):
                    gog_year = datetime.utcfromtimestamp(release_ts).strftime('%Y')
                elif ld_release_date:
                    try: gog_year = ld_release_date[:4]
                    except: pass

                game_obj = None
                # 1. Match by unique identifier (most reliable)
                if releaseKey in key_to_game_map:
                    game_obj = key_to_game_map[releaseKey]
                    stats['matched_key'] += 1
                # 2. Smart match (Score based)
                else:
                    best_score = 0
                    best_game = None
                    
                    # Normalization for comparison (lowercase, no special characters)
                    norm_title = re.sub(r'[^a-z0-9]', '', title.lower())
                    
                    for game in self.games.values():
                        # Ignore games that already have a GOG ID (but allow those with an IGDB ID)
                        gid = game.data.get('game_ID', '')
                        if gid and not gid.startswith('igdb_'):
                            continue

                        local_title = game.data.get('Clean_Title', '')
                        local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
                        
                        score = 0
                        
                        # 1. Title (0-60 points)
                        if local_norm_title == norm_title:
                            score += 60
                        else:
                            ratio = difflib.SequenceMatcher(None, title.lower(), local_title.lower()).ratio()
                            if ratio > 0.6:
                                score += int(ratio * 60)
                            else:
                                continue # Title too different, skipping

                        # 2. Platform (20 points)
                        local_platforms = game.data.get('Platforms', '').lower()
                        if platform.lower() in local_platforms:
                            score += 20

                        # 3. Developer / Publisher (10 points)
                        local_dev = game.data.get('Developer', '').lower()
                        local_pub = game.data.get('Publisher', '').lower()
                        if gog_dev and gog_dev.lower() in local_dev: score += 10
                        elif gog_pub and gog_pub.lower() in local_pub: score += 10
                        
                        # 4. Year (10 points)
                        local_year = game.data.get('Year_Folder', '')
                        if not local_year and game.data.get('Original_Release_Date'):
                             try: local_year = game.data.get('Original_Release_Date')[-4:]
                             except: pass
                        
                        if gog_year and local_year and gog_year == local_year:
                            score += 10

                        if score > best_score:
                            best_score = score
                            best_game = game
                    
                    # Acceptance threshold: 70 points
                    if best_game and best_score >= 70:
                        game_obj = best_game
                        logging.info(f"    [GOG MATCH SMART] Game recognized by title (Score: {best_score}): '{title}' -> '{best_game.data.get('Clean_Title')}'")
                        stats['matched_smart'] += 1
                
                # 3. If no match, it's a new game
                if not game_obj:
                    logging.info(f"    [GOG NEW] Adding game: '{title}' ({platform})")
                    folder_name = title
                    # Replace colons with a space
                    folder_name = folder_name.replace(':', ' ')
                    # Clean forbidden characters and multiple spaces
                    folder_name = re.sub(r'[<>"/\\|?*]', '', folder_name)
                    folder_name = re.sub(r'\s{2,}', ' ', folder_name).strip()
                    # Windows doesn't like folders ending with a dot or space
                    folder_name = folder_name.rstrip('. ')
                    
                    if not folder_name: folder_name = f"Unknown Game [{releaseKey}]"

                    if folder_name in self.games:
                        folder_name = f"{title} [{releaseKey}]" # Avoids name duplicates
                    game_obj = Game(Folder_Name=folder_name, Status_Flag='OK', Path_Root='')
                    stats['new'] += 1

                # --- UPDATING DATA ---
                game_obj.data['game_ID'] = releaseKey
                game_obj.data['Clean_Title'] = title
                
                # Only update the platform if it's not already defined locally (or if it's Warez/Unknown)
                # This prevents an "Amazon" version from overwriting a local version identified as "Epic" or "Steam"
                current_platforms = game_obj.data.get('Platforms', '')
                if platform != 'Amazon' or current_platforms in ['', 'Unknown', 'Warez']:
                     game_obj.data['Platforms'] = platform

                # Summary
                summary = meta_data.get('summary')
                if not summary:
                    s_data = safe_json_load(summary_json)
                    if isinstance(s_data, dict): summary = s_data.get('summary') or s_data.get('value')
                if not summary: summary = ld_summary
                if summary: game_obj.data['Summary'] = summary

                # Developer
                gog_dev = meta_data.get('developer')
                if not gog_dev:
                    # Sometimes 'developers' (plural) in meta
                    devs_list = meta_data.get('developers')
                    if isinstance(devs_list, list):
                        gog_dev = ", ".join([d.get('name', '') if isinstance(d, dict) else str(d) for d in devs_list])
                if not gog_dev:
                    d_data = safe_json_load(developers_json)
                    if isinstance(d_data, list):
                        gog_dev = ", ".join([d.get('name', '') if isinstance(d, dict) else str(d) for d in d_data])
                if gog_dev: game_obj.data['Developer'] = gog_dev

                # Publisher
                gog_pub = meta_data.get('publisher')
                if not gog_pub:
                    pubs_list = meta_data.get('publishers')
                    if isinstance(pubs_list, list):
                        gog_pub = ", ".join([p.get('name', '') if isinstance(p, dict) else str(p) for p in pubs_list])
                if not gog_pub:
                    p_data = safe_json_load(publishers_json)
                    if isinstance(p_data, list):
                        gog_pub = ", ".join([p.get('name', '') if isinstance(p, dict) else str(p) for p in p_data])
                if gog_pub: game_obj.data['Publisher'] = gog_pub

                # Genre
                genres = meta_data.get('genres')
                if genres:
                    if isinstance(genres, list):
                        if len(genres) > 0 and isinstance(genres[0], dict):
                             game_obj.data['Genre'] = ", ".join([g.get('name', '') for g in genres if g.get('name')])
                        else:
                             game_obj.data['Genre'] = ", ".join([str(g) for g in genres])

                # Release Date
                release_date = None
                # GOG uses 'releaseDate' (seen in CSV) or 'releaseTimestamp'
                release_ts = meta_data.get('releaseDate') or meta_data.get('releaseTimestamp')
                if release_ts:
                    try: release_date = datetime.utcfromtimestamp(release_ts).strftime('%d/%m/%Y')
                    except: pass
                elif ld_release_date:
                    # Clean up the date (sometimes "2020-10-05T00:00:00+00:00" or "2020-10-05")
                    clean_date_str = ld_release_date.split('T')[0] # Keep YYYY-MM-DD
                    try:
                        dt = datetime.strptime(clean_date_str, '%Y-%m-%d')
                        release_date = dt.strftime('%d/%m/%Y')
                    except ValueError:
                        release_date = ld_release_date # Keep as is on failure (e.g., just the year)
                if release_date: game_obj.data['Original_Release_Date'] = release_date

                folder_name_for_files = game_obj.data['Folder_Name']
                
                # Strict cleanup for filename on disk (Images/Videos)
                safe_filename = get_safe_filename(folder_name_for_files)

                # --- VIDEO MANAGEMENT (Trailer & Download) ---
                # No longer searching for videos in GOG DB (useless files)
                # Just keep the Trailer Link if present in the base metadata
                if not game_obj.data.get('Trailer_Link'):
                    # Simple search in meta_data (native GOG) for YouTube only
                    videos = meta_data.get('videos', [])
                    yt_video = next((v for v in videos if isinstance(v, dict) and v.get('provider') == 'youtube' and v.get('video_id')), None)
                    
                    if yt_video:
                        game_obj.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={yt_video.get('video_id')}"

                # --- B. Video Preparation (.mp4) ---
                video_url = None
                
                # 1. (Removed) Search in local sources (GOG DB) - Useless files
                
                # 2. Web Search (Steam API) if it's a Steam game and we found nothing
                # We also check for our special flags to avoid re-scanning.
                existing_trailer = game_obj.data.get('Trailer_Link', '')
                if not existing_trailer and platform == 'Steam':
                    try:
                        app_id = releaseKey.replace('steam_', '')
                        if app_id.isdigit():
                            steam_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
                            # Add a User-Agent header to avoid being blocked as a generic script.
                            headers = {'User-Agent': 'ViGaVault/1.0'}
                            resp = requests.get(steam_url, timeout=5, headers=headers)
                            if resp.status_code == 200:
                                data = resp.json()
                                if data and data.get(app_id, {}).get('success'):
                                    movies = data[app_id]['data'].get('movies', [])
                                    if movies:
                                        # Prioritize direct MP4 link at max resolution
                                        video_url = movies[0].get('mp4', {}).get('max')
                                        # If no direct MP4, fall back to a streaming manifest URL (HLS)
                                        if not video_url:
                                            video_url = movies[0].get('hls_h264')

                                        if video_url:
                                            logging.info(f"    [STEAM API] Video URL found for '{title}': {video_url}")
                                        else:
                                            logging.info(f"    [STEAM API] No usable video link found for '{title}' (AppID: {app_id}).")
                                            video_url = 'no_mp4'
                                    else:
                                        logging.info(f"    [STEAM API] No 'movies' section in API response for '{title}' (AppID: {app_id}).")
                                        video_url = 'no_section'
                                else:
                                    logging.warning(f"    [STEAM API] API returned success=false for '{title}' (AppID: {app_id}).")
                            else:
                                logging.warning(f"    [STEAM API] Request for '{title}' (AppID: {app_id}) failed with status code {resp.status_code}.")
                    except requests.exceptions.Timeout:
                        logging.warning(f"    [STEAM API] Request timed out for '{title}'.")
                    except Exception as e:
                        logging.warning(f"    [STEAM API] An unexpected error occurred for '{title}': {e}")

                # If we found a video URL (or a flag), save it.
                # This overwrites a previous flag if a real URL is found, which is correct.
                if video_url:
                    game_obj.data['Trailer_Link'] = video_url

                # Cover download (always)
                cover_url = meta_data.get('image')
                
                # Fallback to originalImages (often present for Steam/Epic according to CSV)
                if not cover_url:
                    orig_imgs = safe_json_load(original_images_json)
                    if orig_imgs:
                        cover_url = orig_imgs.get('verticalCover') or orig_imgs.get('boxart') or orig_imgs.get('poster') or orig_imgs.get('squareIcon') or orig_imgs.get('background')

                if not cover_url and ld_images:
                    imgs = safe_json_load(ld_images)
                    if isinstance(imgs, list) and len(imgs) > 0:
                        # Search for an image of type "boxart", "vertical_cover", "packshot", or "poster"
                        preferred_types = ['boxart', 'vertical_cover', 'packshot', 'poster']
                        cover_url = next((img.get('url') for img in imgs if img.get('type') in preferred_types), None)
                        # If no preferred type, search for anything that is NOT a screenshot
                        if not cover_url:
                            cover_url = next((img.get('url') for img in imgs if img.get('type') != 'screenshot'), None)
                
                if cover_url:
                    if cover_url.startswith('//'): cover_url = "https:" + cover_url
                    
                    # Check if a valid image already exists for this game
                    existing_image_path = game_obj.data.get('Image_Link')
                    image_exists_on_disk = existing_image_path and os.path.exists(existing_image_path)

                    if not image_exists_on_disk:
                        # Determine the image extension from the URL
                        try:
                            path = urlparse(cover_url).path
                            ext = os.path.splitext(path)[1]
                            # If the extension is empty (e.g., URL without .jpg) but it's a GOG image, it's probably webp
                            if not ext and 'gog.com' in cover_url:
                                ext = '.webp'
                            elif not ext:
                                ext = '.jpg' # Fallback for other cases
                        except:
                            ext = '.jpg' # Ultimate fallback in case of parsing error
                        save_path = os.path.join("images", f"{safe_filename}{ext}")
                        try:
                            response = requests.get(cover_url, timeout=5)
                            if response.status_code == 200:
                                with open(save_path, 'wb') as f: f.write(response.content)
                                game_obj.data['Image_Link'] = save_path
                                logging.info(f"    [IMAGE] Downloaded missing image: {safe_filename}{ext}")
                        except Exception as e: logging.error(f"    [IMAGE ERROR] {e}")

                self.games[game_obj.data['Folder_Name']] = game_obj
                stats['processed'] += 1
            except Exception as e:
                logging.error(f"    [GOG ERROR] Error processing game '{title}' (releaseKey: {releaseKey}): {e}")
                stats['errors'] += 1

        # Final report
        report = (
            "\n=== GOG SYNC REPORT ===\n"
            f"Games found in GOG: {stats['total_found']}\n"
            f"Games processed successfully: {stats['processed']}\n"
            f"-----------------------------------\n"
            f"New games added: {stats['new']}\n"
            f"Updates (Unique Key): {stats['matched_key']}\n"
            f"Updates (Smart): {stats['matched_smart']}\n"
            f"Errors / Ignored: {stats['errors']}\n"
            "==================================="
        )
        logging.info(report)
        self.save_db()

    def get_access_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": IGDB_CLIENT_ID, "client_secret": IGDB_CLIENT_SECRET, "grant_type": "client_credentials"}
        response = requests.post(url, params=params)
        if response.status_code == 200:
            logging.info("    [API AUTH] IGDB token successfully generated.")
            return response.json().get("access_token")
        else:
            logging.error(f"    [API AUTH ERROR] Token failure: {response.text}")
            return None

    def load_db(self):
        if os.path.exists(self.db_file):
            df = pd.read_csv(self.db_file, sep=';', encoding='utf-8').fillna('')
            for _, row in df.iterrows():
                game_data = {k: str(v) for k, v in row.to_dict().items()}
                self.games[game_data['Folder_Name']] = Game(**game_data)
            logging.info(f"{len(self.games)} games loaded.")

    def fetch_candidates(self, token, search_term, limit=10):
        search_term = str(search_term).strip()
        # Log start of search
        logging.info(f"    [MANUAL SCAN] API search for: {search_term}")
        
        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}

        # If the term is a numeric ID, search by ID
        if search_term.isdigit():
            query = (f'fields id, name, summary, genres.name, '
                     'involved_companies.company.name, involved_companies.developer, '
                     f'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where id = {search_term};')
        else:
            query = (f'search "{search_term}"; fields id, name, summary, genres.name, '
                     'involved_companies.company.name, involved_companies.developer, '
                     f'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13, 14, 3); limit {limit};')
        
        response = requests.post(api_url, headers=headers, data=query, timeout=10)
        
        if response.status_code == 200:
            results = response.json()
            if results:
                logging.info(f"    [MANUAL SCAN] {len(results)} candidates found:")
                for g in results:
                    # Extract year for logging
                    year = ''
                    if 'release_dates' in g and g['release_dates']:
                        dates = [d['date'] for d in g.get('release_dates', []) if 'date' in d]
                        if dates:
                            try:
                                year = datetime.utcfromtimestamp(min(dates)).strftime('%Y')
                            except Exception:
                                pass # Ignore date conversion errors

                    display_text = g.get('name', 'Unknown')
                    if year:
                        display_text = f"{year} - {display_text}"
                    logging.info(f"        -> {display_text}")
            else:
                logging.warning(f"    [MANUAL SCAN] No results for: {search_term}")
            return results
        else:
            logging.error(f"    [MANUAL SCAN CRITICAL] Erreur API : {response.status_code}")
            return []

    def scan(self, retry_failures=False, worker_thread=None):
        token = self.get_access_token()
        logging.info("--- START OF SCAN ---")
        if retry_failures:
            logging.info("'Retry failures' mode enabled.")
        
        stats = {
            'scanned': 0,
            'new': 0,
            'updated': 0,
            'deleted': 0,
            'fetched_success': 0,
            'fetched_fail': 0
        }
        
        found_folders = set() # To track games actually present on disk

        for root, dirs, files in os.walk(self.root_path):
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("Scan interrupted during folder analysis.")
                break # Exit the os.walk loop

            dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
            rel_path = os.path.relpath(root, self.root_path)
            if rel_path == ".": continue
            
            # Here, we restore the depth check
            depth = rel_path.count(os.sep) + 1
            
            if depth == 1:
                logging.info(f"Analyzing category: {os.path.basename(root)}")
            elif depth == 2:
                for folder in dirs:
                    stats['scanned'] += 1 # Fix: Count each game folder individually
                    found_folders.add(folder)
                    full_path = os.path.join(root, folder)
                    if folder not in self.games:
                        logging.info(f"    [NEW] Discovered: {folder}")
                        self.games[folder] = Game(Folder_Name=folder, Path_Root=full_path)
                        stats['new'] += 1
                    else:
                        logging.info(f"    [CHECK] Checking existing game: {folder}")
                        # For existing games, update the path and re-check the video
                        game = self.games[folder]
                        if game.data.get('Path_Root') != full_path:
                            game.data['Path_Root'] = full_path
                        game._parse_folder_name()
                        game._find_video()
                        game._find_image()
                        stats['updated'] += 1
        
        # Cleanup: Deleting games no longer on disk
        existing_folders = list(self.games.keys())
        for folder in existing_folders:
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("Scan interrupted during orphan file cleanup.")
                break # Exit the deletion loop

            if folder not in found_folders:
                game_to_delete = self.games.get(folder)
                
                # Delete associated media files before deleting the entry
                if game_to_delete:
                    # Deleting image
                    image_path = game_to_delete.data.get('Image_Link')
                    if image_path and os.path.exists(image_path):
                        try:
                            os.remove(image_path)
                            logging.info(f"    [DELETE] Orphan image file deleted: {image_path}")
                        except Exception as e:
                            logging.error(f"    [DELETE ERROR] Could not delete image {image_path}: {e}")
                    
                    # Deleting video
                    video_path = game_to_delete.data.get('Path_Video')
                    if video_path and os.path.exists(video_path):
                        try:
                            os.remove(video_path)
                            logging.info(f"    [DELETE] Orphan video file deleted: {video_path}")
                        except Exception as e:
                            logging.error(f"    [DELETE ERROR] Could not delete video {video_path}: {e}")

                logging.info(f"    [DELETE] Game entry not found on disk, deleting: {folder}")
                del self.games[folder]
                stats['deleted'] += 1
        
        logging.info("--- METADATA VERIFICATION ---")
        for name, game in self.games.items():
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("Scan interrupted during metadata fetching.")
                break # Exit metadata loop

            # SECURITY: Final physical check before request
            if not os.path.exists(game.data.get('Path_Root', '')):
                logging.warning(f"    [GHOST] Folder '{name}' no longer exists physically. Ignored.")
                continue
            
            image_is_missing = not game.data.get('Image_Link') or not os.path.exists(game.data.get('Image_Link'))
            status = game.data.get('Status_Flag')

            # Case 1: The game is NEW. Always fetch full metadata.
            if status == 'NEW':
                logging.info(f"    [FETCHING] Attempting for: {name} (Reason: New game)")
                if token and game.fetch_metadata(token):
                    stats['fetched_success'] += 1
                else:
                    logging.warning(f"    [FAILURE] Failure for: {name}")
                    stats['fetched_fail'] += 1
            
            # Case 2: Game has failed (NEEDS_ATTENTION) and retry option is enabled.
            elif status == 'NEEDS_ATTENTION' and retry_failures:
                logging.info(f"    [FETCHING] Attempting for: {name} (Reason: Retrying a previous failure)")
                if token and game.fetch_metadata(token):
                    stats['fetched_success'] += 1
                else:
                    logging.warning(f"    [FAILURE] Failure for: {name}")
                    stats['fetched_fail'] += 1

            # Case 3: Game is "OK", but the image is missing. Only fetch the image.
            elif status == 'OK' and image_is_missing:
                logging.info(f"    [COVER FETCH] Attempting for: {name} (Reason: Missing image for OK game)")
                if token and game.refetch_cover(token):
                    stats['fetched_success'] += 1
                else:
                    logging.warning(f"    [FAILURE] Failure for: {name}")
                    stats['fetched_fail'] += 1

        
        # Final report
        if worker_thread and worker_thread.isInterruptionRequested():
            report = "\n=== SCAN INTERRUPTED BY USER ===\n"
        else:
            report = (
                "\n=== LOCAL SCAN REPORT ===\n"
                f"Folders scanned: {stats['scanned']}\n"
                f"-----------------------------------\n"
                f"New games detected: {stats['new']}\n"
                f"Existing games checked: {stats['updated']}\n"
                f"Deleted games (not found): {stats['deleted']}\n"
                f"-----------------------------------\n"
                f"Metadata fetched (IGDB): {stats['fetched_success']}\n"
                f"IGDB fetch failures: {stats['fetched_fail']}\n"
                "==================================="
            )
        logging.info(report)
        self.save_db()

    def scan_single_game(self, game_name, manual_search_term=None):
        logging.info(f"--- SCAN UNITAIRE : {game_name} (Terme: {manual_search_term}) ---")
        token = self.get_access_token()
        if not token: return False
        
        game = self.games.get(game_name)
        if game:
            # Pass manual_search_term to fetch_smart_metadata
            success = game.fetch_smart_metadata(token, search_override=manual_search_term)
            self.save_db()
            return success
        return False

    def save_db(self):
        # --- BACKUP LOGIC ---
        if os.path.exists(self.db_file):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(BACKUP_DIR, f"VGVDB_{timestamp}.csv.bak")
            try:
                shutil.copy2(self.db_file, backup_file)
                logging.info(f"    [DB BACKUP] Backup created at {backup_file}")
            except Exception as e:
                logging.error(f"    [DB BACKUP ERROR] Failed to create backup: {e}")
        # --- END BACKUP LOGIC ---

        # 1. Create DataFrame
        df = pd.DataFrame([g.to_dict() for g in self.games.values()])
        
        # 2. List of all expected columns (to guarantee structure)
        expected_columns = [
            'Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 
            'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 
            'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Trailer_Link',
            'game_ID'
        ]
        
        # 3. Force columns: add missing ones (filled with empty strings)
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ''
        
        # 4. Cleanup and save
        df = df[expected_columns] # Reorder cleanly
        for col in ['Year_Folder', 'Original_Release_Date']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')
        
        df.fillna('').to_csv(self.db_file, sep=';', index=False, encoding='utf-8')
        logging.info(f"    [DB SAVE] Database saved to {self.db_file} ({len(df)} games).")

if __name__ == "__main__":
    manager = LibraryManager(ROOT_PATH, DB_FILE)
    manager.load_db()
    
    parser = argparse.ArgumentParser(description="ViGaVault Library Manager.")
    parser.add_argument('--sync-gog', action='store_true', help='Sync games from the GOG Galaxy database.')
    parser.add_argument('--retry', action='store_true', help="Retry fetching metadata for failed games (NEEDS_ATTENTION).")
    args = parser.parse_args()

    if args.sync_gog:
        manager.sync_gog()
    else:
        manager.scan(retry_failures=args.retry)