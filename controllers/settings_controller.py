# WHY: Single Responsibility Principle - Exclusively handles loading/saving application 
# configurations (JSON), window geometry, themes, languages, and UI sidebar generation.
import os
import shutil
import logging
from datetime import datetime
from PySide6.QtCore import QObject, QByteArray
from PySide6.QtWidgets import QApplication, QCheckBox

from backend.library import LibraryManager
from ViGaVault_utils import (get_library_settings_file, build_scanner_config, get_platform_config, 
                             apply_theme, translator, DEFAULT_DISPLAY_SETTINGS, save_encrypted_json, load_encrypted_json, BASE_DIR)

class SettingsController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    def get_user_settings(self):
        # WHY: Use the absolute BASE_DIR to perfectly anchor the settings file regardless of Current Working Directory shifts.
        global_settings = load_encrypted_json(os.path.join(BASE_DIR, "settings.bin"))
        lib_settings = load_encrypted_json(get_library_settings_file())
        return global_settings, lib_settings

    def save_user_settings(self, display_state, data_state, old_image_path=None, move_images=False):
        global_settings, lib_settings = self.get_user_settings()
        
        global_settings.update(display_state)
        local_keys = ["sortDesc", "sortIndex", "searchText", "anchorFolder", "viewNew", "viewDlc", "viewReview", "filterStates", "filterExpansion", "scanGalaxy", "scanGog", "scanEpic", "scanSteam", "scanAmazon", "scanLocal", "scanFolders", "platformMap", "ignoredPrefixes", "rootPath", "localScanConfig", "enableGalaxyDb", "galaxyDbPath", "downloadImages", "downloadVideos", "imagePath", "videoPath"]
        for k in local_keys: global_settings.pop(k, None)
        
        save_encrypted_json(os.path.join(BASE_DIR, "settings.bin"), global_settings)

        global_keys = ["geometry", "theme", "language", "cardImageSize", "cardButtonSize", "cardTextSize", "libraryName", "splitterSizes", "dateFormat"]
        for k in global_keys: lib_settings.pop(k, None)

        lib_settings["rootPath"] = data_state["root_path"]
        lib_settings["localScanConfig"] = data_state["local_scan_config"]
        lib_settings["enableGalaxyDb"] = data_state["enable_galaxy_db"]
        lib_settings["galaxyDbPath"] = data_state["galaxy_db_path"]
        lib_settings["downloadImages"] = data_state["download_images"]
        lib_settings["imagePath"] = data_state["image_path"]
        
        new_image_path = data_state["image_path"]
        if move_images and old_image_path and os.path.exists(old_image_path):
            try:
                os.makedirs(new_image_path, exist_ok=True)
                files = [f for f in os.listdir(old_image_path) if os.path.isfile(os.path.join(old_image_path, f))]
                for f in files:
                    src = os.path.join(old_image_path, f)
                    dst = os.path.join(new_image_path, f)
                    shutil.move(src, dst)
            except Exception as e: logging.error(f"Failed to move media files: {e}")
        
        save_encrypted_json(get_library_settings_file(), lib_settings)

        if hasattr(self.mw, 'display_settings'):
            self.mw.display_settings['image'] = display_state['cardImageSize']
            self.mw.display_settings['button'] = display_state['cardButtonSize']
            self.mw.display_settings['text'] = display_state['cardTextSize']

    def save_settings(self):
        global_settings = load_encrypted_json(os.path.join(BASE_DIR, "settings.bin"))

        try:
            global_settings.update({"geometry": self.mw.saveGeometry().toBase64().data().decode()})
            global_settings.update({"splitterSizes": self.mw.splitter.sizes()})
        except RuntimeError:
            # WHY: Safely ignore C++ teardown errors if save_settings is fired during application closure.
            pass
        
        local_keys = ["sortDesc", "sortIndex", "searchText", "anchorFolder", "viewNew", "viewDlc", "viewReview", "filterStates", "filterExpansion", "scanGalaxy", "scanGog", "scanEpic", "scanSteam", "scanAmazon", "scanLocal", "scanFolders", "platformMap", "ignoredPrefixes", "rootPath", "localScanConfig", "enableGalaxyDb", "galaxyDbPath", "downloadImages", "downloadVideos", "imagePath", "videoPath"]
        for k in local_keys: global_settings.pop(k, None)
        
        save_encrypted_json(os.path.join(BASE_DIR, "settings.bin"), global_settings)

        lib_settings_file = get_library_settings_file()
        lib_settings = load_encrypted_json(lib_settings_file)

        global_keys = ["geometry", "theme", "language", "cardImageSize", "cardButtonSize", "cardTextSize", "libraryName", "splitterSizes", "dateFormat"]
        for k in global_keys: lib_settings.pop(k, None)

        # WHY: Reverted to the unified update block. The previous fix was fundamentally flawed. 
        try:
            filter_states = {}
            if hasattr(self.mw.filter_controller, 'dynamic_filters'):
                for col, item in self.mw.filter_controller.dynamic_filters.items():
                    if col == "Year_Folder":
                        from PySide6.QtWidgets import QLineEdit
                        if isinstance(item, QLineEdit):
                            txt = item.text().strip()
                            if txt:
                                filter_states[col] = [txt]
                    else:
                        if item and not all(chk.isChecked() for chk in item):
                            filter_states[col] = [chk.text() for chk in item if chk.isChecked()]

            saved_expansion = {}
            layout = self.mw.sidebar.filters_layout
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() and hasattr(item.widget(), 'toggle_btn') and hasattr(item.widget(), 'title'):
                    group = item.widget()
                    saved_expansion[group.title] = group.toggle_btn.isChecked()

            checked_folders = [f for f, chk in self.mw.sidebar.chk_scan_folders.items() if chk.isChecked()]

            lib_settings.update({
                "sortDesc": self.mw.sort_desc,
                "sortIndex": self.mw.sidebar.combo_sort.currentIndex(),
                "searchText": self.mw.sidebar.search_bar.text(),
                "anchorFolder": self.mw.library_controller.get_second_visible_folder(),
                "viewNew": self.mw.sidebar.btn_toggle_new.isChecked(),
                "viewDlc": self.mw.sidebar.btn_toggle_dlc.isChecked(),
                "viewReview": self.mw.sidebar.btn_toggle_review.isChecked(),
                "filterStates": filter_states,
                "filterExpansion": saved_expansion,
                "scanGalaxy": self.mw.sidebar.chk_scan_galaxy.isChecked(),
                "scanGog": self.mw.sidebar.chk_scan_gog_web.isChecked(),
                "scanEpic": self.mw.sidebar.chk_scan_epic.isChecked(),
                "scanSteam": self.mw.sidebar.chk_scan_steam.isChecked(),
                "scanAmazon": self.mw.sidebar.chk_scan_amazon.isChecked(),
                "scanLocal": self.mw.sidebar.chk_scan_local.isChecked(),
                "scanFolders": checked_folders,
                "downloadImages": self.mw.sidebar.chk_scan_dl_images.isChecked()
            })
        except RuntimeError:
            pass

        if "platformMap" not in lib_settings:
             pm, ip = get_platform_config()
             lib_settings["platformMap"] = pm
             lib_settings["ignoredPrefixes"] = ip

        save_encrypted_json(lib_settings_file, lib_settings)

    def load_settings(self):
        global_settings, lib_settings = self.get_user_settings()

        try:
            if "geometry" in global_settings:
                self.mw.restoreGeometry(QByteArray.fromBase64(global_settings["geometry"].encode('utf-8')))
            if "splitterSizes" in global_settings:
                self.mw.splitter.setSizes(global_settings["splitterSizes"])
            self.mw.sort_desc = lib_settings.get("sortDesc", True)
            self.mw.sidebar.update_sort_button(self.mw.sort_desc)
            
            self.mw.display_settings['image'] = global_settings.get("cardImageSize", DEFAULT_DISPLAY_SETTINGS['image'])
            self.mw.display_settings['button'] = global_settings.get("cardButtonSize", DEFAULT_DISPLAY_SETTINGS['button'])
            self.mw.display_settings['text'] = global_settings.get("cardTextSize", DEFAULT_DISPLAY_SETTINGS['text'])
            
            # WHY: Suppress Signals - Prevent programmatic UI population from instantly triggering save_settings() 
            # which previously wiped the actual user settings with a blank layout during application boot!
            self.mw.sidebar.chk_scan_galaxy.blockSignals(True)
            self.mw.sidebar.chk_scan_galaxy.setChecked(lib_settings.get("scanGalaxy", False))
            self.mw.sidebar.chk_scan_galaxy.blockSignals(False)
            
            self.mw.sidebar.chk_scan_local.blockSignals(True)
            self.mw.sidebar.chk_scan_local.setChecked(lib_settings.get("scanLocal", False))
            self.mw.sidebar.chk_scan_local.blockSignals(False)
            
            self.mw.sidebar.chk_scan_dl_images.blockSignals(True)
            self.mw.sidebar.chk_scan_dl_images.setChecked(lib_settings.get("downloadImages", True))
            self.mw.sidebar.chk_scan_dl_images.blockSignals(False)
            
            # WHY: Check live connection status to physically forbid the user from toggling scanners for disconnected platforms.
            try:
                from backend.gog.login_gog import is_gog_connected
                gog_enabled = is_gog_connected()
            except ImportError: gog_enabled = False
            self.mw.gog_connected_cache = gog_enabled
            self.mw.sidebar.chk_scan_gog_web.setEnabled(gog_enabled)
            self.mw.sidebar.chk_scan_gog_web.blockSignals(True)
            if not gog_enabled: self.mw.sidebar.chk_scan_gog_web.setChecked(False)
            else: self.mw.sidebar.chk_scan_gog_web.setChecked(lib_settings.get("scanGog", False))
            self.mw.sidebar.chk_scan_gog_web.blockSignals(False)

            try:
                from backend.epic.login_epic import is_epic_connected
                epic_enabled = is_epic_connected()
            except ImportError: epic_enabled = False
            self.mw.epic_connected_cache = epic_enabled
            self.mw.sidebar.chk_scan_epic.setEnabled(epic_enabled)
            self.mw.sidebar.chk_scan_epic.blockSignals(True)
            if not epic_enabled: self.mw.sidebar.chk_scan_epic.setChecked(False)
            else: self.mw.sidebar.chk_scan_epic.setChecked(lib_settings.get("scanEpic", False))
            self.mw.sidebar.chk_scan_epic.blockSignals(False)

            try:
                from backend.steam.login_steam import is_steam_connected
                steam_enabled = is_steam_connected()
            except ImportError: steam_enabled = False
            self.mw.steam_connected_cache = steam_enabled

            try:
                from backend.amazon.login_amazon import is_amazon_connected
                amazon_enabled = is_amazon_connected()
            except ImportError: amazon_enabled = False
            self.mw.amazon_connected_cache = amazon_enabled
            
            # WHY: Cache IGDB status immediately on load so the UI logic doesn't constantly ping the disk.
            try:
                from backend.igdb.login_igdb import is_igdb_connected
                self.mw.igdb_connected_cache = is_igdb_connected()
            except ImportError: 
                self.mw.igdb_connected_cache = False
        
            if hasattr(self.mw.sidebar, 'chk_scan_steam'):
                self.mw.sidebar.chk_scan_steam.setEnabled(steam_enabled)
                self.mw.sidebar.chk_scan_steam.blockSignals(True)
                if not steam_enabled: self.mw.sidebar.chk_scan_steam.setChecked(False)
                else: self.mw.sidebar.chk_scan_steam.setChecked(lib_settings.get("scanSteam", False))
                self.mw.sidebar.chk_scan_steam.blockSignals(False)

            if hasattr(self.mw.sidebar, 'chk_scan_amazon'):
                self.mw.sidebar.chk_scan_amazon.setEnabled(amazon_enabled)
                self.mw.sidebar.chk_scan_amazon.blockSignals(True)
                if not amazon_enabled: self.mw.sidebar.chk_scan_amazon.setChecked(False)
                else: self.mw.sidebar.chk_scan_amazon.setChecked(lib_settings.get("scanAmazon", False))
                self.mw.sidebar.chk_scan_amazon.blockSignals(False)
                
            self.mw.sidebar.update_scan_button_state()
            
            return lib_settings.get("anchorFolder")
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
            return None

    def refresh_scan_folders_ui(self):
        config = build_scanner_config()
        folder_rules = config.get("local_scan_config", {}).get("folder_rules", {})
        
        lib_settings_file = get_library_settings_file()
        lib_settings = load_encrypted_json(lib_settings_file)
            
        was_saved = "scanFolders" in lib_settings
        saved_checked = lib_settings.get("scanFolders", [])
        
        for chk in self.mw.sidebar.chk_scan_folders.values():
            self.mw.sidebar.layout_scan_local.removeWidget(chk)
            chk.deleteLater()
        self.mw.sidebar.chk_scan_folders.clear()
        
        row, col = 1, 0
        master_checked = self.mw.sidebar.chk_scan_local.isChecked()
        for folder in sorted(folder_rules.keys()):
            rule = folder_rules[folder]
            if not rule.get("scan", False): continue
                
            chk = QCheckBox(folder)
            chk.setChecked(folder in saved_checked if was_saved else True)
            chk.setEnabled(master_checked)
            self.mw.sidebar.layout_scan_local.addWidget(chk, row, col)
            self.mw.sidebar.chk_scan_folders[folder] = chk
            col += 1
            if col > 1:
                col = 0
                row += 1
            
        target_row = row if col == 0 else row + 1
        self.mw.sidebar.layout_scan_local.setRowStretch(target_row, 1)

    def reload_global_settings(self):
        global_settings, _ = self.get_user_settings()
        apply_theme(QApplication.instance(), global_settings.get("theme", "System"))
        
        if translator.language != global_settings.get("language", "English"):
            translator.load_language(global_settings.get("language", "English"))
            self.retranslate_ui()
            
        new_format_str = global_settings.get("dateFormat", "DD/MM/YYYY")
        if new_format_str != getattr(self.mw, 'date_format_str', "DD/MM/YYYY"):
            self.mw.date_format_str = new_format_str
            self.mw.library_controller.refresh_data()
            
        self.mw.sidebar.refresh_styles()
        self.mw.list_controller.apply_display_settings(self.mw.display_settings)

    def retranslate_ui(self):
        self.mw.setWindowTitle(translator.tr("app_title"))
        self.mw.menu_controller.create_menu_bar()
        self.mw.sidebar.retranslate_ui()