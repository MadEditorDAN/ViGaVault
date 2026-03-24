# WHY: Single Responsibility Principle - Exclusively handles loading/saving application 
# configurations (JSON), window geometry, themes, languages, and UI sidebar generation.
import os
import json
import shutil
import logging
from datetime import datetime
from PySide6.QtCore import QObject, QByteArray
from PySide6.QtWidgets import QApplication, QCheckBox

from backend.library import LibraryManager
from ViGaVault_utils import (get_library_settings_file, build_scanner_config, get_platform_config, 
                             apply_theme, translator, DEFAULT_DISPLAY_SETTINGS)

class SettingsController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    def get_user_settings(self):
        global_settings = {}
        if os.path.exists("settings.json"):
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
        return global_settings, lib_settings

    def save_user_settings(self, display_state, data_state, old_image_path=None, move_images=False):
        global_settings, lib_settings = self.get_user_settings()
        
        global_settings.update(display_state)
        local_keys = ["sort_desc", "sort_index", "search_text", "anchor_folder", "view_new", "view_dlc", "view_review", "filter_states", "filter_expansion", "sidebar_chk_galaxy", "sidebar_chk_gog_web", "sidebar_chk_epic", "sidebar_chk_steam", "sidebar_chk_local", "sidebar_chk_folders", "platform_map", "ignored_prefixes", "root_path", "local_scan_config", "enable_galaxy_db", "galaxy_db_path", "download_images", "download_videos", "image_path", "video_path"]
        for k in local_keys: global_settings.pop(k, None)
        
        try:
            with open("settings.json", "w", encoding='utf-8') as f:
                json.dump(global_settings, f, indent=4)
        except Exception as e: logging.error(f"Failed to save global settings: {e}")

        global_keys = ["geometry", "theme", "language", "card_image_size", "card_button_size", "card_text_size", "db_path", "splitter_sizes"]
        for k in global_keys: lib_settings.pop(k, None)

        lib_settings["root_path"] = data_state["root_path"]
        lib_settings["local_scan_config"] = data_state["local_scan_config"]
        lib_settings["enable_galaxy_db"] = data_state["enable_galaxy_db"]
        lib_settings["galaxy_db_path"] = data_state["galaxy_db_path"]
        lib_settings["download_images"] = data_state["download_images"]
        lib_settings["image_path"] = data_state["image_path"]
        
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
        
        try:
            with open(get_library_settings_file(), "w", encoding='utf-8') as f:
                json.dump(lib_settings, f, indent=4)
        except Exception as e: logging.error(f"Failed to save library settings: {e}")

        if hasattr(self.mw, 'display_settings'):
            self.mw.display_settings['image'] = display_state['card_image_size']
            self.mw.display_settings['button'] = display_state['card_button_size']
            self.mw.display_settings['text'] = display_state['card_text_size']

    def save_settings(self):
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass

        global_settings.update({"geometry": self.mw.saveGeometry().toBase64().data().decode()})
        global_settings.update({"splitter_sizes": self.mw.splitter.sizes()})
        
        local_keys = ["sort_desc", "sort_index", "search_text", "anchor_folder", "view_new", "view_dlc", "view_review", "filter_states", "filter_expansion", "sidebar_chk_galaxy", "sidebar_chk_gog_web", "sidebar_chk_epic", "sidebar_chk_steam", "sidebar_chk_local", "sidebar_chk_folders", "platform_map", "ignored_prefixes", "root_path", "local_scan_config", "enable_galaxy_db", "galaxy_db_path", "download_images", "download_videos", "image_path", "video_path"]
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
            if item.widget() and hasattr(item.widget(), 'toggle_btn') and hasattr(item.widget(), 'title'):
                group = item.widget()
                saved_expansion[group.title] = group.toggle_btn.isChecked()

        checked_folders = [f for f, chk in self.mw.sidebar.chk_scan_folders.items() if chk.isChecked()]

        lib_settings.update({
            "sort_desc": self.mw.sort_desc,
            "sort_index": self.mw.sidebar.combo_sort.currentIndex(),
            "search_text": self.mw.sidebar.search_bar.text(),
            "anchor_folder": self.mw.library_controller.get_second_visible_folder(),
            "view_new": self.mw.sidebar.btn_toggle_new.isChecked(),
            "view_dlc": self.mw.sidebar.btn_toggle_dlc.isChecked(),
            "view_review": self.mw.sidebar.btn_toggle_review.isChecked(),
            "filter_states": filter_states,
            "filter_expansion": saved_expansion,
            "sidebar_chk_galaxy": self.mw.sidebar.chk_scan_galaxy.isChecked(),
            "sidebar_chk_gog_web": self.mw.sidebar.chk_scan_gog_web.isChecked(),
            "sidebar_chk_epic": self.mw.sidebar.chk_scan_epic.isChecked(),
            "sidebar_chk_steam": self.mw.sidebar.chk_scan_steam.isChecked(),
            "sidebar_chk_local": self.mw.sidebar.chk_scan_local.isChecked(),
            "sidebar_chk_folders": checked_folders,
            "download_images": self.mw.sidebar.chk_scan_dl_images.isChecked()
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
        global_settings, lib_settings = self.get_user_settings()

        try:
            if "geometry" in global_settings:
                self.mw.restoreGeometry(QByteArray.fromBase64(global_settings["geometry"].encode('utf-8')))
            if "splitter_sizes" in global_settings:
                self.mw.splitter.setSizes(global_settings["splitter_sizes"])
            self.mw.sort_desc = lib_settings.get("sort_desc", True)
            self.mw.sidebar.update_sort_button(self.mw.sort_desc)
            
            self.mw.display_settings['image'] = global_settings.get("card_image_size", DEFAULT_DISPLAY_SETTINGS['image'])
            self.mw.display_settings['button'] = global_settings.get("card_button_size", DEFAULT_DISPLAY_SETTINGS['button'])
            self.mw.display_settings['text'] = global_settings.get("card_text_size", DEFAULT_DISPLAY_SETTINGS['text'])
            
            # WHY: Restore UI checkboxes cleanly
            self.mw.sidebar.chk_scan_galaxy.setChecked(lib_settings.get("sidebar_chk_galaxy", False))
            self.mw.sidebar.chk_scan_local.setChecked(lib_settings.get("sidebar_chk_local", False))
            
            # WHY: Check live connection status to physically forbid the user from toggling scanners for disconnected platforms.
            try:
                from backend.gog.login_gog import is_gog_connected
                gog_enabled = is_gog_connected()
            except ImportError: gog_enabled = False
            self.mw.gog_connected_cache = gog_enabled
            self.mw.sidebar.chk_scan_gog_web.setEnabled(gog_enabled)
            if not gog_enabled: self.mw.sidebar.chk_scan_gog_web.setChecked(False)
            else: self.mw.sidebar.chk_scan_gog_web.setChecked(lib_settings.get("sidebar_chk_gog_web", False))

            try:
                from backend.epic.login_epic import is_epic_connected
                epic_enabled = is_epic_connected()
            except ImportError: epic_enabled = False
            self.mw.epic_connected_cache = epic_enabled
            self.mw.sidebar.chk_scan_epic.setEnabled(epic_enabled)
            if not epic_enabled: self.mw.sidebar.chk_scan_epic.setChecked(False)
            else: self.mw.sidebar.chk_scan_epic.setChecked(lib_settings.get("sidebar_chk_epic", False))

            try:
                from backend.steam.login_steam import is_steam_connected
                steam_enabled = is_steam_connected()
            except ImportError: steam_enabled = False
            self.mw.steam_connected_cache = steam_enabled
            
            if hasattr(self.mw.sidebar, 'chk_scan_steam'):
                self.mw.sidebar.chk_scan_steam.setEnabled(steam_enabled)
                if not steam_enabled: self.mw.sidebar.chk_scan_steam.setChecked(False)
                else: self.mw.sidebar.chk_scan_steam.setChecked(lib_settings.get("sidebar_chk_steam", False))
                
            self.mw.sidebar.update_scan_button_state()
            
            return lib_settings.get("anchor_folder")
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
            return None

    def refresh_scan_folders_ui(self):
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
            
        new_format_str = global_settings.get("date_format", "DD/MM/YYYY")
        if new_format_str != getattr(self.mw, 'date_format_str', "DD/MM/YYYY"):
            self.mw.date_format_str = new_format_str
            self.mw.library_controller.refresh_data()
            
        self.mw.sidebar.refresh_styles()
        self.mw.list_controller.apply_display_settings(self.mw.display_settings)

    def retranslate_ui(self):
        self.mw.setWindowTitle(translator.tr("app_title"))
        self.mw.menu_controller.create_menu_bar()
        self.mw.sidebar.retranslate_ui()