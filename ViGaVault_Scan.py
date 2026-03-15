import os
import re
import pandas as pd
import logging
import shutil
import ctypes
import requests
import sqlite3
from datetime import datetime
from urllib.parse import urlparse
import difflib
import json

# --- Optional Dependency Import ---
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


# --- CONFIGURATION ---
# WHY: We define BASE_DIR relative to this script file location.
# This ensures that whether the script is run from CMD, an IDE, or a shortcut,
# Python always knows where to look for relative files (DB, settings, logs)
# instead of relying on the unpredictable 'current working directory' (os.getcwd).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BACKUP_DIR = os.path.join(BASE_DIR, "backups")
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.webm')
MAX_FILES = 10 

# --- API CONFIGURATION ---
IGDB_CLIENT_ID = "a6q5htw1uxkye5kta223vwjs2qlace"
IGDB_CLIENT_SECRET = "psmi013osf0leudnb0jlyzpr8xz9fq"

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

def normalize_genre(text):
    """Normalizes a comma-separated genre string to Title Case."""
    if not text: return ""
    parts = str(text).split(',')
    clean_parts = []
    seen = set()
    for p in parts:
        p = p.strip()
        if not p: continue
        # Force title case to fix PLATFORM -> Platform
        p_norm = p.title()
        if p_norm.lower() not in seen:
            clean_parts.append(p_norm)
            seen.add(p_norm.lower())
    return ", ".join(clean_parts)

def _query_igdb_api(token, search_term=None, limit=5, by_id=False, custom_query=None):
    """
    WHY: Centralized helper to avoid duplicating the IGDB API network logic across multiple methods.
    """
    api_url = "https://api.igdb.com/v4/games"
    headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
    
    if custom_query:
        query = custom_query
    else:
        fields = ('id, name, summary, genres.name, involved_companies.company.name, '
                  'involved_companies.developer, involved_companies.publisher, '
                  'videos.video_id, release_dates.date, cover.url')
        if by_id:
            query = f'fields {fields}; where id = {search_term};'
        else:
            # Platforms filter (includes VR: 161=WinMR, 162=Oculus, 163=SteamVR)
            # WHY: Add VR platforms as discussed and centralize the filter.
            query = f'search "{search_term}"; fields {fields}; where platforms = (3, 6, 13, 14, 161, 162, 163); limit {limit};'
            
    try:
        response = requests.post(api_url, headers=headers, data=query, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"    [IGDB API ERROR] {response.status_code} for query: {query}")
            return None
    except Exception as e:
        logging.error(f"    [IGDB NETWORK ERROR] {e}")
        return None

class Game:
    def __init__(self, config=None, **kwargs):
        self.config = config or {}
        self.data = kwargs
        self.data.setdefault('Folder_Name', 'Unknown')
        self.data.setdefault('Path_Root', '')
        self.data.setdefault('Status_Flag', 'NEW')
        self.data.setdefault('Platforms', '')
        self.data.setdefault('Collection', '')
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
            platform_map = self.config.get('platform_map', {})
            if platform_map:
                platform_pattern = r'|'.join(re.escape(k) for k in platform_map.keys())
                found_platforms_raw = re.findall(platform_pattern, tag_content, re.IGNORECASE)
                
                if found_platforms_raw:
                    canonical_platforms = {platform_map[p.lower()] for p in found_platforms_raw}
                    self.data['Platforms'] = ", ".join(sorted(list(canonical_platforms)))

        if not self.data.get('Platforms'):
            if self.data.get('Path_Root'):
                self.data['Platforms'] = 'Local Files'

        # Clean up the name for the title
        clean_name = re.sub(r'\s*\([^)]*\)$', '', name).strip() # Remove the last parenthesis
        year_match = re.match(r'^(\d{4})\s*-\s*', clean_name)
        if year_match:
            self.data['Year_Folder'] = year_match.group(1)
            clean_name = clean_name[len(year_match.group(0)):]
            
        self.data['Clean_Title'] = clean_name
        self.data['Search_Title'] = clean_name

    def update_media_filenames(self, old_title, old_date):
        """
        WHY: Centralized media renaming (DRY) so both the Edit Window and the Merge Tool 
        can dynamically rename physical files without duplicating code.
        """
        new_title = self.data.get('Clean_Title', '')
        new_date = self.data.get('Original_Release_Date', '')

        if new_title != old_title or new_date != old_date:
            base_filename = new_title
            if new_date and len(new_date) >= 4:
                base_filename += f" ({new_date[-4:]})"
            
            new_safe_name = get_safe_filename(base_filename)
            
            # Rename Image
            old_img_path = self.data.get('Image_Link', '')
            if old_img_path and os.path.exists(old_img_path):
                dir_name = os.path.dirname(old_img_path)
                ext = os.path.splitext(old_img_path)[1]
                new_img_path = os.path.join(dir_name, f"{new_safe_name}{ext}")
                if new_img_path != old_img_path:
                    try:
                        os.rename(old_img_path, new_img_path)
                        self.data['Image_Link'] = new_img_path
                    except Exception as e:
                        logging.error(f"Failed to rename image: {e}")

            # Rename Video
            old_vid_path = self.data.get('Path_Video', '')
            if old_vid_path and os.path.exists(old_vid_path):
                dir_name = os.path.dirname(old_vid_path)
                ext = os.path.splitext(old_vid_path)[1]
                new_vid_path = os.path.join(dir_name, f"{new_safe_name}{ext}")
                if new_vid_path != old_vid_path:
                    try:
                        os.rename(old_vid_path, new_vid_path)
                        self.data['Path_Video'] = new_vid_path
                    except Exception as e:
                        logging.error(f"Failed to rename video: {e}")

    def merge_with(self, other):
        """
        WHY: Handles the pure data logic of merging another game into this one. 
        Automatically combines non-conflicting lists (IDs, Platforms) and returns a package 
        of differing single-value fields for the user to resolve via the UI.
        """
        # 1. Combine IDs
        ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
        ids.update(x.strip() for x in other.data.get('game_ID', '').split(',') if x.strip())
        self.data['game_ID'] = ", ".join(sorted(ids))

        # 2. Combine Platforms
        plats = set(x.strip() for x in self.data.get('Platforms', '').split(',') if x.strip())
        plats.update(x.strip() for x in other.data.get('Platforms', '').split(',') if x.strip())
        # Rule: If any real platform exists (including 'Unknown'), 'Local Files' is removed
        real_plats = [p for p in plats if p.lower() != 'local files']
        if real_plats:
            if 'Local Files' in plats: plats.remove('Local Files')
            if 'local files' in plats: plats.remove('local files')
        self.data['Platforms'] = ", ".join(sorted(plats))

        # 3. Handle Reserved platform_ID_xx fields
        for i in range(1, 51):
            col = f"platform_ID_{i:02d}"
            if not self.data.get(col) and other.data.get(col):
                self.data[col] = other.data.get(col)

        # 4. Detect Conflicts in descriptive fields
        conflicts = {}
        fields_to_check = ['Clean_Title', 'Summary', 'Original_Release_Date', 'Developer', 'Publisher', 'Genre', 'Collection', 'Path_Root', 'Path_Video', 'Image_Link', 'Trailer_Link', 'Year_Folder']
        
        for field in fields_to_check:
            val_a = str(self.data.get(field, '')).strip()
            val_b = str(other.data.get(field, '')).strip()
            
            # Empty vs Filled -> Auto-accept filled
            if not val_a and val_b:
                self.data[field] = val_b
            # Both filled but differ (case-insensitive to prevent fake conflicts)
            elif val_a and val_b and val_a.casefold() != val_b.casefold():
                conflicts[field] = {'A': val_a, 'B': val_b}
                
        return conflicts

    def _find_video(self):
        # If a valid video path already exists, do nothing.
        current_path = self.data.get('Path_Video', '')
        if current_path and os.path.exists(current_path):
            return

        # Only look for videos in the centralized 'videos' folder
        # We ignore any video files that might exist in the game's own folder
        video_dir = self.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
        safe_name = get_safe_filename(self.data.get('Clean_Title') or self.data.get('Folder_Name', ''))
        
        for ext in VIDEO_EXTS:
            potential_path = os.path.join(video_dir, f"{safe_name}{ext}")
            if os.path.exists(potential_path):
                self.data['Path_Video'] = potential_path
                logging.info(f"    [VIDEO] Found locally in videos folder: {safe_name}{ext}")
                return

    def _find_image(self):
        # If the link already exists and is valid, do nothing
        current_path = self.data.get('Image_Link', '')
        if current_path and os.path.exists(current_path):
            return

        # Otherwise, check if an image already exists in the images folder
        safe_name = get_safe_filename(self.data.get('Folder_Name', ''))
        for ext in ['.jpg', '.png', '.jpeg', '.webp']:
            potential_path = os.path.join(BASE_DIR, "images", f"{safe_name}{ext}")
            if os.path.exists(potential_path):
                self.data['Image_Link'] = potential_path
                logging.info(f"    [IMAGE] Found locally: {safe_name}{ext}")
                return

    def _ensure_cover(self, game_info, force_download=False, silent=False):
        existing_path = self.data.get('Image_Link', '')
        
        # If not forcing, check for existence as before
        if not force_download and existing_path and os.path.exists(existing_path):
            return existing_path

        # If we get here, it means we must (re)download
        if 'cover' in game_info:
            images_dir = os.path.join(BASE_DIR, "images")
            os.makedirs(images_dir, exist_ok=True)
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

            save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
            
            try:
                response = requests.get(cover_url, stream=True)
                if response.status_code == 200:
                    with open(save_path, 'wb') as f: shutil.copyfileobj(response.raw, f)
                    if not silent:
                        logging.info(f"    [IMAGE OK] Downloaded (forced={force_download}): {save_path}")
                    return save_path
            except Exception as e:
                if not silent:
                    logging.error(f"    [IMAGE ERROR] {e}")
        return ""

    def refetch_cover(self, token):
        """Fetches only the cover URL from IGDB and downloads the image if missing."""
        # Handle multiple IDs: look for the IGDB one
        game_ids = self.data.get('game_ID', '').split(',')
        igdb_id = next((gid.replace('igdb_', '').strip() for gid in game_ids if gid.strip().startswith('igdb_')), None)

        if not igdb_id:
            # Only warn if we really expected to find one (e.g. Local Copy) or if we are debugging
            # logging.warning(f"    [COVER FETCH] Cannot fetch image for '{self.data['Clean_Title']}', missing IGDB ID.")
            return False

        logging.info(f"    [COVER FETCH] Fetching image URL for '{self.data['Clean_Title']}' (ID: {igdb_id})")

        query = f'fields cover.url; where id = {igdb_id};'

        # WHY: Use DRY helper function.
        results = _query_igdb_api(token, custom_query=query)
        
        if results:
            game_info = results[0]
            # Forcing download because we are here due to a missing image
            new_path = self._ensure_cover(game_info, force_download=True)
            if new_path:
                self.data['Image_Link'] = new_path
                return True

        logging.error(f"    [COVER FETCH ERROR] Could not find info for ID {igdb_id}.")
        
        # WHY: Case 3 - If IGDB explicitly returns no data for this ID, it's a dead ID.
        # We remove it and append "Not_on_IGDB" so we don't query it again.
        current_ids = [x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip()]
        if f"igdb_{igdb_id}" in current_ids:
            current_ids.remove(f"igdb_{igdb_id}")
        if "Not_on_IGDB" not in current_ids:
            current_ids.append("Not_on_IGDB")
        self.data['game_ID'] = ", ".join(sorted(current_ids))
        
        return False

    def fetch_metadata(self, token):
        # Prioritize Search_Title for the API request
        search_term = self.data.get('Search_Title') or self.data.get('Clean_Title') or self.data.get('Folder_Name')
        local_year = self.data.get('Year_Folder', '')
        
        # WHY: Use DRY helper function for metadata fetching.
        results = _query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
            # Scoring Logic
            best_match = None
            best_score = -1
            
            for g in results:
                score = 0
                # Title Score
                if search_term.lower() in g.get('name', '').lower(): score += 10
                
                # Year Score
                api_year = None
                dates = g.get('release_dates', [])
                if dates:
                    try:
                        ts = min([d['date'] for d in dates if 'date' in d])
                        api_year = datetime.utcfromtimestamp(ts).strftime('%Y')
                    except: pass
                
                if local_year and api_year:
                    if local_year == api_year:
                        score += 20
                    elif abs(int(local_year) - int(api_year)) <= 1:
                        score += 10
                
                if score > best_score:
                    best_score = score
                    best_match = g
            
            if best_match:
                g = best_match
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = normalize_genre(", ".join([ge['name'] for ge in g.get('genres', [])]))
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
                self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                dates = g.get('release_dates', [])
                api_year_str = ""
                if dates:
                    valid_dates = [d['date'] for d in dates if 'date' in d]
                    if valid_dates:
                        orig_ts = min(valid_dates)
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
                        api_year_str = datetime.utcfromtimestamp(orig_ts).strftime('%Y')
                
                # If the game has no platform defined (it's a "Local Files"), store its IGDB ID.
                if self.data.get('Platforms') == 'Local Files':
                    if 'id' in g:
                        current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
                        current_ids.add(f"igdb_{g.get('id')}")
                        self.data['game_ID'] = ", ".join(sorted(list(current_ids)))

                self.data['Image_Link'] = self._ensure_cover(g, silent=True)
                self.data['Status_Flag'] = 'OK'
                
                # Consolidated Log
                log_msg = f"    [IGDB] Found: {self.data['Clean_Title']}"
                if api_year_str:
                    log_msg += f" ({api_year_str})"
                logging.info(log_msg)
                return True

        if results is not None:
            logging.warning(f"    [IGDB] No results for '{search_term}'")
            self.data['Status_Flag'] = 'NEEDS_ATTENTION'
        return False

    def fetch_smart_metadata(self, token, search_override=None):
        # 1. Define search term
        search_term = search_override or self.data.get('Search_Title') or self.data.get('Folder_Name')
        logging.info(f"    [SMART SCAN] searching for: {search_term}")
        
        local_dev = self.data.get('Developer', '').lower()
        local_year = self.data.get('Year_Folder', '')

        # WHY: Use DRY helper function for smart metadata fetching.
        results = _query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
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
                self.data['Genre'] = normalize_genre(", ".join([ge['name'] for ge in g.get('genres', [])]))
                
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

    def apply_candidate_data(self, g):
        logging.info(f"    [MANUAL APPLY] Application des données pour '{self.data.get('Clean_Title')}' -> '{g.get('name')}'")
        self.data['Clean_Title'] = g.get('name', self.data.get('Clean_Title'))
        self.data['Summary'] = g.get('summary', '')
        self.data['Genre'] = normalize_genre(", ".join([ge['name'] for ge in g.get('genres', [])]))
        
        companies = g.get('involved_companies', [])
        self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
        self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
        
        videos = g.get('videos', [])
        self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
        
        dates = g.get('release_dates', [])
        if dates:
            orig_ts = min([d['date'] for d in dates if 'date' in d])
            self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
        
        # If the game has no platform defined (it's a "Local Files"), store its IGDB ID.
        # This will make future updates much more reliable.
        if self.data.get('Platforms') == 'Local Files':
            if 'id' in g:
                current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
                current_ids.add(f"igdb_{g.get('id')}")
                self.data['game_ID'] = ", ".join(sorted(list(current_ids)))
                logging.info(f"    [ID UPDATE] IGDB ID {g.get('id')} assigned to game.")

        # Forced image download
        self.data['Image_Link'] = self._ensure_cover(g, force_download=True)
        self.data['Status_Flag'] = 'LOCKED'
        return True

    def to_dict(self):
        return self.data

class LibraryManager:
    def __init__(self, config):
        self.config = config
        self.root_path = config.get('root_path', '')
        self.db_file = config.get('db_file', '')
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

        images_dir = os.path.join(BASE_DIR, "images")
        os.makedirs(images_dir, exist_ok=True)
        video_dir = self.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
        os.makedirs(video_dir, exist_ok=True)
        
        # Stats for the report
        stats = {
            'total_found': 0,
            'processed': 0,
            'new': 0,
            'matched_key': 0,
            'matched_smart': 0,
            'errors': 0,
            'deleted_ghosts': 0,
            'images_found_existing': 0,
            'images_downloaded': 0,
            'videos_found_existing': 0,
            'videos_downloaded': 0,
            'videos_download_fail': 0,
            'new_by_platform': {}
        }

        # Create a map for ultra-fast search by releaseKey
        key_to_game_map = {}
        for game in self.games.values():
            gids = game.data.get('game_ID', '').split(',')
            for gid in gids:
                gid = gid.strip()
                if gid:
                    key_to_game_map[gid] = game
        
        # Track processed title+platform combinations to avoid duplicates within the same sync session
        found_gog_keys = set()
        processed_games_session = set()

        while True:
            # Check for interruption request from the UI thread
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("GOG Sync interrupted by user.")
                break

            row = cursor.fetchone()
            if row is None:
                break # End of results

            stats['total_found'] += 1
            if stats['total_found'] % 100 == 0:
                logging.info(f"    ... processed {stats['total_found']} GOG entries ...")

            (releaseKey, meta_json, title_json, orig_title_json, summary_json, 
             developers_json, publishers_json, original_images_json, all_releases_json, 
             product_name, ld_title, ld_summary, ld_release_date, ld_images) = row

            found_gog_keys.add(releaseKey)

            title = "Unknown"
            metadata = {}
            
            # Helper to safely extract from JSON
            def safe_json_load(json_str):
                if not json_str: return None
                try: return json.loads(json_str)
                except: return None

            # Parse allGameReleases (List of IDs on other platforms)
            all_releases_data = safe_json_load(all_releases_json)
            releases_list = all_releases_data.get('releases', []) if all_releases_data else []

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

                # --- DYNAMIC PLATFORM DETECTION ---
                # Instead of a hardcoded list, we extract the prefix from the key.
                # This ensures new or uncommon platforms (like 'itch', 'rockstar') are captured automatically.
                platform = 'Unknown'
                if '_' in releaseKey:
                    prefix = releaseKey.split('_', 1)[0].lower()
                    
                    # Map known prefixes to "Pretty Names"
                    platform_map = self.config.get('platform_map', {})
                    ignored_prefixes = self.config.get('ignored_prefixes', [])

                    if prefix in ignored_prefixes:
                        platform = 'Unknown'
                    else:
                        # Use the pretty name if known, otherwise just Capitalize the prefix (e.g. 'itch' -> 'Itch')
                        platform = platform_map.get(prefix, prefix.title())
                elif releaseKey.isdigit():
                    # Legacy GOG keys are sometimes just numbers
                    platform = 'GOG'
                else:
                    logging.warning(f"    [PLATFORM UNKNOWN] Could not determine platform for '{title}' (Key: {releaseKey})")

                # --- DUPLICATE CHECK (Session Level) ---
                # If we already processed this exact title on this platform in this sync run, skip it.
                # This filters out DLCs/Editions that GOG Galaxy lists as separate entries but share the same name.
                session_key = (re.sub(r'[^a-z0-9]', '', title.lower()), platform)
                if session_key in processed_games_session:
                    continue
                processed_games_session.add(session_key)

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
                        
                        # Strict Year Check
                        year_mismatch = False
                        if gog_year and local_year:
                            try:
                                if abs(int(gog_year) - int(local_year)) > 3:
                                    year_mismatch = True
                            except: pass
                        
                        if year_mismatch: score -= 50 # Penalize heavily for year mismatch (Reboots)
                        elif gog_year and local_year and gog_year == local_year: score += 10

                        # BONUS: If titles match perfectly, boost score significantly
                        if local_norm_title == norm_title:
                            score += 20

                        if score > best_score:
                            best_score = score
                            best_game = game
                    
                    # Acceptance threshold: 70 points (or 60 if titles match perfectly)
                    threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
                    
                    if best_game and best_score >= threshold:
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
                    game_obj = Game(config=self.config, Folder_Name=folder_name, Status_Flag='OK', Path_Root='')
                    stats['new'] += 1
                    stats['new_by_platform'][platform] = stats['new_by_platform'].get(platform, 0) + 1

                # --- CHECK FOR MANUAL REFRESH ---
                force_media_refresh = game_obj.data.get('Status_Flag') == 'NEW'
                if force_media_refresh:
                    logging.info(f"    [GOG REFRESH] 'NEW' status detected for '{title}'. Checking for missing media.")

                # --- LOCKED STATUS CHECK ---
                if game_obj.data.get('Status_Flag') == 'LOCKED':
                    logging.info(f"    [LOCKED] Skipping metadata update for protected game: {title}")
                    continue

                # --- UPDATING DATA ---
                current_ids = set(x.strip() for x in game_obj.data.get('game_ID', '').split(',') if x.strip())
                current_ids.add(releaseKey)
                game_obj.data['game_ID'] = ", ".join(sorted(list(current_ids)))
                game_obj.data['Clean_Title'] = title
                
                # Platform Merging: Merge new platform with existing ones
                current_platforms = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
                if 'Unknown' in current_platforms: current_platforms.remove('Unknown')
                
                # FIX: Also remove 'Local Files' if we are adding a real platform
                if platform != 'Unknown' and 'Local Files' in current_platforms: current_platforms.remove('Local Files')
                
                # FIX: A Ghost entry (no local path) should never be 'Local Files'
                if not game_obj.data.get('Path_Root') and 'Local Files' in current_platforms:
                    current_platforms.remove('Local Files')
                
                # Add the new platform only if it's specific, or if we have nothing else
                if platform != 'Unknown' or not current_platforms:
                    current_platforms.add(platform)
                
                # Populate reserved platform_ID_xx fields
                for i in range(50):
                    col_name = f"platform_ID_{i+1:02d}"
                    if i < len(releases_list):
                        game_obj.data[col_name] = releases_list[i]
                    else:
                        game_obj.data[col_name] = ""

                game_obj.data['Platforms'] = ", ".join(sorted(list(current_platforms)))

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
                    raw_genre = ""
                    if isinstance(genres, list):
                        if len(genres) > 0 and isinstance(genres[0], dict):
                             raw_genre = ", ".join([g.get('name', '') for g in genres if g.get('name')])
                        else:
                             raw_genre = ", ".join([str(g) for g in genres])
                    game_obj.data['Genre'] = normalize_genre(raw_genre)

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
                base_filename = game_obj.data.get('Clean_Title', folder_name_for_files)
                
                # Append Year if available to ensure uniqueness and clarity
                file_year = ''
                if release_date:
                    file_year = f" ({release_date[-4:]})"
                
                safe_filename = get_safe_filename(f"{base_filename}{file_year}")

                # --- VIDEO MANAGEMENT (Trailer & Download) ---
                # --- B. Video Preparation (.mp4) ---
                video_url = game_obj.data.get('Trailer_Link')
                
                # Web Search (Steam API) if it's a Steam game OR if we found a Steam ID in releases
                # We also check for our special flags to avoid re-scanning.
                existing_trailer = game_obj.data.get('Trailer_Link', '')
                
                steam_app_id = None
                if platform == 'Steam':
                    steam_app_id = releaseKey.replace('steam_', '')
                else:
                    # Check releases_list for a steam key to use as fallback
                    for r in releases_list:
                        if r.startswith('steam_'):
                            steam_app_id = r.replace('steam_', '')
                            break

                if not existing_trailer and steam_app_id and steam_app_id.isdigit():
                    try:
                        app_id = steam_app_id
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

                                    if not video_url:
                                        logging.info(f"    [STEAM API] No usable video link found for '{title}' (AppID: {app_id}).")
                                        video_url = 'Not_on_Steam'
                                else:
                                    logging.info(f"    [STEAM API] No 'movies' section in API response for '{title}' (AppID: {app_id}).")
                                    video_url = 'Not_on_Steam'
                            else:
                                logging.warning(f"    [STEAM API] API returned success=false for '{title}' (AppID: {app_id}).")
                                video_url = 'Not_on_Steam'
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

                # --- C. Video Download (yt-dlp) & Physical Check ---
                existing_video_path = game_obj.data.get('Path_Video')
                video_exists_on_disk = existing_video_path and os.path.exists(existing_video_path)
                
                if video_exists_on_disk:
                    stats['videos_found_existing'] += 1

                # Check if a video already exists physically but is not in the CSV
                if not video_exists_on_disk:
                    for ext in VIDEO_EXTS:
                        potential_path = os.path.join(video_dir, f"{safe_filename}{ext}")
                        if os.path.exists(potential_path):
                            game_obj.data['Path_Video'] = potential_path
                            video_exists_on_disk = True
                            logging.info(f"    [VIDEO] Found existing local video: {potential_path}")
                            stats['videos_found_existing'] += 1
                            break

                # Check for interruption before starting download
                if worker_thread and worker_thread.isInterruptionRequested():
                    break

                # Check if video_url is a real downloadable URL
                is_youtube = video_url and ('youtube.com' in video_url or 'youtu.be' in video_url)
                is_downloadable_url = video_url and video_url.startswith('http') and not is_youtube

                if is_downloadable_url and not video_exists_on_disk:
                    if YT_DLP_AVAILABLE:
                        try:
                            logging.info(f"    [VIDEO] Found video URL ({video_url}), downloading with yt-dlp: {safe_filename} ...")
                            
                            # Hook to stop download if interrupted
                            def progress_hook(d):
                                if worker_thread and worker_thread.isInterruptionRequested():
                                    raise Exception("Download interrupted by user")

                            ydl_opts = {
                                'outtmpl': os.path.join(video_dir, f"{safe_filename}.%(ext)s"),
                                'quiet': True,
                                'no_warnings': True,
                                # 'best' can fail on some HLS streams if they are split audio/video.
                                # 'bestvideo+bestaudio/best' allows merging if needed, or single file if available.
                                # We let yt-dlp decide the best container.
                                'format': 'bestvideo+bestaudio/best', 
                                'progress_hooks': [progress_hook],
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                info = ydl.extract_info(video_url, download=True)
                                filename = ydl.prepare_filename(info)
                                if os.path.exists(filename):
                                    game_obj.data['Path_Video'] = filename
                                    logging.info(f"    [VIDEO] Download finished successfully.")
                                    stats['videos_downloaded'] += 1
                        except Exception as e:
                            if "Download interrupted by user" in str(e):
                                logging.warning(f"    [VIDEO] Download interrupted for '{title}'.")
                                break # Stop the loop entirely
                            logging.error(f"    [VIDEO ERROR] An unexpected error occurred during download for '{title}': {e}")
                            stats['videos_download_fail'] += 1
                    else:
                        if not hasattr(LibraryManager, '_yt_dlp_warning_logged'):
                            logging.warning("    [VIDEO] yt-dlp module not installed, skipping video downloads. Run 'pip install yt-dlp'.")
                            LibraryManager._yt_dlp_warning_logged = True

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

                    if image_exists_on_disk:
                        stats['images_found_existing'] += 1

                    # Check if the target file already exists (handling the Year suffix logic which Game() init might miss)
                    if not image_exists_on_disk:
                        for check_ext in ['.jpg', '.png', '.jpeg', '.webp']:
                            check_path = os.path.join(images_dir, f"{safe_filename}{check_ext}")
                            if os.path.exists(check_path):
                                game_obj.data['Image_Link'] = check_path
                                image_exists_on_disk = True
                                logging.info(f"    [IMAGE] Found existing image on disk: {check_path}")
                                stats['images_found_existing'] += 1
                                break

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
                        save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
                        try:
                            response = requests.get(cover_url, timeout=5)
                            if response.status_code == 200:
                                with open(save_path, 'wb') as f: f.write(response.content)
                                game_obj.data['Image_Link'] = save_path
                                logging.info(f"    [IMAGE] Downloaded missing image: {safe_filename}{ext}")
                                stats['images_downloaded'] += 1
                        except Exception as e: logging.error(f"    [IMAGE ERROR] {e}")

                # If we were forced to refresh, mark as OK now that we've checked/downloaded everything
                if force_media_refresh:
                    game_obj.data['Status_Flag'] = 'OK'

                self.games[game_obj.data['Folder_Name']] = game_obj
                stats['processed'] += 1
            except Exception as e:
                logging.error(f"    [GOG ERROR] Error processing game '{title}' (releaseKey: {releaseKey}): {e}")
                stats['errors'] += 1

        con.close()

        # --- CLEANUP: Remove Ghost entries no longer in GOG ---
        # Only perform cleanup if the sync wasn't interrupted
        if not (worker_thread and worker_thread.isInterruptionRequested()):
            ghosts_to_delete = []
            for folder_name, game in self.games.items():
                # Only check entries without a local path (Ghosts)
                if not game.data.get('Path_Root'):
                    # Check if any of the game's IDs correspond to a key found in this sync
                    game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
                    
                    # If NONE of the game's IDs are in found_gog_keys, it implies the source of this ghost is gone.
                    is_valid = False
                    for gid in game_ids:
                        if gid in found_gog_keys:
                            is_valid = True
                            break
                    
                    if not is_valid:
                        ghosts_to_delete.append(folder_name)

            for folder in ghosts_to_delete:
                logging.info(f"    [GOG CLEANUP] Removing obsolete platform entry: {folder}")
                game_to_delete = self.games[folder]
                
                # Media cleanup is handled by the fact that these are ghosts (usually no local media except what we downloaded)
                # We leave the media files for now to avoid accidental deletion of shared assets, or we could delete them.
                # For safety in this step, we just remove the DB entry. Media will be orphaned and can be cleaned by a future tool if needed.
                del self.games[folder]
                stats['deleted_ghosts'] += 1

        # Final report
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
            f"-----------------------------------\n"
            f"MEDIA STATISTICS\n"
            f"Images:\n"
            f"  - Found existing: {stats['images_found_existing']}\n"
            f"  - Downloaded: {stats['images_downloaded']}\n"
            f"Videos:\n"
            f"  - Found existing: {stats['videos_found_existing']}\n"
            f"  - Downloaded: {stats['videos_downloaded']}\n"
            f"  - Failed: {stats['videos_download_fail']}\n"
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
        """Loads data from storage into memory."""
        # WHY: This is the centralized point for reading data.
        # Currently: Reads a CSV file via Pandas.
        # Future: Will verify if .db exists and execute "SELECT * FROM games".
        if os.path.exists(self.db_file):
            df = pd.read_csv(self.db_file, sep=';', encoding='utf-8').fillna('')
            for _, row in df.iterrows():
                game_data = {k: str(v) for k, v in row.to_dict().items()}
                self.games[game_data['Folder_Name']] = Game(config=self.config, **game_data)
            logging.info(f"{len(self.games)} games loaded.")

    def fetch_candidates(self, token, search_term, limit=10):
        search_term = str(search_term).strip()
        # Log start of search
        logging.info(f"    [MANUAL SCAN] API search for: {search_term}")
        
        # WHY: Use DRY helper function for manual candidates fetching.
        is_id = search_term.isdigit()
        results = _query_igdb_api(token, search_term=search_term, limit=limit, by_id=is_id)
        
        if results is not None:
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
        return []

    def scan(self, retry_failures=False, worker_thread=None):
        token = self.get_access_token()
        scan_config = self.config.get('local_scan_config', {})
        ignore_hidden_global = scan_config.get("ignore_hidden", True)
        scan_mode = scan_config.get("scan_mode", "advanced")
        folder_rules = scan_config.get("folder_rules", {})
        global_type = scan_config.get("global_type", "Genre")

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

        # Determine Target Depth based on mode
        target_game_depth = 3 # Default Advanced
        if scan_mode == "simple":
            if "Direct" in global_type:
                target_game_depth = 1
            else:
                target_game_depth = 2
        
        logging.info(f"Scan Mode: {scan_mode} | Target Game Depth: {target_game_depth}")

        for root, dirs, files in os.walk(self.root_path):
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("Scan interrupted during folder analysis.")
                break # Exit the os.walk loop
            
            # Apply global hidden filter
            if ignore_hidden_global:
                dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
            
            rel_path = os.path.relpath(root, self.root_path)
            if rel_path == ".": continue
            
            depth = rel_path.count(os.sep) + 1
            path_parts = rel_path.split(os.sep)
            lvl1_folder = path_parts[0]

            # --- LEVEL 1 CHECK ---
            # Check if this Lvl 1 folder is allowed to be scanned
            rule = folder_rules.get(lvl1_folder)
            
            # If no rule exists, or scan is False, skip this entire branch
            if not rule or not rule.get("scan", False):
                if depth == 1:
                    logging.info(f"Skipping folder (Scan disabled or new): {lvl1_folder}")
                # Clear dirs to stop os.walk from going deeper into this folder
                dirs[:] = []
                continue
            
            if depth == 1:
                logging.info(f"Analyzing: {lvl1_folder} (Type: {rule.get('type', 'None')})")
                
            elif depth == 2:
                # We are inside a Level 2 folder (e.g. Root/Games/FPS)
                # The 'folder' variable here is the Game Folder (Level 3)
                for folder in dirs:
                    stats['scanned'] += 1 # Fix: Count each game folder individually
                    found_folders.add(folder)
                    full_path = os.path.join(root, folder)
                    if folder not in self.games:
                        # --- GHOST MATCHING LOGIC ---
                        # Check if this folder matches a "Ghost" entry (from GOG sync, no path)
                        ghost_match_key = None
                        
                        temp_game = Game(config=self.config, Folder_Name=folder)
                        local_clean_title = temp_game.data.get('Clean_Title', '')
                        local_norm_title = re.sub(r'[^a-z0-9]', '', local_clean_title.lower())
                        local_year = temp_game.data.get('Year_Folder', '')
                        
                        for k, g in self.games.items():
                            if not g.data.get('Path_Root'): # Is Ghost
                                g_norm = re.sub(r'[^a-z0-9]', '', g.data.get('Clean_Title', '').lower())
                                if g_norm == local_norm_title:
                                    # Check year if available
                                    g_year = ''
                                    if g.data.get('Original_Release_Date'): g_year = g.data.get('Original_Release_Date')[-4:]
                                    
                                    if local_year and g_year:
                                        try:
                                            if abs(int(local_year) - int(g_year)) > 3: continue
                                        except: pass
                                    
                                    ghost_match_key = k
                                    break
                        
                        if ghost_match_key:
                            logging.info(f"    [MERGE] Linking local folder '{folder}' to GOG entry '{ghost_match_key}'")
                            game_obj = self.games.pop(ghost_match_key)
                            game_obj.data['Folder_Name'] = folder
                            game_obj.data['Path_Root'] = full_path
                            if not game_obj.data.get('Year_Folder') and local_year:
                                game_obj.data['Year_Folder'] = local_year
                            
                            # Merge platforms from folder tags
                            p_set = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
                            p_set.update(x.strip() for x in temp_game.data.get('Platforms', '').split(',') if x.strip())
                            if 'Local Files' in p_set and len(p_set) > 1: p_set.remove('Local Files')
                            game_obj.data['Platforms'] = ", ".join(sorted(list(p_set)))
                            
                            self.games[folder] = game_obj
                            stats['updated'] += 1
                        else:
                            logging.info(f"    [NEW] Discovered: {folder}")
                            self.games[folder] = Game(config=self.config, Folder_Name=folder, Path_Root=full_path)
                            stats['new'] += 1
                    else:
                        # logging.info(f"    [CHECK] Checking existing game: {folder}")
                        # For existing games, update the path and re-check the video
                        game = self.games[folder]
                        if game.data.get('Path_Root') != full_path:
                            game.data['Path_Root'] = full_path
                        game._parse_folder_name()
                        
                        # --- APPLY FOLDER STRUCTURE METADATA ---
                        # Apply the rule from Level 1 to the Level 2 folder name
                        # path_parts[1] is the Level 2 folder name (e.g. "FPS" or "Tomb Raider")
                        if len(path_parts) >= 2:
                            content_type = rule.get("type", "None")
                            content_value = path_parts[1]
                            
                            if content_type == "Genre":
                                # Prepend the folder genre to the existing genre string and normalize
                                current = game.data.get('Genre', '')
                                combined = f"{content_value}, {current}" if current else content_value
                                game.data['Genre'] = normalize_genre(combined)
                                    
                            elif content_type == "Collection":
                                game.data['Collection'] = content_value
                                
                            elif content_type == "Publisher":
                                game.data['Publisher'] = content_value
                                
                            elif content_type == "Developer":
                                game.data['Developer'] = content_value
                                
                            elif content_type == "Year":
                                game.data['Year_Folder'] = content_value
                        
                        # Cleanup: If we have real platforms, remove 'Local Files'
                        p_set = set(x.strip() for x in game.data.get('Platforms', '').split(',') if x.strip())
                        if 'Local Files' in p_set and len(p_set) > 1:
                            p_set.remove('Local Files')
                            game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                            
                        stats['updated'] += 1

                    # --- SEQUENTIAL PROCESSING ---
                    # Process metadata and images immediately for this game
                    game = self.games[folder]
                    
                    if worker_thread and worker_thread.isInterruptionRequested():
                        logging.warning("Scan interrupted during metadata fetching.")
                        break 

                    image_is_missing = not game.data.get('Image_Link') or not os.path.exists(game.data.get('Image_Link'))
                    status = game.data.get('Status_Flag')

                    # Case 1: The game is NEW. Always fetch full metadata.
                    if status == 'NEW':
                        if token and game.fetch_metadata(token):
                            stats['fetched_success'] += 1
                        else:
                            logging.warning(f"    [FAILURE] Failure for: {folder}")
                            stats['fetched_fail'] += 1
                    
                    # Case 2: Game has failed (NEEDS_ATTENTION) and retry option is enabled.
                    elif status == 'NEEDS_ATTENTION' and retry_failures:
                        logging.info(f"    [FETCHING] Attempting for: {folder} (Reason: Retrying a previous failure)")
                        if token and game.fetch_metadata(token):
                            stats['fetched_success'] += 1
                        else:
                            logging.warning(f"    [FAILURE] Failure for: {folder}")
                            stats['fetched_fail'] += 1

                    # WHY: Case 2 - Download of missing images for "OK" games removed 
                    # from the main scan loop. This will be handled by the upcoming Media Manager.
        
        # Cleanup: Deleting games no longer on disk
        existing_folders = list(self.games.keys())
        for folder in existing_folders:
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.warning("Scan interrupted during orphan file cleanup.")
                break # Exit the deletion loop

            game_to_check = self.games.get(folder)
            if not game_to_check:
                continue

            # A game is an orphan ONLY if it's not found on disk AND it used to have a path.
            # This prevents deleting "ghost" entries from GOG sync that are not installed.
            is_on_disk = folder in found_folders
            had_a_path = bool(game_to_check.data.get('Path_Root'))

            if not is_on_disk and had_a_path:
                # Check if this is a "Platform Game" (has platforms other than Local Files/Unknown)
                platforms_str = game_to_check.data.get('Platforms', '')
                platform_list = [p.strip() for p in platforms_str.split(',') if p.strip()]
                real_platforms = [p for p in platform_list if p.lower() not in ['local files', 'unknown']]
                
                # Also check IDs for safety (e.g. if Platforms wasn't populated but ID exists)
                game_ids = game_to_check.data.get('game_ID', '')
                has_external_id = any(x in game_ids for x in ['gog_', 'steam_', 'epic_', 'uplay_', 'origin_'])

                if real_platforms or has_external_id:
                    # It's a Platform Game -> Downgrade to Digital Only (remove local path)
                    logging.info(f"    [UPDATE] Local files removed for '{folder}'. Reverting to Platform Entry.")
                    game_to_check.data['Path_Root'] = ''
                    
                    # Remove 'Local Copy' from platforms
                    if 'Local Copy' in platform_list:
                        platform_list.remove('Local Copy')
                        game_to_check.data['Platforms'] = ", ".join(sorted(platform_list))
                    
                    stats['updated'] += 1
                else:
                    # This is a true orphan (Local Files only). It was on disk, but now it's gone.
                    logging.info(f"    [DELETE] Game entry not found on disk, deleting: {folder}")
                    game_to_delete = game_to_check
                    
                    # Delete associated media files before deleting the entry
                    # Deleting image
                    image_path = game_to_delete.data.get('Image_Link')
                    if image_path and os.path.exists(image_path):
                        try:
                            os.remove(image_path)
                            logging.info(f"        -> Orphan image file deleted: {image_path}")
                        except Exception as e:
                            logging.error(f"        -> [DELETE ERROR] Could not delete image {image_path}: {e}")
                    
                    # Deleting video
                    video_path = game_to_delete.data.get('Path_Video')
                    if video_path and os.path.exists(video_path):
                        try:
                            os.remove(video_path)
                            logging.info(f"        -> Orphan video file deleted: {video_path}")
                        except Exception as e:
                            logging.error(f"        -> [DELETE ERROR] Could not delete video {video_path}: {e}")

                    del self.games[folder]
                    stats['deleted'] += 1
        
        
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

    def scan_full(self, retry_failures=False, worker_thread=None):
        logging.info("=== STARTING FULL INTELLIGENT SCAN ===")
        # 1. GOG Sync: Fetches official metadata and creates 'Ghost' entries
        self.sync_gog(worker_thread=worker_thread)
        if worker_thread and worker_thread.isInterruptionRequested(): return
        # 2. Local Scan: Matches local folders to Ghosts and cleans up
        self.scan(retry_failures=retry_failures, worker_thread=worker_thread)
        logging.info("=== FULL SCAN FINISHED ===")

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

    def _create_backup(self):
        """Creates a timestamped backup of the current database file."""
        # WHY: Abstracting backup logic prepares for SQLite. 
        # With SQLite, we might use the 'backup' API or simply copy the .db file,
        # but the logic of 'when' and 'how' to manage old backups stays here.
        if os.path.exists(self.db_file):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            
            # Cleanup old backups
            backups = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith("VGVDB_") and f.endswith(".csv")]
            backups.sort(key=os.path.getctime)
            while len(backups) >= MAX_FILES: # Uses global MAX_FILES
                oldest = backups.pop(0)
                try:
                    os.remove(oldest)
                except Exception as e:
                    logging.error(f"    [BACKUP CLEANUP ERROR] Failed to remove {oldest}: {e}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(BACKUP_DIR, f"VGVDB_{timestamp}.csv")
            try:
                shutil.copy2(self.db_file, backup_file)
                logging.info(f"    [DB BACKUP] Backup created at {backup_file}")
            except Exception as e:
                logging.error(f"    [DB BACKUP ERROR] Failed to create backup: {e}")

    def _get_db_schema(self):
        """Returns the list of columns that constitutes the database schema."""
        # WHY: Defining the schema in one place.
        # Future: This list will determine the fields for the SQLite 'CREATE TABLE' statement.
        return [
            'Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 
            'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 
            'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link',
            'game_ID'
        ] + [f'platform_ID_{i:02d}' for i in range(1, 51)]

    def save_db(self):
        """Persists the current in-memory game list to storage."""
        # WHY: This function acts as the single 'commit' point. 
        # Currently: Serializes objects to CSV.
        # Future: Will manage the SQLite transaction and execute INSERT/UPDATE queries.
        
        # 1. Create Backup before writing
        self._create_backup()

        # 2. Convert memory objects to DataFrame (Presentation Layer for CSV)
        df = pd.DataFrame([g.to_dict() for g in self.games.values()])
        
        # 3. Enforce Schema
        expected_columns = self._get_db_schema()
        
        # Force columns: add missing ones (filled with empty strings)
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ''
        
        # 4. Cleanup and Write
        df = df[expected_columns] # Reorder cleanly
        for col in ['Year_Folder', 'Original_Release_Date']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')
        
        # The actual write operation
        df.fillna('').to_csv(self.db_file, sep=';', index=False, encoding='utf-8')
        logging.info(f"    [DB SAVE] Database saved to {self.db_file} ({len(df)} games).")