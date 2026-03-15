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
from ViGaVault_Scan import LibraryManager, get_safe_filename, normalize_genre
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton, QStackedLayout, QFileDialog, QScrollArea,
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox, QFrame, QAbstractItemView, QCheckBox, QSlider, QStyle, QGroupBox, QProgressBar, QButtonGroup, QRadioButton,
                             QTabWidget, QMenuBar, QMenu, QSizePolicy, QStyleFactory, QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate, QStyleOptionProgressBar)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent, QUrl, QThread, Signal, QObject, Slot, QThreadPool, QRunnable
from PySide6.QtGui import QPixmap, QIcon, QAction, QPalette, QColor, QFont, QImage

# --- CONFIGURATION & UTILS ---
# WHY: Migrated from ViGaVault_Scan.py to centralize file I/O operations and 
# remove dependency of the worker script on the global UI context.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")

def get_db_path():
    """Reads the db_path from settings.json, falling back to the default."""
    settings_file = os.path.join(BASE_DIR, "settings.json")
    default_db = os.path.join(BASE_DIR, "VGVDB.csv")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("db_path", default_db)
        except Exception:
            pass
    return default_db

def get_library_settings_file():
    """Returns the path to the JSON settings file for the current library."""
    db_path = get_db_path()
    return os.path.splitext(db_path)[0] + ".json"

def get_video_path():
    """Returns the configured video path or default 'videos' folder."""
    settings_path = get_library_settings_file()
    default_path = os.path.join(BASE_DIR, "videos")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("video_path", default_path)
        except: pass
    return default_path

def get_root_path():
    """Returns the configured root path from the library's settings."""
    settings_path = get_library_settings_file()
    default_path = r"\\madhdd02\Software\GAMES"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("root_path", default_path)
        except: pass
    global_settings_path = os.path.join(BASE_DIR, "settings.json")
    if os.path.exists(global_settings_path):
         try:
            with open(global_settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("root_path", default_path)
         except: pass
    return default_path

def get_platform_config():
    """Loads platform mapping and ignore list from settings.json or returns defaults."""
    default_map = {
        'gog': 'GOG', 'steam': 'Steam', 'epic': 'Epic Games Store', 'epic games store': 'Epic Games Store',
        'uplay': 'Uplay', 'ubisoft': 'Uplay', 'ubisoft connect': 'Uplay', 'origin': 'Origin', 
        'ea': 'EA', 'ea app': 'EA', 'amazon': 'Amazon', 'amazon prime': 'Amazon',
        'battlenet': 'Battle.net', 'battle.net': 'Battle.net', 'rockstar': 'Rockstar', 
        'bethesda': 'Bethesda', 'itch': 'itch.io', 'itch.io': 'itch.io', 'discord': 'Discord',
        'ffxiv': 'Final Fantasy XIV', 'kartridge': 'Kartridge', 'minecraft': 'Minecraft',
        'oculus': 'Oculus', 'paradox': 'Paradox', 'riot': 'Riot Games', 'stadia': 'Stadia',
        'totalwar': 'Total War', 'twitch': 'Twitch', 'wargaming': 'Wargaming.net',
        'winstore': 'Windows Store', 'windows store': 'Windows Store', 'beamdog': 'Beamdog',
    }
    default_ignore = [
        'humble', 'gmg', 'fanatical', 'nuuvem', 'indiegala', 
        'd2d', 'direct2drive', 'dotemu', 'fxstore', 'gamehouse', 
        'gamesessions', 'gameuk', 'playfire', 'weplay'
    ]
    settings_path = get_library_settings_file()
    global_settings_path = os.path.join(BASE_DIR, "settings.json")
    if not os.path.exists(settings_path):
        settings_path = global_settings_path
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("platform_map", default_map), settings.get("ignored_prefixes", default_ignore)
        except Exception as e:
            logging.error(f"Error loading settings.json: {e}")
    return default_map, default_ignore

def get_local_scan_config():
    """Loads local scan configuration from settings.json."""
    default_config = {
        "ignore_hidden": True,
        "scan_mode": "advanced",
        "global_type": "Genre",
        "folder_rules": {}
    }
    settings_path = get_library_settings_file()
    global_settings_path = os.path.join(BASE_DIR, "settings.json")
    if not os.path.exists(settings_path):
        settings_path = global_settings_path
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("local_scan_config", default_config)
        except:
            pass
    return default_config

def build_scanner_config():
    """Builds the comprehensive configuration dict required by LibraryManager."""
    p_map, p_ignore = get_platform_config()
    return {
        'db_file': get_db_path(),
        'root_path': get_root_path(),
        'video_path': get_video_path(),
        'platform_map': p_map,
        'ignored_prefixes': p_ignore,
        'local_scan_config': get_local_scan_config()
    }

def setup_logging():
    """Sets up file logging for the application."""
    os.makedirs(LOG_DIR, exist_ok=True)
    logs = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.startswith("scan_")]
    logs.sort(key=os.path.getctime)
    while len(logs) >= 10:
        os.remove(logs.pop(0))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"scan_{timestamp}.log")
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s [%(levelname)s] %(message)s', 
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'), 
            logging.StreamHandler()
        ]
    )

# --- TRANSLATION ---
# Handles loading JSON translation files based on user preference.
# It falls back to the key name if a translation is missing.
class Translator:
    def __init__(self):
        self.translations = {}
        self.language = "English"
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def load_language(self, language):
        self.language = language
        lang_code = "en"
        if language == "French":
            lang_code = "fr"
        elif language == "German":
            lang_code = "de"
        elif language == "Spanish":
            lang_code = "es"
        elif language == "Italian":
            lang_code = "it"
        
        # Check lang/ subdirectory first (cleaner), then root
        lang_file = os.path.join(self.base_path, "lang", f"{lang_code}.json")
        if not os.path.exists(lang_file):
            lang_file = os.path.join(self.base_path, f"{lang_code}.json")
            
        if os.path.exists(lang_file):
            try:
                with open(lang_file, "r", encoding='utf-8') as f:
                    self.translations = json.load(f)
                logging.info(f"Loaded language file: {lang_file}")
            except Exception as e:
                logging.error(f"Failed to load language file {lang_file}: {e}")
                self.translations = {}
        else:
            logging.warning(f"Language file not found: {lang_file}")
            self.translations = {}

    def tr(self, key, **kwargs):
        return self.translations.get(key, key).format(**kwargs)

translator = Translator()
# --- Custom Logging Handler for UI ---
# Allows redirecting Python's standard logging output to a PyQt Signal.
# This is used to display scan logs in real-time within the Sidebar UI.
class QtLogSignal(QObject):
    message_written = Signal(str)

class QtLogHandler(logging.Handler):
    def __init__(self, signal_emitter, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_emitter = signal_emitter
        # Set a simple formatter for the UI log, without timestamp/level
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record):
        msg = self.format(record)
        self.signal_emitter.message_written.emit(msg)

# --- WORKER THREADS ---
# Operations like scanning or filtering can take time. We run them in separate threads
# to prevent the GUI from freezing (becoming unresponsive) while they process.
class FullScanWorker(QThread):
    def __init__(self, retry_failures=False, parent=None):
        super().__init__(parent)
        self.retry_failures = retry_failures
        self.config = build_scanner_config()

    def run(self):
        """Runs the full scan process."""
        try:
            manager = LibraryManager(self.config)
            manager.load_db()
            manager.scan_full(retry_failures=self.retry_failures, worker_thread=self)
        except Exception as e:
            logging.error(f"Critical error in full scan thread: {e}")

class FilterWorker(QThread):
    # Emits the filtered DataFrame back to the main thread when done.
    finished = Signal(object)

    def __init__(self, master_df, params, parent=None):
        super().__init__(parent)
        self.master_df = master_df
        self.params = params

    def run(self):
        df = self.master_df.copy()

        # 1. Text Filter (Search Bar)
        search = self.params['search_text'].lower()
        if search:
            df = df[df['Clean_Title'].str.lower().str.contains(search)]
            
        is_scan_new = self.params.get('scan_new', False)

        # 2. Dynamic Filters (Sidebar Checkboxes)
        # Only apply if NOT scanning new games, as new games often lack metadata
        if not is_scan_new:
            active_filters = self.params.get('active_filters', {})
            for col, selected_values in active_filters.items():
                if not selected_values:
                    # If a category is active but has NO items selected, the result is empty.
                    df = df.iloc[0:0] 
                    break
                
                # Regex match for multi-value fields (e.g. "RPG, Action")
                regex_pattern = '|'.join([re.escape(v) for v in selected_values])
                df = df[df[col].astype(str).str.contains(regex_pattern, case=False, na=False)]

        # Status Filter (Exclusive)
        if is_scan_new:
            df = df[~df['Status_Flag'].isin(['OK', 'LOCKED'])]
        else:
            df = df[df['Status_Flag'].isin(['OK', 'LOCKED'])]
            
        # 3. Sorting
        sort_col = self.params['sort_col']
        sort_desc = self.params['sort_desc']
        
        # Use pre-calculated temporary columns for speed (dates, lowercase titles)
        if sort_col == "temp_sort_date" or sort_col == "temp_sort_title":
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last' if sort_col == "temp_sort_date" else 'first')
        else:
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last')
        
        self.finished.emit(df)

class DbLoaderWorker(QThread):
    finished = Signal(object)

    def run(self):
        db_path = get_db_path()
        if os.path.exists(db_path):
            try:
                df = pd.read_csv(db_path, sep=';', encoding='utf-8').fillna('')
                if 'Status_Flag' not in df.columns:
                    df['Status_Flag'] = 'NEW'
                # Pre-calculate columns for faster sorting
                df['temp_sort_date'] = pd.to_datetime(df['Original_Release_Date'], errors='coerce', dayfirst=True)
                df['temp_sort_title'] = df['Clean_Title'].str.lower()
            except Exception as e:
                logging.error(f"Error loading DB: {e}")
                df = pd.DataFrame()
        else:
            df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
            df['temp_sort_date'] = pd.to_datetime([])
            df['temp_sort_title'] = []
        self.finished.emit(df)

class ImageSignals(QObject):
    loaded = Signal(QImage)

class ImageLoader(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.signals = ImageSignals()

    def run(self):
        if self.path and os.path.exists(self.path):
            image = QImage(self.path)
            if not image.isNull():
                self.signals.loaded.emit(image)

# --- CUSTOM WIDGETS ---
# A custom group box that can collapse its content to save space in the sidebar.
class CollapsibleFilterGroup(QGroupBox):
    def __init__(self, title, parent_layout, parent=None):
        super().__init__("", parent)
        self.parent_layout = parent_layout
        self.title = title
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Header Button (acts as the toggle trigger)
        self.toggle_btn = QPushButton(f"▶ {title}")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False) # Default collapsed
        self.toggle_btn.setStyleSheet("""
            QPushButton { text-align: left; font-weight: bold; padding: 5px; border: none; background-color: palette(button); color: palette(button-text); }
            QPushButton:hover { background-color: palette(midlight); }
            QPushButton:checked { background-color: palette(button); }
        """)
        self.toggle_btn.toggled.connect(self.toggle_content)
        self.layout.addWidget(self.toggle_btn)

        # Content Area
        self.content_area = QWidget()
        self.content_area.setVisible(False)
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # All/None Buttons Container
        self.btns_layout = QHBoxLayout()
        self.btns_layout.setContentsMargins(5, 5, 5, 5)
        self.content_layout.addLayout(self.btns_layout)

        # Scroll Area for Checkboxes (Limits size)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Grid layout for checkboxes (2 columns)
        self.checkbox_container = QWidget()
        self.checkbox_layout = QGridLayout(self.checkbox_container)
        self.checkbox_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.checkbox_container)
        
        self.content_layout.addWidget(self.scroll)
        self.layout.addWidget(self.content_area)

    def toggle_content(self, checked):
        self.content_area.setVisible(checked)
        arrow = "▼" if checked else "▶"
        self.toggle_btn.setText(f"{arrow} {self.title}")
        
        if checked:
            # Switch policy to Expanding so it can take available space...
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            
            # ...BUT we manually calculate the exact required height.
            # WHY: By default, Qt splits space equally (50/50) between 'Expanding' widgets.
            # This looks bad if one group is small and another is huge. 
            # By setting MaximumHeight to the content size, we force the layout to give this 
            # group ONLY what it needs, leaving the remaining space for other large groups.
            h_header = self.toggle_btn.sizeHint().height()
            h_content = 0
            if self.btns_layout.count() > 0:
                h_content += self.btns_layout.sizeHint().height() + self.content_layout.spacing()
            
            self.checkbox_container.adjustSize()
            h_list = self.checkbox_container.sizeHint().height()
            h_chrome = 2 * self.scroll.frameWidth() + self.layout.contentsMargins().top() + self.layout.contentsMargins().bottom() + self.layout.spacing()
            
            total_h = h_header + h_content + h_list + h_chrome + 10
            self.setMaximumHeight(total_h)

            if self.parent_layout:
                self.parent_layout.setStretchFactor(self, 1)
        else:
            # Revert to Maximum (Compact) when collapsed
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self.setMaximumHeight(16777215) # Remove limit
            if self.parent_layout:
                self.parent_layout.setStretchFactor(self, 0)
        
        self.updateGeometry()

# --- Dialog Windows for Editing and Scanning ---
# Dialog for manual editing of game metadata.
class ActionDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.parent_window = parent # WHY: Store reference to main window to access master_df for merging
        self.setWindowTitle(translator.tr(title))
        self.setMinimumWidth(850)
        self.original_data = data.copy()
        self.updated_data = {}

        super_main_layout = QVBoxLayout(self)

        # --- Left Column (Form) ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
 
        metadata_group = QGroupBox(translator.tr("dialog_edit_metadata_group"))
        self.form_layout = QFormLayout(metadata_group)
        self.inputs = {}
        
        # Locked Checkbox
        self.chk_locked = QCheckBox(translator.tr("dialog_edit_locked"))
        self.chk_locked.setChecked(self.original_data.get('Status_Flag') == 'LOCKED')
        self.form_layout.addRow("", self.chk_locked)
        
        # Fields that should not be editable by the user to prevent breaking logic
        fields_to_disable = [
            'Folder_Name', 'Path_Video', 'Status_Flag', 'Image_Link', 
            'Platforms'
        ]
        fields_to_exclude = [
            'Trailer_Link', 'game_ID', 'Image_Link', 'temp_sort_date', 'temp_sort_title',
            'Path_Root', 'Year_Folder'
        ]

        for field, value in self.original_data.items():
            if field in fields_to_exclude or field.startswith('platform_ID_'):
                continue
            label_text = field.replace('_', ' ').title()
            if field == "Summary":
                inp = QTextEdit(str(value))
            else:
                inp = QLineEdit(str(value))
            if field in fields_to_disable:
                inp.setEnabled(False)
                inp.setStyleSheet("background-color: palette(window);")
            self.form_layout.addRow(label_text, inp)
            self.inputs[field] = inp
 
        left_layout.addWidget(metadata_group)

        # --- Right Column (Media) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Section 1: Cover Image
        cover_group = QGroupBox(translator.tr("dialog_edit_cover_group"))
        cover_layout = QVBoxLayout(cover_group)
        self.cover_image_label = QLabel(translator.tr("dialog_edit_no_cover"))
        self.cover_image_label.setAlignment(Qt.AlignCenter)
        self.cover_image_label.setFixedSize(200, 266)
        self.update_cover_display()
        btn_select_image = QPushButton(translator.tr("dialog_edit_select_image_btn"))
        btn_select_image.clicked.connect(self.select_new_image)
        cover_layout.addWidget(self.cover_image_label, 0, Qt.AlignHCenter)
        cover_layout.addWidget(btn_select_image)
        right_layout.addWidget(cover_group)

        # Section 2: Trailer
        self.trailer_group = QGroupBox(translator.tr("dialog_edit_trailer_group"))
        self.trailer_layout = QVBoxLayout(self.trailer_group)
        self.trailer_thumbnail_label = QLabel("No Trailer")
        self.trailer_thumbnail_label.setAlignment(Qt.AlignCenter)
        self.trailer_thumbnail_label.setFixedSize(320, 180)
        self.trailer_layout.addWidget(self.trailer_thumbnail_label, 0, Qt.AlignHCenter)

        # URL display and copy button
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel(translator.tr("dialog_edit_trailer_url_label")))
        self.url_line_edit = QLineEdit()
        url_layout.addWidget(self.url_line_edit, 1)
        copy_btn = QPushButton(translator.tr("dialog_edit_trailer_copy_btn"))
        copy_btn.clicked.connect(self.copy_trailer_url)
        url_layout.addWidget(copy_btn)
        self.trailer_layout.addLayout(url_layout)

        self.btn_play_trailer = QPushButton(translator.tr("dialog_edit_trailer_play_btn"))
        self.trailer_layout.addWidget(self.btn_play_trailer)

        self.setup_trailer_section()
        right_layout.addWidget(self.trailer_group)

        right_layout.addStretch()

        columns_layout = QHBoxLayout()
        columns_layout.addWidget(left_widget, 2)
        columns_layout.addWidget(right_widget, 1)
        super_main_layout.addLayout(columns_layout)

        # --- Bottom Buttons ---
        button_box = QHBoxLayout()
        
        # WHY: Add the Merge button here, separated from the Save/Cancel cluster.
        btn_merge = QPushButton(translator.tr("dialog_edit_btn_merge"))
        btn_merge.clicked.connect(self.start_merge)
        button_box.addWidget(btn_merge)
        
        button_box.addStretch()
        
        btn_save = QPushButton(translator.tr("dialog_edit_save_btn"))
        btn_cancel = QPushButton(translator.tr("dialog_edit_cancel_btn"))
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        button_box.addWidget(btn_save)
        button_box.addWidget(btn_cancel)
        super_main_layout.addLayout(button_box)

    def start_merge(self):
        """Opens the Merge Selection window to pick a game to fuse with."""
        dlg = MergeSelectionDialog(self.original_data, self.parent_window.master_df, self)
        if dlg.exec():
            selected_game = dlg.get_selected()
            if selected_game:
                # If the merge was successful, we close the edit window because the library was reloaded.
                if self.parent_window.execute_merge(self.original_data['Folder_Name'], selected_game['Folder_Name']):
                    self.accept()

    def update_cover_display(self):
        img_path = self.updated_data.get('Image_Link') or self.original_data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path).scaled(200, 266, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_image_label.setPixmap(pixmap)
        else:
            self.cover_image_label.setText("No Cover Image")
            self.cover_image_label.setStyleSheet("border: 1px solid #555;")

    def select_new_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Image Files (*.png *.jpg *.jpeg *.webp)")
        if not file_path:
            return
        safe_filename_base = get_safe_filename(self.original_data.get('Folder_Name', ''))
        _, ext = os.path.splitext(file_path)
        new_filename = f"{safe_filename_base}{ext}"
        dest_path = os.path.join("images", new_filename)
        try:
            os.makedirs("images", exist_ok=True)
            shutil.copy(file_path, dest_path)
            logging.info(f"Image manually changed. New image at: {dest_path}")
            self.updated_data['Image_Link'] = dest_path
            self.update_cover_display()
        except Exception as e:
            logging.error(f"Failed to copy new image: {e}")
            QMessageBox.critical(self, "Error", f"Could not copy the image: {e}")

    def copy_trailer_url(self):
        if self.trailer_link:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.trailer_link)
            logging.info(f"URL copied to clipboard: {self.trailer_link}")

    def setup_trailer_section(self):
        self.trailer_link = self.original_data.get('Trailer_Link', '')
        self.url_line_edit.setText(self.trailer_link)

        if not self.trailer_link:
            self.trailer_thumbnail_label.setText("No Trailer URL")
            self.trailer_thumbnail_label.setStyleSheet("border: 1px solid #555;")
            self.btn_play_trailer.setEnabled(False)
            return

        thumbnail_data = None
        self.btn_play_trailer.setEnabled(True)

        if 'youtube.com' in self.trailer_link or 'youtu.be' in self.trailer_link:
            match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", self.trailer_link)
            if match:
                video_id = match.group(1)
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
                try:
                    response = requests.get(thumbnail_url, timeout=2)
                    if response.status_code == 200:
                        thumbnail_data = response.content
                except Exception as e:
                    logging.warning(f"Could not fetch YouTube thumbnail: {e}")
            self.btn_play_trailer.clicked.connect(self.play_trailer)
        elif self.trailer_link.endswith('.mp4'):
            self.trailer_thumbnail_label.setText("MP4 Trailer")
            self.btn_play_trailer.clicked.connect(self.play_trailer)
        else:
            self.trailer_thumbnail_label.setText("Link Available")
            self.trailer_thumbnail_label.setStyleSheet("border: 1px solid #555;")
            self.btn_play_trailer.clicked.connect(self.play_trailer)
            return
        if thumbnail_data:
            pixmap = QPixmap()
            pixmap.loadFromData(thumbnail_data)
            self.trailer_thumbnail_label.setPixmap(pixmap.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.trailer_thumbnail_label.setText("Trailer Available")
            self.trailer_thumbnail_label.setStyleSheet("border: 1px solid #555;")

    def play_trailer(self):
        if not self.trailer_link:
            return
        logging.info(f"Opening trailer in default browser: {self.trailer_link}")
        # new=1 attempts to open a new browser window instead of a new tab.
        # The positioning on the screen is managed by the operating system.
        webbrowser.open(self.trailer_link, new=1)

    def get_data(self):
        new_data = {}
        for field, inp in self.inputs.items():
            if inp.isEnabled():
                if isinstance(inp, QTextEdit):
                    new_data[field] = inp.toPlainText()
                else:
                    new_data[field] = inp.text()
        new_data.update(self.updated_data)
        
        new_data['Status_Flag'] = 'LOCKED' if self.chk_locked.isChecked() else 'OK'
        new_data['Trailer_Link'] = self.url_line_edit.text().strip()
        
        # WHY: Media renaming has been moved to the Game class to be DRY.
        
        return new_data

class MergeSelectionDialog(QDialog):
    def __init__(self, current_data, master_df, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("dialog_merge_title"))
        self.resize(850, 500) # WHY: Make it larger to accommodate the table layout
        self.current_title = current_data.get('Clean_Title', '')
        self.current_folder = current_data.get('Folder_Name', '')
        self.master_df = master_df
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(translator.tr("dialog_merge_desc")))
        
        self.chk_show_all = QCheckBox(translator.tr("dialog_merge_show_all"))
        self.chk_show_all.toggled.connect(self.populate_list)
        layout.addWidget(self.chk_show_all)
        
        # WHY: Replace QListWidget with a QTableWidget to separate columns.
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(3)
        self.table_widget.setHorizontalHeaderLabels([
            translator.tr("dialog_merge_col_date"), 
            translator.tr("dialog_merge_col_name"), 
            translator.tr("dialog_merge_col_path")
        ])
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table_widget)
        
        # Pre-calculate textual resemblance for the default filtered view
        import difflib
        games = master_df.to_dict('records')
        self.resembling = []
        for g in games:
            if g['Folder_Name'] == self.current_folder: continue
            ratio = difflib.SequenceMatcher(None, self.current_title.lower(), str(g.get('Clean_Title', '')).lower()).ratio()
            if ratio > 0.4:
                self.resembling.append((ratio, g))
        self.resembling.sort(key=lambda x: x[0], reverse=True)
        
        self.populate_list()
        
        btn_box = QHBoxLayout()
        btn_confirm = QPushButton(translator.tr("dialog_merge_confirm"))
        btn_cancel = QPushButton(translator.tr("dialog_merge_cancel"))
        btn_confirm.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(btn_confirm)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def populate_list(self):
        self.table_widget.setRowCount(0)
        items_to_show = []
        
        if self.chk_show_all.isChecked():
            # Show all alphabetically
            games = self.master_df.sort_values(by='Clean_Title').to_dict('records')
            for g in games:
                items_to_show.append((None, g))
        else:
            # Show resembling
            for ratio, g in self.resembling:
                items_to_show.append((ratio, g))

        target_row = -1
        for i, (ratio, g) in enumerate(items_to_show):
            row = self.table_widget.rowCount()
            self.table_widget.insertRow(row)
            
            date_val = str(g.get('Original_Release_Date') or g.get('Year_Folder', ''))
            name_val = f"{g.get('Clean_Title')} ({g.get('Platforms')})"
            path_val = str(g.get('Path_Root', ''))
            
            if ratio is not None:
                name_val += f" [Match: {int(ratio*100)}%]"
                
            if g.get('Folder_Name') == self.current_folder:
                name_val = f">>> {name_val} <<<"
                target_row = row
                
            item_date = QTableWidgetItem(date_val)
            item_date.setData(Qt.UserRole, g)
            
            self.table_widget.setItem(row, 0, item_date)
            self.table_widget.setItem(row, 1, QTableWidgetItem(name_val))
            self.table_widget.setItem(row, 2, QTableWidgetItem(path_val))
            
        if target_row >= 0:
            self.table_widget.selectRow(target_row)
            item = self.table_widget.item(target_row, 0)
            if item:
                self.table_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def get_selected(self):
        row = self.table_widget.currentRow()
        if row >= 0:
            item = self.table_widget.item(row, 0)
            return item.data(Qt.UserRole) if item else None
        return None

class ConflictDialog(QDialog):
    def __init__(self, data_a, data_b, conflicts, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("dialog_conflict_title"))
        self.resize(750, 500)
        self.conflicts = conflicts
        self.resolutions = {}
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(translator.tr("dialog_conflict_desc")))
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        
        # WHY: Utilizing a grid allows perfect side-by-side alignment of conflicting elements.
        self.grid = QGridLayout(container)
        
        # Add vertical line for separation
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        self.grid.addWidget(vline, 0, 3, len(conflicts) + 1, 1) # Span all rows

        # Headers
        self.grid.addWidget(QLabel(""), 0, 0)
        lbl_a = QLabel(translator.tr("dialog_conflict_game_a"))
        lbl_a.setStyleSheet("font-weight: bold; font-size: 16px;")
        lbl_a.setAlignment(Qt.AlignCenter)
        self.grid.addWidget(lbl_a, 0, 1, 1, 2)
        
        lbl_b = QLabel(translator.tr("dialog_conflict_game_b"))
        lbl_b.setStyleSheet("font-weight: bold; font-size: 16px;")
        lbl_b.setAlignment(Qt.AlignCenter)
        self.grid.addWidget(lbl_b, 0, 4, 1, 2)
        
        self.bgs = {}
        row = 1
        for field, vals in conflicts.items():
            lbl_field = QLabel(field.replace('_', ' ').title())
            lbl_field.setStyleSheet("font-weight: bold;")
            self.grid.addWidget(lbl_field, row, 0)
            
            bg = QButtonGroup(self)
            self.bgs[field] = bg
            
            rb_a = QRadioButton()
            rb_a.setChecked(True) # Default to Game A
            rb_b = QRadioButton()
            bg.addButton(rb_a, 0)
            bg.addButton(rb_b, 1)
            
            self.grid.addWidget(rb_a, row, 1)
            self.grid.addWidget(self.create_widget(field, vals['A']), row, 2)
            
            self.grid.addWidget(rb_b, row, 4)
            self.grid.addWidget(self.create_widget(field, vals['B']), row, 5)
            
            row += 1
            
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        btn_box = QHBoxLayout()
        btn_confirm = QPushButton(translator.tr("dialog_merge_confirm"))
        btn_confirm.clicked.connect(self.accept)
        btn_box.addStretch()
        btn_box.addWidget(btn_confirm)
        layout.addLayout(btn_box)

    def create_widget(self, field, val):
        """Creates the appropriate display widget based on the field type."""
        if field == 'Image_Link' and os.path.exists(val):
            lbl = QLabel()
            lbl.setPixmap(QPixmap(val).scaled(150, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lbl.setAlignment(Qt.AlignCenter)
            return lbl
        elif field == 'Path_Video' and os.path.exists(val):
            btn = QPushButton(translator.tr("dialog_conflict_btn_play"))
            btn.clicked.connect(lambda _, v=val: os.startfile(v))
            return btn
        elif field == 'Summary':
            txt = QTextEdit(val)
            txt.setReadOnly(True)
            txt.setMaximumHeight(80)
            return txt
        else:
            txt = QLineEdit(val)
            txt.setReadOnly(True)
            # Force cursor to start of text so the start is always visible
            txt.setCursorPosition(0) 
            return txt

    def get_resolutions(self):
        for field, bg in self.bgs.items():
            winner_idx = bg.checkedId()
            self.resolutions[field] = self.conflicts[field]['A'] if winner_idx == 0 else self.conflicts[field]['B']
        return self.resolutions

# Configuration dialog with tabs for Display, Folders, and Data Sources.
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(translator.tr("settings_title"))

        # Define the 10 steps for each slider
        self.IMG_SIZES = [120, 140, 160, 180, 200, 225, 250, 275, 300, 325]
        self.BTN_SIZES = [25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
        self.TXT_SIZES = [14, 16, 18, 20, 22, 24, 26, 28, 30, 32]

        self.resize(700, 500)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Tab 1: Display
        self.tab_display = QWidget()
        self.setup_display_tab()
        self.tabs.addTab(self.tab_display, translator.tr("settings_tab_display"))
        
        # Tab 2: Local Folders
        self.tab_folders = QWidget()
        self.setup_folders_tab()
        self.tabs.addTab(self.tab_folders, translator.tr("settings_tab_folders"))
        
        # Tab 3: Data Sources
        self.tab_data = QWidget()
        self.setup_data_tab()
        self.tabs.addTab(self.tab_data, translator.tr("settings_tab_data"))
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton(translator.tr("settings_btn_apply"))
        btn_save = QPushButton(translator.tr("settings_btn_save"))
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        btn_apply.clicked.connect(self.apply_settings)
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.load_settings()

    def setup_display_tab(self):
        layout = QFormLayout(self.tab_display)
        
        # Theme
        self.combo_theme = QComboBox()
        self.combo_theme.addItems([translator.tr("theme_system"), translator.tr("theme_dark"), translator.tr("theme_light")])
        layout.addRow(translator.tr("settings_display_theme"), self.combo_theme)
        
        # Language
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["English", "French", "German", "Spanish", "Italian"]) # Keep these hardcoded as they map to file names
        layout.addRow(translator.tr("settings_display_language"), self.combo_lang)
        
        # --- Image Size Slider ---
        img_layout = QHBoxLayout()
        self.slider_img_size = QSlider(Qt.Horizontal)
        self.slider_img_size.setRange(0, 9) # 10 steps
        self.slider_img_size.setPageStep(1)
        self.slider_img_size.setTickInterval(1)
        self.slider_img_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_img_size = QLabel("200 px")
        self.lbl_img_size.setFixedWidth(60)
        img_layout.addWidget(self.slider_img_size)
        img_layout.addWidget(self.lbl_img_size)
        layout.addRow(translator.tr("settings_display_img_size"), img_layout)

        # --- Button Size Slider ---
        btn_layout = QHBoxLayout()
        self.slider_btn_size = QSlider(Qt.Horizontal)
        self.slider_btn_size.setRange(0, 9) # 10 steps
        self.slider_btn_size.setPageStep(1)
        self.slider_btn_size.setTickInterval(1)
        self.slider_btn_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_btn_size = QLabel("45 px")
        self.lbl_btn_size.setFixedWidth(60)
        btn_layout.addWidget(self.slider_btn_size)
        btn_layout.addWidget(self.lbl_btn_size)
        layout.addRow(translator.tr("settings_display_btn_size"), btn_layout)

        # --- Text Size Slider ---
        txt_layout = QHBoxLayout()
        self.slider_text_size = QSlider(Qt.Horizontal)
        self.slider_text_size.setRange(0, 9) # 10 steps
        self.slider_text_size.setPageStep(1)
        self.slider_text_size.setTickInterval(1)
        self.slider_text_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_text_size = QLabel("22 px")
        self.lbl_text_size.setFixedWidth(60)
        txt_layout.addWidget(self.slider_text_size)
        txt_layout.addWidget(self.lbl_text_size)
        layout.addRow(translator.tr("settings_display_txt_size"), txt_layout)

        # --- Connections ---
        # Update labels in real-time while dragging
        self.slider_img_size.valueChanged.connect(self.update_preview_labels)
        self.slider_btn_size.valueChanged.connect(self.update_preview_labels)
        self.slider_text_size.valueChanged.connect(self.update_preview_labels)

    def update_preview_labels(self):
        """Updates the 'px' labels next to the sliders."""
        img_val = self.IMG_SIZES[self.slider_img_size.value()]
        btn_val = self.BTN_SIZES[self.slider_btn_size.value()]
        txt_val = self.TXT_SIZES[self.slider_text_size.value()]

        self.lbl_img_size.setText(f"{img_val} px")
        self.lbl_btn_size.setText(f"{btn_val} px")
        self.lbl_text_size.setText(f"{txt_val} px")

    def setup_folders_tab(self):
        # Configures local folder scanning rules (Simple vs Advanced mode)
        layout = QVBoxLayout(self.tab_folders)
        
        # Scan Local Files Checkbox
        self.chk_scan_local = QCheckBox(translator.tr("settings_folders_scan_local"))
        self.chk_scan_local.setChecked(True)
        self.chk_scan_local.toggled.connect(self.toggle_local_scan_options)
        layout.addWidget(self.chk_scan_local)

        grp_root = QGroupBox(translator.tr("settings_folders_root_group"))
        layout_root = QFormLayout(grp_root)
        self.root_path_input = QLineEdit(r"\\madhdd02\Software\GAMES")
        self.btn_browse_root = QPushButton("...")
        self.btn_browse_root.setFixedWidth(40)
        self.btn_browse_root.clicked.connect(self.browse_root_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.root_path_input)
        path_layout.addWidget(self.btn_browse_root)
        
        layout_root.addRow(translator.tr("settings_folders_main_path"), path_layout)
        layout.addWidget(grp_root)
        
        grp_structure = QGroupBox(translator.tr("settings_folders_structure_group"))
        self.struct_layout = QVBoxLayout(grp_structure)
        
        self.chk_ignore_hidden = QCheckBox(translator.tr("settings_folders_ignore_hidden"))
        self.struct_layout.addWidget(self.chk_ignore_hidden)

        # --- MODE 1: SIMPLE / GLOBAL (Depth 1 or 2) ---
        self.mode_simple_widget = QWidget()
        simple_layout = QVBoxLayout(self.mode_simple_widget)
        simple_layout.setContentsMargins(0, 10, 0, 0)
        
        lbl_simple = QLabel(translator.tr("settings_folders_simple_mode_label"))
        lbl_simple.setStyleSheet("font-weight: bold; color: #4CAF50;")
        simple_layout.addWidget(lbl_simple)
        
        form_simple = QFormLayout()
        self.combo_global_type = QComboBox()
        self.combo_global_type.addItems(["Direct (Root -> Games)", "Genre", "Collection", "Publisher", "Developer", "Year", "Other", "None"])
        form_simple.addRow(translator.tr("settings_folders_simple_mode_content"), self.combo_global_type)
        
        self.chk_global_filter = QCheckBox(translator.tr("settings_folders_simple_mode_add_filter"))
        form_simple.addRow("", self.chk_global_filter)
        simple_layout.addLayout(form_simple)
        
        self.btn_switch_advanced = QPushButton(translator.tr("settings_folders_simple_mode_switch_btn"))
        self.btn_switch_advanced.clicked.connect(self.switch_to_advanced)
        simple_layout.addWidget(self.btn_switch_advanced)
        simple_layout.addStretch()
        
        self.struct_layout.addWidget(self.mode_simple_widget)

        # --- MODE 2: ADVANCED / PER-FOLDER (Depth 3) ---
        self.mode_advanced_widget = QWidget()
        adv_layout = QVBoxLayout(self.mode_advanced_widget)
        adv_layout.setContentsMargins(0, 10, 0, 0)
        
        lbl_adv = QLabel(translator.tr("settings_folders_adv_mode_label"))
        lbl_adv.setStyleSheet("font-weight: bold; color: #2196F3;")
        adv_layout.addWidget(lbl_adv)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        self.levels_container = QWidget()
        self.folders_grid = QGridLayout(self.levels_container)
        self.folders_grid.setAlignment(Qt.AlignTop)
        self.folders_grid.setContentsMargins(0, 0, 0, 0)
        
        scroll.setWidget(self.levels_container)
        adv_layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        self.btn_switch_simple = QPushButton(translator.tr("settings_folders_adv_mode_switch_btn"))
        self.btn_switch_simple.clicked.connect(self.switch_to_simple)
        btn_layout.addWidget(self.btn_switch_simple)
        btn_layout.addStretch()
        adv_layout.addLayout(btn_layout)
        
        self.struct_layout.addWidget(self.mode_advanced_widget)
        
        layout.addWidget(grp_structure, 1)

    def toggle_local_scan_options(self, checked):
        """Enables or disables all local scan options based on the checkbox."""
        self.root_path_input.setEnabled(checked)
        self.btn_browse_root.setEnabled(checked)
        # Disable the entire structure group content
        for i in range(self.struct_layout.count()):
            item = self.struct_layout.itemAt(i)
            if item.widget():
                item.widget().setEnabled(checked)

    def switch_to_simple(self):
        self.mode_advanced_widget.hide()
        self.mode_simple_widget.show()
        self.current_scan_mode = "simple"

    def switch_to_advanced(self):
        self.mode_simple_widget.hide()
        self.mode_advanced_widget.show()
        self.current_scan_mode = "advanced"

    def populate_folders_list(self, saved_rules):
        # Populates the list of root folders found on disk for Advanced Mode configuration
        # Clear existing
        while self.folders_grid.count():
            item = self.folders_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # Headers
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_folder")), 0, 0)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_content_type")), 0, 1)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_filter")), 0, 2)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_scan")), 0, 3)

        # Get folders from disk
        root = self.root_path_input.text().strip()
        disk_folders = set()
        if os.path.exists(root):
            try:
                disk_folders = {f for f in os.listdir(root) if os.path.isdir(os.path.join(root, f))}
            except: pass
        
        # Merge with saved rules (to keep rules for disconnected drives)
        all_folders = sorted(list(disk_folders.union(saved_rules.keys())))
        
        self.folder_widgets = {}
        
        row = 1
        for folder in all_folders:
            # Label
            lbl = QLabel(folder)
            if folder not in disk_folders:
                lbl.setStyleSheet("color: red;") # Indicate missing from disk
            
            # Controls
            combo = QComboBox()
            combo.addItems(["None", "Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            
            chk_filter = QCheckBox()
            chk_scan = QCheckBox()
            
            # Defaults
            default_scan = False # Default to NO SCAN for new folders
            
            if folder in saved_rules:
                rule = saved_rules[folder]
                combo.setCurrentText(rule.get("type", "None"))
                chk_filter.setChecked(rule.get("filter", False))
                chk_scan.setChecked(rule.get("scan", True))
            else:
                chk_scan.setChecked(default_scan)
            
            # Logic: Disable controls if Scan is unchecked
            combo.setEnabled(chk_scan.isChecked())
            chk_filter.setEnabled(chk_scan.isChecked())
            
            chk_scan.stateChanged.connect(lambda state, c=combo, f=chk_filter: (c.setEnabled(state), f.setEnabled(state)))
            
            self.folders_grid.addWidget(lbl, row, 0)
            self.folders_grid.addWidget(combo, row, 1)
            self.folders_grid.addWidget(chk_filter, row, 2)
            self.folders_grid.addWidget(chk_scan, row, 3)
            
            self.folder_widgets[folder] = {
                "combo": combo,
                "filter": chk_filter,
                "scan": chk_scan
            }
            row += 1

    def setup_data_tab(self):
        layout = QVBoxLayout(self.tab_data)

        # --- GOG Galaxy Section ---
        grp_gog = QGroupBox(translator.tr("settings_data_gog_group"))
        layout_gog = QGridLayout(grp_gog)
        
        self.chk_enable_gog = QCheckBox(translator.tr("settings_data_gog_checkbox"))
        self.chk_enable_gog.toggled.connect(self.toggle_gog_input)

        self.gog_db_input = QLineEdit()
        default_path = os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')
        self.gog_db_input.setText(default_path)
        
        self.btn_browse_gog = QPushButton("...")
        self.btn_browse_gog.setFixedWidth(40)
        self.btn_browse_gog.clicked.connect(self.browse_gog_db)
        
        layout_gog.addWidget(self.chk_enable_gog, 0, 0)
        layout_gog.addWidget(self.gog_db_input, 0, 1)
        layout_gog.addWidget(self.btn_browse_gog, 0, 2)
        
        layout.addWidget(grp_gog)
        
        # --- Media Download Section ---
        grp_media = QGroupBox(translator.tr("settings_data_media_group"))
        layout_media = QGridLayout(grp_media)
        
        self.chk_download_videos = QCheckBox(translator.tr("settings_data_media_download_videos"))
        
        self.video_path_input = QLineEdit()
        self.btn_browse_video = QPushButton("...")
        self.btn_browse_video.setFixedWidth(40)
        self.btn_browse_video.clicked.connect(self.browse_video_path)
        
        # Layout: All on one line
        layout_media.addWidget(self.chk_download_videos, 0, 0)
        layout_media.addWidget(QLabel(translator.tr("settings_data_media_videos_path")), 0, 1)
        layout_media.addWidget(self.video_path_input, 0, 2)
        layout_media.addWidget(self.btn_browse_video, 0, 3)
        
        layout.addWidget(grp_media)
        
        layout.addStretch()

    def browse_root_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Root Folder", self.root_path_input.text())
        if dir_path:
            self.root_path_input.setText(os.path.normpath(dir_path))

    def browse_gog_db(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select GOG Database", self.gog_db_input.text(), "SQLite DB (*.db);;All Files (*.*)")
        if file_path:
            self.gog_db_input.setText(file_path)

    def browse_video_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Videos Folder", self.video_path_input.text())
        if dir_path:
            self.video_path_input.setText(os.path.normpath(dir_path))

    def toggle_gog_input(self, checked):
        self.gog_db_input.setEnabled(checked)
        self.btn_browse_gog.setEnabled(checked)

    def load_settings(self):
        # Load Global Settings
        global_settings = {}
        if os.path.exists("settings.json"):
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
            # Fallback/Migration: use global settings if lib settings don't exist
            lib_settings = global_settings
                
        # --- Apply Global Settings ---
        theme_map = {
            "System": translator.tr("theme_system"),
            "Dark": translator.tr("theme_dark"),
            "Light": translator.tr("theme_light")
        }
        saved_theme_key = global_settings.get("theme", "System")
        self.combo_theme.setCurrentText(theme_map.get(saved_theme_key, translator.tr("theme_system")))
        self.combo_lang.setCurrentText(global_settings.get("language", "English"))

        saved_img_size = global_settings.get("card_image_size", 200)
        img_index = self.IMG_SIZES.index(min(self.IMG_SIZES, key=lambda x:abs(x-saved_img_size)))
        self.slider_img_size.setValue(img_index)

        saved_btn_size = global_settings.get("card_button_size", 45)
        btn_index = self.BTN_SIZES.index(min(self.BTN_SIZES, key=lambda x:abs(x-saved_btn_size)))
        self.slider_btn_size.setValue(btn_index)

        saved_txt_size = global_settings.get("card_text_size", 22)
        txt_index = self.TXT_SIZES.index(min(self.TXT_SIZES, key=lambda x:abs(x-saved_txt_size)))
        self.slider_text_size.setValue(txt_index)
        self.update_preview_labels()

        # --- Apply Library Settings ---
        self.root_path_input.setText(lib_settings.get("root_path", r"\\madhdd02\Software\GAMES"))
        
        local_config = lib_settings.get("local_scan_config", {})
        self.chk_scan_local.setChecked(local_config.get("enable_local_scan", True))
        self.toggle_local_scan_options(self.chk_scan_local.isChecked())
        self.chk_ignore_hidden.setChecked(local_config.get("ignore_hidden", True))
        
        self.current_scan_mode = local_config.get("scan_mode", "advanced")
        self.combo_global_type.setCurrentText(local_config.get("global_type", "Genre"))
        self.chk_global_filter.setChecked(local_config.get("global_filter", True))

        if self.current_scan_mode == "simple":
            self.switch_to_simple()
        else:
            self.switch_to_advanced()
        
        self.populate_folders_list(local_config.get("folder_rules", {}))
        
        self.chk_enable_gog.setChecked(lib_settings.get("enable_gog_db", True))
        self.gog_db_input.setText(lib_settings.get("gog_db_path", self.gog_db_input.text()))
        self.toggle_gog_input(self.chk_enable_gog.isChecked())
        
        self.chk_download_videos.setChecked(lib_settings.get("download_videos", False))
        default_video_path = os.path.join(os.getcwd(), "videos")
        self.video_path_input.setText(lib_settings.get("video_path", default_video_path))
        self.original_video_path = self.video_path_input.text()

    def save_settings(self):
        # --- Save Global Settings ---
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass
            
        theme_map_rev = {
            translator.tr("theme_system"): "System",
            translator.tr("theme_dark"): "Dark",
            translator.tr("theme_light"): "Light"
        }
        global_settings["theme"] = theme_map_rev.get(self.combo_theme.currentText(), "System")
        global_settings["language"] = self.combo_lang.currentText()
        global_settings["card_image_size"] = self.IMG_SIZES[self.slider_img_size.value()]
        global_settings["card_button_size"] = self.BTN_SIZES[self.slider_btn_size.value()]
        global_settings["card_text_size"] = self.TXT_SIZES[self.slider_text_size.value()]
        
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
             # Migration: if lib file doesn't exist, start with global as base
             lib_settings.update(global_settings)

        lib_settings["root_path"] = self.root_path_input.text()
        
        folder_rules = {}
        for folder, widgets in self.folder_widgets.items():
            folder_rules[folder] = {
                "type": widgets["combo"].currentText(),
                "filter": widgets["filter"].isChecked(),
                "scan": widgets["scan"].isChecked()
            }
        
        lib_settings["local_scan_config"] = {
            "enable_local_scan": self.chk_scan_local.isChecked(),
            "ignore_hidden": self.chk_ignore_hidden.isChecked(),
            "scan_mode": self.current_scan_mode,
            "global_type": self.combo_global_type.currentText(),
            "global_filter": self.chk_global_filter.isChecked(),
            "folder_rules": folder_rules
        }
        
        lib_settings["enable_gog_db"] = self.chk_enable_gog.isChecked()
        lib_settings["gog_db_path"] = self.gog_db_input.text()
        lib_settings["download_videos"] = self.chk_download_videos.isChecked()
        
        # Handle Video Path Change
        new_video_path = self.video_path_input.text()
        lib_settings["video_path"] = new_video_path
        
        if new_video_path != self.original_video_path and os.path.exists(self.original_video_path):
            reply = QMessageBox.question(self, "Move Video Files?",
                f"The video folder has changed from:\n{self.original_video_path}\nto:\n{new_video_path}\n\n"
                "Do you want to move existing video files to the new location?\n\n"
                "YES: Moves files and updates the database.\n"
                "NO: Does NOT move files, but updates the database paths (Links may break until you move files manually).",
                QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                self.move_video_files(self.original_video_path, new_video_path)
                self.update_db_video_paths(self.original_video_path, new_video_path)
            else:
                self.update_db_video_paths(self.original_video_path, new_video_path)
        
        # Update original path for next save if dialog stays open (though accept closes it)
        self.original_video_path = new_video_path
        
        try:
            with open(lib_settings_file, "w", encoding='utf-8') as f:
                json.dump(lib_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving library settings: {e}")

        # Update parent window display settings immediately so refresh_data uses new values
        if self.parent_window and hasattr(self.parent_window, 'display_settings'):
            self.parent_window.display_settings['image'] = self.IMG_SIZES[self.slider_img_size.value()]
            self.parent_window.display_settings['button'] = self.BTN_SIZES[self.slider_btn_size.value()]
            self.parent_window.display_settings['text'] = self.TXT_SIZES[self.slider_text_size.value()]

    def move_video_files(self, old_path, new_path):
        try:
            os.makedirs(new_path, exist_ok=True)
            files = [f for f in os.listdir(old_path) if os.path.isfile(os.path.join(old_path, f))]
            count = 0
            for f in files:
                src = os.path.join(old_path, f)
                dst = os.path.join(new_path, f)
                shutil.move(src, dst)
                count += 1
            QMessageBox.information(self, "Success", f"Moved {count} files to new video folder.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to move files: {e}")

    def update_db_video_paths(self, old_path, new_path):
        if self.parent_window and hasattr(self.parent_window, 'master_df'):
            df = self.parent_window.master_df
            # Normalize paths for comparison
            abs_old = os.path.abspath(old_path)
            abs_new = os.path.abspath(new_path)
            
            count = 0
            for idx, row in df.iterrows():
                current_vid = str(row['Path_Video'])
                if current_vid:
                    # Check if file is in old path
                    if os.path.abspath(os.path.dirname(current_vid)) == abs_old:
                        filename = os.path.basename(current_vid)
                        new_vid_full = os.path.join(abs_new, filename)
                        df.at[idx, 'Path_Video'] = new_vid_full
                        count += 1
            
            if count > 0:
                self.parent_window.save_database()
                logging.info(f"Updated {count} video paths in database.")

    def apply_settings(self):
        self.save_settings()
        if self.parent_window:
            if hasattr(self.parent_window, 'reload_global_settings'):
                self.parent_window.reload_global_settings()
            if hasattr(self.parent_window, 'refresh_data'):
                self.parent_window.refresh_data()

    def accept(self):
        self.apply_settings()
        super().accept()

# The right-hand sidebar containing Counters, Search, Sort, Filters, and the Scan Panel.
class Sidebar(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.setFixedWidth(350)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # --- TOP CONTAINER (Search, Sort, Filters) ---
        self.top_layout = QVBoxLayout()
        self.top_layout.setSpacing(10) # Aération entre les cadres

        font_lbl = QFont()
        font_lbl.setBold(True)
        font_lbl.setPixelSize(16)
        
        # Style commun pour les cadres (bordure visible + fond légèrement différent)
        self.frame_style = """
            QFrame#sidebar_frame {
                border: 1px solid palette(mid);
                border-radius: 6px;
                background-color: palette(alternate-base);
            }
        """

        # 1. Cadre 1: Compteurs et Nom de la librairie
        self.frame_counters = QFrame()
        self.frame_counters.setObjectName("sidebar_frame")
        self.frame_counters.setStyleSheet(self.frame_style)
        counters_layout = QHBoxLayout(self.frame_counters)
        counters_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_counter = QLabel("0/0")
        self.lbl_counter.setFont(QFont(font_lbl.family(), 20, QFont.Bold))
        counters_layout.addWidget(self.lbl_counter)
        
        counters_layout.addStretch()

        self.lbl_lib_name = QLabel("")
        self.lbl_lib_name.setFont(QFont(font_lbl.family(), 20, QFont.Bold))
        self.lbl_lib_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        counters_layout.addWidget(self.lbl_lib_name)
        
        self.top_layout.addWidget(self.frame_counters)
        
        # 2. Cadre 2: Recherche
        self.frame_search = QFrame()
        self.frame_search.setObjectName("sidebar_frame")
        self.frame_search.setStyleSheet(self.frame_style)
        search_layout = QHBoxLayout(self.frame_search)
        search_layout.setContentsMargins(8, 8, 8, 8)

        lbl_search = QLabel(translator.tr("sidebar_search_label"))
        lbl_search.setObjectName("sidebar_search_label")
        lbl_search.setFont(font_lbl)
        search_layout.addWidget(lbl_search)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(translator.tr("sidebar_search_placeholder"))
        self.search_bar.setClearButtonEnabled(True)
        search_layout.addWidget(self.search_bar, 1) # Stretch 1 pour prendre l'espace disponible
        
        self.top_layout.addWidget(self.frame_search)
        
        # 3. Cadre 3: Tri
        self.frame_sort = QFrame()
        self.frame_sort.setObjectName("sidebar_frame")
        self.frame_sort.setStyleSheet(self.frame_style)
        sort_layout = QHBoxLayout(self.frame_sort)
        sort_layout.setContentsMargins(8, 8, 8, 8)

        lbl_sort = QLabel(translator.tr("sidebar_sort_label"))
        lbl_sort.setObjectName("sidebar_sort_label")
        lbl_sort.setFont(font_lbl)
        sort_layout.addWidget(lbl_sort)

        self.combo_sort = QComboBox()
        self.combo_sort.addItems([translator.tr("sidebar_sort_name"), translator.tr("sidebar_sort_release_date"), translator.tr("sidebar_sort_developer")])
        sort_layout.addWidget(self.combo_sort, 1) # Stretch 1 pour prendre l'espace disponible
        
        self.btn_toggle_sort = QPushButton()
        self.btn_toggle_sort.setFixedWidth(50)
        self.update_sort_button(self.parent.sort_desc)
        sort_layout.addWidget(self.btn_toggle_sort)
        
        self.top_layout.addWidget(self.frame_sort)

        # 4. Cadre 4: Filtres
        self.frame_filters = QFrame()
        self.frame_filters.setObjectName("sidebar_frame")
        self.frame_filters.setStyleSheet(self.frame_style)
        filters_frame_layout = QVBoxLayout(self.frame_filters)
        filters_frame_layout.setContentsMargins(8, 8, 8, 8)

        # WHY: Grouping Filters label and Show NEW checkbox in the same horizontal line.
        filters_header_layout = QHBoxLayout()
        lbl_filters = QLabel(translator.tr("sidebar_filters_label"))
        lbl_filters.setObjectName("sidebar_filters_label")
        lbl_filters.setFont(font_lbl)
        filters_header_layout.addWidget(lbl_filters)

        # WHY: Add a stretch spacer to push the "Show NEW" checkbox to the far right edge of the layout.
        filters_header_layout.addStretch()

        # --- SHOW NEW CHECKBOX (Moved here) ---
        self.chk_show_new = QCheckBox(translator.tr("sidebar_chk_show_new"))
        self.chk_show_new.setLayoutDirection(Qt.RightToLeft)
        filters_header_layout.addWidget(self.chk_show_new, 0, Qt.AlignRight)

        filters_frame_layout.addLayout(filters_header_layout)

        # We remove the outer scroll area to let individual groups handle their scrolling/sizing
        self.filters_container = QWidget()
        self.filters_layout = QVBoxLayout(self.filters_container)
        self.filters_layout.setContentsMargins(0, 0, 0, 0)
        
        filters_frame_layout.addWidget(self.filters_container, 1)
        
        self.top_layout.addWidget(self.frame_filters, 1) # Give it stretch to take available space
        self.layout.addLayout(self.top_layout, 1) # Give top part stretch priority

        # --- SCAN PANEL (Manual Scan / Full Scan Logs) ---
        # Hidden by default, shown when scanning starts
        self.scan_panel = QWidget()
        self.scan_layout = QVBoxLayout(self.scan_panel)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken) # Uses QPalette.Shadow, customized for dark mode
        self.scan_layout.addWidget(line)
        
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText(translator.tr("sidebar_manual_scan_placeholder"))

        scan_action_layout = QHBoxLayout()
        self.scan_btn = QPushButton(translator.tr("sidebar_manual_scan_search_btn"))
        scan_action_layout.addWidget(self.scan_btn, 3)

        self.scan_limit_combo = QComboBox()
        self.scan_limit_combo.addItems(['10', '20', '30', '40', '50'])
        self.scan_limit_combo.setCurrentText('10')
        scan_action_layout.addWidget(self.scan_limit_combo, 1)

        self.scan_results = QListWidget()
        self.scan_results.setIconSize(QSize(50, 70))

        self.btns_layout = QHBoxLayout()
        self.btn_confirm = QPushButton(translator.tr("sidebar_manual_scan_confirm_btn"))
        self.btn_cancel = QPushButton(translator.tr("sidebar_manual_scan_cancel_btn"))
        self.btns_layout.addWidget(self.btn_confirm)
        self.btns_layout.addWidget(self.btn_cancel)
        
        self.scan_title_label = QLabel(translator.tr("sidebar_manual_scan_title"))
        self.scan_layout.addWidget(self.scan_title_label)
        self.scan_layout.addWidget(self.scan_input)
        self.scan_layout.addLayout(scan_action_layout)
        self.scan_layout.addWidget(self.scan_results)
        self.scan_layout.addLayout(self.btns_layout)

        # --- BOTTOM CONTAINER (Scan Buttons) ---
        self.bottom_layout = QHBoxLayout()
        
        # --- FULL SCAN BUTTON ---
        self.btn_full_scan = QPushButton(translator.tr("sidebar_btn_full_scan"))
        
        # --- RETRY FAILURES CHECKBOX (Replaces Show NEW) ---
        # WHY: Adding the Retry Failures option where Show NEW used to be.
        self.chk_retry_failures = QCheckBox(translator.tr("sidebar_chk_retry_failures"))
        self.chk_retry_failures.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.chk_retry_failures.setLayoutDirection(Qt.RightToLeft)

        self.bottom_layout.addWidget(self.btn_full_scan, 2) # 2/3 stretch
        self.bottom_layout.addWidget(self.chk_retry_failures, 1)  # 1/3 stretch

        self.layout.addWidget(self.scan_panel)
        self.scan_panel.hide()
        self.layout.addLayout(self.bottom_layout)
        
        # --- CONNECTIONS ---
        self.search_bar.textChanged.connect(self.parent.request_filter_update)
        self.combo_sort.currentIndexChanged.connect(self.parent.request_filter_update)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        self.btn_full_scan.clicked.connect(self.parent.start_full_scan)
        self.chk_show_new.toggled.connect(self.parent.request_filter_update)

        # Scan Connections
        self.scan_btn.clicked.connect(self.parent.on_manual_search_trigger)
        self.scan_input.returnPressed.connect(self.parent.on_manual_search_trigger)
        self.btn_confirm.clicked.connect(self.parent.apply_inline_selection)
        self.btn_cancel.clicked.connect(self.parent.cancel_inline_scan)
        self.scan_results.itemDoubleClicked.connect(self.parent.apply_inline_selection)

    def update_sort_button(self, is_desc):
        # Updates label between UP (Ascending) and DOWN (Descending)
        key = "sidebar_sort_descending" if is_desc else "sidebar_sort_ascending"
        self.btn_toggle_sort.setText(translator.tr(key))

    def refresh_styles(self):
        # Only refresh elements that use stylesheets and might cache colors
        for frame in [self.frame_counters, self.frame_search, self.frame_sort, self.frame_filters]:
            frame.setStyleSheet(self.frame_style)

        # Refresh Filter Groups to pick up new palette
        for i in range(self.filters_layout.count()):
            item = self.filters_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), CollapsibleFilterGroup):
                w = item.widget()
                # Force re-eval of palette() keywords
                sheet = w.toggle_btn.styleSheet()
                w.toggle_btn.setStyleSheet("")
                w.toggle_btn.setStyleSheet(sheet)

    def retranslate_ui(self):
        self.findChild(QLabel, "sidebar_search_label").setText(translator.tr("sidebar_search_label"))
        self.search_bar.setPlaceholderText(translator.tr("sidebar_search_placeholder"))
        self.findChild(QLabel, "sidebar_sort_label").setText(translator.tr("sidebar_sort_label"))
        self.combo_sort.setItemText(0, translator.tr("sidebar_sort_name"))
        self.combo_sort.setItemText(1, translator.tr("sidebar_sort_release_date"))
        self.combo_sort.setItemText(2, translator.tr("sidebar_sort_developer"))
        self.update_sort_button(self.parent.sort_desc)
        self.findChild(QLabel, "sidebar_filters_label").setText(translator.tr("sidebar_filters_label"))
        self.chk_show_new.setText(translator.tr("sidebar_chk_show_new"))
        self.btn_full_scan.setText(translator.tr("sidebar_btn_full_scan"))
        self.chk_retry_failures.setText(translator.tr("sidebar_chk_retry_failures"))
        # Scan panel
        self.scan_title_label.setText(translator.tr("sidebar_manual_scan_title"))
        self.scan_input.setPlaceholderText(translator.tr("sidebar_manual_scan_placeholder"))
        self.scan_btn.setText(translator.tr("sidebar_manual_scan_search_btn"))
        self.btn_confirm.setText(translator.tr("sidebar_manual_scan_confirm_btn"))
        self.btn_cancel.setText(translator.tr("sidebar_manual_scan_cancel_btn"))

class PlatformManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("tools_platform_title"))
        self.resize(400, 300)
        layout = QVBoxLayout(self)
        
        lbl = QLabel(translator.tr("tools_platform_header"))
        lbl.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl.setFont(font)
        
        layout.addStretch()
        layout.addWidget(lbl)
        layout.addWidget(QLabel(translator.tr("tools_platform_desc"), alignment=Qt.AlignCenter))
        layout.addWidget(QLabel(translator.tr("tools_platform_soon"), alignment=Qt.AlignCenter))
        layout.addStretch()
        
        btn_close = QPushButton(translator.tr("btn_close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

class ProgressBarDelegate(QStyledItemDelegate):
    """
    WHY: Draws a progress bar natively inside the cell. 
    Using setCellWidget() breaks table sorting (widgets don't move when sorted).
    This delegate guarantees the progress bar follows the data when headers are clicked.
    """
    def paint(self, painter, option, index):
        val = index.data(Qt.EditRole)
        max_val = index.data(Qt.UserRole)
        show_text = index.data(Qt.UserRole + 1)
        
        if val is not None and max_val:
            opts = QStyleOptionProgressBar()
            opts.rect = option.rect
            opts.minimum = 0
            opts.maximum = int(max_val)
            opts.progress = int(val)
            if show_text:
                opts.textVisible = True
                opts.text = str(val)
                opts.textAlignment = Qt.AlignCenter
            else:
                opts.textVisible = False
            QApplication.style().drawControl(QStyle.CE_ProgressBar, opts, painter)
        else:
            super().paint(painter, option, index)

class StatisticsDialog(QDialog):
    def __init__(self, df, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("tools_stats_title"))
        self.resize(1300, 800) # WHY: Increase width to comfortably fit the 3 side-by-side graphs
        self.df = df
        
        layout = QVBoxLayout(self)
        
        # WHY: Replace tabs with a single scrollable dashboard page for a better at-a-glance view
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        container = QWidget()
        dashboard_layout = QVBoxLayout(container)
        
        lbl_overview = QLabel(translator.tr("tools_stats_overview"))
        lbl_overview.setStyleSheet("font-size: 18px; font-weight: bold;")
        dashboard_layout.addWidget(lbl_overview)
        
        # Top Section: Overview Cards & Text Stats
        dashboard_layout.addWidget(self.create_overview_section())
        
        # Bottom Section: 3 Graphs Side-by-Side
        graphs_layout = QHBoxLayout()
        graphs_layout.addWidget(self.create_distribution_section("Platforms", translator.tr("tools_stats_platforms")))
        graphs_layout.addWidget(self.create_distribution_section("Genre", translator.tr("tools_stats_genres")))
        graphs_layout.addWidget(self.create_timeline_section())
        
        dashboard_layout.addLayout(graphs_layout)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        btn_close = QPushButton(translator.tr("btn_close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

    def create_overview_section(self):
        widget = QWidget()
        # WHY: Use a vertical layout to separate the colored boxes row from the text columns row.
        # A grid layout caused the text_container (added without span) to constrain itself 
        # into column 0, forcing the first colored box to stretch enormously.
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 15) # Add some spacing at the bottom
        
        # Calculate Stats
        total_games = len(self.df)
        scrapped = len(self.df[self.df['Status_Flag'].isin(['OK', 'LOCKED'])])
        incomplete = total_games - scrapped
        
        boxes_layout = QHBoxLayout()

        # Helper for Cards
        def add_stat_card(title, value, color):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet(f"background-color: {color}; border-radius: 10px; color: white;")
            fl = QVBoxLayout(frame)
            lbl_val = QLabel(str(value))
            lbl_val.setStyleSheet("font-size: 36px; font-weight: bold;")
            lbl_val.setAlignment(Qt.AlignCenter)
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("font-size: 14px;")
            lbl_title.setAlignment(Qt.AlignCenter)
            fl.addWidget(lbl_val)
            fl.addWidget(lbl_title)
            # Stretch=1 guarantees perfectly equal horizontal widths
            boxes_layout.addWidget(frame, 1)

        add_stat_card(translator.tr("tools_stats_total"), total_games, "#2196F3")
        add_stat_card(translator.tr("tools_stats_scrapped"), scrapped, "#4CAF50")
        add_stat_card(translator.tr("tools_stats_incomplete"), incomplete, "#FF9800")

        layout.addLayout(boxes_layout)

        stats_data = []

        # Helper to get top count from comma-separated columns
        def get_top_count(col):
            if col not in self.df.columns: return "N/A"
            all_vals = []
            for x in self.df[col].dropna():
                all_vals.extend([v.strip() for v in str(x).split(',') if v.strip()])
            if not all_vals: return "N/A"
            c = pd.Series(all_vals).value_counts()
            return f"{c.idxmax()} ({c.max()})"
            
        def get_unique_count(col):
            if col not in self.df.columns: return 0
            all_vals = {v.strip() for x in self.df[col].dropna() for v in str(x).split(',') if v.strip()}
            return len(all_vals)

        # 1. Standard & Useful Stats
        stats_data.append(("tools_stats_top_plat", get_top_count('Platforms')))
        stats_data.append(("tools_stats_top_genre", get_top_count('Genre')))
        stats_data.append(("tools_stats_top_dev", get_top_count('Developer')))
        stats_data.append(("tools_stats_top_pub", get_top_count('Publisher')))
        stats_data.append(("tools_stats_total_col", get_unique_count('Collection')))
        stats_data.append(("tools_stats_top_col", get_top_count('Collection')))
        stats_data.append(("tools_stats_unique_devs", get_unique_count('Developer')))
        
        years = pd.to_datetime(self.df['Original_Release_Date'], errors='coerce', dayfirst=True).dt.year if 'Original_Release_Date' in self.df.columns else pd.Series(dtype=int)
        if not years.dropna().empty:
            yc = years.value_counts()
            stats_data.append(("tools_stats_best_year", f"{int(yc.idxmax())} ({yc.max()})"))
        else:
            stats_data.append(("tools_stats_best_year", "N/A"))

        has_img = len(self.df[self.df['Image_Link'].astype(str).str.strip() != '']) if 'Image_Link' in self.df.columns else 0
        media_pct = round((has_img / total_games * 100) if total_games else 0, 1)
        stats_data.append(("tools_stats_media_comp", f"{media_pct}% ({has_img})"))

        has_trailer = len(self.df[(self.df['Trailer_Link'].astype(str).str.strip() != '') | (self.df['Path_Video'].astype(str).str.strip() != '')]) if 'Trailer_Link' in self.df.columns else 0
        stats_data.append(("tools_stats_trailer_hoarder", has_trailer))

        indie_count = self.df['Genre'].astype(str).str.contains('Indie', case=False, na=False).sum() if 'Genre' in self.df.columns else 0
        stats_data.append(("tools_stats_indie_games", indie_count))
        
        # Oldest/Newest
        if 'Original_Release_Date' in self.df.columns:
            valid_dates = self.df[pd.to_datetime(self.df['Original_Release_Date'], errors='coerce', dayfirst=True).notna()].copy()
            if not valid_dates.empty:
                valid_dates['DateObj'] = pd.to_datetime(valid_dates['Original_Release_Date'], errors='coerce', dayfirst=True)
                sorted_dates = valid_dates.sort_values('DateObj')
                oldest = sorted_dates.iloc[0]
                newest = sorted_dates.iloc[-1]
                stats_data.append(("tools_stats_oldest_relic", f"{oldest['Clean_Title']} ({oldest['DateObj'].year})"))
                stats_data.append(("tools_stats_newest_edge", f"{newest['Clean_Title']} ({newest['DateObj'].year})"))
            else:
                stats_data.extend([("tools_stats_oldest_relic", "N/A"), ("tools_stats_newest_edge", "N/A")])

        # Fun/Quirky Stats
        if 'Clean_Title' in self.df.columns:
            valid_titles = self.df['Clean_Title'].dropna().astype(str)
            if not valid_titles.empty:
                lengths = valid_titles.str.len()
                stats_data.append(("tools_stats_longest_title", valid_titles.loc[lengths.idxmax()]))
                stats_data.append(("tools_stats_shortest_title", valid_titles.loc[lengths.idxmin()]))
                
                import re
                words = []
                stopwords = {'the', 'of', 'and', 'in', 'to', 'a', 'for', 'on', 'with', 'edition', 'game', 'hd', 'remastered', 'collection', 'director', 'cut'}
                for title in valid_titles:
                    w_list = re.findall(r'\b[^\d\W_]{3,}\b', title.lower()) # 3+ letters, ignoring digits
                    words.extend([w for w in w_list if w not in stopwords])
                if words:
                    stats_data.append(("tools_stats_common_word", pd.Series(words).value_counts().idxmax().title()))
                else:
                    stats_data.append(("tools_stats_common_word", "N/A"))
            else:
                stats_data.extend([("tools_stats_longest_title", "N/A"), ("tools_stats_shortest_title", "N/A"), ("tools_stats_common_word", "N/A")])

        if 'Summary' in self.df.columns:
            valid_sums = self.df['Summary'].fillna('').astype(str)
            sum_lengths = valid_sums.str.len()
            if not sum_lengths.empty and sum_lengths.max() > 0:
                stats_data.append(("tools_stats_longest_sum", self.df.loc[sum_lengths.idxmax(), 'Clean_Title']))
            else:
                stats_data.append(("tools_stats_longest_sum", "N/A"))
            stats_data.append(("tools_stats_no_sum", len(valid_sums[valid_sums.str.strip() == ''])))
            
        if 'Platforms' in self.df.columns:
            warez_count = len(self.df[self.df['Platforms'].astype(str).str.lower() == 'warez'])
            warez_pct = round((warez_count / total_games * 100) if total_games else 0, 1)
            stats_data.append(("tools_stats_warez_ratio", f"{warez_pct}% ({warez_count})"))

        # WHY: Using QHBoxLayout with 3 QFormLayouts guarantees equal spacing horizontally 
        # and automatically aligns labels so the colons perfectly form a straight vertical line.
        text_container = QWidget()
        text_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        h_layout = QHBoxLayout(text_container)
        h_layout.setContentsMargins(0, 10, 0, 0)
        h_layout.setSpacing(20)

        forms = [QFormLayout(), QFormLayout(), QFormLayout()]
        for f in forms:
            f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h_layout.addLayout(f, 1) # stretch=1 to ensure 3 perfectly equal columns

        num_items = len(stats_data)
        items_per_col = (num_items + 2) // 3 # Ceiling division

        for i, (key, val) in enumerate(stats_data):
            form_idx = i // items_per_col
            
            # Add single quotes for common word since we removed them from the json strings
            if key == "tools_stats_common_word" and val != "N/A":
                val = f"'{val}'"
                
            lbl_title = QLabel(translator.tr(key) + " :")
            lbl_val = QLabel(str(val))
            lbl_val.setWordWrap(True)
            lbl_val.setStyleSheet("font-weight: bold;")
            
            forms[form_idx].addRow(lbl_title, lbl_val)
            
        layout.addWidget(text_container)
        return widget

    def create_distribution_section(self, col_name, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Process Data (Split comma separated values)
        all_values = []
        for item in self.df[col_name].dropna():
            parts = [x.strip() for x in str(item).split(',') if x.strip()]
            all_values.extend(parts)
            
        counts = pd.Series(all_values).value_counts()
        
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([title, translator.tr("tools_stats_col_count"), translator.tr("tools_stats_col_dist")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setRowCount(len(counts))
        
        # WHY: Disable edits and selection so the table behaves purely as a visual chart
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        
        # WHY: Attach custom delegate so progress bar draws based on data correctly during sorting
        delegate = ProgressBarDelegate(table)
        table.setItemDelegateForColumn(2, delegate)

        max_val = counts.max() if not counts.empty else 1
        
        for i, (name, count) in enumerate(counts.items()):
            item_name = QTableWidgetItem()
            item_name.setData(Qt.EditRole, name)
            table.setItem(i, 0, item_name)
            
            # EditRole enforces native numeric sorting
            item_count = QTableWidgetItem()
            item_count.setData(Qt.EditRole, int(count))
            table.setItem(i, 1, item_count)
            
            item_pbar = QTableWidgetItem()
            item_pbar.setData(Qt.EditRole, int(count)) # Native sorting
            item_pbar.setData(Qt.UserRole, int(max_val))
            item_pbar.setData(Qt.UserRole + 1, False) # Show text = False
            table.setItem(i, 2, item_pbar)
            
        table.setSortingEnabled(True)
        table.sortItems(1, Qt.DescendingOrder)
            
        layout.addWidget(table)
        return widget

    def create_timeline_section(self):
        # Simplified histogram using QTableWidget
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        years = pd.to_datetime(self.df['Original_Release_Date'], errors='coerce', dayfirst=True).dt.year
        year_counts = years.dropna().astype(int).value_counts().sort_index()
        
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels([translator.tr("tools_stats_col_year"), translator.tr("tools_stats_col_released")])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setRowCount(len(year_counts))
        
        # WHY: Disable edits and selection so the table behaves purely as a visual chart
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        
        delegate = ProgressBarDelegate(table)
        table.setItemDelegateForColumn(1, delegate)
        
        max_val = year_counts.max() if not year_counts.empty else 1
        
        for i, (year, count) in enumerate(year_counts.items()):
            item_year = QTableWidgetItem()
            item_year.setData(Qt.EditRole, int(year))
            table.setItem(i, 0, item_year)
            
            item_pbar = QTableWidgetItem()
            item_pbar.setData(Qt.EditRole, int(count))
            item_pbar.setData(Qt.UserRole, int(max_val))
            item_pbar.setData(Qt.UserRole + 1, True) # Show text = True
            table.setItem(i, 1, item_pbar)
            
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.AscendingOrder)
            
        layout.addWidget(table)
        return widget

class SelectionDialog(QDialog):
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose the correct game")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Multiple results found. Please select the correct one:"))
        
        self.list_widget = QListWidget()
        for g in candidates:
            # Create an item for the list
            item = QListWidgetItem(g.get('name', 'Unknown'))
            # Store the full game object (g) in the item's data (UserRole)
            item.setData(Qt.UserRole, g) 
            self.list_widget.addItem(item)
            
        layout.addWidget(self.list_widget)
        
        btn_confirm = QPushButton("Confirm")
        btn_confirm.clicked.connect(self.accept)
        layout.addWidget(btn_confirm)
        
    def get_selected_candidate(self):
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.UserRole) # Retrieve the stored object
        return None

# The core display widget for a single game in the list.
# Handles image display, text wrapping, and buttons.
class GameCard(QWidget):
    def __init__(self, game_data, parent_window, item):
        super().__init__()
        self.data = game_data
        self.parent_window = parent_window
        self.item = item
        self.info_labels = [] # Store references for dynamic style updates
        self.cached_pixmap = None
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Get display settings from parent
        settings = getattr(self.parent_window, 'display_settings', {'image': 200, 'button': 45, 'text': 22})
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33) # Aspect ratio 3:4

        # Image
        self.img_label = QLabel()
        self.img_label.setFixedSize(img_w, img_h)
        self.img_label.setAlignment(Qt.AlignCenter)
        img_path = game_data.get('Image_Link', '')
        if img_path:
            self.img_label.setText("Loading...")
            self.start_image_load(img_path)
        else:
            self.img_label.setText("No Image")
            self.img_label.setStyleSheet("border: 1px solid #555;")
        self.img_label.installEventFilter(self)
        main_layout.addWidget(self.img_label, 0, Qt.AlignTop)
        
        # --- RIGHT COLUMN (DETAILS) ---
        # Details
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0) 
        details_layout.setSpacing(0)
        details_layout.setAlignment(Qt.AlignTop)
        
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Title Layout (Title + Path Label)
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        
        self.title_lbl = QLabel(game_data.get('Clean_Title', 'Unknown'))
        self.title_lbl.setStyleSheet(f"font-weight: bold; font-size: {settings.get('text', 22)}px;")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # SizePolicy ignored to allow text to shrink/wrap correctly in tight spaces
        self.title_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.title_lbl.setMinimumWidth(0)
        title_layout.addWidget(self.title_lbl)

        path_root = game_data.get('Path_Root', '')
        path_text = f"({path_root})" if path_root else ""
        self.path_lbl = QLabel(path_text)
        self.path_lbl.setStyleSheet("font-size: 11px; color: gray;")
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_lbl.setWordWrap(True)
        self.path_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.path_lbl.setMinimumWidth(0)
        title_layout.addWidget(self.path_lbl)
        
        header_layout.addLayout(title_layout, 1) # Give title stretch priority
        
        # Buttons
        self.video_path = str(game_data.get('Path_Video', '')).strip()
        self.trailer_link = game_data.get('Trailer_Link', '')

        has_local_video = bool(self.video_path and os.path.exists(self.video_path))
        # Check for a valid trailer link, ignoring our special flags.
        has_trailer = bool(self.trailer_link and self.trailer_link not in ['no_section', 'no_mp4'])

        button_definitions = {
            'local_video': {'enabled': has_local_video, 'fallback': "🎞️", 'font_size': "32px"},
            'youtube':     {'enabled': has_trailer,     'fallback': "▶", 'font_size': "30px"},
            'folder':      {'enabled': True,            'fallback': "📁", 'font_size': "32px"},
            'edit':        {'enabled': True,            'fallback': "✏️", 'font_size': "28px"},
            'scan':        {'enabled': True,            'fallback': "🔍", 'font_size': "28px"}
        }

        self.buttons = {}
        btn_size = settings.get('button', 45)
        for name, props in button_definitions.items():
            btn = QPushButton()
            self.buttons[name] = btn

            icon_to_load = name
            if not props['enabled'] and name in ['local_video', 'youtube']:
                icon_to_load = f"{name}_disabled"

            icon_path = f"icons/{icon_to_load}.png"
            icon_path = f"assets/{icon_to_load}.png"

            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
                btn.setIconSize(QSize(int(btn_size*0.7), int(btn_size*0.7)))
                btn.setStyleSheet("border: none;")
            else:
                # Fallback to emoji if icon file is missing
                fallback_emoji = props['fallback']
                font_size = props['font_size']
                style = f"font-size: {font_size}; border: none;"
                if fallback_emoji == "▶":
                    style += " color: #FF0000;"
                btn.setStyleSheet(style)
            
            btn.setEnabled(props['enabled'])
            
            if name == 'local_video' and not props['enabled'] and self.video_path:
                btn.setToolTip(f"File not found: {self.video_path}")

        buttons = [self.buttons['local_video'], self.buttons['youtube'], self.buttons['folder'], self.buttons['edit'], self.buttons['scan']]
            
        for btn in buttons:
            btn.setFixedSize(btn_size, btn_size)
            btn.installEventFilter(self)
            header_layout.addWidget(btn)

        self.buttons['local_video'].clicked.connect(self.start_video)
        self.buttons['youtube'].clicked.connect(self.start_trailer)
        self.buttons['folder'].clicked.connect(self.open_folder)
        self.buttons['edit'].clicked.connect(self.edit_game)
        self.buttons['scan'].clicked.connect(self.scan_game)
        
        details_layout.addLayout(header_layout)
        
        # Info
        info_font_size = max(10, settings.get('text', 22) - 6)
        # WHY: Reordered fields to group Platforms/Genre, Dev/Pub, and Collection. Added spacing between these groups.
        for field in ['Original_Release_Date', 'Platforms', 'Genre', 'Developer', 'Publisher', 'Collection']:
            display_name = 'Developer' # Default
            if field == 'Original_Release_Date': display_name = translator.tr("gamecard_info_release_date")
            elif field == 'Platforms': display_name = translator.tr("gamecard_info_platforms")
            elif field == 'Genre': display_name = translator.tr("gamecard_info_genre")            
            elif field == 'Developer': display_name = translator.tr("gamecard_info_developer")
            elif field == 'Publisher': display_name = translator.tr("gamecard_info_publisher")
            elif field == 'Collection': display_name = translator.tr("gamecard_info_collection")
            label = QLabel(f"<b>{display_name}:</b> {game_data.get(field, '')}")
            label.setStyleSheet(f"font-weight: bold; font-size: {info_font_size}px;")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            # Policy and MinimumWidth are crucial to prevent "disappearing buttons" bug
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
            details_layout.addWidget(label)
            self.info_labels.append(label)
            
            if field in ['Genre', 'Publisher']:
                details_layout.addSpacing(10)
        
        self.summary_title = QLabel(translator.tr("gamecard_summary_title"))
        self.summary_title.setStyleSheet(f"font-weight: bold; font-size: {info_font_size}px;")
        details_layout.addWidget(self.summary_title)

        summary_font_size = max(10, settings.get('text', 22) - 8)
        self.summary_content = QLabel(game_data.get('Summary', ''))
        self.summary_content.setWordWrap(True)
        self.summary_content.setStyleSheet(f"font-size: {summary_font_size}px;")
        self.summary_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Vertical Policy Minimum prevents the summary from forcing the card to be too tall
        self.summary_content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        details_layout.addWidget(self.summary_content)
        main_layout.addLayout(details_layout)

    def start_image_load(self, path):
        loader = ImageLoader(path)
        loader.signals.loaded.connect(self.on_image_loaded)
        self.parent_window.thread_pool.start(loader)

    def on_image_loaded(self, image):
        self.cached_pixmap = QPixmap.fromImage(image)
        self.update_image_display()

    def update_image_display(self):
        settings = getattr(self.parent_window, 'display_settings', {'image': 200})
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33)
        
        if self.cached_pixmap:
            self.img_label.setPixmap(self.cached_pixmap.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.img_label.setText("") # Clear text

    def update_style(self, settings):
        """Updates the card style dynamically."""
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33)
        btn_size = settings.get('button', 45)
        text_size = settings.get('text', 22)
        
        # Update Image
        self.img_label.setFixedSize(img_w, img_h)
        if self.cached_pixmap:
            self.img_label.setPixmap(self.cached_pixmap.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
        # Update Buttons
        for btn in self.buttons.values():
            btn.setFixedSize(btn_size, btn_size)
            if btn.icon().isNull(): # Emoji fallback
                # Simple heuristic for emoji font size
                btn.setStyleSheet(f"font-size: {int(btn_size*0.7)}px; border: none;")
            else:
                btn.setIconSize(QSize(int(btn_size*0.7), int(btn_size*0.7)))

        # Update Text
        self.title_lbl.setStyleSheet(f"font-weight: bold; font-size: {text_size}px;")
        
        info_size = max(10, text_size - 6)
        for lbl in self.info_labels:
            lbl.setStyleSheet(f"font-weight: bold; font-size: {info_size}px;")
        self.summary_title.setStyleSheet(f"font-weight: bold; font-size: {info_size}px;")
        self.summary_content.setStyleSheet(f"font-size: {max(10, text_size - 8)}px;")

    def calculate_size_hint(self, target_width):
        """
        Manually calculates the exact required height for the card at a specific width.
        Why: The standard sizeHint() often fails during resize events or when text wraps,
        leading to huge vertical gaps or cut-off text. We compute the math manually to guarantee precision.
        """
        m = self.layout().contentsMargins()
        spacing_main = self.layout().spacing()
        if spacing_main == -1: spacing_main = 6
        
        img_w = self.img_label.width()
        img_h = self.img_label.height()
        
        # Width available for the Details Column
        details_w = target_width - m.left() - m.right() - img_w - spacing_main
        if details_w <= 50: return QSize(target_width, max(img_h + m.top() + m.bottom(), 100))
        
        # 1. Header Height
        spacing_header = 6
        btn_count = 5
        btn_size = self.buttons['edit'].width()
        # 5 buttons + spacing between title_layout and buttons
        buttons_block_w = (btn_count * btn_size) + (btn_count * spacing_header)
        
        title_w = details_w - buttons_block_w
        if title_w < 10: title_w = 10
        
        h_title = self.title_lbl.heightForWidth(title_w)
        h_path = self.path_lbl.heightForWidth(title_w)
        # Fallback if heightForWidth returns -1 (valid for non-wrapping, but safe to check)
        if h_title <= 0: h_title = self.title_lbl.sizeHint().height()
        if h_path <= 0: h_path = self.path_lbl.sizeHint().height()
        
        h_header = max(h_title + h_path, btn_size)
        
        # 2. Rest of the content (Info + Summary)
        h_rest = 0
        labels_to_measure = self.info_labels + [self.summary_title, self.summary_content]
        for lbl in labels_to_measure:
            h = lbl.heightForWidth(details_w)
            if h <= 0: h = lbl.sizeHint().height()
            h_rest += h
            
        h_rest += 20 # WHY: Account for the 2x10px spacing added between info groups
            
        final_h = max(img_h, h_header + h_rest) + m.top() + m.bottom() + 4 # +4 buffer
        return QSize(target_width, final_h)

    def mousePressEvent(self, event):
        self.item.listWidget().setCurrentItem(self.item)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.MouseButtonPress:
                self.item.listWidget().setCurrentItem(self.item)
            return super().eventFilter(obj, event)
        except (KeyboardInterrupt, RuntimeError, AttributeError):
            return False

    def start_trailer(self):
        if self.trailer_link:
            logging.info(f"Opening trailer in browser: {self.trailer_link}")
            webbrowser.open(self.trailer_link, new=1)

    def start_video(self):
        if self.video_path and os.path.exists(self.video_path):
            try:
                logging.info(f"Opening local video with default player: {self.video_path}")
                os.startfile(self.video_path)
            except Exception as e:
                logging.error(f"Could not open local video: {e}")
                QMessageBox.critical(self.parent_window, "Error", f"Could not open video file:\n{e}")
        else:
            logging.warning(f"Attempted to play a non-existent local video: {self.video_path}")

    def open_folder(self):
        if os.path.exists(self.data.get('Path_Root', '')):
            os.startfile(self.data.get('Path_Root', ''))

    def edit_game(self):
        dlg = ActionDialog("dialog_edit_title", self.data, self.parent_window)
        if dlg.exec():
            new_data = dlg.get_data()
            if new_data:
                self.parent_window.update_game_data(self.data['Folder_Name'], new_data)

    def scan_game(self):
        if hasattr(self.parent_window, 'start_inline_scan'):
            self.parent_window.start_inline_scan(self.data)

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
        
        # 2. Game list (left, takes 3/4 of the space)
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.verticalScrollBar().setSingleStep(25)
        self.list_widget.verticalScrollBar().valueChanged.connect(self.check_scroll_load)
        main_layout.addWidget(self.list_widget, stretch=3)
        
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

    def show_statistics(self):
        dlg = StatisticsDialog(self.master_df, self)
        dlg.exec()

    def load_database_async(self):
        self.list_widget.clear()
        loading_item = QListWidgetItem("Loading Database...")
        loading_item.setTextAlignment(Qt.AlignCenter)
        self.list_widget.addItem(loading_item)
        self.sidebar.setEnabled(False)
        
        self.db_worker = DbLoaderWorker()
        self.db_worker.finished.connect(self.on_db_loaded)
        self.db_worker.start()

    def on_db_loaded(self, df):
        self.master_df = df
        self.list_widget.clear() # Remove Loading message
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
        self.request_filter_update()

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
        self.update_display_with_results(filtered_df)
        QApplication.restoreOverrideCursor()
        self.sidebar.setEnabled(True)
        self.list_widget.setEnabled(True)
        self.sidebar.search_bar.setFocus()

        if self.is_startup:
            self.is_startup = False
            if hasattr(self, 'pending_scroll') and self.pending_scroll > 0:
                # Use a timer to ensure the list has time to render before scrolling
                QTimer.singleShot(100, self.restore_scroll_position)

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
        if not hasattr(self, 'pending_scroll'): return
        
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

def apply_theme(app, theme_name):
    effective_theme = theme_name
    if theme_name == "System":
        try:
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            if value == 0:
                effective_theme = "Dark"
            else:
                effective_theme = "Light"
        except:
            pass

    # Always use Fusion to ensure consistency and palette respect
    app.setStyle(QStyleFactory.create("Fusion"))

    if effective_theme == "Dark":
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.WindowText, Qt.white)
        dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
        dark_palette.setColor(QPalette.ToolTipText, Qt.white)
        dark_palette.setColor(QPalette.Text, Qt.white)
        dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ButtonText, Qt.white)
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.Highlight, QColor(50, 50, 50))
        dark_palette.setColor(QPalette.HighlightedText, Qt.white)
        
        # WHY: Explicitly set disabled colors so disabled widgets (like All/None buttons) actually look greyed out.
        dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.gray)
        dark_palette.setColor(QPalette.Disabled, QPalette.Text, Qt.gray)
        dark_palette.setColor(QPalette.Disabled, QPalette.WindowText, Qt.gray)
        
        app.setPalette(dark_palette)
    else: # Light or System
        # Force a Light Palette to ensure it doesn't inherit Dark Mode from OS
        light_palette = QPalette()
        light_palette.setColor(QPalette.Window, QColor(240, 240, 240))
        light_palette.setColor(QPalette.WindowText, Qt.black)
        light_palette.setColor(QPalette.Base, Qt.white)
        light_palette.setColor(QPalette.AlternateBase, QColor(233, 233, 233))
        light_palette.setColor(QPalette.ToolTipBase, Qt.white)
        light_palette.setColor(QPalette.ToolTipText, Qt.black)
        light_palette.setColor(QPalette.Text, Qt.black)
        light_palette.setColor(QPalette.Button, QColor(240, 240, 240))
        light_palette.setColor(QPalette.ButtonText, Qt.black)
        light_palette.setColor(QPalette.BrightText, Qt.red)
        light_palette.setColor(QPalette.Link, QColor(0, 0, 255))
        
        # Custom Highlight (Grey instead of Blue)
        light_palette.setColor(QPalette.Highlight, QColor(200, 200, 200))
        light_palette.setColor(QPalette.HighlightedText, Qt.black)
        
        # WHY: Explicitly set disabled colors so disabled widgets (like All/None buttons) actually look greyed out.
        light_palette.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.gray)
        light_palette.setColor(QPalette.Disabled, QPalette.Text, Qt.gray)
        light_palette.setColor(QPalette.Disabled, QPalette.WindowText, Qt.gray)
        
        app.setPalette(light_palette)

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