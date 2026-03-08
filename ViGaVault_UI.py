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
from ViGaVault_Scan import LibraryManager, get_safe_filename, get_platform_config
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton, QStackedLayout, QFileDialog, QScrollArea,
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox, QFrame, QAbstractItemView, QCheckBox, QSlider, QStyle, QGroupBox)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent, QUrl, QThread, Signal, QObject, Slot
from PySide6.QtGui import QPixmap, QIcon


DB_FILE = "VGVDB.csv"

# --- Custom Logging Handler for UI ---
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

# --- Worker Thread for GOG Sync ---
class GogSyncWorker(QThread):
    def run(self):
        """Runs the GOG sync process."""
        try:
            # We create the manager inside the thread
            manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
            manager.load_db()
            manager.sync_gog(worker_thread=self)
        except Exception as e:
            # Log any exceptions that happen inside the thread
            logging.error(f"Critical error in GOG sync thread: {e}")

class LocalScanWorker(QThread):
    def __init__(self, retry_failures=False):
        super().__init__()
        self.retry_failures = retry_failures

    def run(self, ):
        """Runs the local folder scan process."""
        try:
            # We create the manager inside the thread
            manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
            manager.load_db()
            # Pass the thread itself to the manager so it can check for interruption
            manager.scan(retry_failures=self.retry_failures, worker_thread=self)
        except Exception as e:
            # Log any exceptions that happen inside the thread
            logging.error(f"Critical error in local scan thread: {e}")

class FullScanWorker(QThread):
    def __init__(self, retry_failures=False):
        super().__init__()
        self.retry_failures = retry_failures

    def run(self):
        """Runs the full scan process."""
        try:
            manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
            manager.load_db()
            manager.scan_full(retry_failures=self.retry_failures, worker_thread=self)
        except Exception as e:
            logging.error(f"Critical error in full scan thread: {e}")

class FilterWorker(QThread):
    finished = Signal(object)

    def __init__(self, master_df, params, parent=None):
        super().__init__(parent)
        self.master_df = master_df
        self.params = params

    def run(self):
        df = self.master_df.copy()

        # Text Filter
        search = self.params['search_text'].lower()
        if search:
            df = df[df['Clean_Title'].str.lower().str.contains(search)]
            
        # Platform Filter
        selected_platforms = self.params['selected_platforms']
        if selected_platforms:
            regex_pattern = '|'.join([re.escape(p) for p in selected_platforms])
            df = df[df['Platforms'].astype(str).str.contains(regex_pattern, case=False, na=False)]
        else:
            df = df.iloc[0:0]

        # Quick Filters
        if self.params['chk_new']:
            df = df[df['Status_Flag'] != 'OK']
        else:
            df = df[df['Status_Flag'] == 'OK']
        
        if self.params['chk_a_tester']:
            df = df[df['Path_Root'].str.contains('_temp', case=False, na=False)]

        if self.params['chk_vr']:
            df = df[df['Path_Root'].str.contains('VR', case=False, na=False)]
            
        # Sorting
        sort_col = self.params['sort_col']
        sort_desc = self.params['sort_desc']
        
        if sort_col == "temp_sort_date" or sort_col == "temp_sort_title":
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last' if sort_col == "temp_sort_date" else 'first')
        else:
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last')
        
        self.finished.emit(df)

# --- Dialog Windows for Editing and Scanning ---
class ActionDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(850)
        self.original_data = data.copy()
        self.updated_data = {}

        super_main_layout = QVBoxLayout(self)

        # --- Left Column (Form) ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
 
        metadata_group = QGroupBox("Metadata")
        self.form_layout = QFormLayout(metadata_group)
        self.inputs = {}
        fields_to_disable = [
            'Folder_Name', 'Path_Root', 'Path_Video', 'Status_Flag', 'Image_Link', 
            'Year_Folder', 'Platforms'
        ]
        fields_to_exclude = [
            'Trailer_Link', 'game_ID', 'Image_Link', 'temp_sort_date', 'temp_sort_title'
        ]

        for field, value in self.original_data.items():
            if field in fields_to_exclude:
                continue
            label_text = field.replace('_', ' ').title()
            if field == "Summary":
                inp = QTextEdit(str(value))
            else:
                inp = QLineEdit(str(value))
            if field in fields_to_disable:
                inp.setEnabled(False)
            self.form_layout.addRow(label_text, inp)
            self.inputs[field] = inp
 
        left_layout.addWidget(metadata_group)

        # --- Right Column (Media) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Section 1: Cover Image
        cover_group = QGroupBox("Cover Image")
        cover_layout = QVBoxLayout(cover_group)
        self.cover_image_label = QLabel("No Cover")
        self.cover_image_label.setAlignment(Qt.AlignCenter)
        self.cover_image_label.setFixedSize(200, 266)
        self.update_cover_display()
        btn_select_image = QPushButton("Select another Image From Disk")
        btn_select_image.clicked.connect(self.select_new_image)
        cover_layout.addWidget(self.cover_image_label, 0, Qt.AlignHCenter)
        cover_layout.addWidget(btn_select_image)
        right_layout.addWidget(cover_group)

        # Section 2: Trailer
        self.trailer_group = QGroupBox("Trailer")
        self.trailer_layout = QVBoxLayout(self.trailer_group)
        self.trailer_thumbnail_label = QLabel("No Trailer")
        self.trailer_thumbnail_label.setAlignment(Qt.AlignCenter)
        self.trailer_thumbnail_label.setFixedSize(320, 180)
        self.trailer_layout.addWidget(self.trailer_thumbnail_label, 0, Qt.AlignHCenter)

        # URL display and copy button
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.url_line_edit = QLineEdit()
        self.url_line_edit.setReadOnly(True)
        url_layout.addWidget(self.url_line_edit)
        copy_btn = QPushButton("📋")
        copy_btn.setToolTip("Copy URL to clipboard")
        copy_btn.clicked.connect(self.copy_trailer_url)
        url_layout.addWidget(copy_btn)
        self.trailer_layout.addLayout(url_layout)

        self.btn_play_trailer = QPushButton("Play in browser")
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
        btn_save = QPushButton("Save")
        btn_cancel = QPushButton("Cancel")
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        button_box.addWidget(btn_save)
        button_box.addStretch()
        button_box.addWidget(btn_cancel)
        super_main_layout.addLayout(button_box)

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
        if not self.trailer_link:
            self.trailer_group.hide()
            return
        thumbnail_data = None
        self.url_line_edit.setText(self.trailer_link)

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
            self.trailer_group.hide()
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

        # --- RENAME MEDIA FILES IF TITLE OR DATE CHANGED ---
        old_title = self.original_data.get('Clean_Title', '')
        new_title = new_data.get('Clean_Title', '')
        old_date = self.original_data.get('Original_Release_Date', '')
        new_date = new_data.get('Original_Release_Date', '')

        if new_title != old_title or new_date != old_date:
            # Calculate new base filename
            base_filename = new_title
            if new_date and len(new_date) >= 4:
                base_filename += f" ({new_date[-4:]})"
            
            new_safe_name = get_safe_filename(base_filename)
            
            # Rename Image
            old_img_path = new_data.get('Image_Link', '')
            if old_img_path and os.path.exists(old_img_path):
                dir_name = os.path.dirname(old_img_path)
                ext = os.path.splitext(old_img_path)[1]
                new_img_path = os.path.join(dir_name, f"{new_safe_name}{ext}")
                if new_img_path != old_img_path:
                    try:
                        os.rename(old_img_path, new_img_path)
                        new_data['Image_Link'] = new_img_path
                    except Exception as e:
                        logging.error(f"Failed to rename image: {e}")

            # Rename Video
            old_vid_path = new_data.get('Path_Video', '')
            if old_vid_path and os.path.exists(old_vid_path) and "videos" in os.path.abspath(old_vid_path):
                dir_name = os.path.dirname(old_vid_path)
                ext = os.path.splitext(old_vid_path)[1]
                new_vid_path = os.path.join(dir_name, f"{new_safe_name}{ext}")
                if new_vid_path != old_vid_path:
                    try:
                        os.rename(old_vid_path, new_vid_path)
                        new_data['Path_Video'] = new_vid_path
                    except Exception as e:
                        logging.error(f"Failed to rename video: {e}")

        return new_data

class Sidebar(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.setFixedWidth(350)
        self.layout = QVBoxLayout(self)
        
        # --- FILTER PANEL ---
        self.filter_panel = QWidget()
        self.filter_layout = QVBoxLayout(self.filter_panel)
        
        label_style = "font-weight: bold; font-size: 16px;"
        
        # 1. Header (Recherche + Compteur)
        header_layout = QHBoxLayout()
        lbl_search = QLabel("Search")
        lbl_search.setStyleSheet(label_style)
        header_layout.addWidget(lbl_search)
        header_layout.addStretch()
        self.lbl_counter = QLabel("0/0")
        self.lbl_counter.setStyleSheet("font-weight: bold; font-size: 20px; color: white;")
        header_layout.addWidget(self.lbl_counter)
        self.filter_layout.addLayout(header_layout)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Game name...")
        self.search_bar.setClearButtonEnabled(True)
        self.filter_layout.addWidget(self.search_bar)
        
        # 3. Tri
        lbl_sort = QLabel("Sort by")
        lbl_sort.setStyleSheet(label_style)
        self.filter_layout.addWidget(lbl_sort)

        sort_layout = QHBoxLayout()
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["Name", "Release Date", "Developer"])
        sort_layout.addWidget(self.combo_sort, 4)
        
        self.btn_toggle_sort = QPushButton("⇅ Order")
        self.btn_toggle_sort.setStyleSheet("font-size: 16px;")
        sort_layout.addWidget(self.btn_toggle_sort, 1)
        self.filter_layout.addLayout(sort_layout)

        # --- FILTERS ---
        filters_group = QGroupBox("Filters")
        self.filters_layout = QGridLayout(filters_group)
        self.filter_layout.addWidget(filters_group)

        # --- PLATFORMS ---
        self.platforms_group = QGroupBox("Platforms")
        self.platforms_layout = QGridLayout(self.platforms_group)
        self.filter_layout.addWidget(self.platforms_group)

        self.platform_checkboxes = []


        # --- GOG SYNC BUTTON ---
        self.btn_sync_gog = QPushButton("Sync GOG")
        self.filter_layout.addWidget(self.btn_sync_gog)

        # --- LOCAL SCAN BUTTON ---
        scan_local_layout = QHBoxLayout()
        self.btn_scan_local = QPushButton("Scan Local Folders")
        scan_local_layout.addWidget(self.btn_scan_local, 3)

        self.chk_retry_failures = QCheckBox("Retry")
        self.chk_retry_failures.setToolTip("If checked, the scan will attempt to retrieve metadata for games marked 'NEEDS_ATTENTION'.")
        scan_local_layout.addWidget(self.chk_retry_failures, 1)
        
        self.filter_layout.addLayout(scan_local_layout)

        # --- FULL SCAN BUTTON ---
        self.btn_full_scan = QPushButton("Full Scan (GOG + Local)")
        self.filter_layout.addWidget(self.btn_full_scan)

        # --- PANNEAU SCAN ---
        self.scan_panel = QWidget()
        self.scan_layout = QVBoxLayout(self.scan_panel)
        
        # Ligne de séparation
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.scan_layout.addWidget(line)
        
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Game name to search...")

        scan_action_layout = QHBoxLayout()
        self.scan_btn = QPushButton("Search")
        scan_action_layout.addWidget(self.scan_btn, 3)

        self.scan_limit_combo = QComboBox()
        self.scan_limit_combo.addItems(['10', '20', '30', '40', '50'])
        self.scan_limit_combo.setCurrentText('10')
        self.scan_limit_combo.setToolTip("Number of results to display.")
        scan_action_layout.addWidget(self.scan_limit_combo, 1)

        self.scan_results = QListWidget()
        self.scan_results.setIconSize(QSize(50, 70))

        self.btns_layout = QHBoxLayout()
        self.btn_confirm = QPushButton("Confirm Choice")
        self.btn_cancel = QPushButton("Cancel")
        self.btns_layout.addWidget(self.btn_confirm)
        self.btns_layout.addWidget(self.btn_cancel)
        
        self.scan_title_label = QLabel("Manual Scan")
        self.scan_layout.addWidget(self.scan_title_label)
        self.scan_layout.addWidget(self.scan_input)
        self.scan_layout.addLayout(scan_action_layout)
        self.scan_layout.addWidget(self.scan_results)
        self.scan_layout.addLayout(self.btns_layout)
        
        self.filter_layout.addWidget(self.scan_panel, 1)
        self.filter_layout.addStretch()
        self.layout.addWidget(self.filter_panel)
        self.scan_panel.hide() 
        
        # --- CONNECTIONS ---
        self.search_bar.textChanged.connect(self.parent.request_filter_update)
        self.combo_sort.currentIndexChanged.connect(self.parent.request_filter_update)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        self.btn_sync_gog.clicked.connect(self.parent.start_gog_sync)
        self.btn_scan_local.clicked.connect(self.parent.start_local_scan)
        self.btn_full_scan.clicked.connect(self.parent.start_full_scan)

        # Scan Connections
        self.scan_btn.clicked.connect(self.parent.on_manual_search_trigger)
        self.scan_input.returnPressed.connect(self.parent.on_manual_search_trigger)
        self.btn_confirm.clicked.connect(self.parent.apply_inline_selection)
        self.btn_cancel.clicked.connect(self.parent.cancel_inline_scan)
        self.scan_results.itemDoubleClicked.connect(self.parent.apply_inline_selection)

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

class GameCard(QWidget):
    def __init__(self, game_data, parent_window, item):
        super().__init__()
        self.data = game_data
        self.parent_window = parent_window
        self.item = item
        
        main_layout = QHBoxLayout(self)
        
        # Image
        self.img_label = QLabel()
        self.img_label.setFixedSize(200, 266)
        self.img_label.setAlignment(Qt.AlignCenter)
        img_path = game_data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path).scaled(200, 266, Qt.KeepAspectRatio, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)
        else:
            self.img_label.setText("No Image")
            self.img_label.setStyleSheet("border: 1px solid #555;")
        self.img_label.installEventFilter(self)
        main_layout.addWidget(self.img_label)
        
        # Details
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0) 
        details_layout.setSpacing(2)
        
        header_layout = QHBoxLayout()
        
        title_layout = QVBoxLayout()
        title_layout.setSpacing(0)
        
        title = QLabel(game_data.get('Clean_Title', 'Unknown'))
        title.setStyleSheet("font-weight: bold; font-size: 22px;")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.installEventFilter(self)
        title_layout.addWidget(title)
        
        path_lbl = QLabel(f"({game_data.get('Path_Root', '')})")
        path_lbl.setStyleSheet("font-size: 11px; color: gray;")
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_lbl.installEventFilter(self)
        title_layout.addWidget(path_lbl)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        # Buttons
        self.video_path = game_data.get('Path_Video', '')
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
        for name, props in button_definitions.items():
            btn = QPushButton()
            self.buttons[name] = btn

            icon_to_load = name
            if not props['enabled'] and name in ['local_video', 'youtube']:
                icon_to_load = f"{name}_disabled"

            icon_path = f"icons/{icon_to_load}.png"

            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
                btn.setIconSize(QSize(35, 35))
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

        buttons = [self.buttons['local_video'], self.buttons['youtube'], self.buttons['folder'], self.buttons['edit'], self.buttons['scan']]
            
        for btn in buttons:
            btn.setFixedSize(45, 45)
            btn.installEventFilter(self)
            header_layout.addWidget(btn)

        self.buttons['local_video'].clicked.connect(self.start_video)
        self.buttons['youtube'].clicked.connect(self.start_trailer)
        self.buttons['folder'].clicked.connect(self.open_folder)
        self.buttons['edit'].clicked.connect(self.edit_game)
        self.buttons['scan'].clicked.connect(self.scan_game)
        
        details_layout.addLayout(header_layout)
        
        # Info
        for field in ['Original_Release_Date', 'Platforms', 'Developer']:
            display_name = 'Developer' # Default
            if field == 'Original_Release_Date':
                display_name = 'Release Date'
            elif field == 'Platforms':
                display_name = 'Platform(s)'

            label = QLabel(f"{display_name}: {game_data.get(field, '')}")
            label.setStyleSheet("font-weight: bold; font-size: 16px;")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.installEventFilter(self)
            details_layout.addWidget(label)
        
        summary_title = QLabel("Summary")
        summary_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        details_layout.addWidget(summary_title)

        summary_content = QLabel(game_data.get('Summary', ''))
        summary_content.setWordWrap(True)
        summary_content.setStyleSheet("font-size: 14px;")
        summary_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary_content.installEventFilter(self)
        details_layout.addWidget(summary_content)
        main_layout.addLayout(details_layout)

    def mousePressEvent(self, event):
        self.item.listWidget().setCurrentItem(self.item)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            self.item.listWidget().setCurrentItem(self.item)
        return super().eventFilter(obj, event)

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
        dlg = ActionDialog("Edit Game", self.data, self.parent_window)
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
        self.setWindowTitle("ViGaVault Library")
        self.resize(1200, 800)
        self.is_startup = True
        self.sort_desc = True
        
        
        # Variables for Lazy Loading
        self.batch_size = 30
        self.current_df = pd.DataFrame()
        self.loaded_count = 0
        
        # Timer for background loading
        self.background_loader = QTimer()
        self.background_loader.setInterval(100) # Load a batch every 100ms
        self.background_loader.timeout.connect(self.load_more_items)
        
        # Timer to avoid reloading the list on every keystroke (Debounce)
        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(300) # Wait 300ms after the last change
        self.filter_timer.timeout.connect(self.start_filter_worker)

        self.current_scan_game = None
        self.gog_sync_in_progress = False # Flag to prevent multiple syncs
        self.local_scan_in_progress = False
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
        
        # 4. Data loading
        if os.path.exists(DB_FILE):
            self.master_df = pd.read_csv(DB_FILE, sep=';', encoding='utf-8').fillna('')
            
            # Pre-calculate columns for faster sorting
            self.master_df['temp_sort_date'] = pd.to_datetime(self.master_df['Original_Release_Date'], errors='coerce', dayfirst=True)
            self.master_df['temp_sort_title'] = self.master_df['Clean_Title'].str.lower()
        else:
            # Initialize empty DataFrame if DB doesn't exist
            self.master_df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
            self.master_df['temp_sort_date'] = pd.to_datetime([])
            self.master_df['temp_sort_title'] = []
            
        # Populate Filters section (Static)
        self.sidebar.chk_new = QCheckBox("NEW")
        self.sidebar.chk_a_tester = QCheckBox("TO TEST")
        self.sidebar.chk_vr = QCheckBox("VR")

        # Add main filters
        self.sidebar.filters_layout.addWidget(self.sidebar.chk_new, 0, 0)
        self.sidebar.filters_layout.addWidget(self.sidebar.chk_a_tester, 0, 1)
        self.sidebar.filters_layout.addWidget(self.sidebar.chk_vr, 0, 2)

        self.sidebar.chk_new.stateChanged.connect(self.request_filter_update)
        self.sidebar.chk_a_tester.stateChanged.connect(self.request_filter_update)
        self.sidebar.chk_vr.stateChanged.connect(self.request_filter_update)

        # Populate platforms in the sidebar (Dynamic)
        self.populate_platforms()
            
        # --- RESTORATION ---
        if os.path.exists("settings.json"):
            saved_scroll = self.load_settings()
            if saved_scroll:
                self.pending_scroll = saved_scroll
        else:
            # Default sort on "Release Date"
            self.sidebar.combo_sort.setCurrentIndex(1)
        
        # Initial display
        self.request_filter_update()

    def populate_platforms(self):
        """Rebuilds the platform checkboxes based on the current master_df."""
        # Clear existing items in the layout
        layout = self.sidebar.platforms_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.sidebar.platform_checkboxes = []

        # Get platforms
        all_platforms = set()
        if hasattr(self, 'master_df') and not self.master_df.empty and 'Platforms' in self.master_df.columns:
            for platform_list in self.master_df['Platforms'].dropna().unique():
                for platform in str(platform_list).split(','):
                    p = platform.strip()
                    if p:
                        all_platforms.add(p)
        
        has_warez = "Warez" in all_platforms
        if has_warez:
            all_platforms.remove("Warez")

        # Re-add buttons
        btn_all_platforms = QPushButton("All")
        btn_none_platforms = QPushButton("None")
        
        btn_all_platforms.clicked.connect(self.select_all_platforms)
        btn_none_platforms.clicked.connect(self.select_none_platforms)

        layout.addWidget(btn_all_platforms, 0, 0)
        layout.addWidget(btn_none_platforms, 0, 1)
        
        row, col = 0, 2 # Start after buttons

        if has_warez:
            self.sidebar.chk_warez = QCheckBox("Warez")
            self.sidebar.chk_warez.stateChanged.connect(self.request_filter_update)
            layout.addWidget(self.sidebar.chk_warez, row, col)
            self.sidebar.platform_checkboxes.append(self.sidebar.chk_warez)
            col += 1
        
        for platform in sorted(list(all_platforms)):
            if col > 2:
                col = 0
                row += 1
            chk = QCheckBox(platform)
            chk.stateChanged.connect(self.request_filter_update)
            layout.addWidget(chk, row, col)
            self.sidebar.platform_checkboxes.append(chk)
            col += 1
            
        # Default to checked to ensure visibility of new data
        for chk in self.sidebar.platform_checkboxes:
            chk.setChecked(True)

    def start_gog_sync(self):
        if self.gog_sync_in_progress or self.local_scan_in_progress or self.full_scan_in_progress:
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

        self.gog_sync_in_progress = True
        self.sidebar.btn_sync_gog.setEnabled(False)
        self.sidebar.btn_sync_gog.setText("Syncing...")
        self.sidebar.btn_full_scan.setEnabled(False)
        self.sidebar.btn_scan_local.setEnabled(False)

        # Show the scan panel as a log viewer
        self.sidebar.scan_panel.show()
        self.sidebar.scan_title_label.setText("GOG Sync")
        self.sidebar.scan_input.hide()
        self.sidebar.scan_btn.hide()
        self.sidebar.scan_limit_combo.hide()
        self.sidebar.btn_confirm.hide()
        self.sidebar.btn_cancel.setText("Stop")
        self.sidebar.scan_results.clear()
        self.sidebar.scan_results.addItem("Starting GOG sync...")

        # Disconnect previous signals and connect the stop function
        try: self.sidebar.btn_cancel.clicked.disconnect()
        except: pass
        self.sidebar.btn_cancel.clicked.connect(self.stop_gog_sync)

        # Setup logging to UI
        self.log_signal = QtLogSignal()
        self.log_signal.message_written.connect(self.update_sync_log)
        self.qt_log_handler = QtLogHandler(self.log_signal)
        logging.getLogger().addHandler(self.qt_log_handler)

        # Setup and start worker thread
        self.gog_worker = GogSyncWorker()
        self.gog_worker.finished.connect(self.finish_gog_sync)
        self.gog_worker.start()

    def stop_gog_sync(self):
        """Requests interruption of the GOG sync thread and closes the panel."""
        if self.gog_sync_in_progress and hasattr(self, 'gog_worker'):
            logging.info("--- GOG Sync interrupted by user. ---")
            self.gog_worker.requestInterruption()
            self.sidebar.scan_panel.hide()
            self.restore_scan_panel()

    def update_sync_log(self, message):
        self.sidebar.scan_results.addItem(message)
        self.sidebar.scan_results.scrollToBottom()

    def finish_gog_sync(self):
        logging.getLogger().removeHandler(self.qt_log_handler)

        # If the panel is still visible, it means the sync completed without interruption.
        if self.sidebar.scan_panel.isVisible():
            self.sidebar.scan_results.addItem("--- Sync complete! ---")
            self.sidebar.scan_results.scrollToBottom()
            # Change button to "Close" and set its action to close the panel.
            self.sidebar.btn_cancel.setText("Close")
            try: self.sidebar.btn_cancel.clicked.disconnect()
            except: pass
            self.sidebar.btn_cancel.clicked.connect(self.cancel_inline_scan)

        self.gog_sync_in_progress = False
        self.sidebar.btn_sync_gog.setEnabled(True)
        self.sidebar.btn_sync_gog.setText("Sync GOG")
        self.sidebar.btn_full_scan.setEnabled(True)
        self.sidebar.btn_scan_local.setEnabled(True)
        self.refresh_data()

    def start_local_scan(self):
        if self.gog_sync_in_progress or self.local_scan_in_progress or self.full_scan_in_progress:
            QMessageBox.information(self, "Info", "Another task is already in progress.")
            return

        self.local_scan_in_progress = True
        self.sidebar.btn_scan_local.setEnabled(False)
        self.sidebar.btn_scan_local.setText("Scanning...")
        self.sidebar.btn_full_scan.setEnabled(False)
        self.sidebar.btn_sync_gog.setEnabled(False)

        # Show the scan panel as a log viewer
        self.sidebar.scan_panel.show()
        self.sidebar.scan_title_label.setText("Local Folders Scan")
        self.sidebar.scan_input.hide()
        self.sidebar.scan_btn.hide()
        self.sidebar.scan_limit_combo.hide()
        self.sidebar.btn_confirm.hide()
        self.sidebar.btn_cancel.setText("Stop")
        self.sidebar.scan_results.clear()
        self.sidebar.scan_results.addItem("Starting local folders scan...")

        # Disconnect previous signals and connect the stop function
        try: self.sidebar.btn_cancel.clicked.disconnect()
        except: pass
        self.sidebar.btn_cancel.clicked.connect(self.stop_local_scan)

        # Setup logging to UI
        self.log_signal = QtLogSignal()
        self.log_signal.message_written.connect(self.update_sync_log)
        self.qt_log_handler = QtLogHandler(self.log_signal)
        logging.getLogger().addHandler(self.qt_log_handler)

        # Setup and start worker thread
        retry = self.sidebar.chk_retry_failures.isChecked()
        self.local_scan_worker = LocalScanWorker(retry_failures=retry)
        self.local_scan_worker.finished.connect(self.finish_local_scan)
        self.local_scan_worker.start()

    def stop_local_scan(self):
        """Requests interruption of the local scan thread and closes the panel."""
        if self.local_scan_in_progress and hasattr(self, 'local_scan_worker'):
            logging.info("--- Scan interrupted by user. ---")
            self.local_scan_worker.requestInterruption()
            self.sidebar.scan_panel.hide()
            self.restore_scan_panel()

    def finish_local_scan(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        
        self.local_scan_in_progress = False
        self.sidebar.btn_scan_local.setEnabled(True)
        self.sidebar.btn_scan_local.setText("Scan Local Folders")
        self.sidebar.btn_full_scan.setEnabled(True)
        self.sidebar.btn_sync_gog.setEnabled(True)

        # If the panel is still visible, it means the scan completed without interruption.
        if self.sidebar.scan_panel.isVisible():
            self.sidebar.scan_results.addItem("--- Folder scan finished! ---")
            self.sidebar.scan_results.scrollToBottom()
            # Change button to "Close" and set its action to close the panel.
            self.sidebar.btn_cancel.setText("Close")
            try: self.sidebar.btn_cancel.clicked.disconnect()
            except: pass
            self.sidebar.btn_cancel.clicked.connect(self.cancel_inline_scan)

        self.refresh_data()

    def start_full_scan(self):
        if self.gog_sync_in_progress or self.local_scan_in_progress or self.full_scan_in_progress:
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
        self.sidebar.btn_sync_gog.setEnabled(False)
        self.sidebar.btn_scan_local.setEnabled(False)

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
        retry = self.sidebar.chk_retry_failures.isChecked()
        self.full_scan_worker = FullScanWorker(retry_failures=retry)
        self.full_scan_worker.finished.connect(self.finish_full_scan)
        self.full_scan_worker.start()

    def stop_full_scan(self):
        """Requests interruption of the full scan thread and closes the panel."""
        if self.full_scan_in_progress and hasattr(self, 'full_scan_worker'):
            logging.info("--- Full Scan interrupted by user. ---")
            self.full_scan_worker.requestInterruption()
            self.sidebar.scan_panel.hide()
            self.restore_scan_panel()

    def finish_full_scan(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        
        self.full_scan_in_progress = False
        self.sidebar.btn_full_scan.setEnabled(True)
        self.sidebar.btn_full_scan.setText("Full Scan (GOG + Local)")
        self.sidebar.btn_sync_gog.setEnabled(True)
        self.sidebar.btn_scan_local.setEnabled(True)

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

        self.restore_scan_panel()
        
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

        # On diffère légèrement le lancement pour laisser l'interface s'afficher (message d'attente)
        # This logic is now here to ensure the context is always correct.
        if hasattr(self, 'run_inline_search'):
            QTimer.singleShot(50, self.run_inline_search)

    def update_game_data(self, folder_name, new_data):
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        
        game_obj = manager.games.get(folder_name)
        if not game_obj:
            QMessageBox.critical(self, "Error", f"Game '{folder_name}' not found in the database.")
            return

        # Met à jour les données du jeu
        for key, value in new_data.items():
            game_obj.data[key] = value
        
        # Sauvegarde dans le CSV
        while True:
            try:
                manager.save_db()
                break
            except PermissionError:
                reply = QMessageBox.warning(self, "File Locked",
                                    f"The file {DB_FILE} is open in another program (e.g., Excel).\n\n"
                                    "Please close it, then click OK to retry.",
                                    QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Cancel:
                    return
        
        QMessageBox.information(self, "Success", "Changes have been saved.")
        
        # Refresh the interface to show changes
        # The existing anchoring system will handle repositioning the view
        self.refresh_data()

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
        
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
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
                    pass # On ignore silencieusement les erreurs d'image pour ne pas bloquer
            self.sidebar.scan_results.addItem(item)

        if not candidates:
            item = QListWidgetItem("No results found.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.sidebar.scan_results.addItem(item)

    def restore_scan_panel(self):
        """Resets the scan panel to its default state for manual scanning."""
        self.sidebar.scan_title_label.setText("Manual Scan")
        self.sidebar.scan_input.show()
        self.sidebar.scan_btn.show()
        self.sidebar.scan_limit_combo.show()
        self.sidebar.btn_confirm.show()
        self.sidebar.btn_cancel.setText("Cancel")

    def cancel_inline_scan(self):
        self.sidebar.scan_panel.hide()
        self.sidebar.scan_results.clear()
        self.sidebar.scan_input.clear()
        self.restore_scan_panel() # Ensure it's reset for next time

    def apply_inline_selection(self):
        item = self.sidebar.scan_results.currentItem()
        if not item: return
        
        chosen_game = item.data(Qt.UserRole)
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        game_obj = manager.games.get(self.current_scan_game.get('Folder_Name'))
        
        if game_obj.apply_candidate_data(chosen_game):
            while True:
                try:
                    manager.save_db()
                    break
                except PermissionError:
                    reply = QMessageBox.warning(self, "File Locked",
                                        f"The file {DB_FILE} is open in another program (e.g., Excel).\n\n"
                                        "Please close it, then click OK to retry.",
                                        QMessageBox.Ok | QMessageBox.Cancel)
                    if reply == QMessageBox.Cancel:
                        return

            self.refresh_data()
            
            # Position the list on the modified game
            target_folder = self.current_scan_game.get('Folder_Name')
            
            # Find the position of the game in the full data list
            folders_list = self.current_df['Folder_Name'].tolist()
            if target_folder in folders_list:
                row_index = folders_list.index(target_folder)
                
                # Force loading items until this row is reached
                while self.loaded_count <= row_index:
                    self.load_more_items()
                
                # Now that the item is created, we can select it
                list_item = self.list_widget.item(row_index)
                if list_item:
                    self.list_widget.scrollToItem(list_item)
                    self.list_widget.setCurrentItem(list_item)
            
            self.sidebar.scan_results.clear()
            item = QListWidgetItem("Update complete!")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.sidebar.scan_results.addItem(item)
            
            # Fermeture automatique du panneau après 2 secondes
            QTimer.singleShot(2000, self.cancel_inline_scan)

    def select_all_platforms(self):
        for chk in self.sidebar.platform_checkboxes:
            chk.blockSignals(True)
        for chk in self.sidebar.platform_checkboxes:
            chk.setChecked(True)
        for chk in self.sidebar.platform_checkboxes:
            chk.blockSignals(False)
        self.request_filter_update()

    def select_none_platforms(self):
        for chk in self.sidebar.platform_checkboxes:
            chk.blockSignals(True)
        for chk in self.sidebar.platform_checkboxes:
            chk.setChecked(False)
        for chk in self.sidebar.platform_checkboxes:
            chk.blockSignals(False)
        self.request_filter_update()

    def closeEvent(self, event):
        self.save_settings()
        event.accept()

    def save_settings(self):
        # Load existing settings first to preserve keys not managed by UI (like platform_map)
        current_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r") as f:
                    current_settings = json.load(f)
            except: pass

        current_settings.update({
            "geometry": self.saveGeometry().toBase64().data().decode(),
            "sort_desc": self.sort_desc,
            "sort_index": self.sidebar.combo_sort.currentIndex(),
            "checked_platforms": [chk.text() for chk in self.sidebar.platform_checkboxes if chk.isChecked()],
            "search_text": self.sidebar.search_bar.text(),
            "scroll_value": self.list_widget.verticalScrollBar().value(),
            "chk_new": self.sidebar.chk_new.isChecked() if hasattr(self.sidebar, 'chk_new') else False,
            "chk_a_tester": self.sidebar.chk_a_tester.isChecked() if hasattr(self.sidebar, 'chk_a_tester') else False,
            "chk_vr": self.sidebar.chk_vr.isChecked() if hasattr(self.sidebar, 'chk_vr') else False,
        })

        # Ensure platform config exists in file if it wasn't there
        if "platform_map" not in current_settings:
             pm, ip = get_platform_config()
             current_settings["platform_map"] = pm
             current_settings["ignored_prefixes"] = ip

        try:
            with open("settings.json", "w") as f:
                json.dump(current_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def load_settings(self):
        try:
            with open("settings.json", "r") as f:
                settings = json.load(f)
            
            if "geometry" in settings:
                self.restoreGeometry(QByteArray.fromBase64(settings["geometry"].encode()))
                
            self.sort_desc = settings.get("sort_desc", True)
            
            # Block signals to avoid triggering apply_filters multiple times
            self.sidebar.combo_sort.blockSignals(True)
            
            idx = settings.get("sort_index", 1)
            if 0 <= idx < self.sidebar.combo_sort.count():
                self.sidebar.combo_sort.setCurrentIndex(idx)
                
            self.sidebar.search_bar.setText(settings.get("search_text", ""))
            
            # Block signals for filter checkboxes during setup
            if hasattr(self.sidebar, 'chk_new'): self.sidebar.chk_new.blockSignals(True)
            if hasattr(self.sidebar, 'chk_a_tester'): self.sidebar.chk_a_tester.blockSignals(True)
            if hasattr(self.sidebar, 'chk_vr'): self.sidebar.chk_vr.blockSignals(True)
            for chk in self.sidebar.platform_checkboxes: chk.blockSignals(True)

            if hasattr(self.sidebar, 'chk_new'): self.sidebar.chk_new.setChecked(settings.get("chk_new", False))
            if hasattr(self.sidebar, 'chk_a_tester'): self.sidebar.chk_a_tester.setChecked(settings.get("chk_a_tester", False))
            if hasattr(self.sidebar, 'chk_vr'): self.sidebar.chk_vr.setChecked(settings.get("chk_vr", False))

            # Restore platform selections
            checked_platforms = settings.get("checked_platforms", [])
            for chk in self.sidebar.platform_checkboxes:
                chk.setChecked(chk.text() in checked_platforms)
            
            self.sidebar.combo_sort.blockSignals(False)
            for chk in self.sidebar.platform_checkboxes: chk.blockSignals(False)
            # Unblock signals for other filter checkboxes
            if hasattr(self.sidebar, 'chk_new'): self.sidebar.chk_new.blockSignals(False)
            if hasattr(self.sidebar, 'chk_a_tester'): self.sidebar.chk_a_tester.blockSignals(False)
            if hasattr(self.sidebar, 'chk_vr'): self.sidebar.chk_vr.blockSignals(False)

            return settings.get("scroll_value", 0)
        except Exception as e:
            print(f"Error loading settings: {e}")
            return 0

    def refresh_data(self):
        """Reloads the CSV and updates the display"""
        if os.path.exists(DB_FILE):
            self.master_df = pd.read_csv(DB_FILE, sep=';', encoding='utf-8').fillna('')
            # Re-add temporary sorting columns after reloading
            self.master_df['temp_sort_date'] = pd.to_datetime(self.master_df['Original_Release_Date'], errors='coerce', dayfirst=True)
            self.master_df['temp_sort_title'] = self.master_df['Clean_Title'].str.lower()
            self.populate_platforms()
            self.request_filter_update()

    def load_data(self):
        for _, row in df.iterrows():
            item = QListWidgetItem(self.list_widget)
            # ICI : On passe 'self' (la MainWindow) en deuxième argument
            card = GameCard(row.to_dict(), self) 
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

    def toggle_sort_order(self):
        self.sort_desc = not self.sort_desc
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

        sort_col_map = {"Name": "temp_sort_title", "Release Date": "temp_sort_date", "Developer": "Developer"}
        
        selected_platforms = []
        if hasattr(self.sidebar, 'platform_checkboxes'):
            selected_platforms = [chk.text() for chk in self.sidebar.platform_checkboxes if chk.isChecked()]

        params = {
            'search_text': self.sidebar.search_bar.text(),
            'selected_platforms': selected_platforms,
            'chk_new': self.sidebar.chk_new.isChecked() if hasattr(self.sidebar, 'chk_new') else False,
            'chk_a_tester': self.sidebar.chk_a_tester.isChecked() if hasattr(self.sidebar, 'chk_a_tester') else False,
            'chk_vr': self.sidebar.chk_vr.isChecked() if hasattr(self.sidebar, 'chk_vr') else False,
            'sort_col': sort_col_map[self.sidebar.combo_sort.currentText()],
            'sort_desc': self.sort_desc,
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
        if self.loaded_count >= len(self.current_df):
            self.background_loader.stop()
            return
            
        # Determine the end of the batch
        end_index = min(self.loaded_count + self.batch_size, len(self.current_df))
        batch_df = self.current_df.iloc[self.loaded_count:end_index]
        
        for _, row in batch_df.iterrows():
            item = QListWidgetItem(self.list_widget)
            card = GameCard(row.to_dict(), self, item)
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, row['Folder_Name'])
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
            
        self.loaded_count = end_index

    def update_display_with_results(self, df):
        # Stop the previous loading if it's in progress
        self.background_loader.stop()

        # --- ANCHORING: Save selection ---
        current_item = self.list_widget.currentItem()
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

    def restore_scroll_position(self):
        if not hasattr(self, 'pending_scroll'): return
        
        sb = self.list_widget.verticalScrollBar()
        
        # If we can still load and haven't reached the target
        if sb.maximum() < self.pending_scroll and self.loaded_count < len(self.current_df):
            self.load_more_items()
            # Force layout update to recalculate the maximum immediately
            self.list_widget.doItemsLayout() 
            # Immediate recall to continue loading if necessary
            QTimer.singleShot(0, self.restore_scroll_position)
        else:
            # Target reached or everything loaded: apply final position
            sb.setValue(self.pending_scroll)
            del self.pending_scroll

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()
    window.raise_()
    sys.exit(app.exec())