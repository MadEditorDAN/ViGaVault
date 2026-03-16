# WHY: Re-architected application to solve the "Massive View Controller" pattern.
# This file now strictly serves as the Core UI Coordinator, initializing the 
# visual layout and instantly delegating logic to the modular Controllers.
import sys
import pandas as pd
import os
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QWidget, 
                               QHBoxLayout, QAbstractItemView, QStackedLayout, QLabel)
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot
from PySide6.QtGui import QFont

from ViGaVault_utils import setup_logging, translator, apply_theme
from ViGaVault_widgets import Sidebar

from controllers import MenuController, LibraryController, ListController, FilterController, ScanController

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(translator.tr("app_title"))
        self.resize(1200, 800)
        self.is_startup = True
        self.sort_desc = True
        self.display_settings = {'image': 200, 'button': 45, 'text': 22}
        self.thread_pool = QThreadPool()
        
        
        # Variables for Lazy Loading
        self.batch_size = 30
        self.current_df = pd.DataFrame()
        self.loaded_count = 0
        
        self.last_viewport_width = 0
        self.background_loader = QTimer()
        self.background_loader.setInterval(200)
        
        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(600)

        self.current_scan_game = None
        self.full_scan_in_progress = False
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        self.left_container = QWidget()
        self.left_layout = QStackedLayout(self.left_container)
        
        self.loading_label = QLabel("Loading Database...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)
        self.loading_label.setFont(font)
        
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.verticalScrollBar().setSingleStep(25)
        
        self.left_layout.addWidget(self.loading_label) # Index 0
        self.left_layout.addWidget(self.list_widget)   # Index 1
        main_layout.addWidget(self.left_container, stretch=3)
        
        # 3. Sidebar (right, takes 1/4 of the space)
        # The entire design (filters + scan) is handled in the Sidebar class
        self.sidebar = Sidebar(self)
        main_layout.addWidget(self.sidebar, stretch=1)
        
        # Initialize empty DataFrame required for filters logic before DB loads
        self.master_df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
        self.master_df['temp_sort_date'] = pd.to_datetime([])
        self.master_df['temp_sort_title'] = []
        
        # WHY: Instantiate Controllers
        self.menu_controller = MenuController(self)
        self.library_controller = LibraryController(self)
        self.list_controller = ListController(self)
        self.filter_controller = FilterController(self)
        self.scan_controller = ScanController(self)

        # Wire up Timers to Controllers
        self.background_loader.timeout.connect(self.list_controller.load_more_items)
        self.filter_timer.timeout.connect(self.filter_controller.start_filter_worker)
        self.list_widget.verticalScrollBar().valueChanged.connect(self.list_controller.check_scroll_load)

        # Run Initialization
        self.menu_controller.create_menu_bar()
        self.library_controller.load_database_async()
        if os.path.exists("settings.json"):
            self.library_controller.load_settings()
        self.library_controller.update_library_info()

        if os.path.exists("settings.json"):
            saved_scroll = self.library_controller.load_settings()
            if saved_scroll:
                self.pending_scroll = saved_scroll
        else:
            self.sidebar.combo_sort.setCurrentIndex(1)

    # =================================================================================
    # WHY: Proxy Methods limit coupling issues and safely override the 
    # deprecated monolithic functions left over in this file.
    # =================================================================================
    def request_filter_update(self): self.filter_controller.request_filter_update()
    def toggle_sort_order(self): self.filter_controller.toggle_sort_order()
    def start_full_scan(self): self.scan_controller.start_full_scan()
    def on_manual_search_trigger(self): self.scan_controller.on_manual_search_trigger()
    def apply_inline_selection(self): self.scan_controller.apply_inline_selection()
    def cancel_inline_scan(self): self.scan_controller.cancel_inline_scan()
    def start_inline_scan(self, game_data): self.scan_controller.start_inline_scan(game_data)
    def update_game_flags(self, folder, flags): self.library_controller.update_game_flags(folder, flags)
    def update_game_data(self, folder, data): self.library_controller.update_game_data(folder, data)
    def execute_merge(self, a, b): return self.library_controller.execute_merge(a, b)
    def save_database(self): self.library_controller.save_database()
    def save_settings(self): self.library_controller.save_settings()
    def refresh_data(self): self.library_controller.refresh_data()
    def reload_global_settings(self): self.library_controller.reload_global_settings()

    def closeEvent(self, event):
        self.library_controller.save_settings()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.list_controller.update_item_sizes()

if __name__ == "__main__":
    setup_logging()
    app = QApplication(sys.argv)

    # Load and apply theme/language at startup
    global_settings = {}
    if os.path.exists("settings.json"):
        try:
            with open("settings.json", "r", encoding='utf-8') as f:
                global_settings = json.load(f)
        except: pass
    
    apply_theme(app, global_settings.get("theme", "System"))
    translator.load_language(global_settings.get("language", "English"))

    window = MainWindow()
    window.show()
    window.raise_()
    sys.exit(app.exec())