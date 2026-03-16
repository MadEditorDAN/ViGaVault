import os
import json
import shutil
import logging
from datetime import datetime
import pandas as pd
from PySide6.QtCore import QObject, Slot, QByteArray
from PySide6.QtWidgets import QFileDialog, QMessageBox, QApplication

from backend.library import LibraryManager
from ViGaVault_utils import (get_db_path, get_library_settings_file, build_scanner_config, 
                             get_platform_config, apply_theme, translator)
from ViGaVault_workers import DbLoaderWorker, StartupSyncWorker
from dialogs import ConflictDialog

class LibraryController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    def update_library_info(self):
        lib_name = os.path.basename(get_db_path()).replace('.csv', '')
        self.mw.setWindowTitle(f"ViGaVault Library - [{lib_name}]")
        self.mw.sidebar.lbl_lib_name.setText(f"{lib_name}")

    def select_library(self):
        filePath, _ = QFileDialog.getSaveFileName(self.mw, "Switch or Create Library", "", "ViGaVault Library (*.csv)")
        if filePath:
            self.save_settings()
            if not filePath.lower().endswith('.csv'): filePath += '.csv'
            is_new_file = not os.path.exists(filePath)

            try:
                settings = {}
                if os.path.exists("settings.json"):
                    with open("settings.json", "r", encoding='utf-8') as f:
                        settings = json.load(f)
                settings['db_path'] = filePath
                with open("settings.json", "w", encoding='utf-8') as f:
                    json.dump(settings, f, indent=4)
                
                if is_new_file:
                    expected_columns = [
                        'Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 
                        'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 
                        'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link',
                        'game_ID', 'Is_Local', 'Has_Image', 'Has_Video'
                    ] + [f'platform_ID_{i:02d}' for i in range(1, 51)]
                    pd.DataFrame(columns=expected_columns).to_csv(filePath, sep=';', index=False, encoding='utf-8')
                    
                    lib_settings_path = os.path.splitext(filePath)[0] + ".json"
                    default_lib_settings = {
                        "root_path": r"\\madhdd02\Software\GAMES",
                        "local_scan_config": {"ignore_hidden": True, "scan_mode": "advanced", "global_type": "Genre", "folder_rules": {}},
                        "gog_db_path": os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db'),
                        "enable_gog_db": True, "sort_desc": True, "sort_index": 1, "scan_new": False, "filter_states": {}, "filter_expansion": {}
                    }
                    with open(lib_settings_path, "w", encoding='utf-8') as f:
                        json.dump(default_lib_settings, f, indent=4)

                self.reload_ui_for_new_library()
            except Exception as e:
                QMessageBox.critical(self.mw, "Error", f"Could not switch library: {e}")

    def reload_ui_for_new_library(self):
        self.mw.background_loader.stop()
        self.mw.filter_timer.stop()
        self.mw.list_widget.clear()
        self.mw.sidebar.search_bar.clear()
        self.load_database_async()

    def load_database_async(self):
        self.mw.list_widget.clear()
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

        # WHY: Ensure scroll position is seamlessly recovered when switching libraries mid-session.
        if not hasattr(self.mw, 'pending_scroll') and not getattr(self.mw, 'pending_anchor_folder', None):
            saved_scroll = lib_settings.get("scroll_value", 0)
            if saved_scroll > 0:
                self.mw.pending_scroll = saved_scroll

        saved_filters = lib_settings.get("filter_states")
        saved_expansion = lib_settings.get("filter_expansion")

        self.mw.filter_controller.populate_dynamic_filters(saved_filters, saved_expansion)

        self.mw.sidebar.combo_sort.blockSignals(True)
        self.mw.sidebar.chk_show_new.blockSignals(True)

        self.mw.sort_desc = lib_settings.get("sort_desc", True)
        self.mw.sidebar.combo_sort.setCurrentIndex(lib_settings.get("sort_index", 1))
        self.mw.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
        self.mw.sidebar.chk_show_new.setChecked(lib_settings.get("scan_new", False))
        self.mw.sidebar.update_sort_button(self.mw.sort_desc)

        self.mw.sidebar.combo_sort.blockSignals(False)
        self.mw.sidebar.chk_show_new.blockSignals(False)

        self.update_library_info()

        if self.mw.is_startup:
            self.mw.filter_controller.start_filter_worker()
        else:
            self.mw.filter_controller.request_filter_update()
        
        if not hasattr(self.mw, 'startup_sync_done'):
            self.mw.startup_sync_done = True
            self.startup_worker = StartupSyncWorker(build_scanner_config())
            self.startup_worker.finished.connect(self.on_startup_sync_finished)
            self.startup_worker.start()

    @Slot(bool)
    def on_startup_sync_finished(self, changes_made):
        if changes_made: self.refresh_data()

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
            logging.info(f"    [DB BACKUP] Backup created at {backup_file}")
        
        try:
            df_to_save = self.mw.master_df.drop(columns=['temp_sort_date', 'temp_sort_title'], errors='ignore')
            df_to_save.to_csv(db_path, sep=';', index=False, encoding='utf-8')
            logging.info(f"    [DB SAVE] Database saved to {db_path} ({len(self.mw.master_df)} games).")
            QMessageBox.information(self.mw, "Save Complete", translator.tr("msg_save_success", db_path=db_path))
        except PermissionError:
             QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=db_path))
        except Exception as e:
            logging.error(f"Failed to save database: {e}")
            QMessageBox.critical(self.mw, "Error", f"Could not save the library: {e}")

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
        
        self.mw.pending_anchor_folder = folder_name
        self.refresh_data()

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
        for f in rejected_media:
            try: os.remove(f)
            except: pass
                
        manager.save_db()
        self.mw.pending_anchor_folder = folder_a
        self.refresh_data()
        return True

    def update_game_flags(self, folder_name, flags_dict):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game = manager.games.get(folder_name)
        if game:
            for k, v in flags_dict.items(): game.data[k] = v
            manager.save_db()
            idx = self.mw.master_df.index[self.mw.master_df['Folder_Name'] == folder_name].tolist()
            if idx:
                for k, v in flags_dict.items(): self.mw.master_df.at[idx[0], k] = v

    def save_settings(self):
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass

        global_settings.update({"geometry": self.mw.saveGeometry().toBase64().data().decode()})
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
        elif os.path.exists("settings.json"):
             lib_settings.update(global_settings)

        filter_states = {}
        if hasattr(self.mw.filter_controller, 'dynamic_filters'):
            for col, checkboxes in self.mw.filter_controller.dynamic_filters.items():
                if checkboxes and not all(chk.isChecked() for chk in checkboxes):
                    filter_states[col] = [chk.text() for chk in checkboxes if chk.isChecked()]

        saved_expansion = {}
        layout = self.mw.sidebar.filters_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            from ViGaVault_widgets import CollapsibleFilterGroup
            if item.widget() and isinstance(item.widget(), CollapsibleFilterGroup):
                group = item.widget()
                saved_expansion[group.title] = group.toggle_btn.isChecked()

        lib_settings.update({
            "sort_desc": self.mw.sort_desc,
            "sort_index": self.mw.sidebar.combo_sort.currentIndex(),
            "search_text": self.mw.sidebar.search_bar.text(),
            "scroll_value": self.mw.list_widget.verticalScrollBar().value(),
            "scan_new": self.mw.sidebar.chk_show_new.isChecked(),
            "filter_states": filter_states,
            "filter_expansion": saved_expansion
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
        else:
            lib_settings = global_settings

        try:
            if "geometry" in global_settings:
                # WHY: The JSON stores a base64 string. We must decode it back to a binary QByteArray for Qt.
                self.mw.restoreGeometry(QByteArray.fromBase64(global_settings["geometry"].encode('utf-8')))
            self.mw.sort_desc = lib_settings.get("sort_desc", True)
            self.mw.sidebar.update_sort_button(self.mw.sort_desc)
            
            self.mw.display_settings['image'] = global_settings.get("card_image_size", 200)
            self.mw.display_settings['button'] = global_settings.get("card_button_size", 45)
            self.mw.display_settings['text'] = global_settings.get("card_text_size", 22)
            
            self.mw.sidebar.combo_sort.blockSignals(True)
            idx = lib_settings.get("sort_index", 1)
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
            
            # WHY: Sync the scan panel's quick-toggle checkboxes with the global configuration.
            # If a feature is disabled in the main settings, it is correctly greyed out and forced off here.
            enable_gog = lib_settings.get("enable_gog_db", True)
            enable_local = lib_settings.get("local_scan_config", {}).get("enable_local_scan", True)
            self.mw.sidebar.chk_scan_gog.setEnabled(enable_gog)
            if not enable_gog: self.mw.sidebar.chk_scan_gog.setChecked(False)
            self.mw.sidebar.chk_scan_local.setEnabled(enable_local)
            if not enable_local: self.mw.sidebar.chk_scan_local.setChecked(False)
            
            return lib_settings.get("scroll_value", 0)
        except Exception as e:
            print(f"Error loading settings: {e}")
            return 0

    def refresh_data(self):
        # WHY: Automatically preserve the user's scroll position during mid-session refreshes 
        # (like Full Scans) as long as no explicit game anchor was requested.
        if not getattr(self.mw, 'pending_anchor_folder', None):
            self.mw.pending_scroll = self.mw.list_widget.verticalScrollBar().value()
            
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
            
        self.mw.sidebar.refresh_styles()

    def retranslate_ui(self):
        self.mw.setWindowTitle(translator.tr("app_title"))
        self.mw.menu_controller.create_menu_bar()
        self.mw.sidebar.retranslate_ui()