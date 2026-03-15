# WHY: Extracted background workers into a dedicated module to isolate multi-threading logic
# from the main UI thread. This prevents GUI freezes and improves maintainability.
import os
import re
import logging
import pandas as pd
from PySide6.QtCore import QThread, Signal, QRunnable, QObject
from PySide6.QtGui import QImage

from ViGaVault_Scan import LibraryManager
from ViGaVault_utils import get_db_path, build_scanner_config

# --- WORKER THREADS ---
# Operations like scanning or filtering can take time. We run them in separate threads
# to prevent the GUI from freezing (becoming unresponsive) while they process.
class FullScanWorker(QThread):
    def __init__(self, retry_failures=False, parent=None):
        super().__init__(parent)
        self.retry_failures = retry_failures
        self.config = build_scanner_config()

    def run(self):
        """Runs the full scan process."""
        try:
            manager = LibraryManager(self.config)
            manager.load_db()
            manager.scan_full(retry_failures=self.retry_failures, worker_thread=self)
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
        if search:
            df = df[df['Clean_Title'].str.lower().str.contains(search)]
            
        is_scan_new = self.params.get('scan_new', False)

        # 2. Dynamic Filters (Sidebar Checkboxes)
        # Only apply if NOT scanning new games, as new games often lack metadata
        if not is_scan_new:
            active_filters = self.params.get('active_filters', {})
            for col, selected_values in active_filters.items():
                if not selected_values:
                    # If a category is active but has NO items selected, the result is empty.
                    df = df.iloc[0:0] 
                    break
                
                # Regex match for multi-value fields (e.g. "RPG, Action")
                regex_pattern = '|'.join([re.escape(v) for v in selected_values])
                df = df[df[col].astype(str).str.contains(regex_pattern, case=False, na=False)]

        # Status Filter (Exclusive)
        if is_scan_new:
            df = df[~df['Status_Flag'].isin(['OK', 'LOCKED'])]
        else:
            df = df[df['Status_Flag'].isin(['OK', 'LOCKED'])]
            
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
        if os.path.exists(db_path):
            try:
                df = pd.read_csv(db_path, sep=';', encoding='utf-8').fillna('')
                if 'Status_Flag' not in df.columns:
                    df['Status_Flag'] = 'NEW'
                # Pre-calculate columns for faster sorting
                df['temp_sort_date'] = pd.to_datetime(df['Original_Release_Date'], errors='coerce', dayfirst=True)
                df['temp_sort_title'] = df['Clean_Title'].str.lower()
            except Exception as e:
                logging.error(f"Error loading DB: {e}")
                df = pd.DataFrame()
        else:
            df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
            df['temp_sort_date'] = pd.to_datetime([])
            df['temp_sort_title'] = []
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