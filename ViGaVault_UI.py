import sys
import pandas as pd
import os
import re
import requests
import json
import logging
import subprocess
import shutil
from datetime import datetime
import webbrowser
from ViGaVault_Scan import LibraryManager
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                               QWidget, QHBoxLayout, QPushButton, QFileDialog, 
                               QMessageBox, QAbstractItemView, QCheckBox, QSizePolicy,
                               QStackedLayout, QLabel)
from PySide6.QtCore import Qt, QTimer, QByteArray, Slot, QThreadPool, QSize
from PySide6.QtGui import QPixmap, QIcon, QAction, QPalette, QFont

# WHY: Added imports for newly modularized utils and dialogs to maintain functionality without circular imports.
from ViGaVault_utils import (BASE_DIR, LOG_DIR, get_db_path, get_library_settings_file, 
                             get_video_path, get_root_path, get_platform_config, 
                             get_local_scan_config, build_scanner_config, setup_logging, 
                             translator, apply_theme, QtLogSignal, QtLogHandler)                             
from dialogs import (ActionDialog, MergeSelectionDialog, ConflictDialog, 
                     SettingsDialog, PlatformManagerDialog, ProgressBarDelegate, 
                     StatisticsDialog, SelectionDialog, MediaManagerDialog)
from ViGaVault_workers import FullScanWorker, FilterWorker, DbLoaderWorker, StartupSyncWorker
from ViGaVault_widgets import CollapsibleFilterGroup, Sidebar, GameCard

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(translator.tr("app_title"))
        self.resize(1200, 800)
        self.is_startup = True
        self.create_menu_bar()
        self.sort_desc = True
        self.display_settings = {'image': 200, 'button': 45, 'text': 22}
        self.thread_pool = QThreadPool()
        
        
        # Variables for Lazy Loading
        self.batch_size = 30
        self.current_df = pd.DataFrame()
        self.loaded_count = 0
        
        # Timer for background loading: adds items in chunks to keep UI responsive
        self.last_viewport_width = 0
        self.background_loader = QTimer()
        self.background_loader.setInterval(200) # Load a batch every 200ms
        self.background_loader.timeout.connect(self.load_more_items)
        
        # Timer to avoid reloading the list on every keystroke (Debounce)
        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(600) # Wait 600ms after the last change
        self.filter_timer.timeout.connect(self.start_filter_worker)

        self.current_scan_game = None
        self.full_scan_in_progress = False
        
        # 1. Setup main layout (Horizontal)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 2. Game list and Loading screen (left, takes 3/4 of the space)
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
        self.list_widget.verticalScrollBar().valueChanged.connect(self.check_scroll_load)
        
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
        
        # 4. Data loading (Async)
        self.load_database_async()
            
        # Load display settings early
        if os.path.exists("settings.json"):
            self.load_settings()

        # Update visual cues for library
        self.update_library_info()

        # --- RESTORATION ---
        if os.path.exists("settings.json"):
            saved_scroll = self.load_settings()
            if saved_scroll:
                self.pending_scroll = saved_scroll
        else:
            # Default sort on "Release Date"
            self.sidebar.combo_sort.setCurrentIndex(1)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        menu_bar.clear()
        
        # --- File ---
        file_menu = menu_bar.addMenu(translator.tr("menu_file"))
        
        action_select_lib = QAction(translator.tr("menu_file_switch_lib"), self)
        action_select_lib.triggered.connect(self.select_library)
        file_menu.addAction(action_select_lib)
        
        action_save = QAction(translator.tr("menu_file_save"), self)
        action_save.setShortcut("Ctrl+S")
        action_save.triggered.connect(self.save_database)
        file_menu.addAction(action_save)
        
        file_menu.addSeparator()
        
        action_settings = QAction(translator.tr("menu_file_settings"), self)
        action_settings.triggered.connect(self.open_settings)
        file_menu.addAction(action_settings)

        file_menu.addSeparator()
        
        action_quit = QAction(translator.tr("menu_file_exit"), self)
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)
        
        # --- Tools ---
        tools_menu = menu_bar.addMenu(translator.tr("menu_tools"))
        
        action_full_scan = QAction(translator.tr("sidebar_btn_full_scan"), self) # Reusing "Full Scan" translation
        action_full_scan.triggered.connect(self.start_full_scan)
        tools_menu.addAction(action_full_scan)
        
        # WHY: Appending the Media Manager window hook under Full Scan
        action_media_manager = QAction(translator.tr("menu_tools_media_manager"), self)
        action_media_manager.triggered.connect(self.show_media_manager)
        tools_menu.addAction(action_media_manager)
        
        action_platforms = QAction(translator.tr("menu_tools_platform_manager"), self)
        action_platforms.triggered.connect(self.show_platform_manager)
        tools_menu.addAction(action_platforms)
        
        action_stats = QAction(translator.tr("menu_tools_stats"), self)
        action_stats.triggered.connect(self.show_statistics)
        tools_menu.addAction(action_stats)
        
        # --- Help ---
        help_menu = menu_bar.addMenu(translator.tr("menu_help"))
        
        action_docs = QAction(translator.tr("menu_help_docs"), self)
        action_docs.triggered.connect(self.show_documentation)
        help_menu.addAction(action_docs)
        
        action_about = QAction(translator.tr("menu_help_about"), self)
        action_about.triggered.connect(self.show_about)
        help_menu.addAction(action_about)

    def update_library_info(self):
        """Updates window title and sidebar label with current library name."""
        lib_name = os.path.basename(get_db_path()).replace('.csv', '')
        self.setWindowTitle(f"ViGaVault Library - [{lib_name}]")
        self.sidebar.lbl_lib_name.setText(f"{lib_name}")

    def select_library(self):
        """Opens a dialog to select an existing library or create a new one, then soft-reloads the UI."""
        filePath, _ = QFileDialog.getSaveFileName(self, "Switch or Create Library", "", "ViGaVault Library (*.csv)")
        if filePath:
            # Save settings for the current library before switching
            self.save_settings() # Save state of current library before switching

            if not filePath.lower().endswith('.csv'):
                filePath += '.csv'
            
            is_new_file = not os.path.exists(filePath)

            try:
                # Update settings.json to point to the new library path
                settings = {}
                if os.path.exists("settings.json"):
                    with open("settings.json", "r", encoding='utf-8') as f:
                        settings = json.load(f)
                settings['db_path'] = filePath
                with open("settings.json", "w", encoding='utf-8') as f:
                    json.dump(settings, f, indent=4)
                
                if is_new_file:
                    # Create the new CSV and its JSON settings file
                    expected_columns = [
                        'Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 
                        'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 
                        'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Collection', 'Trailer_Link',
                        'game_ID'
                    ] + [f'platform_ID_{i:02d}' for i in range(1, 51)]
                    pd.DataFrame(columns=expected_columns).to_csv(filePath, sep=';', index=False, encoding='utf-8')
                    
                    lib_settings_path = os.path.splitext(filePath)[0] + ".json"
                    default_lib_settings = {
                        "root_path": r"\\madhdd02\Software\GAMES",
                        "local_scan_config": {
                            "ignore_hidden": True, "scan_mode": "advanced", "global_type": "Genre", "folder_rules": {}
                        },
                        "gog_db_path": os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db'),
                        "enable_gog_db": True,
                        "sort_desc": True, "sort_index": 1, "scan_new": False,
                        "filter_states": {}, "filter_expansion": {}
                    }
                    with open(lib_settings_path, "w", encoding='utf-8') as f:
                        json.dump(default_lib_settings, f, indent=4)

                # Perform the soft reload
                self.reload_ui_for_new_library()

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not switch library: {e}")

    def reload_ui_for_new_library(self):
        """Performs a 'soft reload' of the UI to load a new library without restarting."""
        # Stop any background tasks
        self.background_loader.stop()
        self.filter_timer.stop()

        # Clear UI elements
        self.list_widget.clear()
        self.sidebar.search_bar.clear()

        # 1. Async Load
        self.load_database_async()

    def show_platform_manager(self):
        dlg = PlatformManagerDialog(self)
        dlg.exec()

    def show_media_manager(self):
        # WHY: Capture the exact scroll position before opening the dialog so we can freeze it later.
        current_scroll = self.list_widget.verticalScrollBar().value()
        
        # WHY: Opens the newly modularized Media Manager tool for fixing images and videos manually
        dlg = MediaManagerDialog(self)
        dlg.exec()
        
        # WHY: Instead of refreshing on every single apply click, we refresh only once when the manager closes.
        if getattr(dlg, 'global_changes_made', False):
            self.pending_scroll = current_scroll
            self.refresh_data()

    def show_statistics(self):
        dlg = StatisticsDialog(self.master_df, self)
        dlg.exec()

    def load_database_async(self):
        self.left_layout.setCurrentIndex(0) # Show Loading Label curtain
        self.list_widget.clear()
        self.sidebar.setEnabled(False)
        
        self.db_worker = DbLoaderWorker()
        self.db_worker.finished.connect(self.on_db_loaded)
        self.db_worker.start()

    def on_db_loaded(self, df):
        self.master_df = df
        # WHY: Keep the "Loading Database..." message visible (Curtain effect) 
        # until the filter worker completely finishes sorting and preparing the list.
        self.sidebar.setEnabled(True)
        
        # 2. Load all settings for the new library
        lib_settings = {}
        lib_settings_file = get_library_settings_file()
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass

        saved_filters = lib_settings.get("filter_states") # Can be None
        saved_expansion = lib_settings.get("filter_expansion") # Can be None

        # 3. Rebuild filters with the loaded state
        self.populate_dynamic_filters(saved_filters, saved_expansion)

        # 4. Apply other UI settings from the loaded library settings
        self.sidebar.combo_sort.blockSignals(True)
        self.sidebar.chk_show_new.blockSignals(True)

        self.sort_desc = lib_settings.get("sort_desc", True)
        self.sidebar.combo_sort.setCurrentIndex(lib_settings.get("sort_index", 1))
        self.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
        self.sidebar.chk_show_new.setChecked(lib_settings.get("scan_new", False))
        self.sidebar.update_sort_button(self.sort_desc)

        self.sidebar.combo_sort.blockSignals(False)
        self.sidebar.chk_show_new.blockSignals(False)

        # 5. Update window title and GOG button state
        self.update_library_info()
        enable_gog = lib_settings.get("enable_gog_db", True)

        # 6. Trigger a filter and display update
        # WHY: Bypass the 600ms debounce timer during startup for an instant launch.
        if self.is_startup:
            self.start_filter_worker()
        else:
            self.request_filter_update()
        
        # WHY: Start the Silent Startup Sync ONLY once per application launch
        if not hasattr(self, 'startup_sync_done'):
            self.startup_sync_done = True
            self.startup_worker = StartupSyncWorker(build_scanner_config())
            self.startup_worker.finished.connect(self.on_startup_sync_finished)
            self.startup_worker.start()

    @Slot(bool)
    def on_startup_sync_finished(self, changes_made):
        """
        WHY: If the silent sync detected changes on disk, we refresh the UI slightly in the background 
        to lock the buttons natively.
        """
        if changes_made:
            self.refresh_data()

    def save_database(self):
        """Saves the current in-memory database to the CSV file, including a backup."""
        logging.info("Manual save requested.")
        db_path = get_db_path()
        if os.path.exists(db_path):
            BACKUP_DIR = "./backups"
            MAX_FILES = 10
            os.makedirs(BACKUP_DIR, exist_ok=True)
            
            backups = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".csv")]
            backups.sort(key=os.path.getctime)
            while len(backups) >= MAX_FILES:
                os.remove(backups.pop(0))

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_filename = os.path.basename(db_path)
            backup_file = os.path.join(BACKUP_DIR, f"{os.path.splitext(db_filename)[0]}_{timestamp}.csv")
            shutil.copy2(db_path, backup_file)
            logging.info(f"    [DB BACKUP] Backup created at {backup_file}")
        
        try:
            df_to_save = self.master_df.drop(columns=['temp_sort_date', 'temp_sort_title'], errors='ignore')
            df_to_save.to_csv(db_path, sep=';', index=False, encoding='utf-8')
            logging.info(f"    [DB SAVE] Database saved to {db_path} ({len(self.master_df)} games).")
            QMessageBox.information(self, "Save Complete", f"Library saved successfully to\n{db_path}.")
        except PermissionError:
             QMessageBox.warning(self, "File Locked",
                                f"The file {db_path} is open in another program (e.g., Excel).\n\nPlease close it and try again.")
        except Exception as e:
            logging.error(f"Failed to save database: {e}")
            QMessageBox.critical(self, "Error", f"Could not save the library: {e}")

    def load_html_asset(self, filename):
        """Helper to load HTML content from the assets folder."""
        base_path = os.path.dirname(os.path.abspath(__file__))
        asset_path = os.path.join(base_path, "assets", filename)
        if os.path.exists(asset_path):
            try:
                with open(asset_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    assets_dir = os.path.join(base_path, "assets").replace("\\", "/")
                    
                    # Detect current theme brightness to select correct logo
                    bg_color = QApplication.palette().color(QPalette.Window)
                    if bg_color.lightness() < 128:
                        logo_file = "MadEditor_Logo_Dark.png"
                    else:
                        logo_file = "MadEditor_Logo_Light.png"

                    content = content.replace("{assets_path}", assets_dir)
                    return content.replace("{logo_filename}", logo_file)
            except Exception as e:
                logging.error(f"Error loading asset {filename}: {e}")
                return f"<p>Error loading content: {e}</p>"
        return f"<p>Content not found: {filename}</p>"

    def show_documentation(self):
        title = translator.tr("menu_help_docs")
        text = self.load_html_asset("doc.html")
        QMessageBox(QMessageBox.NoIcon, title, text, QMessageBox.Ok, self).exec()

    def show_about(self):
        title = translator.tr("menu_help_about")
        text = self.load_html_asset("about.html")
        QMessageBox.about(self, title, text)

    def populate_dynamic_filters(self, saved_state=None, saved_expansion=None):
        """Rebuilds the sidebar filters based on settings and data."""
        # Clear existing items in the layout
        layout = self.sidebar.filters_layout
        while layout.count():
            item = layout.takeAt(0)
            # Check for widget or layout before deleting
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # This part is tricky, but for a simple addStretch, just taking it is enough
                pass
        
        self.dynamic_filters = {}
        self.filter_buttons = {} # WHY: Keep track of All/None buttons to change their enabled state

        # Load rules
        local_config = {}
        rules = {}
        
        # Load from library settings
        lib_settings_file = get_library_settings_file()
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    local_config = json.load(f).get("local_scan_config", {})
            except: pass
        elif os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    local_config = json.load(f).get("local_scan_config", {})
            except: pass
            
        scan_mode = local_config.get("scan_mode", "advanced")
        rules = local_config.get("folder_rules", {})

        # 1. Always add Platform filter (it's core)
        is_expanded = saved_expansion.get("Platforms", False) if saved_expansion else False
        self.add_filter_group("Platforms", "Platforms", self.sidebar.filters_layout, is_expanded)

        # 2. Add dynamic filters based on rules
        # We group by Type (e.g. if multiple folders map to "Genre", we show one "Genre" filter)
        active_types = set()
        
        if scan_mode == "advanced":
            for folder, rule in rules.items():
                if rule.get("filter", False):
                    active_types.add(rule.get("type"))
        else:
            # Simple mode
            if local_config.get("global_filter", False):
                g_type = local_config.get("global_type", "Genre")
                if "Direct" not in g_type and "None" not in g_type:
                    active_types.add(g_type)
        
        type_map = {
            "Genre": "Genre",
            "Collection": "Collection",
            "Publisher": "Publisher",
            "Developer": "Developer",
            "Year": "Year_Folder"
        }
        
        for type_name, col_name in type_map.items():
            if type_name in active_types:
                is_expanded = saved_expansion.get(type_name, False) if saved_expansion else False
                self.add_filter_group(type_name, col_name, self.sidebar.filters_layout, is_expanded)
        
        # Add a stretch at the end to push groups up
        self.sidebar.filters_layout.addStretch(0)

        # Restore state if provided
        # If saved_state is None, the default (checked=True) will apply.
        if saved_state is not None:
            for col, checkboxes in self.dynamic_filters.items():
                if col in saved_state:
                    for chk in checkboxes:
                        chk.setChecked(chk.text() in saved_state.get(col, []))

    def add_filter_group(self, title, col_name, parent_layout, is_expanded=False):
        group = CollapsibleFilterGroup(title, parent_layout)
        
        # Ensure columns take equal width (50% each)
        group.checkbox_layout.setColumnStretch(0, 1)
        group.checkbox_layout.setColumnStretch(1, 1)
        
        # Add All/None buttons for Platform and Genre
        if title in ["Platforms", "Genre", "Collection"]:
            btn_all = QPushButton("All")
            btn_none = QPushButton("None")
            btn_all.clicked.connect(lambda: self.set_filter_group_state(col_name, True))
            btn_none.clicked.connect(lambda: self.set_filter_group_state(col_name, False))
            group.btns_layout.addWidget(btn_all)
            group.btns_layout.addWidget(btn_none)
            self.filter_buttons[col_name] = (btn_all, btn_none) # WHY: Store references to toggle their greyed-out state later
        
        # Get unique values
        values = set()
        if hasattr(self, 'master_df') and not self.master_df.empty and col_name in self.master_df.columns:
            for val_list in self.master_df[col_name].dropna().unique():
                for val in str(val_list).split(','):
                    v = val.strip()
                    if v: values.add(v)
        
        checkboxes = []
        row, col = 0, 0
        for val in sorted(list(values)):
            chk = QCheckBox(val)
            chk.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            chk.setChecked(True) # Default all checked
            chk.stateChanged.connect(lambda state, c=col_name: self.update_filter_buttons(c)) # WHY: Live update button states when a single checkbox is manually toggled
            chk.stateChanged.connect(self.request_filter_update)
            group.checkbox_layout.addWidget(chk, row, col)
            checkboxes.append(chk)
            col += 1
            if col > 1: # 2 columns
                col = 0
                row += 1
        
        self.dynamic_filters[col_name] = checkboxes
        self.update_filter_buttons(col_name) # WHY: Set initial greyed-out states correctly (e.g. 'All' will start greyed out)
        parent_layout.addWidget(group)
        
        # WHY: We must trigger expansion (setChecked) AFTER adding the widget and items.
        # If done before, the group calculates its size based on empty content, 
        # resulting in a visual glitch (group locked to a tiny height).
        # Doing it here ensures toggle_content() sees the correct content size.
        if is_expanded:
            group.toggle_btn.setChecked(True)

    def set_filter_group_state(self, col_name, state):
        if col_name in self.dynamic_filters:
            for chk in self.dynamic_filters[col_name]:
                chk.blockSignals(True)
                chk.setChecked(state)
                chk.blockSignals(False)
                self.update_filter_buttons(col_name) # WHY: Ensure buttons grey out appropriately since signals were blocked above
            self.request_filter_update()

    def update_filter_buttons(self, col_name):
        """Updates the enabled state of the All/None buttons based on checkbox states."""
        # WHY: Greys out 'All' when all are selected, and 'None' when none are selected
        if hasattr(self, 'filter_buttons') and col_name in self.filter_buttons:
            btn_all, btn_none = self.filter_buttons[col_name]
            checkboxes = self.dynamic_filters.get(col_name, [])
            if not checkboxes: return
            
            all_checked = all(chk.isChecked() for chk in checkboxes)
            none_checked = not any(chk.isChecked() for chk in checkboxes)
            
            btn_all.setEnabled(not all_checked)
            btn_none.setEnabled(not none_checked)

    def set_filters_ui_state(self, enabled):
        """Enables/Disables filter groups and collapses them when disabled."""
        layout = self.sidebar.filters_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                widget = item.widget()
                if isinstance(widget, CollapsibleFilterGroup):
                    widget.setEnabled(enabled)
                    if not enabled:
                        widget.toggle_btn.setChecked(False) # Collapse

        # Adjust stretch factors to prioritize scan panel when visible
        if not enabled:
            self.sidebar.layout.setStretchFactor(self.sidebar.top_layout, 0)
            self.sidebar.layout.setStretchFactor(self.sidebar.scan_panel, 1)
        else:
            self.sidebar.layout.setStretchFactor(self.sidebar.top_layout, 1)
            self.sidebar.layout.setStretchFactor(self.sidebar.scan_panel, 0)
    
    def update_sync_log(self, message):
        self.sidebar.scan_results.addItem(message)
        self.sidebar.scan_results.scrollToBottom()

    def start_full_scan(self):
        if self.full_scan_in_progress:
            QMessageBox.information(self, "Info", "Another task is already in progress.")
            return

        # Check if GOG Galaxy is running
        try:
            output = subprocess.check_output('tasklist', shell=True).decode(errors='ignore')
            if "GalaxyClient.exe" in output:
                reply = QMessageBox.question(self, "GOG Galaxy Detected",
                                            "GOG Galaxy is running. It must be closed to access the database.\n\nPlease close it and click Yes.",
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No: return
        except: pass

        self.full_scan_in_progress = True
        self.sidebar.btn_full_scan.setEnabled(False)
        self.sidebar.btn_full_scan.setText("Scanning...")
        self.sidebar.chk_show_new.setEnabled(False)
        self.sidebar.chk_retry_failures.setEnabled(False)
        self.set_filters_ui_state(False)

        # Show the scan panel as a log viewer
        self.sidebar.scan_panel.show()
        self.sidebar.scan_title_label.setText("Full Intelligent Scan")
        self.sidebar.scan_input.hide()
        self.sidebar.scan_btn.hide()
        self.sidebar.scan_limit_combo.hide()
        self.sidebar.btn_confirm.hide()
        self.sidebar.btn_cancel.setText("Stop")
        self.sidebar.scan_results.clear()
        self.sidebar.scan_results.addItem("Starting Full Scan (GOG Sync + Local)...")

        # Disconnect previous signals and connect the stop function
        try: self.sidebar.btn_cancel.clicked.disconnect()
        except: pass
        self.sidebar.btn_cancel.clicked.connect(self.stop_full_scan)

        # Setup logging to UI
        self.log_signal = QtLogSignal()
        self.log_signal.message_written.connect(self.update_sync_log)
        self.qt_log_handler = QtLogHandler(self.log_signal)
        logging.getLogger().addHandler(self.qt_log_handler)

        # Setup and start worker thread
        do_retry = self.sidebar.chk_retry_failures.isChecked()
        self.full_scan_worker = FullScanWorker(retry_failures=do_retry)
        self.full_scan_worker.finished.connect(self.finish_full_scan)
        self.full_scan_worker.start()

    def stop_full_scan(self):
        """Requests interruption of the full scan thread and closes the panel."""
        if self.full_scan_in_progress and hasattr(self, 'full_scan_worker'):
            logging.info("--- Full Scan interrupted by user. ---")
            self.full_scan_worker.requestInterruption()
            self.sidebar.scan_panel.hide()
            self.set_filters_ui_state(True)
            self.restore_scan_panel()

    def finish_full_scan(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        
        self.full_scan_in_progress = False
        self.sidebar.btn_full_scan.setEnabled(True)
        self.sidebar.btn_full_scan.setText(translator.tr("sidebar_btn_full_scan"))
        self.sidebar.chk_show_new.setEnabled(True)
        self.sidebar.chk_retry_failures.setEnabled(True)

        # If the panel is still visible, it means the scan completed without interruption.
        if self.sidebar.scan_panel.isVisible():
            self.sidebar.scan_results.addItem("--- Full Scan finished! ---")
            self.sidebar.scan_results.scrollToBottom()
            # Change button to "Close" and set its action to close the panel.
            self.sidebar.btn_cancel.setText("Close")
            try: self.sidebar.btn_cancel.clicked.disconnect()
            except: pass
            self.sidebar.btn_cancel.clicked.connect(self.cancel_inline_scan)

        self.refresh_data()

    def start_inline_scan(self, game_data):
        self.current_scan_game = game_data
        self.sidebar.scan_panel.show()
        self.set_filters_ui_state(False)

        self.restore_scan_panel()
        
        # Pre-process name for search: remove Year and platform tags to get clean title
        # Clean up folder name for search
        raw_name = game_data.get('Folder_Name', '')
        # 1. Remove year at the beginning (e.g., "1992 - Dune" -> "Dune")
        clean_name = re.sub(r'^\d{4}\s*-\s*', '', raw_name)
        # 2. Remove the last pair of parentheses (e.g., "Portal (Steam)" -> "Portal")
        clean_name = re.sub(r'\s*\([^)]*\)$', '', clean_name).strip()
        self.sidebar.scan_input.setText(clean_name)
        
        self.sidebar.scan_results.clear()
        
        item = QListWidgetItem("Searching on IGDB...")
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        self.sidebar.scan_results.addItem(item)
        self.sidebar.scan_input.setFocus()

        # Slightly delay the launch to let the interface display (waiting message)
        # This logic is now here to ensure the context is always correct.
        if hasattr(self, 'run_inline_search'):
            QTimer.singleShot(50, self.run_inline_search)

    def update_game_data(self, folder_name, new_data):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        
        game_obj = manager.games.get(folder_name)
        if not game_obj:
            QMessageBox.critical(self, "Error", f"Game '{folder_name}' not found in the database for this library.")
            return

        old_title = game_obj.data.get('Clean_Title', '')
        old_date = game_obj.data.get('Original_Release_Date', '')

        # Updates game data
        for key, value in new_data.items():
            game_obj.data[key] = value
            
        # Rename media properly via the Game class methods
        game_obj.update_media_filenames(old_title, old_date)
        
        # Save to CSV
        while True:
            try:
                manager.save_db()
                break
            except PermissionError:
                reply = QMessageBox.warning(self, "File Locked",
                                    f"The file {get_db_path()} is open in another program (e.g., Excel).\n\n"
                                    "Please close it, then click OK to retry.",
                                    QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Cancel:
                    return
        
        # WHY: Set a pending anchor before refreshing so the async loader focuses the updated game.
        self.pending_anchor_folder = folder_name
        self.refresh_data()

    def execute_merge(self, folder_a, folder_b):
        """Runs the entire merge sequence from data combination to conflict UI."""
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
            dlg = ConflictDialog(game_a.data, game_b.data, conflicts, self)
            if dlg.exec():
                resolutions = dlg.get_resolutions()
                for field, val in resolutions.items():
                    game_a.data[field] = val
                    
                # WHY: Collect rejected media paths to safely delete orphaned files
                if 'Image_Link' in conflicts:
                    rejected = conflicts['Image_Link']['B'] if resolutions['Image_Link'] == conflicts['Image_Link']['A'] else conflicts['Image_Link']['A']
                    if rejected and os.path.exists(rejected): rejected_media.append(rejected)
                if 'Path_Video' in conflicts:
                    rejected = conflicts['Path_Video']['B'] if resolutions['Path_Video'] == conflicts['Path_Video']['A'] else conflicts['Path_Video']['A']
                    if rejected and os.path.exists(rejected): rejected_media.append(rejected)
            else:
                return False # User cancelled

        # Combine and apply. Cleanup trailing data.
        del manager.games[folder_b]

        game_a.update_media_filenames(old_title, old_year)
        
        for f in rejected_media:
            try: os.remove(f)
            except Exception as e: logging.error(f"Could not delete orphaned media {f}: {e}")
                
        manager.save_db()
        # WHY: Set a pending anchor to focus on the merged game.
        self.pending_anchor_folder = folder_a
        self.refresh_data()
        return True

    def update_game_flags(self, folder_name, flags_dict):
        """
        WHY: Support function for Just-In-Time Database discrepancy modifications. 
        Allows a specific UI component to inform the system that a file has vanished.
        """
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game = manager.games.get(folder_name)
        if game:
            for k, v in flags_dict.items():
                game.data[k] = v
            manager.save_db()
            
            # Sync the Pandas dataframe so UI sorts/filters aren't out of step
            idx = self.master_df.index[self.master_df['Folder_Name'] == folder_name].tolist()
            if idx:
                for k, v in flags_dict.items():
                    self.master_df.at[idx[0], k] = v

    def on_manual_search_trigger(self):
        self.sidebar.scan_results.clear()
        item = QListWidgetItem("Searching on IGDB...")
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        self.sidebar.scan_results.addItem(item)
        QTimer.singleShot(50, self.run_inline_search)

    def run_inline_search(self):
        term = self.sidebar.scan_input.text()
        if not term: return
        
        if not self.current_scan_game:
            QMessageBox.warning(self, "Error", "No game selected for scanning. Please click the scan icon on a game.")
            return
        
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        token = manager.get_access_token()

        limit = int(self.sidebar.scan_limit_combo.currentText())
        candidates = manager.fetch_candidates(token, term, limit=limit)
        
        self.sidebar.scan_results.clear()
        for g in candidates:
            # Extract year
            year = ''
            if 'release_dates' in g and g['release_dates']:
                dates = [d['date'] for d in g['release_dates'] if 'date' in d]
                if dates:
                    try:
                        year = datetime.utcfromtimestamp(min(dates)).strftime('%Y')
                    except Exception:
                        pass # Ignore date conversion errors

            display_text = g.get('name', 'Unknown')
            if year:
                display_text = f"{year} - {display_text}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, g)
            
            # Fetch and display cover
            if 'cover' in g and 'url' in g['cover']:
                try:
                    img_url = "https:" + g['cover']['url'].replace("t_thumb", "t_cover_small")
                    data = requests.get(img_url, timeout=2).content
                    pix = QPixmap()
                    pix.loadFromData(data)
                    item.setIcon(QIcon(pix))
                except Exception:
                    pass # Silently ignore image errors to avoid blocking
            self.sidebar.scan_results.addItem(item)

        if not candidates:
            item = QListWidgetItem("No results found.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.sidebar.scan_results.addItem(item)

    def restore_scan_panel(self):
        """Resets the scan panel to its default state for manual scanning."""
        # WHY: Use the translator instead of a hardcoded string so the updated title is correctly displayed.
        self.sidebar.scan_title_label.setText(translator.tr("sidebar_manual_scan_title"))
        self.sidebar.scan_input.show()
        self.sidebar.scan_btn.show()
        self.sidebar.scan_limit_combo.show()
        self.sidebar.btn_confirm.show()
        self.sidebar.btn_cancel.setText("Cancel")

    def cancel_inline_scan(self):
        self.sidebar.scan_panel.hide()
        self.set_filters_ui_state(True)
        self.sidebar.scan_results.clear()
        self.sidebar.scan_input.clear()
        self.restore_scan_panel() # Ensure it's reset for next time

    def apply_inline_selection(self):
        item = self.sidebar.scan_results.currentItem()
        if not item: return
        
        chosen_game = item.data(Qt.UserRole)
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game_obj = manager.games.get(self.current_scan_game.get('Folder_Name'))
        
        if game_obj.apply_candidate_data(chosen_game):
            while True:
                try:
                    manager.save_db()
                    break # Exit loop on success
                except PermissionError:
                    reply = QMessageBox.warning(self, "File Locked",
                                        f"The file {get_db_path()} is open in another program (e.g., Excel).\n\n"
                                        "Please close it, then click OK to retry.",
                                        QMessageBox.Ok | QMessageBox.Cancel)
                    if reply == QMessageBox.Cancel:
                        return

            # WHY: Remove the synchronous scrolling logic that fails due to async background loading.
            # Instead, we pass the folder to the pending anchor system.
            self.pending_anchor_folder = self.current_scan_game.get('Folder_Name')
            self.refresh_data()
            
            self.sidebar.scan_results.clear()
            item = QListWidgetItem("Update complete!")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.sidebar.scan_results.addItem(item)
            
            # Automatically close the panel after 2 seconds
            QTimer.singleShot(2000, self.cancel_inline_scan)

    def closeEvent(self, event):
        self.save_settings()
        event.accept()

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def save_settings(self):
        # --- Save Global Settings ---
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass

        global_settings.update({
            "geometry": self.saveGeometry().toBase64().data().decode(),
            # Theme/Lang/Card sizes are saved via SettingsDialog or preserved here
        })
        
        try:
            with open("settings.json", "w", encoding='utf-8') as f:
                json.dump(global_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving global settings: {e}")

        # --- Save Library Settings ---
        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
             try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
             except: pass
        elif os.path.exists("settings.json"):
             # Migration: try to read lib settings from settings.json if lib file doesn't exist
             lib_settings.update(global_settings)

        # Save filter states
        filter_states = {}
        if hasattr(self, 'dynamic_filters'):
            for col, checkboxes in self.dynamic_filters.items():
                # WHY: "Implicit All" logic. If all boxes are checked, we don't save the explicit list.
                # This ensures that when a scan discovers a NEW category (e.g., a new genre),
                # it will default to checked upon reload, instead of being unchecked because it 
                # was missing from the old explicitly saved list.
                if checkboxes and not all(chk.isChecked() for chk in checkboxes):
                    filter_states[col] = [chk.text() for chk in checkboxes if chk.isChecked()]

        # Save expansion state
        saved_expansion = {}
        layout = self.sidebar.filters_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), CollapsibleFilterGroup):
                group = item.widget()
                saved_expansion[group.title] = group.toggle_btn.isChecked()

        lib_settings.update({
            "sort_desc": self.sort_desc,
            "sort_index": self.sidebar.combo_sort.currentIndex(),
            "search_text": self.sidebar.search_bar.text(),
            "scroll_value": self.list_widget.verticalScrollBar().value(),
            "scan_new": self.sidebar.chk_show_new.isChecked(),
            "filter_states": filter_states,
            "filter_expansion": saved_expansion
        })

        # Ensure platform config exists in file if it wasn't there
        if "platform_map" not in lib_settings:
             pm, ip = get_platform_config()
             lib_settings["platform_map"] = pm
             lib_settings["ignored_prefixes"] = ip

        try:
            with open(lib_settings_file, "w", encoding='utf-8') as f:
                json.dump(lib_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving library settings: {e}")

    def preview_display_settings(self, img_size, btn_size, text_size):
        """Updates the display settings and refreshes visible cards immediately."""
        self.display_settings = {
            'image': img_size,
            'button': btn_size,
            'text': text_size
        }
        # Iterate over all items in the list widget to update them
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, GameCard):
                widget.update_style(self.display_settings)
                item.setSizeHint(widget.sizeHint())

    def load_settings(self):
        # Load Global Settings
        global_settings = {}
        try:
            with open("settings.json", "r", encoding='utf-8') as f:
                global_settings = json.load(f)
        except: pass

        # Load Library Settings
        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass
        else:
            # Fallback/Migration
            lib_settings = global_settings

        try:
            if "geometry" in global_settings:
                self.restoreGeometry(QByteArray.fromBase64(global_settings["geometry"].encode()))
                
            self.sort_desc = lib_settings.get("sort_desc", True)
            self.sidebar.update_sort_button(self.sort_desc)
            
            # Load display settings
            self.display_settings['image'] = global_settings.get("card_image_size", 200)
            self.display_settings['button'] = global_settings.get("card_button_size", 45)
            self.display_settings['text'] = global_settings.get("card_text_size", 22)
            
            # Block signals to avoid triggering apply_filters multiple times
            self.sidebar.combo_sort.blockSignals(True)
            
            idx = lib_settings.get("sort_index", 1)
            if 0 <= idx < self.sidebar.combo_sort.count():
                self.sidebar.combo_sort.setCurrentIndex(idx)
                
            self.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
            
            # Block signals for filter checkboxes during setup
            self.sidebar.chk_show_new.blockSignals(True)
            
            if hasattr(self, 'dynamic_filters'):
                for checkboxes in self.dynamic_filters.values():
                    for chk in checkboxes:
                        chk.blockSignals(True)

            self.sidebar.chk_show_new.setChecked(lib_settings.get("scan_new", False))

            # Restore filter selections
            filter_states = lib_settings.get("filter_states") # Can be None
            if hasattr(self, 'dynamic_filters'):
                if filter_states is not None:
                    for col, checkboxes in self.dynamic_filters.items():
                        if col in filter_states:
                            saved_checked = filter_states.get(col, [])
                            for chk in checkboxes:
                                chk.setChecked(chk.text() in saved_checked)
                        if hasattr(self, 'update_filter_buttons'): # WHY: Update greyed-out button states after restoring user filters
                            self.update_filter_buttons(col)
                elif "checked_platforms" in lib_settings: # Legacy fallback
                    for chk in self.dynamic_filters.get("Platforms", []):
                        chk.setChecked(chk.text() in lib_settings["checked_platforms"])
                    if hasattr(self, 'update_filter_buttons'): # WHY: Refresh button states for legacy fallback too
                        self.update_filter_buttons("Platforms")
            
            self.sidebar.combo_sort.blockSignals(False)
            if hasattr(self, 'dynamic_filters'):
                for checkboxes in self.dynamic_filters.values():
                    for chk in checkboxes:
                        chk.blockSignals(False)
            
            self.sidebar.chk_show_new.blockSignals(False)

            return lib_settings.get("scroll_value", 0)
        except Exception as e:
            print(f"Error loading settings: {e}")
            return 0

    def refresh_data(self):
        """Reloads the CSV and updates the display"""
        self.save_settings() # Save current UI state to file
        self.load_database_async() # Reload using standard flow (which reads settings)

    def load_data(self):
        for _, row in df.iterrows():
            item = QListWidgetItem(self.list_widget)
            # HERE: We pass 'self' (the MainWindow) as the second argument
            card = GameCard(row.to_dict(), self) 
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

    def toggle_sort_order(self):
        self.sort_desc = not self.sort_desc
        self.sidebar.update_sort_button(self.sort_desc)
        self.request_filter_update()
        
    def request_filter_update(self):
        """Starts the timer to apply filters after a short delay."""
        self.filter_timer.start()

    def start_filter_worker(self):
        if not hasattr(self, 'master_df'): return

        # Disable UI to prevent user interaction during filtering
        self.sidebar.setEnabled(False)
        self.list_widget.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        sort_col_map = ["temp_sort_title", "temp_sort_date", "Developer"] # Index-based: 0=Name, 1=Date, 2=Dev
        
        # Gather active filters
        active_filters = {}
        if hasattr(self, 'dynamic_filters'):
            for col, checkboxes in self.dynamic_filters.items():
                # Only apply filter if there are checkboxes in this group
                if checkboxes:
                    # Optimization: If ALL are checked, we don't filter at all.
                    # This ensures that items with empty/missing values in this column are still shown.
                    if not all(chk.isChecked() for chk in checkboxes):
                        active_filters[col] = [chk.text() for chk in checkboxes if chk.isChecked()]

        params = {
            'search_text': self.sidebar.search_bar.text(),
            'active_filters': active_filters,
            'sort_col': sort_col_map[self.sidebar.combo_sort.currentIndex()],
            'sort_desc': self.sort_desc,
            'scan_new': self.sidebar.chk_show_new.isChecked(),
        }

        self.filter_worker = FilterWorker(self.master_df, params)
        self.filter_worker.finished.connect(self.on_filtering_finished)
        self.filter_worker.start()

    @Slot(object)
    def on_filtering_finished(self, filtered_df):
        # WHY: Use the StackedLayout curtain to completely hide the visual jitter of the list 
        # while it rebuilds and restores the scroll position in the background.
        has_scroll = hasattr(self, 'pending_scroll') and self.pending_scroll > 0
            
        self.update_display_with_results(filtered_df)
        
        QApplication.restoreOverrideCursor()

        if self.is_startup:
            self.is_startup = False
            
        if has_scroll:
            # Use a short timer to let the GUI event loop breathe before we start crawling.
            QTimer.singleShot(100, self.restore_scroll_position)
        else:
            self.left_layout.setCurrentIndex(1) # Unveil the list
            self.sidebar.setEnabled(True)
            self.list_widget.setEnabled(True)
            self.sidebar.search_bar.setFocus()

    def check_scroll_load(self, value):
        # If we are near the bottom (85%), load more
        maximum = self.list_widget.verticalScrollBar().maximum()
        if maximum > 0 and value >= maximum * 0.85:
            self.load_more_items()

    def load_more_items(self):
        # Lazy loading logic: Adds items in chunks (batch_size) to prevent UI freeze
        if self.loaded_count >= len(self.current_df):
            self.background_loader.stop()
            return
            
        # Determine the end of the batch
        end_index = min(self.loaded_count + self.batch_size, len(self.current_df))
        batch_df = self.current_df.iloc[self.loaded_count:end_index]
        
        # Sanity check: If viewport width is tiny (startup/minimized), assume a safe default (e.g. 600)
        # This prevents text from wrapping into infinite lines and creating huge vertical gaps.
        vp_width = self.list_widget.viewport().width()
        current_width = vp_width if vp_width > 100 else 600
        
        # Check if width changed (e.g. scrollbar appeared), update existing items if needed
        if self.loaded_count > 0 and abs(current_width - self.last_viewport_width) > 2:
            self.update_item_sizes()
            current_width = self.list_widget.viewport().width()
        
        self.last_viewport_width = current_width
        
        for _, row in batch_df.iterrows():
            item = QListWidgetItem(self.list_widget)
            card = GameCard(row.to_dict(), self, item)
            
            card.setFixedWidth(current_width)
            card.adjustSize()
            item.setSizeHint(card.sizeHint())
            
            # Unlock width
            card.setMinimumWidth(0)
            card.setMaximumWidth(16777215)
            
            item.setData(Qt.UserRole, row['Folder_Name'])
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
            
        self.loaded_count = end_index

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Triggers recalculation of all item heights when the window width changes
        self.update_item_sizes()

    def update_item_sizes(self):
        vp_width = self.list_widget.viewport().width()
        # Same sanity check for resize events
        viewport_width = vp_width if vp_width > 100 else 600
        
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget:
                widget.setFixedWidth(viewport_width)
                widget.adjustSize()
                item.setSizeHint(widget.sizeHint())
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(16777215)
        self.last_viewport_width = viewport_width

    def update_display_with_results(self, df):
        # Stop the previous loading if it's in progress
        self.background_loader.stop()

        # --- ANCHORING: Save selection ---
        current_item = self.list_widget.currentItem()
        
        # WHY: Prioritize explicit anchors requested from actions like Manual Scan/Edit over current UI selection.
        if hasattr(self, 'pending_anchor_folder') and self.pending_anchor_folder:
            anchor_folder = self.pending_anchor_folder
            self.pending_anchor_folder = None
        else:
            anchor_folder = current_item.data(Qt.UserRole) if current_item else None

        # Update UI
        self.current_df = df

        # Update Counter
        self.sidebar.lbl_counter.setText(f"{len(df)}/{len(self.master_df)}")

        self.list_widget.clear()
        self.loaded_count = 0

        # Load the first batch
        self.load_more_items()
        
        # --- ANCHORING: Restoration ---
        if anchor_folder:
            folders_list = self.current_df['Folder_Name'].tolist()
            if anchor_folder in folders_list:
                row_index = folders_list.index(anchor_folder)
                
                # Force loading until the item to be able to display it
                while self.loaded_count <= row_index:
                    self.load_more_items()
                
                item = self.list_widget.item(row_index)
                if item:
                    self.list_widget.setCurrentItem(item)
                    self.list_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)

        # Start loading the rest in the background
        self.background_loader.start()

    def restore_scroll_position(self, retries=10):
        if not hasattr(self, 'pending_scroll'):
            self.left_layout.setCurrentIndex(1) # Unveil the list
            self.sidebar.setEnabled(True)
            self.list_widget.setEnabled(True)
            return
        
        sb = self.list_widget.verticalScrollBar()
        
        # If we can still load and haven't reached the target
        if sb.maximum() < self.pending_scroll and self.loaded_count < len(self.current_df):
            self.load_more_items()
            # Force layout update to recalculate the maximum immediately
            self.list_widget.doItemsLayout() 
            # WHY: Give the GUI layout engine actual time (10ms) to recalculate the scrollbar maximum.
            # A 0ms timer often triggers before the layout finishes rendering the complex cards.
            QTimer.singleShot(10, lambda: self.restore_scroll_position(10))
        elif sb.maximum() < self.pending_scroll and self.loaded_count >= len(self.current_df) and retries > 0:
            # WHY: All items are loaded into the data model, but the graphical layout is still 
            # calculating heights. Wait a bit and retry before forcing the final scroll value.
            QTimer.singleShot(50, lambda: self.restore_scroll_position(retries - 1))
        else:
            # Target reached or everything loaded: apply final position
            sb.setValue(self.pending_scroll)
            del self.pending_scroll
            self.left_layout.setCurrentIndex(1) # Unveil the list
            self.sidebar.setEnabled(True)
            self.list_widget.setEnabled(True)
            self.sidebar.search_bar.setFocus()

    def refresh_styles(self):
        if hasattr(self, 'sidebar'):
            self.sidebar.refresh_styles()

    def reload_global_settings(self):
        """Reloads global settings (theme, language) and applies them."""
        global_settings = {}
        try:
            with open("settings.json", "r", encoding='utf-8') as f:
                global_settings = json.load(f)
        except: pass
        
        new_theme = global_settings.get("theme", "System")
        new_lang = global_settings.get("language", "English")
        
        apply_theme(QApplication.instance(), new_theme)
        
        if translator.language != new_lang:
            translator.load_language(new_lang)
            self.retranslate_ui()
            
        self.refresh_styles()

    def retranslate_ui(self):
        """Update all user-facing strings after a language change."""
        self.setWindowTitle(translator.tr("app_title"))
        self.create_menu_bar() # Easiest way to re-translate menus
        self.sidebar.retranslate_ui()

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