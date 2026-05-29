# WHY: Strategy Pattern Orchestrator - Coordinates loading/saving DataFrames, and dispatches scanning tasks to specialized modules.
import os
import io
import pandas as pd
import logging
import shutil
import difflib
import requests
from urllib.parse import urlparse
from datetime import datetime

from ViGaVault_utils import BASE_DIR, get_safe_filename, encrypt_string_to_file, decrypt_file_to_string
from .game import Game
from .api_igdb import get_igdb_access_token, query_igdb_api
from .api_galaxy import sync_galaxy_database
from .gog.scan_gog import scan_gog_account
from .epic.scan_epic import scan_epic_account
from .steam.scan_steam import scan_steam_account
from .amazon.sync_amazon import sync_amazon_database
from .local_copy_scanner import scan_local_system

BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MAX_FILES = 10 

def get_pre_scan_checklist_text(config):
    from ViGaVault_utils import (
        format_header_row, format_separator_row, format_box_bottom
    )
    
    do_galaxy = config.get("enable_galaxy_db", True)
    do_gog = config.get("enable_gog_web", False)
    do_epic = config.get("enable_epic_web", False)
    do_steam = config.get("enable_steam_web", False)
    do_amazon = config.get("enable_amazon_web", False)
    local_cfg = config.get('local_scan_config', {})
    do_local = local_cfg.get("enable_local_scan", True)
    target_folders = local_cfg.get("target_folders")
    folder_rules = local_cfg.get("folder_rules", {})
    do_images = config.get('download_images', True)
    
    lines = [format_header_row("FULL SCAN CHECKLIST", is_secondary=False, col_spec=[17, 60])]
    
    def fmt_check_row(label, val):
        col1 = f" {label:<15} "
        col2 = f" {val:<58} "
        return f"║{col1}│{col2}║"
        
    lines.append(fmt_check_row("Amazon", "ON" if do_amazon else "OFF"))
    lines.append(fmt_check_row("GOG", "ON" if do_gog else "OFF"))
    lines.append(fmt_check_row("Epic Games", "ON" if do_epic else "OFF"))
    lines.append(fmt_check_row("Steam", "ON" if do_steam else "OFF"))
    lines.append(fmt_check_row("Galaxy Sync", "ON" if do_galaxy else "OFF"))
    
    if do_local:
        lines.append("╟" + "═"*17 + "╪" + "═"*36 + "╤" + "═"*23 + "╣")
        
        def fmt_3col_row(col1_val, col2_val, col3_val):
            col1 = f" {col1_val:<15} "
            col2 = f" {col2_val:<34} "
            col3 = f" {col3_val:<21} "
            return f"║{col1}│{col2}│{col3}║"
            
        lines.append(fmt_3col_row("Local Folders", "ON", "Content Type"))
        lines.append("╟" + "─"*17 + "┼" + "─"*36 + "┼" + "─"*23 + "╢")
        
        active_folders = []
        if target_folders is not None:
            active_folders = sorted(list(target_folders))
        else:
            active_folders = sorted([f for f, r in folder_rules.items() if r.get("scan", False)])
            
        for f in active_folders:
            rule = folder_rules.get(f, {})
            c_type = rule.get("type", "None")
            import os
            f_display = os.path.basename(f)
            if not f_display: f_display = f
            lines.append(fmt_3col_row("Folder name", f_display, c_type))
            
        lines.append("╟" + "═"*17 + "╪" + "═"*36 + "╧" + "═"*23 + "╣")
    else:
        lines.append("╟" + "═"*17 + "╪" + "═"*60 + "╣")
        lines.append(fmt_check_row("Local Folders", "OFF"))
        lines.append("╟" + "═"*17 + "╪" + "═"*60 + "╣")
        
    lines.append(fmt_check_row("Image Download", "ON" if do_images else "OFF"))
    lines.append(format_box_bottom([17, 60]))
    
    return "\n".join(lines)

class LibraryManager:
    def __init__(self, config):
        self.config = config
        self.root_path = config.get('root_path', '')
        self.db_file = config.get('db_file', '')
        self.games = {}

    def load_db(self):
        # WHY: Read the encrypted blob from the disk and pipe the plaintext string natively into Pandas via StringIO.
        csv_str = decrypt_file_to_string(self.db_file)
        if csv_str:
            try:
                df = pd.read_csv(io.StringIO(csv_str), sep=';', encoding='utf-8', dtype=str).fillna('')
                
                # WHY: Guarantee schema integrity so dict unpacking never throws KeyErrors.
                for col in self._get_db_schema():
                    if col not in df.columns:
                        df[col] = ''
                
                # WHY: Cleanly map each row to a fully populated, structured Game object in our in-memory cache.
                for idx, row in df.iterrows():
                    game_data = row.to_dict()
                    folder = game_data.get('Folder_Name')
                    if folder:
                        self.games[folder] = Game(config=self.config, **game_data)
            except Exception as e:
                logging.error(f"Error loading LibraryManager DB: {e}")

    def scan_full(self, worker_thread=None, amazon_claims=None, amazon_stats=None):
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        images_only = self.config.get('images_only', False)
        
        skip_checklist = self.config.get('skip_checklist_logging', False)
        if not skip_checklist:
            if images_only:
                logging.info(f"[{now_str}] \n{' STANDALONE MEDIA BACKFILL STARTED ':=^80}")
            else:
                logging.info(f"[{now_str}] \n{' FULL INTELLIGENT SCAN STARTED ':=^80}")
            
        do_galaxy = self.config.get("enable_galaxy_db", True)
        do_gog = self.config.get("enable_gog_web", False)
        do_epic = self.config.get("enable_epic_web", False)
        do_steam = self.config.get("enable_steam_web", False)
        do_amazon = self.config.get("enable_amazon_web", False)
        local_cfg = self.config.get('local_scan_config', {})
        do_local = local_cfg.get("enable_local_scan", True)
        
        if not skip_checklist:
            logging.info(get_pre_scan_checklist_text(self.config) + "\n")

        galaxy_stats = None
        gog_stats = None
        epic_stats = None
        steam_stats = None
        
        # WHY: Store Amazon statistics accumulated sequentially in the dynamic crawl.
        # We reuse the stats passed from the GUI controller if available.
        # If running from a test or direct context, we execute the full sync.
        
        local_stats = None

        if not images_only:
            # 1. Amazon (Runs first sequentially)
            if do_amazon:
                if amazon_stats is not None:
                    # WHY: Amazon was already scanned and synced sequentially.
                    # We reuse its statistics directly for the final matrix report.
                    pass
                else:
                    claims = amazon_claims if amazon_claims is not None else []
                    amazon_changes, amazon_stats = sync_amazon_database(self.config, self.games, claims, worker_thread=worker_thread, print_header=False)
                    if amazon_changes: self.save_db()
                if worker_thread and worker_thread.isInterruptionRequested(): return

            # 2. GOG
            if do_gog:
                gog_changes, gog_stats = scan_gog_account(self.config, self.games, worker_thread=worker_thread)
                if gog_changes: self.save_db()
                if worker_thread and worker_thread.isInterruptionRequested(): return

            # 3. Epic Games
            if do_epic:
                epic_changes, epic_stats = scan_epic_account(self.config, self.games, worker_thread=worker_thread)
                if epic_changes: self.save_db()
                if worker_thread and worker_thread.isInterruptionRequested(): return

            # 4. Steam
            if do_steam:
                steam_changes, steam_stats = scan_steam_account(self.config, self.games, worker_thread=worker_thread)
                if steam_changes: self.save_db()
                if worker_thread and worker_thread.isInterruptionRequested(): return

            # 5. Galaxy Sync
            if do_galaxy:
                galaxy_stats = sync_galaxy_database(self.config, self.games, worker_thread=worker_thread)
                self.save_db()
                if worker_thread and worker_thread.isInterruptionRequested(): return

            # 6. Local Copy
            if do_local:
                local_stats = scan_local_system(self.config, self.games, worker_thread=worker_thread)
                self.save_db()
                if worker_thread and worker_thread.isInterruptionRequested(): return
        
        self.sync_media_flags_batch(worker_thread=worker_thread)
        # WHY: Run the unified IGDB scrapper engine after all platforms have finished their fast data intake.
        self.run_igdb_scrapper(worker_thread=worker_thread, images_only=images_only)
        
        # --- GLOBAL CONSOLIDATION REPORT ---
        if not images_only:
            from ViGaVault_utils import (
                format_matrix_row, format_matrix_divider, format_report_row,
                format_total_db_row
            )

            gal_s = galaxy_stats or {}
            gog_s = gog_stats or {}
            epi_s = epic_stats or {}
            stm_s = steam_stats or {}
            amz_s = amazon_stats or {}
            loc_s = local_stats or {}

            amz_scan = amz_s.get('total_cloud', 0)
            amz_add = amz_s.get('new_added', 0)
            amz_merge = amz_s.get('matched_smart', 0)
            amz_del = amz_s.get('deleted_ghosts', 0)
            amz_already = amz_s.get('already_in_db', 0)
            amz_err = 0

            gal_scan = gal_s.get('total_found', 0)
            gal_add = gal_s.get('new', 0)
            gal_merge = gal_s.get('matched_smart', 0)
            gal_del = gal_s.get('deleted_ghosts', 0)
            gal_already = gal_scan - gal_add - gal_merge
            if gal_already < 0: gal_already = 0
            gal_err = gal_s.get('errors', 0)

            gog_scan = gog_s.get('total_cloud', 0)
            gog_add = gog_s.get('new_added', 0)
            gog_merge = gog_s.get('matched_smart', 0)
            gog_del = 0
            gog_already = gog_s.get('already_in_db', 0)
            gog_err = gog_s.get('failed', 0)

            epi_scan = epi_s.get('total_cloud', 0)
            epi_add = epi_s.get('new_added', 0)
            epi_merge = epi_s.get('matched_smart', 0)
            epi_del = 0
            epi_already = epi_s.get('already_in_db', 0)
            epi_err = epi_s.get('errors', 0) + epi_s.get('skipped', 0)

            stm_scan = stm_s.get('total_cloud', 0)
            stm_add = stm_s.get('new_added', 0)
            stm_merge = stm_s.get('matched_smart', 0)
            stm_del = 0
            stm_already = stm_s.get('already_in_db', 0)
            stm_err = 0

            loc_scan = loc_s.get('scanned', 0)
            loc_add = loc_s.get('new', 0)
            loc_merge = loc_s.get('updated', 0)
            loc_del = loc_s.get('deleted', 0)
            loc_already = loc_scan - loc_add - loc_merge
            if loc_already < 0: loc_already = 0
            loc_err = 0

            total_scanned = amz_scan + gal_scan + gog_scan + epi_scan + stm_scan + loc_scan
            total_added = amz_add + gal_add + gog_add + epi_add + stm_add + loc_add
            total_merged = amz_merge + gal_merge + gog_merge + epi_merge + stm_merge + loc_merge
            total_deleted = amz_del + gal_del + gog_del + epi_del + stm_del + loc_del
            total_already = amz_already + gal_already + gog_already + epi_already + stm_already + loc_already
            total_errors = amz_err + gal_err + gog_err + epi_err + stm_err + loc_err

            title_part = "╣ FULL SCAN REPORT ╠"
            logging.info("╔" + "═"*18 + title_part + "═"*40 + "╗")
            logging.info(format_matrix_divider(is_middle=False))

            logging.info(format_matrix_row("Amazon", amz_scan, amz_add, amz_merge, amz_del))
            logging.info(format_matrix_row("GOG.com", gog_scan, gog_add, gog_merge, gog_del))
            logging.info(format_matrix_row("Epic Games", epi_scan, epi_add, epi_merge, epi_del))
            logging.info(format_matrix_row("Steam", stm_scan, stm_add, stm_merge, stm_del))
            logging.info(format_matrix_row("GALAXY", gal_scan, gal_add, gal_merge, gal_del))
            logging.info(format_matrix_row("Local Copy", loc_scan, loc_add, loc_merge, loc_del))

            logging.info(format_matrix_divider(is_middle=True))

            logging.info(format_report_row("Total Games", total_scanned))
            logging.info(format_report_row("Already in DB", total_already))
            logging.info(format_report_row("New Added", total_added))
            logging.info(format_report_row("Smart Merged", total_merged))
            logging.info(format_report_row("Deleted", total_deleted))
            logging.info(format_report_row("Errors/Ignored", total_errors))

            logging.info("╠" + "═"*17 + "╧" + "═"*46 + "╤" + "═"*13 + "╣")
            logging.info(format_total_db_row("TOTAL Games in the Database - VGV-DB.DAT", len(self.games)))
            logging.info("╚" + "═"*64 + "╧" + "═"*13 + "╝")

        end_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if images_only:
            logging.info(f"{' STANDALONE MEDIA BACKFILL FINISHED ':=^80}\n[{end_str}]\n")
        else:
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

    def fetch_candidates(self, token, search_term, limit=10, go_wild=False):
        return query_igdb_api(token, search_term=str(search_term).strip(), limit=limit, by_id=str(search_term).strip().isdigit(), go_wild=go_wild)

    def get_access_token(self):
        return get_igdb_access_token()

    def _get_db_schema(self):
        # WHY: Inject Is_DLC and Is_Excluded into the permanent schema matrix so manual batch tags persist perfectly to the hard drive.
        return ['Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Status_Flag', 'Image_Link', 'Cover_URL', 'Year_Folder', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link', 'game_ID', 'Is_Local', 'Has_Image', 'Is_DLC', 'Is_Excluded'] + [f'platform_ID_{i:02d}' for i in range(1, 51)]

    def save_db(self):
        if os.path.exists(self.db_file):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            backups = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith("VGVDB_") and f.endswith(".dat")]
            backups.sort(key=os.path.getctime)
            while len(backups) >= MAX_FILES: os.remove(backups.pop(0))
            shutil.copy2(self.db_file, os.path.join(BACKUP_DIR, f"VGVDB_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dat"))
        
        df = pd.DataFrame([g.to_dict() for g in self.games.values()])
        expected_columns = self._get_db_schema()
        for col in expected_columns:
            if col not in df.columns: df[col] = ''
        df = df[expected_columns]
        for col in ['Year_Folder', 'Original_Release_Date']:
            if col in df.columns: df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')
        
        csv_str = df.fillna('').to_csv(sep=';', index=False)
        encrypt_string_to_file(self.db_file, csv_str)

    def sync_media_flags_batch(self, worker_thread=None):
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
            if worker_thread and worker_thread.isInterruptionRequested():
                logging.info("[SYNC] Interruption requested during media flags sync. Exiting early.")
                return False
                
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

    def run_igdb_scrapper(self, worker_thread=None, images_only=False):
        """
        WHY: The Unified Scrapper Engine.
        Executes strictly after all platform scans have finished. It targets any games 
        flagged as 'NEW', queries IGDB for their missing metadata and cover URLs, 
        evaluates their final completion status, and performs batch image downloading.
        """
        from ViGaVault_utils import (
            format_header_row, format_middle_header, format_box_bottom,
            format_separator_row, format_report_row, format_operation_row
        )

        logging.info(format_header_row("IGDB SCRAPPER", is_secondary=False, col_spec=[17, 36, 5, 5, 5, 5]))
        images_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        dl_images = self.config.get('download_images', True)

        changes_made = False
        igdb_token = None
        
        stats = {'scraped': 0, 'downloads': 0, 'ok': 0, 'needs_attention': 0}
        ops_logged = 0

        for folder, game in self.games.items():
            if worker_thread and worker_thread.isInterruptionRequested(): break

            action_taken = False
            safe_filename = get_safe_filename(game.data.get('Folder_Name', ''))
            status = game.data.get('Status_Flag')

            # --- PHASE 1: METADATA SCRAPING ---
            db_has_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            needs_cover_rescue = not db_has_img and game.data.get('Cover_URL', '') == ''
            
            if images_only:
                should_scrape = needs_cover_rescue
            else:
                should_scrape = (status in ['NEW', ''] or needs_cover_rescue)
                
            if should_scrape:
                action_taken = True
                op_name = "Scraping"
                title_disp = game.data.get('Clean_Title', folder)
                
                if ops_logged == 0:
                    logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
                
                logging.info("UI_START|" + format_operation_row(op_name, title_disp, False, False))
                ops_logged += 1
                
                if igdb_token is None: igdb_token = get_igdb_access_token()
                
                if igdb_token:
                    if game.fill_missing_metadata(igdb_token, images_only=images_only):
                        stats['scraped'] += 1
                        changes_made = True
                        
                if game.data.get('Cover_URL', '') == '':
                    game.data['Cover_URL'] = 'NOT_FOUND'
                    changes_made = True
                
                if not images_only:
                    missing_meta = not all([game.data.get(f) for f in ['Genre', 'Summary']])
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
                if cover_url_raw and cover_url_raw != 'NOT_FOUND':
                    
                    if not action_taken:
                        op_name = "Cover Download"
                        title_disp = game.data.get('Clean_Title', folder)
                        
                        if ops_logged == 0:
                            logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
                            
                        logging.info("UI_START|" + format_operation_row(op_name, title_disp, False, False))
                        action_taken = True
                        ops_logged += 1
                        
                    url_candidates = [u.strip() for u in cover_url_raw.split('|') if u.strip().startswith('http')]
                    active_candidates = url_candidates.copy()
                    success = False
                    for cover_url in url_candidates:
                        try:
                            clean_url = cover_url.split('?')[0]
                            path = urlparse(clean_url).path
                            ext = os.path.splitext(path)[1]
                            if not ext: ext = '.jpg'
                            save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
                            
                            if os.path.exists(save_path):
                                game.data['Image_Link'] = f"{safe_filename}{ext}"
                                game.data['Has_Image'] = True
                                changes_made = True
                                success = True
                                break
                                
                            headers = {'User-Agent': 'Mozilla/5.0'}
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
                                action_taken = True
                                break
                            elif response.status_code in [404, 403]:
                                if cover_url in active_candidates:
                                    active_candidates.remove(cover_url)
                        except Exception as e: pass
                    
                    if not success:
                        new_cover_raw = "|".join(active_candidates) if active_candidates else 'NOT_FOUND'
                        if game.data.get('Cover_URL') != new_cover_raw:
                            game.data['Cover_URL'] = new_cover_raw
                            changes_made = True
                            
            if action_taken:
                title_disp = game.data.get('Clean_Title', folder)
                has_img_now = str(game.data.get('Has_Image')).lower() in ['true', '1']
                has_trl_now = bool(game.data.get('Trailer_Link') and str(game.data.get('Trailer_Link')).startswith('http'))
                
                if status in ['NEW', 'NEEDS_ATTENTION', '']:
                    op_name = "Scraping"
                else:
                    op_name = "Cover Download"
                    
                logging.info("UI_UPDATE|" + format_operation_row(op_name, title_disp, has_img_now, has_trl_now))

        if changes_made: self.save_db()
        
        if ops_logged > 0:
            logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┴", "┴", "┴"]))
            
        logging.info(format_middle_header("REPORT", col_spec=[17, 36, 5, 5, 5, 5]))
        logging.info(format_report_row("Games Scraped", stats['scraped']))
        logging.info(format_report_row("OK", stats['ok']))
        logging.info(format_report_row("Needs Attention", stats['needs_attention']))
        logging.info(format_report_row("Covers D/L'd", stats['downloads']))
        logging.info(format_box_bottom([17, 60]))
