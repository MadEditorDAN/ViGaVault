# WHY: Re-architected application to solve the "Massive View Controller" pattern.
# This file now strictly serves as the Core UI Coordinator, initializing the 
# visual layout and instantly delegating logic to the modular Controllers.
import sys
import pandas as pd
import os
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QListView, QWidget, 
                               QVBoxLayout, QSplitter, QAbstractItemView)
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot
from PySide6.QtGui import QFont

from ViGaVault_utils import setup_logging, translator, apply_theme, MAIN_WINDOW_SIZE, DEFAULT_DISPLAY_SETTINGS
from widgets import Sidebar

from controllers import MenuController, LibraryController, ListController, FilterController, ScanController, SettingsController, GameOperationsController

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(translator.tr("app_title"))
        self.resize(*MAIN_WINDOW_SIZE)
        # WHY: Establish a baseline minimum size so Qt doesn't falsely inherit maximum dimensions from multi-monitor geometry restorations.
        self.setMinimumSize(800, 600)
        self.is_startup = True
        self.sort_desc = True
        self.display_settings = DEFAULT_DISPLAY_SETTINGS.copy()
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
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # WHY: Use a QSplitter to allow the user to manually adjust the boundary between the list and the sidebar.
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)
        
        self.list_widget = QListView()
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.verticalScrollBar().setSingleStep(25)
        
        # WHY: Removed the massive invisible borders to reclaim space. 
        # Selection now natively relies on background highlighting without squishing the layout.
        self.list_widget.setStyleSheet("""
            QListView::item { padding: 5px; border-bottom: 1px solid palette(dark); }
            QListView::item:selected { background-color: palette(highlight); border-radius: 3px; }
        """)
        
        self.splitter.addWidget(self.list_widget)
        
        # 3. Sidebar (right, takes 1/4 of the space)
        # The entire design (filters + scan) is handled in the Sidebar class
        self.sidebar = Sidebar(self)
        self.splitter.addWidget(self.sidebar)
        
        # WHY: Establish the initial 1/4 layout ratio. The resizeEvent mathematically enforces the 1/3 maximum.
        self.splitter.setSizes([1200, 400])
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        
        # Initialize empty DataFrame required for filters logic before DB loads
        self.master_df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
        self.master_df['temp_sort_date'] = pd.to_datetime([])
        self.master_df['temp_sort_title'] = []
        
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass
            
        self.date_format_str = global_settings.get("date_format", "DD/MM/YYYY")
        # WHY: Instantiate Controllers
        self.menu_controller = MenuController(self)
        self.library_controller = LibraryController(self)
        self.list_controller = ListController(self)
        self.filter_controller = FilterController(self)
        self.scan_controller = ScanController(self)
        self.settings_controller = SettingsController(self)
        self.game_operations_controller = GameOperationsController(self)

        # Wire up Timers to Controllers
        self.background_loader.timeout.connect(self.list_controller.load_more_items)
        self.filter_timer.timeout.connect(self.filter_controller.start_filter_worker)
        self.list_widget.verticalScrollBar().valueChanged.connect(self.list_controller.check_scroll_load)
        # WHY: Trigger live card resizing dynamically when the user drags the QSplitter boundary.
        self.splitter.splitterMoved.connect(self.list_controller.update_item_sizes)

        # Run Initialization
        self.menu_controller.create_menu_bar()
        self.library_controller.load_database_async()
        self.library_controller.update_library_info()

        if os.path.exists("settings.json"):
            # WHY: Point the startup loader to the new dedicated SettingsController.
            saved_anchor = self.settings_controller.load_settings()
            if saved_anchor:
                self.pending_anchor_folder = saved_anchor
        else:
            self.sidebar.combo_sort.setCurrentIndex(0)

    # =================================================================================
    # WHY: Proxy Methods limit coupling issues and safely override the 
    # deprecated monolithic functions left over in this file.
    # =================================================================================
    def request_filter_update(self): self.filter_controller.request_filter_update()
    def approve_reviews(self): self.game_operations_controller.approve_reviews()
    def toggle_sort_order(self): self.filter_controller.toggle_sort_order()
    def start_full_scan(self): self.scan_controller.start_full_scan()
    def open_scan_settings(self): self.scan_controller.open_scan_settings()
    def close_scan_settings(self): self.scan_controller.close_scan_settings()
    def on_manual_search_trigger(self): self.scan_controller.on_manual_search_trigger()
    def apply_inline_selection(self): self.scan_controller.apply_inline_selection()
    def cancel_inline_scan(self): self.scan_controller.cancel_inline_scan()
    def start_inline_scan(self, game_data): self.scan_controller.start_inline_scan(game_data)
    def update_game_flags(self, folder, flags): self.game_operations_controller.update_game_flags(folder, flags)
    def update_game_data(self, folder, data): self.game_operations_controller.update_game_data(folder, data)
    def delete_game(self, folder): self.game_operations_controller.delete_game(folder)
    def execute_merge(self, a, b): return self.game_operations_controller.execute_merge(a, b)
    def save_database(self): self.library_controller.save_database()
    def save_settings(self): self.settings_controller.save_settings()
    def refresh_data(self): self.library_controller.refresh_data()
    def reload_global_settings(self): self.settings_controller.reload_global_settings()

    def closeEvent(self, event):
        self.settings_controller.save_settings()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.list_controller.update_item_sizes()
        
        # WHY: Enforce the maximum width of the sidebar dynamically to exactly 1/3 of the main window width.
        self.sidebar.setMaximumWidth(self.width() // 3)

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