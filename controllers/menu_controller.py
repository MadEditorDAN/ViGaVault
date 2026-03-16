import os
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtGui import QAction, QPalette

from ViGaVault_utils import translator
from dialogs import PlatformManagerDialog, MediaManagerDialog, StatisticsDialog, SettingsDialog

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
        action_settings = QAction(translator.tr("menu_file_settings"), self.mw)
        action_settings.triggered.connect(self.open_settings)
        file_menu.addAction(action_settings)

        file_menu.addSeparator()
        action_quit = QAction(translator.tr("menu_file_exit"), self.mw)
        action_quit.triggered.connect(self.mw.close)
        file_menu.addAction(action_quit)
        
        tools_menu = menu_bar.addMenu(translator.tr("menu_tools"))
        action_full_scan = QAction(translator.tr("sidebar_btn_full_scan"), self.mw)
        action_full_scan.triggered.connect(self.mw.scan_controller.start_full_scan)
        tools_menu.addAction(action_full_scan)
        
        action_media_manager = QAction(translator.tr("menu_tools_media_manager"), self.mw)
        action_media_manager.triggered.connect(self.show_media_manager)
        tools_menu.addAction(action_media_manager)
        
        action_platforms = QAction(translator.tr("menu_tools_platform_manager"), self.mw)
        action_platforms.triggered.connect(self.show_platform_manager)
        tools_menu.addAction(action_platforms)
        
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

    def open_settings(self):
        dlg = SettingsDialog(self.mw)
        dlg.exec()

    def show_platform_manager(self):
        dlg = PlatformManagerDialog(self.mw)
        dlg.exec()

    def show_media_manager(self):
        # WHY: Media manager refresh relies on the centralized scroll tracking in LibraryController (DRY).
        dlg = MediaManagerDialog(self.mw)
        dlg.exec()
        if getattr(dlg, 'global_changes_made', False):
            self.mw.library_controller.refresh_data()

    def show_statistics(self):
        dlg = StatisticsDialog(self.mw.master_df, self.mw)
        dlg.exec()

    def load_html_asset(self, filename):
        # Resolves path by going up one level out of the controllers folder
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        asset_path = os.path.join(base_path, "assets", filename)
        if os.path.exists(asset_path):
            try:
                with open(asset_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    assets_dir = os.path.join(base_path, "assets").replace("\\", "/")
                    bg_color = QApplication.palette().color(QPalette.Window)
                    logo_file = "MadEditor_Logo_Dark.png" if bg_color.lightness() < 128 else "MadEditor_Logo_Light.png"
                    content = content.replace("{assets_path}", assets_dir)
                    return content.replace("{logo_filename}", logo_file)
            except Exception as e:
                return f"<p>Error loading content: {e}</p>"
        return f"<p>Content not found: {filename}</p>"

    def show_documentation(self):
        title = translator.tr("menu_help_docs")
        text = self.load_html_asset("doc.html")
        QMessageBox(QMessageBox.NoIcon, title, text, QMessageBox.Ok, self.mw).exec()

    def show_about(self):
        title = translator.tr("menu_help_about")
        text = self.load_html_asset("about.html")
        QMessageBox.about(self.mw, title, text)