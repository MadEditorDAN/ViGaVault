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
from .epic.scan_epic import scan_epic_account
from .steam.scan_steam import scan_steam_account
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
        do_epic = self.config.get("enable_epic_web", False)
        do_steam = self.config.get("enable_steam_web", False)
        local_cfg = self.config.get('local_scan_config', {})
        do_local = local_cfg.get("enable_local_scan", True)
        target_folders = local_cfg.get("target_folders")
        
        # WHY: Display a clean, strictly formatted 80-column checklist mirroring user settings and mockup.
        checklist = f"{' PRE-SCAN CHECKLIST ':-^80}\n"
        checklist += f"{'Galaxy Sync':<16}: {'ON' if do_galaxy else 'OFF'}\n"
        checklist += f"{'GOG':<16}: {'ON' if do_gog else 'OFF'}\n"
        checklist += f"{'Epic Games':<16}: {'ON' if do_epic else 'OFF'}\n"
        checklist += f"{'Steam':<16}: {'ON' if do_steam else 'OFF'}\n"
        if do_local:
            checklist += f"{'Local Folders':<16}: ON\n"
            if target_folders is not None and len(target_folders) > 0:
                for tf in sorted(target_folders):
                    checklist += f"  - {tf}\n"
            else:
                checklist += "  - All Folders\n"
        else:
            checklist += f"{'Local Folders':<16}: OFF\n"
        checklist += f"{'Images Download':<16}: {'ON' if self.config.get('download_images', True) else 'OFF'}"
        logging.info(checklist + "\n")

        if do_galaxy:
            sync_galaxy_database(self.config, self.games, worker_thread=worker_thread)
            self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
        
        if do_gog:
            gog_changes = scan_gog_account(self.config, self.games, worker_thread=worker_thread)
            if gog_changes: self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
            
        if do_epic:
            epic_changes = scan_epic_account(self.config, self.games, worker_thread=worker_thread)
            if epic_changes: self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return

        if do_steam:
            steam_changes = scan_steam_account(self.config, self.games, worker_thread=worker_thread)
            if steam_changes: self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return

        if do_local:
            scan_local_system(self.config, self.games, worker_thread=worker_thread)
            self.save_db()
            if worker_thread and worker_thread.isInterruptionRequested(): return
        
        self.sync_media_flags_batch()
        # WHY: Run the unified IGDB scrapper engine after all platforms have finished their fast data intake.
        self.run_igdb_scrapper(worker_thread=worker_thread)
        
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
        # WHY: Inject Is_DLC into the permanent schema matrix so manual batch tags persist perfectly to the hard drive.
        return ['Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Status_Flag', 'Image_Link', 'Cover_URL', 'Year_Folder', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link', 'game_ID', 'Is_Local', 'Has_Image', 'Is_DLC'] + [f'platform_ID_{i:02d}' for i in range(1, 51)]

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
        
        root_path = self.config.get('root_path', '')
        root_accessible = os.path.exists(root_path)

        # WHY: Smart Refresh - Instead of hitting os.path.exists() on a NAS drive for every single game's subfolder,
        # we perform one single os.listdir() on the root path and cache the existing folders in RAM.
        # This turns a potential 30-second network I/O bottleneck into a 0.01-second memory lookup.
        local_folders_cache = set()
        if root_accessible:
            try:
                local_folders_cache = {f for f in os.listdir(root_path)}
            except: pass

        for folder, game in self.games.items():
            old_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            old_loc = str(game.data.get('Is_Local')).lower() in ['true', '1']

            img_base = os.path.basename(game.data.get('Image_Link', '')).lower()
            new_img = bool(img_base and img_base in img_set)
            
            new_loc = old_loc
            if root_accessible:
                path_root = game.data.get('Path_Root', '')
                if path_root:
                    try:
                        rel_path = os.path.relpath(path_root, root_path)
                        top_folder = rel_path.split(os.sep)[0]
                        new_loc = top_folder in local_folders_cache
                    except:
                        new_loc = os.path.exists(path_root)
                else:
                    new_loc = False

            if new_img != old_img or new_loc != old_loc:
                game.data['Has_Image'] = new_img
                game.data['Is_Local'] = new_loc
                changes_made = True
                
        if changes_made: self.save_db()
        return changes_made

    def run_igdb_scrapper(self, worker_thread=None):
        """
        WHY: The Unified Scrapper Engine.
        Executes strictly after all platform scans have finished. It targets any games 
        flagged as 'NEW', queries IGDB for their missing metadata and cover URLs, 
        evaluates their final completion status, and performs batch image downloading.
        """
        logging.info(f"\n{' IGDB SCRAPPER & MEDIA BACKFILL ':=^80}")
        images_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        dl_images = self.config.get('download_images', True)

        changes_made = False
        igdb_token = None
        
        stats = {'scraped': 0, 'downloads': 0, 'ok': 0, 'needs_attention': 0}

        for folder, game in self.games.items():
            if worker_thread and worker_thread.isInterruptionRequested(): break

            safe_filename = get_safe_filename(game.data.get('Folder_Name', ''))
            status = game.data.get('Status_Flag')

            # --- PHASE 1: METADATA SCRAPING ---
            # WHY: Only scrape games marked as NEW. This completely prevents infinite API loops on broken titles.
            if status == 'NEW':
                if igdb_token is None: igdb_token = get_igdb_access_token()
                
                if igdb_token:
                    # fill_missing_metadata intelligently skips fields that are already populated
                    if game.fill_missing_metadata(igdb_token):
                        stats['scraped'] += 1
                        changes_made = True
                
                # Evaluate final completion status
                missing_meta = not all([game.data.get(f) for f in ['Developer', 'Publisher', 'Genre', 'Summary', 'Original_Release_Date']])
                has_cover = bool(game.data.get('Cover_URL')) or bool(game.data.get('Image_Link'))
                
                if missing_meta or not has_cover:
                    game.data['Status_Flag'] = 'NEEDS_ATTENTION'
                    stats['needs_attention'] += 1
                else:
                    game.data['Status_Flag'] = 'OK'
                    stats['ok'] += 1
                changes_made = True

            # --- PHASE 2: MEDIA DOWNLOADING ---
            if dl_images and not (str(game.data.get('Has_Image')).lower() in ['true', '1']):
                cover_url_raw = game.data.get('Cover_URL', '')
                if cover_url_raw:
                    url_candidates = [u.strip() for u in cover_url_raw.split('|') if u.strip().startswith('http')]
                    active_candidates = url_candidates.copy()
                    success = False
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
                                success = True
                                break
                                
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            # WHY: Reduce timeout strictly to 3 seconds to prevent massive delays when a server is unresponsive.
                            response = requests.get(cover_url, stream=True, timeout=3, headers=headers)
                            if response.status_code == 200:
                                os.makedirs(images_dir, exist_ok=True)
                                with open(save_path, 'wb') as f:
                                    shutil.copyfileobj(response.raw, f)
                                game.data['Image_Link'] = f"{safe_filename}{ext}"
                                game.data['Has_Image'] = True
                                stats['downloads'] += 1
                                changes_made = True
                                success = True
                                
                                action_title = f"Cover Download : {folder}"
                                logging.info(f"|{action_title[:55]:<55}| Img: Yes | Trl: --- |")
                                break # Stop trying fallbacks once we succeed!
                            elif response.status_code in [404, 403]:
                                # WHY: If the link is permanently dead (404/403), remove it from active candidates.
                                if cover_url in active_candidates:
                                    active_candidates.remove(cover_url)
                        except Exception as e: pass
                    
                    if not success:
                        # WHY: If all downloads failed, overwrite the Cover_URL field in the DB to physically 
                        # erase dead links. This prevents the scanner from infinitely retrying them on every scan.
                        new_cover_raw = "|".join(active_candidates)
                        if game.data.get('Cover_URL') != new_cover_raw:
                            game.data['Cover_URL'] = new_cover_raw
                            changes_made = True

        if changes_made: self.save_db()
        
        report = f"{' SCRAPPER REPORT ':=^80}\n"
        report += f"Games Scraped  : {stats['scraped']}\n"
        report += f"Promoted to OK : {stats['ok']}\n"
        report += f"Needs Attention: {stats['needs_attention']}\n"
        report += f"Covers D/L'd   : {stats['downloads']}\n"
        report += f"{'='*80}"
        logging.info(report)