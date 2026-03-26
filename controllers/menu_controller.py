import os
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtGui import QAction, QPalette

from ViGaVault_utils import translator, BASE_DIR
from dialogs import MediaManagerDialog, StatisticsDialog, SettingsDialog, DocumentationDialog, MetadataManagerDialog, GameManagerDialog

class MenuController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    def create_menu_bar(self):
        menu_bar = self.mw.menuBar()
        menu_bar.clear()
        
        file_menu = menu_bar.addMenu(translator.tr("menu_file"))
        action_select_lib = QAction(translator.tr("menu_file_switch_lib"), self.mw)
        action_select_lib.triggered.connect(self.mw.library_controller.select_library)
        file_menu.addAction(action_select_lib)
        
        action_save = QAction(translator.tr("menu_file_save"), self.mw)
        action_save.setShortcut("Ctrl+S")
        action_save.triggered.connect(self.mw.library_controller.save_database)
        file_menu.addAction(action_save)
        
        file_menu.addSeparator()
        action_import = QAction(translator.tr("menu_file_import"), self.mw)
        action_import.triggered.connect(self.mw.library_controller.import_from_csv)
        file_menu.addAction(action_import)
        
        action_export = QAction(translator.tr("menu_file_export"), self.mw)
        action_export.triggered.connect(self.mw.library_controller.export_to_csv)
        file_menu.addAction(action_export)
        
        file_menu.addSeparator()
        action_settings = QAction(translator.tr("menu_file_settings"), self.mw)
        action_settings.triggered.connect(self.open_settings)
        file_menu.addAction(action_settings)

        file_menu.addSeparator()
        action_quit = QAction(translator.tr("menu_file_exit"), self.mw)
        action_quit.triggered.connect(self.mw.close)
        file_menu.addAction(action_quit)
        
        tools_menu = menu_bar.addMenu(translator.tr("menu_tools"))
        action_media_manager = QAction(translator.tr("menu_tools_media_manager"), self.mw)
        action_media_manager.triggered.connect(self.show_media_manager)
        tools_menu.addAction(action_media_manager)
        
        action_metadata_manager = QAction(translator.tr("menu_tools_metadata_manager"), self.mw)
        action_metadata_manager.triggered.connect(self.show_metadata_manager)
        tools_menu.addAction(action_metadata_manager)
        
        action_game_manager = QAction(translator.tr("menu_tools_game_manager"), self.mw)
        action_game_manager.triggered.connect(self.show_game_manager)
        tools_menu.addAction(action_game_manager)
        
        action_stats = QAction(translator.tr("menu_tools_stats"), self.mw)
        action_stats.triggered.connect(self.show_statistics)
        tools_menu.addAction(action_stats)
        
        help_menu = menu_bar.addMenu(translator.tr("menu_help"))
        action_docs = QAction(translator.tr("menu_help_docs"), self.mw)
        action_docs.triggered.connect(self.show_documentation)
        help_menu.addAction(action_docs)
        
        action_about = QAction(translator.tr("menu_help_about"), self.mw)
        action_about.triggered.connect(self.show_about)
        help_menu.addAction(action_about)

    def open_settings(self, tab_index=0):
        # WHY: Block settings access during a full scan to prevent modifying paths or rules while the background thread is actively using them.
        if self.mw.full_scan_in_progress:
            QMessageBox.warning(self.mw, "Warning", translator.tr("msg_wait_for_scan"))
            return
        dlg = SettingsDialog(self.mw)
        dlg.tabs.setCurrentIndex(tab_index)
        dlg.exec()

    def show_media_manager(self):
        # WHY: Block media manager access during a full scan to prevent race conditions on database saves and file moves.
        if self.mw.full_scan_in_progress:
            QMessageBox.warning(self.mw, "Warning", translator.tr("msg_wait_for_scan"))
            return
        dlg = MediaManagerDialog(self.mw)
        dlg.exec()

    def show_metadata_manager(self):
        # WHY: Block metadata manager access during a full scan to prevent data corruption via race conditions.
        if self.mw.full_scan_in_progress:
            QMessageBox.warning(self.mw, "Warning", translator.tr("msg_wait_for_scan"))
            return
        dlg = MetadataManagerDialog(self.mw)
        dlg.exec()

    def show_game_manager(self):
        # WHY: Block game manager access during a full scan to prevent data corruption via race conditions during batch edits.
        if self.mw.full_scan_in_progress:
            QMessageBox.warning(self.mw, "Warning", translator.tr("msg_wait_for_scan"))
            return
        dlg = GameManagerDialog(self.mw)
        dlg.exec()

    def show_statistics(self):
        dlg = StatisticsDialog(self.mw.master_df, self.mw)
        dlg.exec()

    def load_html_asset(self, filename):
        # WHY: DRY Principle & Portability - Always use the centralized BASE_DIR instead of relative __file__ leaps 
        # so path resolution remains perfectly accurate whether running as a script or compiled .exe.
        asset_path = os.path.join(BASE_DIR, "assets", filename)
        if os.path.exists(asset_path):
            try:
                with open(asset_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    assets_dir = os.path.join(BASE_DIR, "assets").replace("\\", "/")
                    bg_color = QApplication.palette().color(QPalette.Window)
                    logo_file = "images/MadEditor_Logo_Dark.png" if bg_color.lightness() < 128 else "images/MadEditor_Logo_Light.png"
                    content = content.replace("{assets_path}", assets_dir)
                    return content.replace("{logo_filename}", logo_file)
            except Exception as e:
                return f"<p>Error loading content: {e}</p>"
        return f"<p>Content not found: {filename}</p>"

    def show_documentation(self):
        # WHY: Dynamically route to the correct localized HTML asset based on the current UI language.
        lang_map = {"English": "en", "French": "fr", "German": "de", "Spanish": "es", "Italian": "it"}
        lang_code = lang_map.get(translator.language, "en")
        text = self.load_html_asset(f"doc_{lang_code}.html")
        DocumentationDialog(text, self.mw).exec()

    def show_about(self):
        title = translator.tr("menu_help_about")
        text = self.load_html_asset("about.html")
        QMessageBox.about(self.mw, title, text)