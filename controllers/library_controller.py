# WHY: Single Responsibility Principle - Strictly manages DataFrame memory, background asynchronous loaders, 
# and primary disk-to-memory synchronization operations.
import os
import json
import shutil
import logging
from datetime import datetime
import pandas as pd
from PySide6.QtCore import QObject, Slot, Qt, QPoint, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from backend.library import LibraryManager
from ViGaVault_utils import get_db_path, get_library_settings_file, build_scanner_config, translator
from ViGaVault_workers import DbLoaderWorker, StartupSyncWorker

class LibraryController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    @Slot()
    def trigger_initial_settings(self):
        """WHY: Explicitly bound slot guarantees the PySide6 C++ engine retains the reference for the delayed timer."""
        try:
            from backend.igdb.login_igdb import is_igdb_connected
            igdb_ready = is_igdb_connected()
        except ImportError:
            igdb_ready = False
            
        if not igdb_ready:
            logging.info("[STARTUP] Missing IGDB configuration detected. Redirecting user to Platform Manager.")
            QMessageBox.information(self.mw, translator.tr("app_title"), translator.tr("msg_welcome_first_launch"))
            if hasattr(self.mw, 'menu_controller'):
                self.mw.menu_controller.open_settings(tab_index=2)
        else:
            logging.info("[STARTUP] Triggering initial Settings Dialog...")
            if hasattr(self.mw, 'menu_controller'):
                self.mw.menu_controller.open_settings(tab_index=1)

    def get_second_visible_folder(self):
        """WHY: Finds the second item visible at the top of the list to act as a stable layout anchor immune to pixel shifts."""
        if self.mw.list_widget.model() is None or self.mw.list_widget.model().rowCount() == 0:
            return None
            
        vp_width = self.mw.list_widget.viewport().width()
        x_pos = vp_width // 2 if vp_width > 0 else 100
        first_index = self.mw.list_widget.indexAt(QPoint(x_pos, 30))
        
        if not first_index.isValid():
            for i in range(self.mw.list_widget.model().rowCount()):
                idx = self.mw.list_widget.model().index(i, 0)
                if self.mw.list_widget.visualRect(idx).bottom() > 0:
                    first_index = idx
                    break
                    
        if first_index.isValid():
            row = first_index.row()
            if row + 1 < self.mw.list_widget.model().rowCount():
                return self.mw.list_widget.model().data(self.mw.list_widget.model().index(row + 1, 0), Qt.UserRole + 1)
            return self.mw.list_widget.model().data(first_index, Qt.UserRole + 1)
        return None

    def update_status_checkboxes_state(self):
        """WHY: Single Responsibility Principle - Actively inspects the database to grey out options that have no results."""
        if not hasattr(self.mw, 'master_df') or self.mw.master_df.empty: return
            
        # WHY: Include both strictly new games AND games that failed the metadata fetch (NEEDS_ATTENTION)
        # under the "Show NEW" toggle umbrella so they don't become permanently invisible ghosts.
        has_new = 'NEW' in self.mw.master_df['Status_Flag'].values or 'NEEDS_ATTENTION' in self.mw.master_df['Status_Flag'].values
        has_review = 'REVIEW' in self.mw.master_df['Status_Flag'].values
        has_dlc = self.mw.master_df['Is_DLC'].any() or self.mw.master_df['Is_Excluded'].any()
        
        self.mw.sidebar.btn_toggle_new.setEnabled(has_new)
        self.mw.sidebar.btn_toggle_review.setEnabled(has_review)
        self.mw.sidebar.btn_toggle_dlc.setEnabled(has_dlc)
        self.mw.sidebar.btn_approve_review.setEnabled(has_review)
        
        # Uncheck instantly if there are no more results to prevent a blank UI
        if not has_new and self.mw.sidebar.btn_toggle_new.isChecked(): self.mw.sidebar.btn_toggle_new.setChecked(False)
        if not has_review and self.mw.sidebar.btn_toggle_review.isChecked(): self.mw.sidebar.btn_toggle_review.setChecked(False)
        if not has_dlc and self.mw.sidebar.btn_toggle_dlc.isChecked(): self.mw.sidebar.btn_toggle_dlc.setChecked(False)

    def update_library_info(self):
        lib_name = os.path.basename(get_db_path()).replace('.csv', '')
        self.mw.setWindowTitle(f"ViGaVault Library - [{lib_name}]")
        self.mw.sidebar.lbl_lib_name.setText(f"{lib_name}")

    def select_library(self):
        # WHY: Use DontConfirmOverwrite to suppress the OS-level "File exists, replace?" warning, replacing it with our custom contextual load prompt.
        filePath, _ = QFileDialog.getSaveFileName(self.mw, "Switch or Create Library", "", "ViGaVault Library (*.csv)", options=QFileDialog.DontConfirmOverwrite)
        if filePath:
            if not filePath.lower().endswith('.csv'): filePath += '.csv'
            is_new_file = not os.path.exists(filePath)

            if not is_new_file:
                reply = QMessageBox.question(self.mw, translator.tr("dialog_switch_lib_exist_title"),
                                            translator.tr("dialog_switch_lib_exist_msg"),
                                            QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No: return

            self.mw.settings_controller.save_settings()
            
            try:
                settings = {}
                if os.path.exists("settings.json"):
                    with open("settings.json", "r", encoding='utf-8') as f:
                        settings = json.load(f)
                settings['db_path'] = filePath
                with open("settings.json", "w", encoding='utf-8') as f:
                    json.dump(settings, f, indent=4)
                
                if is_new_file:
                    self.mw.force_settings_open = True
                    expected_columns = [
                        'Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 
                        'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 
                        'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link',
                        'game_ID', 'Is_Local', 'Has_Image', 'Has_Video'
                    ] + [f'platform_ID_{i:02d}' for i in range(1, 51)]
                    pd.DataFrame(columns=expected_columns).to_csv(filePath, sep=';', index=False, encoding='utf-8')
                    
                    lib_settings_path = os.path.splitext(filePath)[0] + ".json"
                    default_lib_settings = {
                        "root_path": "",
                        "local_scan_config": {"enable_local_scan": False, "ignore_hidden": True, "scan_mode": "simple", "global_type": "Genre", "global_filter": True, "folder_rules": {}},
                        "galaxy_db_path": os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db'),
                    # WHY: Set default download_images to True so fresh libraries automatically backfill covers from API scans.
                    "enable_galaxy_db": False, "download_images": True, "download_videos": False, "sort_desc": True, "sort_index": 0, "view_new": False, "view_dlc": False, "view_review": False, "filter_states": {}, "filter_expansion": {}
                    }
                    with open(lib_settings_path, "w", encoding='utf-8') as f:
                        json.dump(default_lib_settings, f, indent=4)

                self.reload_ui_for_new_library()
            except Exception as e:
                QMessageBox.critical(self.mw, "Error", f"Could not switch library: {e}")

    def reload_ui_for_new_library(self):
        self.mw.background_loader.stop()
        self.mw.filter_timer.stop()
        if self.mw.list_widget.model():
             self.mw.list_widget.model().beginResetModel()
             self.mw.list_widget.model().df = pd.DataFrame()
             self.mw.list_widget.model().endResetModel()
        self.mw.sidebar.search_bar.clear()
        self.load_database_async()

    def load_database_async(self):
        if self.mw.list_widget.model():
             self.mw.list_widget.model().beginResetModel()
             self.mw.list_widget.model().df = pd.DataFrame()
             self.mw.list_widget.model().endResetModel()
        self.mw.sidebar.setEnabled(False)
        self.db_worker = DbLoaderWorker()
        self.db_worker.finished.connect(self.on_db_loaded)
        self.db_worker.start()

    @Slot(object)
    def on_db_loaded(self, df):
        self.mw.master_df = df
        self.mw.sidebar.setEnabled(True)
        
        lib_settings = {}
        lib_settings_file = get_library_settings_file()
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass

        if not hasattr(self.mw, 'pending_anchor_folder') or not getattr(self.mw, 'pending_anchor_folder', None):
            saved_anchor = lib_settings.get("anchor_folder")
            if saved_anchor:
                self.mw.pending_anchor_folder = saved_anchor

        saved_filters = lib_settings.get("filter_states")
        saved_expansion = lib_settings.get("filter_expansion")

        self.mw.filter_controller.populate_dynamic_filters(saved_filters, saved_expansion)

        self.mw.sidebar.combo_sort.blockSignals(True)
        self.mw.sidebar.btn_toggle_new.blockSignals(True)
        self.mw.sidebar.btn_toggle_dlc.blockSignals(True)
        self.mw.sidebar.btn_toggle_review.blockSignals(True)

        self.mw.sort_desc = lib_settings.get("sort_desc", True)
        self.mw.sidebar.combo_sort.setCurrentIndex(lib_settings.get("sort_index", 0))
        self.mw.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
        self.mw.sidebar.btn_toggle_new.setChecked(lib_settings.get("view_new", False))
        self.mw.sidebar.btn_toggle_dlc.setChecked(lib_settings.get("view_dlc", False))
        self.mw.sidebar.btn_toggle_review.setChecked(lib_settings.get("view_review", False))
        self.mw.sidebar.update_sort_button(self.mw.sort_desc)

        self.mw.sidebar.combo_sort.blockSignals(False)
        self.mw.sidebar.btn_toggle_new.blockSignals(False)
        self.mw.sidebar.btn_toggle_dlc.blockSignals(False)
        self.mw.sidebar.btn_toggle_review.blockSignals(False)
        self.update_status_checkboxes_state()

        self.update_library_info()
        
        # WHY: Generate the dynamic folder checkboxes strictly AFTER the specific library context 
        # is fully loaded. This guarantees the correct VGVDB.json rules are applied on boot and when switching libraries!
        self.mw.settings_controller.refresh_scan_folders_ui()

        if self.mw.is_startup:
            # WHY: The first launch process must always trigger on boot if the IGDB keys are missing, 
            # regardless of whether the local database and settings already exist.
            try:
                from backend.igdb.login_igdb import is_igdb_connected
                if not is_igdb_connected():
                    self.mw.force_settings_open = True
            except ImportError:
                pass
                
            if not os.path.exists(lib_settings_file):
                self.mw.force_settings_open = True            
            self.mw.filter_controller.start_filter_worker()
        else:
            self.mw.filter_controller.request_filter_update()
        # WHY: Explicit Intent Tracking. Instead of guessing based on config states, 
        # we strictly check the physical existence of the configuration file or the UI intent to create a new one.
        if getattr(self.mw, 'force_settings_open', False):
            self.mw.force_settings_open = False
            # WHY: Use a persistent QTimer object attached to 'self' instead of a static singleShot. 
            # PySide6's aggressive Garbage Collector can sometimes destroy singleShot bound slots before they fire.
            logging.info("[STARTUP] Bare database detected. Queuing Settings window...")
            self._startup_timer = QTimer(self)
            self._startup_timer.setSingleShot(True)
            self._startup_timer.setInterval(800)
            self._startup_timer.timeout.connect(self.trigger_initial_settings)
            self._startup_timer.start()

        if not hasattr(self.mw, 'startup_sync_done'):
            self.mw.startup_sync_done = True
            self.startup_worker = StartupSyncWorker(build_scanner_config())
            self.startup_worker.finished.connect(self.on_startup_sync_finished)
            self.startup_worker.start()

    @Slot(bool)
    def on_startup_sync_finished(self, changes_made):
        if changes_made: self.refresh_data()

    def patch_memory_df(self, folder_name, new_data):
        """WHY: DRY Principle - Centralizes the Pandas memory patching logic to ensure type safety and prevent FutureWarnings."""
        for df_name in ['master_df', 'current_df']:
            if hasattr(self.mw, df_name):
                df = getattr(self.mw, df_name)
                idx = df.index[df['Folder_Name'] == folder_name].tolist()
                if idx:
                    for k, v in new_data.items():
                        if k in df.columns:
                            # WHY: Pre-cast columns to object to prevent Pandas from throwing FutureWarnings 
                            # when injecting strings into columns it previously inferred as pure int/float.
                            if df[k].dtype not in [bool, object]:
                                df[k] = df[k].astype(object)
                            df.at[idx[0], k] = bool(v) if df[k].dtype == bool else (str(v) if isinstance(v, bool) else v)

    def save_database(self):
        logging.info("Manual save requested.")
        db_path = get_db_path()
        if os.path.exists(db_path):
            backup_dir = "./backups"
            os.makedirs(backup_dir, exist_ok=True)
            backups = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".csv")]
            backups.sort(key=os.path.getctime)
            while len(backups) >= 10: os.remove(backups.pop(0))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_filename = os.path.basename(db_path)
            backup_file = os.path.join(backup_dir, f"{os.path.splitext(db_filename)[0]}_{timestamp}.csv")
            shutil.copy2(db_path, backup_file)
            logging.info(f"{'DB BACKUP':<15} : Backup created at {backup_file}")
        
        try:
            # WHY: Because master_df now safely drops excluded games for UI counter accuracy, 
            # we MUST route the manual save exclusively through LibraryManager to prevent permanently deleting them from the CSV.
            manager = LibraryManager(build_scanner_config())
            manager.load_db()
            manager.save_db()
            logging.info(f"{'DB SAVE':<15} : Database saved to {db_path} ({len(manager.games)} physical games).")
            QMessageBox.information(self.mw, "Save Complete", translator.tr("msg_save_success", db_path=db_path))
        except PermissionError:
             QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=db_path))
        except Exception as e:
            logging.error(f"Failed to save database: {e}")
            QMessageBox.critical(self.mw, "Error", f"Could not save the library: {e}")

    def refresh_data(self):
        # WHY: Automatically preserve the user's scroll position during mid-session refreshes 
        # (like Full Scans) as long as no explicit game anchor was requested.
        if not getattr(self.mw, 'pending_anchor_folder', None):
            self.mw.pending_anchor_folder = self.get_second_visible_folder()
            
        self.mw.settings_controller.save_settings()
        self.load_database_async()