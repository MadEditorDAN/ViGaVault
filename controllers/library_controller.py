import os
import json
import shutil
import logging
from datetime import datetime
import pandas as pd
from PySide6.QtCore import QObject, Slot, QByteArray, Qt, QPoint, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox, QApplication, QCheckBox

from backend.library import LibraryManager
from ViGaVault_utils import (get_db_path, get_library_settings_file, build_scanner_config, 
                             get_platform_config, apply_theme, translator, DEFAULT_DISPLAY_SETTINGS)
from ViGaVault_utils import get_image_path, get_video_path
from ViGaVault_workers import DbLoaderWorker, StartupSyncWorker
from dialogs import ConflictDialog

class LibraryController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    @Slot()
    def trigger_initial_settings(self):
        """WHY: Explicitly bound slot guarantees the PySide6 C++ engine retains the reference for the delayed timer."""
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
        
        self.mw.sidebar.chk_show_new.setEnabled(has_new)
        self.mw.sidebar.chk_show_review.setEnabled(has_review)
        self.mw.sidebar.btn_approve_review.setEnabled(has_review)
        
        # Uncheck instantly if there are no more results to prevent a blank UI
        if not has_new and self.mw.sidebar.chk_show_new.isChecked(): self.mw.sidebar.chk_show_new.setChecked(False)
        if not has_review and self.mw.sidebar.chk_show_review.isChecked(): self.mw.sidebar.chk_show_review.setChecked(False)

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

            self.save_settings()
            
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
                    "enable_galaxy_db": False, "download_images": True, "download_videos": False, "sort_desc": True, "sort_index": 0, "scan_new": False, "filter_states": {}, "filter_expansion": {}
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
        self.mw.sidebar.chk_show_new.blockSignals(True)
        self.mw.sidebar.chk_show_review.blockSignals(True)

        self.mw.sort_desc = lib_settings.get("sort_desc", True)
        self.mw.sidebar.combo_sort.setCurrentIndex(lib_settings.get("sort_index", 0))
        self.mw.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
        self.mw.sidebar.chk_show_new.setChecked(lib_settings.get("scan_new", False))
        self.mw.sidebar.update_sort_button(self.mw.sort_desc)

        self.mw.sidebar.combo_sort.blockSignals(False)
        self.mw.sidebar.chk_show_new.blockSignals(False)
        self.mw.sidebar.chk_show_review.blockSignals(False)
        self.update_status_checkboxes_state()

        self.update_library_info()
        
        # WHY: Generate the dynamic folder checkboxes strictly AFTER the specific library context 
        # is fully loaded. This guarantees the correct VGVDB.json rules are applied on boot and when switching libraries!
        self.refresh_scan_folders_ui()

        if self.mw.is_startup:
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
            df_to_save = self.mw.master_df.drop(columns=['temp_sort_date', 'temp_sort_title'], errors='ignore')
            df_to_save.to_csv(db_path, sep=';', index=False, encoding='utf-8')
            logging.info(f"{'DB SAVE':<15} : Database saved to {db_path} ({len(self.mw.master_df)} games).")
            QMessageBox.information(self.mw, "Save Complete", translator.tr("msg_save_success", db_path=db_path))
        except PermissionError:
             QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=db_path))
        except Exception as e:
            logging.error(f"Failed to save database: {e}")
            QMessageBox.critical(self.mw, "Error", f"Could not save the library: {e}")

    def approve_reviews(self):
        """WHY: Instantly converts all pending REVIEW games into OK status and synchronizes the UI."""
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        changes_made = False
        for folder, game in manager.games.items():
            if game.data.get('Status_Flag') == 'REVIEW':
                game.data['Status_Flag'] = 'OK'
                changes_made = True
                
        if changes_made:
            while True:
                try:
                    manager.save_db()
                    break
                except PermissionError:
                    reply = QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=get_db_path()), QMessageBox.Ok | QMessageBox.Cancel)
                    if reply == QMessageBox.Cancel: return

            if 'Status_Flag' in self.mw.master_df.columns:
                self.mw.master_df.loc[self.mw.master_df['Status_Flag'] == 'REVIEW', 'Status_Flag'] = 'OK'
            if 'Status_Flag' in self.mw.current_df.columns:
                self.mw.current_df.loc[self.mw.current_df['Status_Flag'] == 'REVIEW', 'Status_Flag'] = 'OK'

            self.update_status_checkboxes_state()
            self.mw.list_controller.update_visible_widgets()
            logging.info(f"{'Approved':<15} : All games pending review have been approved")

    def update_game_data(self, folder_name, new_data):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game_obj = manager.games.get(folder_name)
        if not game_obj: return

        old_title = game_obj.data.get('Clean_Title', '')
        old_date = game_obj.data.get('Original_Release_Date', '')

        for key, value in new_data.items(): game_obj.data[key] = value
        game_obj.update_media_filenames(old_title, old_date)
        
        while True:
            try:
                manager.save_db()
                break
            except PermissionError:
                reply = QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=get_db_path()), QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Cancel: return
        
        # WHY: Patch Memory and Trigger Targeted Update instead of Hard Reload
        # Extract the final dictionary from the Game object AFTER media renaming has occurred
        final_data = game_obj.to_dict()
        self.patch_memory_df(folder_name, final_data)
        self.update_status_checkboxes_state()
            
        self.mw.list_controller.update_single_card(folder_name, force_media_reload=True)
        self.save_settings()

    def execute_merge(self, folder_a, folder_b):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game_a = manager.games.get(folder_a)
        game_b = manager.games.get(folder_b)
        if not game_a or not game_b: return False
        
        old_title = game_a.data.get('Clean_Title', '')
        old_year = game_a.data.get('Original_Release_Date', '')
        conflicts = game_a.merge_with(game_b)
        rejected_media = []

        if conflicts:
            dlg = ConflictDialog(game_a.data, game_b.data, conflicts, self.mw)
            if dlg.exec():
                resolutions = dlg.get_resolutions()
                for field, val in resolutions.items(): game_a.data[field] = val
                if 'Image_Link' in conflicts:
                    rejected = conflicts['Image_Link']['B'] if resolutions['Image_Link'] == conflicts['Image_Link']['A'] else conflicts['Image_Link']['A']
                    if rejected and os.path.exists(rejected): rejected_media.append(rejected)
                if 'Path_Video' in conflicts:
                    rejected = conflicts['Path_Video']['B'] if resolutions['Path_Video'] == conflicts['Path_Video']['A'] else conflicts['Path_Video']['A']
                    if rejected and os.path.exists(rejected): rejected_media.append(rejected)
            else: return False

        del manager.games[folder_b]
        game_a.update_media_filenames(old_title, old_year)
        
        # WHY: A manual merge represents deliberate user curation. 
        # We automatically lock the resulting game to protect these curated changes from future API scans.
        game_a.data['Status_Flag'] = 'LOCKED'
        
        for f in rejected_media:
            try: os.remove(f)
            except: pass
                
        manager.save_db()
        
        # WHY: Soft-refresh logic (Memory Patch + Visually deleting the sacrificed card)
        new_data_a = game_a.to_dict()
        self.patch_memory_df(folder_a, new_data_a)
            
        self.mw.master_df = self.mw.master_df[self.mw.master_df['Folder_Name'] != folder_b]
        self.mw.current_df = self.mw.current_df[self.mw.current_df['Folder_Name'] != folder_b]
        self.update_status_checkboxes_state()

        self.mw.list_controller.update_single_card(folder_a, force_media_reload=True)
        self.mw.list_controller.remove_single_card(folder_b)
        self.save_settings()
        return True

    def update_game_flags(self, folder_name, flags_dict):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game = manager.games.get(folder_name)
        if game:
            for k, v in flags_dict.items(): game.data[k] = v
            manager.save_db()
            self.patch_memory_df(folder_name, flags_dict)

    def delete_game(self, folder_name):
        """
        WHY: Single Responsibility Principle - Handles the complete removal of a game from 
        the database, the physical disk (media), and the live visual layout.
        """
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        
        game_obj = manager.games.get(folder_name)
        if game_obj:
            img_name = game_obj.data.get('Image_Link', '')
            vid_name = game_obj.data.get('Path_Video', '')
            
            if img_name:
                try: os.remove(os.path.join(get_image_path(), os.path.basename(img_name)))
                except: pass
            if vid_name:
                try: os.remove(os.path.join(get_video_path(), os.path.basename(vid_name)))
                except: pass
                
            del manager.games[folder_name]
            manager.save_db()
            
        # WHY: Targeted Update - Erase from Pandas in-memory and dynamically update visual list.
        self.mw.master_df = self.mw.master_df[self.mw.master_df['Folder_Name'] != folder_name]
        self.mw.current_df = self.mw.current_df[self.mw.current_df['Folder_Name'] != folder_name]
        self.mw.list_controller.remove_single_card(folder_name)
        self.update_status_checkboxes_state()
        self.save_settings()
        logging.info(f"{'Deleted':<15} : {folder_name}")

    def batch_delete_metadata(self, field, items_to_delete):
        """
        WHY: Performs a safe string-based batch deletion of metadata tags across the entire DB.
        Updates memory DataFrames directly and triggers a targeted UI refresh.
        """
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        
        items_set = set(i.lower() for i in items_to_delete)
        changes_made = False
        
        for folder, game in manager.games.items():
            val = str(game.data.get(field, ''))
            if val:
                parts = [p.strip() for p in val.split(',')]
                new_parts = [p for p in parts if p.lower() not in items_set]
                if len(parts) != len(new_parts):
                    game.data[field] = ", ".join(new_parts)
                    changes_made = True
                    
        if changes_made:
            manager.save_db()
            
            # WHY: Targeted Update - Patch Pandas memory to reflect deletions without reloading from disk
            def remove_items(val):
                if not val: return val
                parts = [p.strip() for p in str(val).split(',')]
                new_parts = [p for p in parts if p.lower() not in items_set]
                return ", ".join(new_parts)
            
            if field in self.mw.master_df.columns:
                self.mw.master_df[field] = self.mw.master_df[field].apply(remove_items)
            if field in self.mw.current_df.columns:
                self.mw.current_df[field] = self.mw.current_df[field].apply(remove_items)
                
            # WHY: Smart Refresh - Update visible cards instantly
            self.mw.list_controller.update_visible_widgets()
            
            # WHY: Rebuild Sidebar Filters so deleted items physically disappear from the checkboxes
            self.save_settings()
            self.mw.library_controller.load_settings()

    def save_settings(self):
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass

        global_settings.update({"geometry": self.mw.saveGeometry().toBase64().data().decode()})
        
        # WHY: Extract the precise pixel width of both zones inside the QSplitter to persist user layout preference.
        global_settings.update({"splitter_sizes": self.mw.splitter.sizes()})
        
        # WHY: Targeted Cleanup - Scrub local library data out of the global settings file to fix legacy data bleed.
        local_keys = ["sort_desc", "sort_index", "search_text", "anchor_folder", "scan_new", "filter_states", "filter_expansion", "sidebar_chk_galaxy", "sidebar_chk_gog_web", "sidebar_chk_epic", "sidebar_chk_local", "sidebar_chk_folders", "platform_map", "ignored_prefixes", "root_path", "local_scan_config", "enable_galaxy_db", "galaxy_db_path", "download_images", "download_videos", "image_path", "video_path"]
        for k in local_keys: global_settings.pop(k, None)
        
        try:
            with open("settings.json", "w", encoding='utf-8') as f:
                json.dump(global_settings, f, indent=4)
        except: pass

        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
             try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
             except: pass

        # WHY: Targeted Cleanup - Scrub global OS data out of the local library settings file.
        global_keys = ["geometry", "theme", "language", "card_image_size", "card_button_size", "card_text_size", "db_path", "splitter_sizes"]
        for k in global_keys: lib_settings.pop(k, None)

        filter_states = {}
        if hasattr(self.mw.filter_controller, 'dynamic_filters'):
            for col, checkboxes in self.mw.filter_controller.dynamic_filters.items():
                if checkboxes and not all(chk.isChecked() for chk in checkboxes):
                    filter_states[col] = [chk.text() for chk in checkboxes if chk.isChecked()]

        saved_expansion = {}
        layout = self.mw.sidebar.filters_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            # WHY: Use duck-typing instead of importing modules during application closeEvent teardowns.
            if item.widget() and hasattr(item.widget(), 'toggle_btn') and hasattr(item.widget(), 'title'):
                group = item.widget()
                saved_expansion[group.title] = group.toggle_btn.isChecked()

        checked_folders = [f for f, chk in self.mw.sidebar.chk_scan_folders.items() if chk.isChecked()]

        lib_settings.update({
            "sort_desc": self.mw.sort_desc,
            "sort_index": self.mw.sidebar.combo_sort.currentIndex(),
            "search_text": self.mw.sidebar.search_bar.text(),
            "anchor_folder": self.get_second_visible_folder(),
            "scan_new": self.mw.sidebar.chk_show_new.isChecked(),
            "filter_states": filter_states,
            "filter_expansion": saved_expansion,
            # WHY: Reverted to explicit key mapping to match the original GOG logic exactly. 
            # Checkbox states are securely batched here and written to VGVDB.json on application close.
            "sidebar_chk_galaxy": self.mw.sidebar.chk_scan_galaxy.isChecked(),
            "sidebar_chk_gog_web": self.mw.sidebar.chk_scan_gog_web.isChecked(),
            "sidebar_chk_epic": self.mw.sidebar.chk_scan_epic.isChecked(),
            "sidebar_chk_local": self.mw.sidebar.chk_scan_local.isChecked(),
            "sidebar_chk_folders": checked_folders
        })

        if "platform_map" not in lib_settings:
             pm, ip = get_platform_config()
             lib_settings["platform_map"] = pm
             lib_settings["ignored_prefixes"] = ip

        try:
            with open(lib_settings_file, "w", encoding='utf-8') as f:
                json.dump(lib_settings, f, indent=4)
        except: pass

    def load_settings(self):
        global_settings = {}
        try:
            with open("settings.json", "r", encoding='utf-8') as f:
                global_settings = json.load(f)
        except: pass

        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass

        try:
            if "geometry" in global_settings:
                # WHY: The JSON stores a base64 string. We must decode it back to a binary QByteArray for Qt.
                self.mw.restoreGeometry(QByteArray.fromBase64(global_settings["geometry"].encode('utf-8')))
            if "splitter_sizes" in global_settings:
                # WHY: Restore the internal layout boundary before generating the visible lists.
                self.mw.splitter.setSizes(global_settings["splitter_sizes"])
            self.mw.sort_desc = lib_settings.get("sort_desc", True)
            self.mw.sidebar.update_sort_button(self.mw.sort_desc)
            
            self.mw.display_settings['image'] = global_settings.get("card_image_size", DEFAULT_DISPLAY_SETTINGS['image'])
            self.mw.display_settings['button'] = global_settings.get("card_button_size", DEFAULT_DISPLAY_SETTINGS['button'])
            self.mw.display_settings['text'] = global_settings.get("card_text_size", DEFAULT_DISPLAY_SETTINGS['text'])
            
            self.mw.sidebar.combo_sort.blockSignals(True)
            idx = lib_settings.get("sort_index", 0)
            if 0 <= idx < self.mw.sidebar.combo_sort.count(): self.mw.sidebar.combo_sort.setCurrentIndex(idx)
            self.mw.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
            
            self.mw.sidebar.chk_show_new.blockSignals(True)
            if hasattr(self.mw.filter_controller, 'dynamic_filters'):
                for checkboxes in self.mw.filter_controller.dynamic_filters.values():
                    for chk in checkboxes: chk.blockSignals(True)

            self.mw.sidebar.chk_show_new.setChecked(lib_settings.get("scan_new", False))

            filter_states = lib_settings.get("filter_states")
            if hasattr(self.mw.filter_controller, 'dynamic_filters'):
                if filter_states is not None:
                    for col, checkboxes in self.mw.filter_controller.dynamic_filters.items():
                        if col in filter_states:
                            saved_checked = filter_states.get(col, [])
                            for chk in checkboxes: chk.setChecked(chk.text() in saved_checked)
                        if hasattr(self.mw.filter_controller, 'update_filter_buttons'):
                            self.mw.filter_controller.update_filter_buttons(col)
                elif "checked_platforms" in lib_settings:
                    for chk in self.mw.filter_controller.dynamic_filters.get("Platforms", []):
                        chk.setChecked(chk.text() in lib_settings["checked_platforms"])
                    if hasattr(self.mw.filter_controller, 'update_filter_buttons'):
                        self.mw.filter_controller.update_filter_buttons("Platforms")
            
            self.mw.sidebar.combo_sort.blockSignals(False)
            if hasattr(self.mw.filter_controller, 'dynamic_filters'):
                for checkboxes in self.mw.filter_controller.dynamic_filters.values():
                    for chk in checkboxes: chk.blockSignals(False)
            
            self.mw.sidebar.chk_show_new.blockSignals(False)
            
            enable_galaxy = lib_settings.get("enable_galaxy_db", False)
            enable_local = lib_settings.get("local_scan_config", {}).get("enable_local_scan", False)
            
            # WHY: Sync the scan panel's quick-toggle checkboxes with the global configuration.
            # If a feature is disabled in the main settings, it is correctly greyed out and forced off here.
            self.mw.sidebar.chk_scan_galaxy.setEnabled(enable_galaxy)
            if not enable_galaxy: self.mw.sidebar.chk_scan_galaxy.setChecked(False)
            else: self.mw.sidebar.chk_scan_galaxy.setChecked(lib_settings.get("sidebar_chk_galaxy", False))

            # WHY: Strict Token Check - Grey out the GOG scan checkbox if the user has no valid login session.
            try:
                from backend.gog.login_gog import is_gog_connected
                gog_enabled = is_gog_connected()
            except ImportError: gog_enabled = False
            self.mw.gog_connected_cache = gog_enabled
            
            self.mw.sidebar.chk_scan_gog_web.setEnabled(gog_enabled)
            if not gog_enabled: self.mw.sidebar.chk_scan_gog_web.setChecked(False)
            else: self.mw.sidebar.chk_scan_gog_web.setChecked(lib_settings.get("sidebar_chk_gog_web", False))

            
            self.mw.sidebar.chk_scan_local.setEnabled(enable_local)
            if not enable_local: self.mw.sidebar.chk_scan_local.setChecked(False)
            else: self.mw.sidebar.chk_scan_local.setChecked(lib_settings.get("sidebar_chk_local", False))
            
            # WHY: Update the scan button state based on the loaded checkbox configuration
            self.mw.sidebar.update_scan_button_state()
            return lib_settings.get("anchor_folder")
        except Exception as e:
            print(f"Error loading settings: {e}")
            return None

    def refresh_scan_folders_ui(self):
        """WHY: Single Responsibility - Dynamically regenerates the UI checkboxes representing the Local Folder Rules."""
        # WHY: Rely on the unified config builder to ensure settings are correctly resolved, even if the user hasn't explicitly saved them yet.
        config = build_scanner_config()
        folder_rules = config.get("local_scan_config", {}).get("folder_rules", {})
        
        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass
            
        was_saved = "sidebar_chk_folders" in lib_settings
        saved_checked = lib_settings.get("sidebar_chk_folders", [])
        
        for chk in self.mw.sidebar.chk_scan_folders.values():
            self.mw.sidebar.layout_scan_local.removeWidget(chk)
            chk.deleteLater()
        self.mw.sidebar.chk_scan_folders.clear()
        
        row, col = 1, 0
        master_checked = self.mw.sidebar.chk_scan_local.isChecked()
        for folder in sorted(folder_rules.keys()):
            rule = folder_rules[folder]
            # WHY: Only display the checkbox if the folder is actually designated to be scanned in the Advanced settings.
            if not rule.get("scan", False):
                continue
                
            chk = QCheckBox(folder)
            chk.setChecked(folder in saved_checked if was_saved else True)
            chk.setEnabled(master_checked)
            self.mw.sidebar.layout_scan_local.addWidget(chk, row, col)
            self.mw.sidebar.chk_scan_folders[folder] = chk
            col += 1
            if col > 1:
                col = 0
                row += 1
            
        # WHY: Push the grid items to the top to prevent them from floating vertically in the center.
        target_row = row if col == 0 else row + 1
        self.mw.sidebar.layout_scan_local.setRowStretch(target_row, 1)

    def refresh_data(self):
        # WHY: Automatically preserve the user's scroll position during mid-session refreshes 
        # (like Full Scans) as long as no explicit game anchor was requested.
        if not getattr(self.mw, 'pending_anchor_folder', None):
            self.mw.pending_anchor_folder = self.get_second_visible_folder()
            
        self.save_settings()
        self.load_database_async()

    def reload_global_settings(self):
        global_settings = {}
        try:
            with open("settings.json", "r", encoding='utf-8') as f:
                global_settings = json.load(f)
        except: pass
        
        apply_theme(QApplication.instance(), global_settings.get("theme", "System"))
        
        if translator.language != global_settings.get("language", "English"):
            translator.load_language(global_settings.get("language", "English"))
            self.retranslate_ui()
            
        # WHY: Check Date Format Migration. If the user changed their regional date format,
        # we must instantly migrate the physical CSV database to prevent mismatched sorting loops.
        new_format_str = global_settings.get("date_format", "DD/MM/YYYY")
        old_format_str = getattr(self.mw, 'date_format_str', "DD/MM/YYYY")
        
        if new_format_str != old_format_str:
            from ViGaVault_utils import get_date_format_mapping
            old_format = get_date_format_mapping().get(old_format_str, "%d/%m/%Y")
            new_format = get_date_format_mapping().get(new_format_str, "%d/%m/%Y")
            
            manager = LibraryManager(build_scanner_config())
            manager.load_db()
            changes_made = False
            
            for folder, game in manager.games.items():
                old_date = game.data.get('Original_Release_Date', '')
                if old_date:
                    try:
                        # Strictly convert only if it perfectly matches the old format
                        dt = datetime.strptime(old_date, old_format)
                        game.data['Original_Release_Date'] = dt.strftime(new_format)
                        changes_made = True
                    except Exception:
                        pass # Ignore if it's just a year like "2020" or completely unparseable
                        
            if changes_made:
                manager.save_db()
                logging.info(f"Successfully migrated database dates from {old_format_str} to {new_format_str}.")
            
            self.mw.date_format_str = new_format_str
            self.refresh_data()
            
        self.mw.sidebar.refresh_styles()
        
        # WHY: Force re-evaluation of CSS palette variables inside custom widgets when the application theme switches dynamically.
        self.mw.list_controller.apply_display_settings(self.mw.display_settings)

    def retranslate_ui(self):
        self.mw.setWindowTitle(translator.tr("app_title"))
        self.mw.menu_controller.create_menu_bar()
        self.mw.sidebar.retranslate_ui()