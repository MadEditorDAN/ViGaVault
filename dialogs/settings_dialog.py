# WHY: Orchestrator logic perfectly stripped down. The UI components live inside settings_tabs.py, 
# while this file purely acts to bind the JSON IO and event broadcasting.
import os
import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton, QMessageBox

# WHY: Restored DEFAULT_DISPLAY_SETTINGS import so the orchestrator can safely initialize dirty flags if the JSON is missing.
from ViGaVault_utils import translator, DIALOG_STD_SIZE, center_window, DEFAULT_DISPLAY_SETTINGS
from .tabs import DisplayTabWidget, LocalSourcesTabWidget, PlatformsTabWidget

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(translator.tr("settings_title"))
        
        self.btn_apply = None

        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.tab_display = DisplayTabWidget(self)
        self.tabs.addTab(self.tab_display, translator.tr("settings_tab_display"))
        
        self.tab_data = LocalSourcesTabWidget(self)
        self.tabs.addTab(self.tab_data, translator.tr("settings_tab_data"))
        
        self.tab_platforms = PlatformsTabWidget(self)
        self.tabs.addTab(self.tab_platforms, translator.tr("settings_tab_platforms"))
        
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton(translator.tr("settings_btn_apply"))
        self.btn_apply.setEnabled(False)
        btn_save = QPushButton(translator.tr("settings_btn_save"))
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        self.btn_apply.clicked.connect(self.apply_settings)
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        self.tab_display.changed.connect(self.mark_changed)
        self.tab_data.changed.connect(self.mark_changed)
        self.tab_platforms.changed.connect(self.mark_changed)
        
        # WHY: Loosely couple the UI changes inside the platform tab to the Application's sidebar.
        self.tab_platforms.connection_changed.connect(self.on_platform_connection_changed)

        self.load_settings()

    def mark_changed(self, *args):
        if self.btn_apply:
            self.btn_apply.setEnabled(True)

    def on_platform_connection_changed(self, platform_id, is_connected):
        """WHY: Single Responsibility - Listens to the Platforms tab and updates the main sidebar state safely."""
        if self.parent_window and hasattr(self.parent_window, 'sidebar'):
            if platform_id == "epic":
                self.parent_window.sidebar.chk_scan_epic.setEnabled(is_connected)
                if not is_connected: self.parent_window.sidebar.chk_scan_epic.setChecked(False)
                self.parent_window.epic_connected_cache = is_connected
            elif platform_id == "gog":
                self.parent_window.sidebar.chk_scan_gog_web.setEnabled(is_connected)
                if not is_connected: self.parent_window.sidebar.chk_scan_gog_web.setChecked(False)
                self.parent_window.gog_connected_cache = is_connected
            elif platform_id == "steam":
                self.parent_window.sidebar.chk_scan_steam.setEnabled(is_connected)
                if not is_connected: self.parent_window.sidebar.chk_scan_steam.setChecked(False)
                self.parent_window.steam_connected_cache = is_connected
            self.parent_window.sidebar.update_scan_button_state()
        self.mark_changed()

    def load_settings(self):
        if self.parent_window and hasattr(self.parent_window, 'settings_controller'):
            global_settings, lib_settings = self.parent_window.settings_controller.get_user_settings()
        else:
            global_settings, lib_settings = {}, {}
            
        # WHY: State Delegation - Pass the loaded JSON directly to the dedicated tab controllers.
        self.tab_display.set_state(global_settings)
        
        self.initial_date = global_settings.get("date_format", "DD/MM/YYYY")
        
        live_dl_images = None
        if self.parent_window and hasattr(self.parent_window, 'sidebar'):
            live_dl_images = self.parent_window.sidebar.chk_scan_dl_images.isChecked()
            
        self.tab_data.set_state(lib_settings, live_dl_images)
        self.original_image_path = self.tab_data.image_path_input.text()
        
        # WHY: "Dirty Flags" initialization. We save the starting states of purely cosmetic variables.
        self.initial_theme = global_settings.get("theme", "System")
        self.initial_lang = global_settings.get("language", "English")
        self.initial_img_size = global_settings.get("card_image_size", DEFAULT_DISPLAY_SETTINGS['image'])
        self.initial_btn_size = global_settings.get("card_button_size", DEFAULT_DISPLAY_SETTINGS['button'])
        self.initial_txt_size = global_settings.get("card_text_size", DEFAULT_DISPLAY_SETTINGS['text'])
        self.initial_galaxy = lib_settings.get("enable_galaxy_db", False)
        self.initial_gog_web = lib_settings.get("sidebar_chk_gog_web", False)
        self.initial_epic_web = lib_settings.get("sidebar_chk_epic", False)
        self.initial_steam_web = lib_settings.get("sidebar_chk_steam", False)
        self.initial_local = lib_settings.get("local_scan_config", {}).get("enable_local_scan", False)
        
        if self.btn_apply:
            self.btn_apply.setEnabled(False)

    def apply_settings(self):
        # WHY: Input Validation - Prevent saving an invalid state where the local scan engine is enabled but has nowhere to look.
        data_state = self.tab_data.get_state()
        if data_state["local_scan_config"]["enable_local_scan"] and not data_state["root_path"].strip():
            QMessageBox.warning(self, "Warning", translator.tr("msg_local_path_mandatory"))
            return False
            
        display_state = self.tab_display.get_state()
        
        new_image_path = data_state["image_path"]
        if new_image_path != self.original_image_path and os.path.exists(self.original_image_path):
            reply = QMessageBox.question(self, "Move Image Files?",
                f"The image folder has changed from:\n{self.original_image_path}\nto:\n{new_image_path}\n\n"
                "Do you want to move existing image files to the new location?\n\n"
                "YES: Moves files to the new location.\n"
                "NO: Does NOT move files (Links may break until you move files manually).",
                QMessageBox.Yes | QMessageBox.No)
            
            move_images = (reply == QMessageBox.Yes)
        else:
            move_images = False

        # WHY: Delegation - The UI passes pure dictionaries to the Controller to perform the actual disk save.
        if self.parent_window and hasattr(self.parent_window, 'settings_controller'):
            self.parent_window.settings_controller.save_user_settings(display_state, data_state, self.original_image_path, move_images)

        self.original_image_path = new_image_path
        
        # WHY: Smart Refresh logic checking Dirty Flags
        new_theme = display_state['theme']
        new_lang = display_state['language']
        new_date = display_state['date_format']
        new_img = display_state['card_image_size']
        new_btn = display_state['card_button_size']
        new_txt = display_state['card_text_size']
        
        if new_theme != self.initial_theme or new_lang != self.initial_lang or new_date != self.initial_date:
            if self.parent_window and hasattr(self.parent_window, 'reload_global_settings'):
                self.parent_window.reload_global_settings()
                self.initial_theme = new_theme
                self.initial_lang = new_lang
                self.initial_date = new_date
                
        if new_img != self.initial_img_size or new_btn != self.initial_btn_size or new_txt != self.initial_txt_size:
            if self.parent_window and hasattr(self.parent_window, 'list_controller'):
                self.parent_window.list_controller.apply_display_settings(self.parent_window.display_settings)
                self.initial_img_size = new_img
                self.initial_btn_size = new_btn
                self.initial_txt_size = new_txt
                
        new_galaxy = data_state["enable_galaxy_db"]
        new_gog_web = self.parent_window.sidebar.chk_scan_gog_web.isChecked() if self.parent_window else self.initial_gog_web
        new_epic_web = self.parent_window.sidebar.chk_scan_epic.isChecked() if self.parent_window else self.initial_epic_web
        new_steam_web = self.parent_window.sidebar.chk_scan_steam.isChecked() if self.parent_window else self.initial_steam_web
        new_local = data_state["local_scan_config"]["enable_local_scan"]
        
        # WHY: Dynamically push disabled states back to the quick-toggles in the sidebar
        if new_galaxy != self.initial_galaxy or new_local != self.initial_local or new_gog_web != self.initial_gog_web or new_epic_web != self.initial_epic_web or new_steam_web != self.initial_steam_web:
            if self.parent_window and hasattr(self.parent_window, 'sidebar'):
                self.parent_window.sidebar.chk_scan_galaxy.setEnabled(new_galaxy)
                if not new_galaxy: self.parent_window.sidebar.chk_scan_galaxy.setChecked(False)
                self.parent_window.sidebar.chk_scan_local.setEnabled(new_local)
                if not new_local: self.parent_window.sidebar.chk_scan_local.setChecked(False)
            self.parent_window.sidebar.update_scan_button_state()
            self.initial_galaxy = new_galaxy
            self.initial_gog_web = new_gog_web
            self.initial_epic_web = new_epic_web
            self.initial_steam_web = new_steam_web
            
        # WHY: Push the dialog's visual state back into the Sidebar's live physical checkbox.
        new_dl_images = data_state["download_images"]
        if self.parent_window and hasattr(self.parent_window, 'sidebar'):
            self.parent_window.sidebar.chk_scan_dl_images.setChecked(new_dl_images)
            
        if self.parent_window and hasattr(self.parent_window, 'settings_controller'):
            self.parent_window.settings_controller.refresh_scan_folders_ui()
            
        # WHY: State successfully committed.
        self.btn_apply.setEnabled(False)
        return True

    def accept(self):
        if self.apply_settings():
            super().accept()

    def reject(self):
        super().reject()