# WHY: Strategy Pattern Orchestrator - Coordinates loading/saving DataFrames, and dispatches scanning tasks to specialized modules.
import os
import pandas as pd
import logging
import shutil
import requests
from urllib.parse import urlparse
from datetime import datetime

from ViGaVault_utils import BASE_DIR, get_safe_filename
from .game import Game
from .api_igdb import get_igdb_access_token, query_igdb_api
from .api_gog import sync_gog_database
from .local_copy_scanner import scan_local_system

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

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
        logging.info("=== STARTING FULL INTELLIGENT SCAN ===")
        if self.config.get("enable_gog_db", True):
            sync_gog_database(self.config, self.games, worker_thread=worker_thread)
            self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
        else:
            logging.info("--- GOG SYNC DISABLED FOR THIS SCAN ---")
        
        local_config = self.config.get('local_scan_config', {})
        if local_config.get("enable_local_scan", True):
            token = get_igdb_access_token()
            scan_local_system(self.config, self.games, token, worker_thread=worker_thread)
            self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
        else:
            logging.info("--- LOCAL SCAN DISABLED FOR THIS SCAN ---")
        
        self.sync_media_flags_batch()
        # WHY: Run the self-healing backfill loop after standard processing finishes.
        self.process_pending_downloads(worker_thread=worker_thread)
        logging.info("=== FULL SCAN FINISHED ===")

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
        return ['Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 'Status_Flag', 'Image_Link', 'Cover_URL', 'Year_Folder', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link', 'game_ID', 'Is_Local', 'Has_Image', 'Has_Video'] + [f'platform_ID_{i:02d}' for i in range(1, 51)]

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
        img_set = set(os.listdir(self.config.get('image_path', ''))) if os.path.exists(self.config.get('image_path', '')) else set()
        vid_set = set(os.listdir(self.config.get('video_path', ''))) if os.path.exists(self.config.get('video_path', '')) else set()
        root_accessible = os.path.exists(self.config.get('root_path', ''))

        for folder, game in self.games.items():
            old_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            old_vid = str(game.data.get('Has_Video')).lower() in ['true', '1']
            old_loc = str(game.data.get('Is_Local')).lower() in ['true', '1']

            new_img = bool(game.data.get('Image_Link', '') and os.path.basename(game.data.get('Image_Link', '')) in img_set)
            new_vid = bool(game.data.get('Path_Video', '') and os.path.basename(game.data.get('Path_Video', '')) in vid_set)
            
            new_loc = old_loc
            if root_accessible:
                path_root = game.data.get('Path_Root', '')
                new_loc = bool(path_root and os.path.exists(path_root))

            if new_img != old_img or new_vid != old_vid or new_loc != old_loc:
                game.data['Has_Image'] = new_img
                game.data['Has_Video'] = new_vid
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
        logging.info("--- STARTING MEDIA BACKFILL ---")
        images_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        video_dir = self.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
        dl_images = self.config.get('download_images', True)
        dl_videos = self.config.get('download_videos', False)

        changes_made = False

        for folder, game in self.games.items():
            if worker_thread and worker_thread.isInterruptionRequested(): break

            safe_filename = get_safe_filename(game.data.get('Folder_Name', ''))

            if dl_images and not (str(game.data.get('Has_Image')).lower() in ['true', '1']):
                cover_url = game.data.get('Cover_URL', '')
                if cover_url and cover_url.startswith('http'):
                    try:
                        path = urlparse(cover_url).path
                        ext = os.path.splitext(path)[1]
                        if not ext: ext = '.jpg'
                        save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
                        
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        response = requests.get(cover_url, stream=True, timeout=10, headers=headers)
                        if response.status_code == 200:
                            os.makedirs(images_dir, exist_ok=True)
                            with open(save_path, 'wb') as f:
                                shutil.copyfileobj(response.raw, f)
                            game.data['Image_Link'] = f"{safe_filename}{ext}"
                            game.data['Has_Image'] = True
                            changes_made = True
                            logging.info(f"    [BACKFILL] Downloaded missing cover for: {folder}")
                    except Exception as e: pass

            if dl_videos and not (str(game.data.get('Has_Video')).lower() in ['true', '1']) and YT_DLP_AVAILABLE:
                trailer_link = game.data.get('Trailer_Link', '')
                is_youtube = trailer_link and ('youtube.com' in trailer_link or 'youtu.be' in trailer_link)
                is_downloadable = trailer_link and trailer_link.startswith('http') and not is_youtube
                
                if is_downloadable:
                    try:
                        def progress_hook(d):
                            if worker_thread and worker_thread.isInterruptionRequested(): raise Exception("Download interrupted")
                        ydl_opts = {'outtmpl': os.path.join(video_dir, f"{safe_filename}.%(ext)s"), 'quiet': True, 'no_warnings': True, 'format': 'bestvideo+bestaudio/best', 'progress_hooks': [progress_hook]}
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(trailer_link, download=True)
                            filename = ydl.prepare_filename(info)
                            if os.path.exists(filename):
                                game.data['Path_Video'] = os.path.basename(filename)
                                game.data['Has_Video'] = True
                                changes_made = True
                                logging.info(f"    [BACKFILL] Downloaded missing video for: {folder}")
                    except Exception as e: pass

        if changes_made: self.save_db()