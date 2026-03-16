# WHY: Strategy Pattern Orchestrator - Coordinates loading/saving DataFrames, and dispatches scanning tasks to specialized modules.
import os
import pandas as pd
import logging
import shutil
from datetime import datetime

from ViGaVault_utils import BASE_DIR, get_safe_filename
from .game import Game
from .api_igdb import get_igdb_access_token, query_igdb_api
from .api_gog import sync_gog_database
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
        return ['Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link', 'game_ID', 'Is_Local', 'Has_Image', 'Has_Video'] + [f'platform_ID_{i:02d}' for i in range(1, 51)]

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
            new_img = bool(game.data.get('Image_Link', '') and os.path.basename(game.data.get('Image_Link', '')) in img_set)
            if new_img != (str(game.data.get('Has_Image')).lower() in ['true', '1']): game.data['Has_Image'], changes_made = new_img, True
        if changes_made: self.save_db()
        return changes_made