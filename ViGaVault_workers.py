# WHY: Extracted background workers into a dedicated module to isolate multi-threading logic
# from the main UI thread. This prevents GUI freezes and improves maintainability.
import os
import re
import logging
import pandas as pd
from PySide6.QtCore import QThread, Signal, QRunnable, QObject
from PySide6.QtGui import QImage

from backend.library import LibraryManager
from ViGaVault_utils import get_db_path, build_scanner_config, get_library_settings_file
import json

# --- WORKER THREADS ---
# Operations like scanning or filtering can take time. We run them in separate threads
# to prevent the GUI from freezing (becoming unresponsive) while they process.
class FullScanWorker(QThread):
    def __init__(self, do_galaxy=True, do_local=True, do_gog_web=False, do_epic=False, do_steam=False, do_download_images=True, target_folders=None, parent=None):
        super().__init__(parent)
        self.do_galaxy = do_galaxy
        self.do_local = do_local
        self.do_gog_web = do_gog_web
        self.do_epic = do_epic
        self.do_steam = do_steam
        self.do_download_images = do_download_images
        self.target_folders = target_folders
        self.config = build_scanner_config()

    def run(self):
        """Runs the full scan process."""
        # WHY: Dynamically overriding the execution config with UI instructions
        # ensures the LibraryManager respects user choice cleanly without modifying permanent settings.
        self.config['enable_galaxy_db'] = self.do_galaxy
        self.config['enable_gog_web'] = self.do_gog_web
        self.config['enable_epic_web'] = self.do_epic
        self.config['enable_steam_web'] = self.do_steam
        self.config['download_images'] = self.do_download_images
        
        if 'local_scan_config' not in self.config:
            self.config['local_scan_config'] = {}
        self.config['local_scan_config']['enable_local_scan'] = self.do_local
        self.config['local_scan_config']['target_folders'] = self.target_folders
        
        try:
            manager = LibraryManager(self.config)
            manager.load_db()
            manager.scan_full(worker_thread=self)
        except Exception as e:
            logging.error(f"Critical error in full scan thread: {e}")

class FilterWorker(QThread):
    # Emits the filtered DataFrame back to the main thread when done.
    finished = Signal(object)

    def __init__(self, master_df, params, parent=None):
        super().__init__(parent)
        self.master_df = master_df
        self.params = params

    def run(self):
        df = self.master_df.copy()

        # 1. Text Filter (Search Bar)
        search = self.params['search_text'].lower()
        search_target = self.params.get('search_target', 'Name')
        
        if search:
            if search_target == 'Name':
                mask_title = df['Clean_Title'].fillna('').str.lower().str.contains(search)
                mask_folder = df['Folder_Name'].fillna('').str.lower().str.contains(search)
                mask_search = df['Search_Title'].fillna('').str.lower().str.contains(search) if 'Search_Title' in df.columns else False
                df = df[mask_title | mask_folder | mask_search]
            elif search_target == 'Developer':
                df = df[df['Developer'].fillna('').str.lower().str.contains(search)]
            elif search_target == 'Publisher':
                df = df[df['Publisher'].fillna('').str.lower().str.contains(search)]
            elif search_target == 'Summary':
                df = df[df['Summary'].fillna('').str.lower().str.contains(search)]
            
        is_scan_new = self.params.get('scan_new', False)
        is_scan_dlc = self.params.get('scan_dlc', False)
        is_scan_review = self.params.get('scan_review', False)

        # 2. Dynamic Filters (Sidebar Checkboxes)
        # Only apply if NOT scanning new games, as new games often lack metadata
        if not is_scan_new and not is_scan_review:
            active_filters = self.params.get('active_filters', {})
            for col, selected_values in active_filters.items():
                if not selected_values:
                    # If a category is active but has NO items selected, the result is empty.
                    df = df.iloc[0:0] 
                    break
                
                # Regex match for multi-value fields (e.g. "RPG, Action")
                regex_pattern = '|'.join([re.escape(v) for v in selected_values])
                df = df[df[col].astype(str).str.contains(regex_pattern, case=False, na=False)]

        # WHY: Status & DLC Filter - Ensures Excluded and DLC items strictly vanish from standard UI views unless manually requested via the DLC toggle.
        allowed_flags = []
        if is_scan_new: 
            allowed_flags.extend(['NEW', 'NEEDS_ATTENTION'])
        if is_scan_review: allowed_flags.append('REVIEW')
        
        if is_scan_dlc:
            # Show strictly DLCs and Exclusions
            df = df[df['Is_DLC'] | df['Is_Excluded']]
        elif allowed_flags:
            # Show target statuses, but protect against DLC/Exclusion pollution
            df = df[df['Status_Flag'].isin(allowed_flags) & ~df['Is_DLC'] & ~df['Is_Excluded']]
        else:
            # Default safe view
            df = df[df['Status_Flag'].isin(['OK', 'LOCKED']) & ~df['Is_DLC'] & ~df['Is_Excluded']]
            
        # 3. Sorting
        sort_col = self.params['sort_col']
        sort_desc = self.params['sort_desc']
        
        # Use pre-calculated temporary columns for speed (dates, lowercase titles)
        if sort_col == "temp_sort_date" or sort_col == "temp_sort_title":
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last' if sort_col == "temp_sort_date" else 'first')
        else:
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last')
        
        self.finished.emit(df)

class DbLoaderWorker(QThread):
    finished = Signal(object)

    def run(self):
        db_path = get_db_path()
        config = build_scanner_config()
        date_fmt = config.get('date_format', '%d/%m/%Y')
        
        if os.path.exists(db_path):
            try:
                df = pd.read_csv(db_path, sep=';', encoding='utf-8').fillna('')
                if 'Status_Flag' not in df.columns:
                    df['Status_Flag'] = 'NEW'
                    
                # WHY: Guarantee Is_DLC resolves as a strict boolean for Pandas processing.
                if 'Is_DLC' not in df.columns: df['Is_DLC'] = False
                else: df['Is_DLC'] = df['Is_DLC'].astype(str).str.lower().isin(['true', '1'])
                    
                # WHY: Pass 1 - Strictly parse dates using the globally configured Regional Format to prevent day/month swapping.
                
                # WHY: Targeted Update - Instead of destructively dropping rows, strictly flag them via 'Is_Excluded' so they remain in memory.
                df['Is_Excluded'] = False
                lib_settings_file = get_library_settings_file()
                if os.path.exists(lib_settings_file):
                    try:
                        with open(lib_settings_file, "r", encoding='utf-8') as f:
                            settings = json.load(f)
                            exclusions = settings.get("exclusion_words", [])
                            if exclusions:
                                pattern = '|'.join([re.escape(w) for w in exclusions])
                                mask = df['Clean_Title'].str.contains(pattern, case=False, na=False)
                                df.loc[mask, 'Is_Excluded'] = True
                    except Exception as e:
                        logging.error(f"Error applying exclusions: {e}")

                parsed_dates = pd.to_datetime(df['Original_Release_Date'], format=date_fmt, errors='coerce')
                # WHY: Pass 2 - Catch dates that failed (like pure "2020" years) and fallback to generic parsing.
                mask = parsed_dates.isna() & (df['Original_Release_Date'] != '')
                if mask.any():
                    fallback = pd.to_datetime(df.loc[mask, 'Original_Release_Date'], errors='coerce')
                    parsed_dates.update(fallback)
                    
                df['temp_sort_date'] = parsed_dates
                df['temp_sort_title'] = df['Clean_Title'].str.lower()
                # WHY: Store the physical CSV row number to allow sorting by "Date Added".
                df['temp_sort_index'] = df.index
            except Exception as e:
                logging.error(f"Error loading DB: {e}")
                df = pd.DataFrame()
        else:
            # WHY: Automatically instantiate a physical blank database on the hard drive if it's missing on boot.
            expected_columns = ['Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 'Status_Flag', 'Image_Link', 'Cover_URL', 'Year_Folder', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link', 'game_ID', 'Is_Local', 'Has_Image', 'Has_Video'] + [f'platform_ID_{i:02d}' for i in range(1, 51)]
            pd.DataFrame(columns=expected_columns).to_csv(db_path, sep=';', index=False, encoding='utf-8')
            logging.info(f"Created new empty database at {db_path}")
            df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
            df['temp_sort_date'] = pd.to_datetime([])
            df['temp_sort_title'] = []
            df['temp_sort_index'] = []
        self.finished.emit(df)

class ImageSignals(QObject):
    loaded = Signal(QImage)

class ImageLoader(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.signals = ImageSignals()

    def run(self):
        if self.path and os.path.exists(self.path):
            image = QImage(self.path)
            if not image.isNull():
                self.signals.loaded.emit(image)

class StartupSyncWorker(QThread):
    """
    WHY: A silent startup worker designed to seamlessly align Database flags with OS Reality 
    in the background immediately after boot without freezing the main visual interface.
    """
    finished = Signal(bool)
    
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        
    def run(self):
        manager = LibraryManager(self.config)
        manager.load_db()
        changes_made = manager.sync_media_flags_batch()
        self.finished.emit(changes_made)