# WHY: Strategy Pattern Orchestrator - Coordinates loading/saving DataFrames, and dispatches scanning tasks to specialized modules.
import os
import pandas as pd
import logging
import shutil
import difflib
import requests
from urllib.parse import urlparse
from datetime import datetime

from ViGaVault_utils import BASE_DIR, get_safe_filename
from .game import Game
from .api_igdb import get_igdb_access_token, query_igdb_api
from .api_galaxy import sync_galaxy_database
from .gog.scan_gog import scan_gog_account
from .local_copy_scanner import scan_local_system

BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MAX_FILES = 10 

class LibraryManager:
    def __init__(self, config):
        self.config = config
        self.root_path = config.get('root_path', '')
        self.db_file = config.get('db_file', '')
        self.games = {}

    def load_db(self):
        if os.path.exists(self.db_file):
            df = pd.read_csv(self.db_file, sep=';', encoding='utf-8').fillna('')
            for _, row in df.iterrows():
                game_data = {k: str(v) for k, v in row.to_dict().items()}
                self.games[game_data['Folder_Name']] = Game(config=self.config, **game_data)

    def scan_full(self, worker_thread=None):
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logging.info(f"[{now_str}] \n{' FULL INTELLIGENT SCAN STARTED ':=^80}")
        
        do_galaxy = self.config.get("enable_galaxy_db", True)
        do_gog = self.config.get("enable_gog_web", False)
        local_cfg = self.config.get('local_scan_config', {})
        do_local = local_cfg.get("enable_local_scan", True)
        target_folders = local_cfg.get("target_folders")
        
        # WHY: Display a clean, strictly formatted 80-column checklist mirroring user settings.
        checklist = f"{' PRE-SCAN CHECKLIST ':-^80}\n"
        checklist += f"Galaxy Sync     : {'ON' if do_galaxy else 'OFF'}\n"
        checklist += f"GOG.com Web     : {'ON' if do_gog else 'OFF'}\n"
        if do_local:
            checklist += "Local Folders   : ON\n"
            if target_folders is not None and len(target_folders) > 0:
                for tf in sorted(target_folders):
                    checklist += f"                : {tf}\n"
            else:
                checklist += "                : All Folders\n"
        else:
            checklist += "Local Folders   : OFF\n"
        checklist += f"Images Download : {'ON' if self.config.get('download_images', True) else 'OFF'}"
        logging.info(checklist + "\n")

        if do_galaxy:
            sync_galaxy_database(self.config, self.games, worker_thread=worker_thread)
            self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
        
        if do_gog:
            gog_changes = scan_gog_account(self.config, self.games, worker_thread=worker_thread)
            if gog_changes: self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return

        if do_local:
            token = get_igdb_access_token()
            scan_local_system(self.config, self.games, token, worker_thread=worker_thread)
            self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
        
        self.sync_media_flags_batch()
        # WHY: Run the self-healing backfill loop after standard processing finishes.
        self.process_pending_downloads(worker_thread=worker_thread)
        
        end_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logging.info(f"{' FULL INTELLIGENT SCAN FINISHED ':=^80}\n[{end_str}]\n")

    def scan_single_game(self, game_name, manual_search_term=None):
        token = get_igdb_access_token()
        if not token: return False
        game = self.games.get(game_name)
        if game:
            success = game.fetch_smart_metadata(token, search_override=manual_search_term)
            self.save_db()
            return success
        return False

    def fetch_candidates(self, token, search_term, limit=10):
        return query_igdb_api(token, search_term=str(search_term).strip(), limit=limit, by_id=str(search_term).strip().isdigit())

    def get_access_token(self):
        return get_igdb_access_token()

    def _get_db_schema(self):
        return ['Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Status_Flag', 'Image_Link', 'Cover_URL', 'Year_Folder', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link', 'game_ID', 'Is_Local', 'Has_Image'] + [f'platform_ID_{i:02d}' for i in range(1, 51)]

    def save_db(self):
        if os.path.exists(self.db_file):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            backups = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith("VGVDB_") and f.endswith(".csv")]
            backups.sort(key=os.path.getctime)
            while len(backups) >= MAX_FILES: os.remove(backups.pop(0))
            shutil.copy2(self.db_file, os.path.join(BACKUP_DIR, f"VGVDB_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"))
        
        df = pd.DataFrame([g.to_dict() for g in self.games.values()])
        expected_columns = self._get_db_schema()
        for col in expected_columns:
            if col not in df.columns: df[col] = ''
        df = df[expected_columns]
        for col in ['Year_Folder', 'Original_Release_Date']:
            if col in df.columns: df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')
        df.fillna('').to_csv(self.db_file, sep=';', index=False, encoding='utf-8')

    def sync_media_flags_batch(self):
        changes_made = False
        
        # WHY: Convert physical directory listings to lowercase sets. This completely fixes a 
        # Windows case-sensitivity bug where 'Game.jpg' in DB didn't match 'game.jpg' on disk, 
        # causing the app to erroneously flag the image as missing and trigger massive re-downloads.
        img_set = {f.lower() for f in os.listdir(self.config.get('image_path', ''))} if os.path.exists(self.config.get('image_path', '')) else set()
        root_accessible = os.path.exists(self.config.get('root_path', ''))

        for folder, game in self.games.items():
            old_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            old_loc = str(game.data.get('Is_Local')).lower() in ['true', '1']

            img_base = os.path.basename(game.data.get('Image_Link', '')).lower()
            new_img = bool(img_base and img_base in img_set)
            
            new_loc = old_loc
            if root_accessible:
                path_root = game.data.get('Path_Root', '')
                new_loc = bool(path_root and os.path.exists(path_root))

            if new_img != old_img or new_loc != old_loc:
                game.data['Has_Image'] = new_img
                game.data['Is_Local'] = new_loc
                changes_made = True
                
        if changes_made: self.save_db()
        return changes_made

    def process_pending_downloads(self, worker_thread=None):
        """
        WHY: Asynchronous Media Backfill Engine.
        Scans the library for missing media that has a stored URL and downloads it
        if global settings have been re-enabled, completely saving API calls.
        """
        logging.info(f"\n{' MEDIA BACKFILL ENGINE ':=^80}")
        images_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        dl_images = self.config.get('download_images', True)

        changes_made = False
        
        # WHY: Cache the IGDB token outside the loop to avoid authenticating repeatedly for every missing cover.
        igdb_token = None

        for folder, game in self.games.items():
            if worker_thread and worker_thread.isInterruptionRequested(): break

            safe_filename = get_safe_filename(game.data.get('Folder_Name', ''))

            if dl_images and not (str(game.data.get('Has_Image')).lower() in ['true', '1']):
                cover_url_raw = game.data.get('Cover_URL', '')
                
                # WHY: Unified IGDB Fallback. If ANY game reaches this point without a Cover URL 
                # (e.g. from a Local Folder scan), we automatically query IGDB and flag it for user REVIEW.
                if not cover_url_raw and game.data.get('Status_Flag') != 'LOCKED':
                    if igdb_token is None:
                        igdb_token = get_igdb_access_token()
                    if igdb_token:
                        search_term = game.data.get('Clean_Title') or game.data.get('Folder_Name')
                        igdb_res = query_igdb_api(igdb_token, search_term=search_term, limit=3)
                        if igdb_res:
                            best_match, best_score = None, -1
                            for g in igdb_res:
                                score = int(difflib.SequenceMatcher(None, search_term.lower(), g.get('name', '').lower()).ratio() * 100)
                                if g.get('category', 0) == 0: score += 15
                                elif g.get('category', 0) in [1, 2]: score -= 30
                                if score > best_score and 'cover' in g and 'url' in g['cover']:
                                    best_score, best_match = score, g
                            if best_match:
                                cover_url_raw = "https:" + best_match['cover']['url'].replace('t_thumb', 't_cover_big')
                                game.data['Cover_URL'] = cover_url_raw
                                game.data['Status_Flag'] = 'REVIEW'
                                log_act = "IGDB Cover"
                                changes_made = True

                if cover_url_raw:
                    # WHY: Split by '|' to support a fallback chain of URLs. 
                    # The engine tries each URL in order and breaks instantly on the first HTTP 200 success.
                    url_candidates = [u.strip() for u in cover_url_raw.split('|') if u.strip().startswith('http')]
                    for cover_url in url_candidates:
                        try:
                            # WHY: Clean the URL of trailing parameters for a safe file extension extraction.
                            clean_url = cover_url.split('?')[0]
                            path = urlparse(clean_url).path
                            ext = os.path.splitext(path)[1]
                            if not ext: ext = '.jpg'
                            save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
                            
                            # WHY: Safety Guard. If the image physically exists on disk but the DB 
                            # somehow lost the internal Has_Image flag, instantly re-link it without hitting the network.
                            if os.path.exists(save_path):
                                game.data['Image_Link'] = f"{safe_filename}{ext}"
                                game.data['Has_Image'] = True
                                changes_made = True
                                break
                                
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            response = requests.get(cover_url, stream=True, timeout=10, headers=headers)
                            if response.status_code == 200:
                                os.makedirs(images_dir, exist_ok=True)
                                with open(save_path, 'wb') as f:
                                    shutil.copyfileobj(response.raw, f)
                                game.data['Image_Link'] = f"{safe_filename}{ext}"
                                game.data['Has_Image'] = True
                                log_act = "Cover DL"
                                changes_made = True
                                break # Stop trying fallbacks once we succeed!
                        except Exception as e: pass

            if 'log_act' in locals() and log_act:
                action_title = f"{log_act} : {folder}"
                logging.info(f"|{action_title[:56]:<56}| Img: Yes | Trl: --- |")

        if changes_made: self.save_db()