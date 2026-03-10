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
from ViGaVault_Scan import LibraryManager, get_safe_filename, get_platform_config, get_library_settings_file, get_db_path, get_root_path
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton, QStackedLayout, QFileDialog, QScrollArea,
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox, QFrame, QAbstractItemView, QCheckBox, QSlider, QStyle, QGroupBox,
                             QTabWidget, QMenuBar, QMenu, QSizePolicy)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent, QUrl, QThread, Signal, QObject, Slot
from PySide6.QtGui import QPixmap, QIcon, QAction

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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_path = get_root_path()
        self.db_path = get_db_path()

    def run(self):
        """Runs the GOG sync process."""
        try:
            manager = LibraryManager(self.root_path, self.db_path)
            manager.load_db()
            manager.sync_gog(worker_thread=self)
        except Exception as e:
            # Log any exceptions that happen inside the thread
            logging.error(f"Critical error in GOG sync thread: {e}")

class LocalScanWorker(QThread):
    def __init__(self, retry_failures=False, parent=None):
        super().__init__(parent)
        self.retry_failures = retry_failures
        self.root_path = get_root_path()
        self.db_path = get_db_path()

    def run(self, ):
        """Runs the local folder scan process."""
        try:
            manager = LibraryManager(self.root_path, self.db_path)
            manager.load_db()
            # Pass the thread itself to the manager so it can check for interruption
            manager.scan(retry_failures=self.retry_failures, worker_thread=self)
        except Exception as e:
            # Log any exceptions that happen inside the thread
            logging.error(f"Critical error in local scan thread: {e}")

class FullScanWorker(QThread):
    def __init__(self, retry_failures=False, parent=None):
        super().__init__(parent)
        self.retry_failures = retry_failures
        self.root_path = get_root_path()
        self.db_path = get_db_path()

    def run(self):
        """Runs the full scan process."""
        try:
            manager = LibraryManager(self.root_path, self.db_path)
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
            
        is_scan_new = self.params.get('scan_new', False)

        # Dynamic Filters
        # Only apply if NOT scanning new games, as new games often lack metadata
        if not is_scan_new:
            active_filters = self.params.get('active_filters', {})
            for col, selected_values in active_filters.items():
                if not selected_values:
                    df = df.iloc[0:0] # Empty result if nothing selected in a category
                    break
                
                regex_pattern = '|'.join([re.escape(v) for v in selected_values])
                df = df[df[col].astype(str).str.contains(regex_pattern, case=False, na=False)]

        # Status Filter (Exclusive)
        if is_scan_new:
            df = df[df['Status_Flag'] != 'OK']
            df = df[df['Status_Flag'].astype(str) != 'OK']
        else:
            df = df[df['Status_Flag'] == 'OK']
            df = df[df['Status_Flag'].astype(str) == 'OK']
            
        # Sorting
        sort_col = self.params['sort_col']
        sort_desc = self.params['sort_desc']
        
        if sort_col == "temp_sort_date" or sort_col == "temp_sort_title":
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last' if sort_col == "temp_sort_date" else 'first')
        else:
            df = df.sort_values(by=sort_col, ascending=not sort_desc, na_position='last')
        
        self.finished.emit(df)

class CollapsibleFilterGroup(QGroupBox):
    def __init__(self, title, parent_layout, parent=None):
        super().__init__("", parent)
        self.parent_layout = parent_layout
        self.title = title
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Header Button
        self.toggle_btn = QPushButton(f"▶ {title}")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False) # Default collapsed
        self.toggle_btn.setStyleSheet("""
            QPushButton { text-align: left; font-weight: bold; padding: 5px; border: none; background-color: #333; }
            QPushButton:hover { background-color: #444; }
            QPushButton:checked { background-color: #333; }
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
        if self.parent_layout:
            self.parent_layout.setStretchFactor(self, 100 if checked else 0)

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
            if old_vid_path and os.path.exists(old_vid_path):
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

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Settings")

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
        self.tabs.addTab(self.tab_display, "Display")
        
        # Tab 2: Local Folders
        self.tab_folders = QWidget()
        self.setup_folders_tab()
        self.tabs.addTab(self.tab_folders, "Local Folders")
        
        # Tab 3: Data Sources
        self.tab_data = QWidget()
        self.setup_data_tab()
        self.tabs.addTab(self.tab_data, "Data Sources")
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Save")
        btn_cancel = QPushButton("Cancel")
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.cancel_and_revert)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.load_settings()

    def setup_display_tab(self):
        layout = QFormLayout(self.tab_display)
        
        # Theme
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["System", "Dark", "Light"])
        layout.addRow("Theme:", self.combo_theme)
        
        # Language
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["English", "French"])
        layout.addRow("Language:", self.combo_lang)
        
        # --- Image Size Slider ---
        img_layout = QHBoxLayout()
        self.slider_img_size = QSlider(Qt.Horizontal)
        self.slider_img_size.setRange(0, 9) # 10 steps
        self.slider_img_size.setTickInterval(1)
        self.slider_img_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_img_size = QLabel("200 px")
        self.lbl_img_size.setFixedWidth(60)
        img_layout.addWidget(self.slider_img_size)
        img_layout.addWidget(self.lbl_img_size)
        layout.addRow("Image Size:", img_layout)

        # --- Button Size Slider ---
        btn_layout = QHBoxLayout()
        self.slider_btn_size = QSlider(Qt.Horizontal)
        self.slider_btn_size.setRange(0, 9) # 10 steps
        self.slider_btn_size.setTickInterval(1)
        self.slider_btn_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_btn_size = QLabel("45 px")
        self.lbl_btn_size.setFixedWidth(60)
        btn_layout.addWidget(self.slider_btn_size)
        btn_layout.addWidget(self.lbl_btn_size)
        layout.addRow("Button Size:", btn_layout)

        # --- Text Size Slider ---
        txt_layout = QHBoxLayout()
        self.slider_text_size = QSlider(Qt.Horizontal)
        self.slider_text_size.setRange(0, 9) # 10 steps
        self.slider_text_size.setTickInterval(1)
        self.slider_text_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_text_size = QLabel("22 px")
        self.lbl_text_size.setFixedWidth(60)
        txt_layout.addWidget(self.slider_text_size)
        txt_layout.addWidget(self.lbl_text_size)
        layout.addRow("Text Size:", txt_layout)

        # --- Connections ---
        # Update labels in real-time while dragging
        self.slider_img_size.valueChanged.connect(self.update_preview_labels)
        self.slider_btn_size.valueChanged.connect(self.update_preview_labels)
        self.slider_text_size.valueChanged.connect(self.update_preview_labels)
        # Update the main UI only when the slider is released (solves performance issue)
        self.slider_img_size.sliderReleased.connect(self.on_display_setting_changed)
        self.slider_btn_size.sliderReleased.connect(self.on_display_setting_changed)
        self.slider_text_size.sliderReleased.connect(self.on_display_setting_changed)

    def update_preview_labels(self):
        """Updates the 'px' labels next to the sliders."""
        img_val = self.IMG_SIZES[self.slider_img_size.value()]
        btn_val = self.BTN_SIZES[self.slider_btn_size.value()]
        txt_val = self.TXT_SIZES[self.slider_text_size.value()]

        self.lbl_img_size.setText(f"{img_val} px")
        self.lbl_btn_size.setText(f"{btn_val} px")
        self.lbl_text_size.setText(f"{txt_val} px")

    def on_display_setting_changed(self):
        """Triggers dynamic update in the main window."""
        if self.parent_window and hasattr(self.parent_window, 'preview_display_settings'):
            self.parent_window.preview_display_settings(
                self.IMG_SIZES[self.slider_img_size.value()],
                self.BTN_SIZES[self.slider_btn_size.value()],
                self.TXT_SIZES[self.slider_text_size.value()]
            )

    def cancel_and_revert(self):
        """Reverts any previewed changes by reloading from settings.json and closes."""
        if self.parent_window and hasattr(self.parent_window, 'preview_display_settings'):
            # Defaults
            img_size = 200
            btn_size = 45
            text_size = 22
            
            # Display settings are Global, so we check settings.json
            if os.path.exists("settings.json"):
                try:
                    with open("settings.json", "r", encoding='utf-8') as f:
                        settings = json.load(f)
                        img_size = settings.get("card_image_size", 200)
                        btn_size = settings.get("card_button_size", 45)
                        text_size = settings.get("card_text_size", 22)
                except:
                    pass
            
            self.parent_window.preview_display_settings(img_size, btn_size, text_size)
            
        self.reject()

    def setup_folders_tab(self):
        layout = QVBoxLayout(self.tab_folders)
        
        grp_root = QGroupBox("Root")
        layout_root = QFormLayout(grp_root)
        self.root_path_input = QLineEdit(r"\\madhdd02\Software\GAMES")
        
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self.browse_root_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.root_path_input)
        path_layout.addWidget(btn_browse)
        
        layout_root.addRow("Main Path:", path_layout)
        layout.addWidget(grp_root)
        
        grp_structure = QGroupBox("Folder Structure")
        self.struct_layout = QVBoxLayout(grp_structure)
        
        self.chk_ignore_hidden = QCheckBox("Ignore Hidden Folders (Global)")
        self.struct_layout.addWidget(self.chk_ignore_hidden)

        # --- MODE 1: SIMPLE / GLOBAL (Depth 1 or 2) ---
        self.mode_simple_widget = QWidget()
        simple_layout = QVBoxLayout(self.mode_simple_widget)
        simple_layout.setContentsMargins(0, 10, 0, 0)
        
        lbl_simple = QLabel("Mode: Global Structure")
        lbl_simple.setStyleSheet("font-weight: bold; color: #4CAF50;")
        simple_layout.addWidget(lbl_simple)
        
        form_simple = QFormLayout()
        self.combo_global_type = QComboBox()
        self.combo_global_type.addItems(["Direct (Root -> Games)", "Genre", "Collection", "Publisher", "Developer", "Year", "Other", "None"])
        form_simple.addRow("Content of Root Folders:", self.combo_global_type)
        
        self.chk_global_filter = QCheckBox("Add to Filters")
        form_simple.addRow("", self.chk_global_filter)
        simple_layout.addLayout(form_simple)
        
        self.btn_switch_advanced = QPushButton("Add Folder Level (Advanced Mode)")
        self.btn_switch_advanced.clicked.connect(self.switch_to_advanced)
        simple_layout.addWidget(self.btn_switch_advanced)
        simple_layout.addStretch()
        
        self.struct_layout.addWidget(self.mode_simple_widget)

        # --- MODE 2: ADVANCED / PER-FOLDER (Depth 3) ---
        self.mode_advanced_widget = QWidget()
        adv_layout = QVBoxLayout(self.mode_advanced_widget)
        adv_layout.setContentsMargins(0, 10, 0, 0)
        
        lbl_adv = QLabel("Mode: Per-Folder Rules (Root -> Folders -> Categories -> Games)")
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
        self.btn_switch_simple = QPushButton("Remove Folder Level")
        self.btn_switch_simple.clicked.connect(self.switch_to_simple)
        btn_layout.addWidget(self.btn_switch_simple)
        btn_layout.addStretch()
        adv_layout.addLayout(btn_layout)
        
        self.struct_layout.addWidget(self.mode_advanced_widget)
        
        layout.addWidget(grp_structure, 1)

    def switch_to_simple(self):
        self.mode_advanced_widget.hide()
        self.mode_simple_widget.show()
        self.current_scan_mode = "simple"

    def switch_to_advanced(self):
        self.mode_simple_widget.hide()
        self.mode_advanced_widget.show()
        self.current_scan_mode = "advanced"

    def populate_folders_list(self, saved_rules):
        # Clear existing
        while self.folders_grid.count():
            item = self.folders_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # Headers
        self.folders_grid.addWidget(QLabel("Folder"), 0, 0)
        self.folders_grid.addWidget(QLabel("Content Type"), 0, 1)
        self.folders_grid.addWidget(QLabel("Filter"), 0, 2)
        self.folders_grid.addWidget(QLabel("Scan"), 0, 3)

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
        grp_gog = QGroupBox("GOG Galaxy")
        layout_gog = QGridLayout(grp_gog)
        
        self.chk_enable_gog = QCheckBox("GOG Galaxy DB")
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
        grp_media = QGroupBox("Media Download")
        layout_media = QGridLayout(grp_media)
        
        self.chk_download_videos = QCheckBox("Download Videos")
        
        self.video_path_input = QLineEdit()
        self.btn_browse_video = QPushButton("...")
        self.btn_browse_video.setFixedWidth(40)
        self.btn_browse_video.clicked.connect(self.browse_video_path)
        
        # Layout: Checkbox on top, Path below
        layout_media.addWidget(self.chk_download_videos, 0, 0, 1, 3)
        
        layout_media.addWidget(QLabel("Videos Path:"), 1, 0)
        layout_media.addWidget(self.video_path_input, 1, 1)
        layout_media.addWidget(self.btn_browse_video, 1, 2)
        
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
        self.combo_theme.setCurrentText(global_settings.get("theme", "System"))
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
            
        global_settings["theme"] = self.combo_theme.currentText()
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

    def accept(self):
        self.save_settings()
        super().accept()
        
        # Refresh the main window data and filters if parent is MainWindow
        if self.parent() and hasattr(self.parent(), 'refresh_data'):
            self.parent().refresh_data()

class Sidebar(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.setFixedWidth(350)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # --- TOP CONTAINER (Search, Sort, Filters) ---
        self.top_layout = QVBoxLayout()

        label_style = "font-weight: bold; font-size: 16px;"
        
        # 1. Header (Search + Counter)
        header_layout = QHBoxLayout()
        lbl_search = QLabel("Search")
        lbl_search.setStyleSheet(label_style)
        header_layout.addWidget(lbl_search)
        header_layout.addStretch()
        self.lbl_counter = QLabel("0/0")
        self.lbl_counter.setStyleSheet("font-weight: bold; font-size: 20px; color: white;")
        header_layout.addWidget(self.lbl_counter)
        
        self.lbl_lib_name = QLabel("")
        self.lbl_lib_name.setStyleSheet("font-size: 12px; color: #AAAAAA; margin-left: 5px; font-weight: bold;")
        self.lbl_lib_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self.lbl_lib_name)
        
        self.top_layout.addLayout(header_layout)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Game name...")
        self.search_bar.setClearButtonEnabled(True)
        self.top_layout.addWidget(self.search_bar)
        
        # 3. Sort
        lbl_sort = QLabel("Sort by")
        lbl_sort.setStyleSheet(label_style)
        self.top_layout.addWidget(lbl_sort)

        sort_layout = QHBoxLayout()
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["Name", "Release Date", "Developer"])
        sort_layout.addWidget(self.combo_sort, 4)
        
        self.btn_toggle_sort = QPushButton("⇅ Order")
        self.btn_toggle_sort.setStyleSheet("font-size: 16px;")
        sort_layout.addWidget(self.btn_toggle_sort, 1)
        self.top_layout.addLayout(sort_layout)

        # --- FILTERS ---
        lbl_filters = QLabel("Filters")
        lbl_filters.setStyleSheet(label_style)
        self.top_layout.addWidget(lbl_filters)

        # We remove the outer scroll area to let individual groups handle their scrolling/sizing
        self.filters_container = QWidget()
        self.filters_layout = QVBoxLayout(self.filters_container)
        self.filters_layout.setContentsMargins(0, 0, 0, 0)
        
        self.top_layout.addWidget(self.filters_container, 1) # Give it stretch to take available space
        self.layout.addLayout(self.top_layout, 1) # Give top part stretch priority

        # --- SCAN PANEL ---
        self.scan_panel = QWidget()
        self.scan_layout = QVBoxLayout(self.scan_panel)
        
        # Separator line
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

        # --- BOTTOM CONTAINER (Scan Buttons) ---
        self.bottom_layout = QVBoxLayout()
        
        # --- SCAN BUTTONS ---
        scan_btns_layout = QHBoxLayout()
        
        self.btn_sync_gog = QPushButton("Sync GOG")
        self.btn_scan_local = QPushButton("Scan Local")
        self.btn_scan_new = QPushButton("Scan NEW")
        self.btn_scan_new.setCheckable(True)
        self.btn_scan_new.setStyleSheet("QPushButton:checked { background-color: #ff5555; color: white; }")
        
        scan_btns_layout.addWidget(self.btn_sync_gog)
        scan_btns_layout.addWidget(self.btn_scan_local)
        scan_btns_layout.addWidget(self.btn_scan_new)
        
        self.bottom_layout.addLayout(scan_btns_layout)

        # --- FULL SCAN BUTTON ---
        self.btn_full_scan = QPushButton("FULL Scan")
        self.bottom_layout.addWidget(self.btn_full_scan)

        self.layout.addWidget(self.scan_panel)
        self.scan_panel.hide()
        self.layout.addLayout(self.bottom_layout)
        
        # --- CONNECTIONS ---
        self.search_bar.textChanged.connect(self.parent.request_filter_update)
        self.combo_sort.currentIndexChanged.connect(self.parent.request_filter_update)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        self.btn_sync_gog.clicked.connect(self.parent.start_gog_sync)
        self.btn_scan_local.clicked.connect(self.parent.start_local_scan)
        self.btn_full_scan.clicked.connect(self.parent.start_full_scan)
        self.btn_scan_new.toggled.connect(self.parent.request_filter_update)

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
        self.info_labels = [] # Store references for dynamic updates
        
        main_layout = QHBoxLayout(self)
        
        # Get display settings from parent
        settings = getattr(self.parent_window, 'display_settings', {'image': 200, 'button': 45, 'text': 22})
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33) # Aspect ratio 3:4

        # Image
        self.img_label = QLabel()
        self.img_label.setFixedSize(img_w, img_h)
        self.img_label.setAlignment(Qt.AlignCenter)
        img_path = game_data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path).scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.FastTransformation)
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
        
        self.title_lbl = QLabel(game_data.get('Clean_Title', 'Unknown'))
        self.title_lbl.setStyleSheet(f"font-weight: bold; font-size: {settings.get('text', 22)}px;")
        self.title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.title_lbl.installEventFilter(self)
        title_layout.addWidget(self.title_lbl)
        
        path_root = game_data.get('Path_Root', '')
        path_text = f"({path_root})" if path_root else ""
        self.path_lbl = QLabel(path_text)
        self.path_lbl.setStyleSheet("font-size: 11px; color: gray;")
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_lbl.installEventFilter(self)
        title_layout.addWidget(self.path_lbl)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
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
        for field in ['Original_Release_Date', 'Platforms', 'Developer']:
            display_name = 'Developer' # Default
            if field == 'Original_Release_Date':
                display_name = 'Release Date'
            elif field == 'Platforms':
                display_name = 'Platform(s)'

            label = QLabel(f"{display_name}: {game_data.get(field, '')}")
            label.setStyleSheet(f"font-weight: bold; font-size: {info_font_size}px;")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.installEventFilter(self)
            details_layout.addWidget(label)
            self.info_labels.append(label)
        
        self.summary_title = QLabel("Summary")
        self.summary_title.setStyleSheet(f"font-weight: bold; font-size: {info_font_size}px;")
        details_layout.addWidget(self.summary_title)

        summary_font_size = max(10, settings.get('text', 22) - 8)
        self.summary_content = QLabel(game_data.get('Summary', ''))
        self.summary_content.setWordWrap(True)
        self.summary_content.setStyleSheet(f"font-size: {summary_font_size}px;")
        self.summary_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary_content.installEventFilter(self)
        details_layout.addWidget(self.summary_content)
        main_layout.addLayout(details_layout)

    def update_style(self, settings):
        """Updates the card style dynamically."""
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33)
        btn_size = settings.get('button', 45)
        text_size = settings.get('text', 22)
        
        # Update Image
        self.img_label.setFixedSize(img_w, img_h)
        img_path = self.data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path).scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)
            
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
        self.create_menu_bar()
        self.sort_desc = True
        self.display_settings = {'image': 200, 'button': 45, 'text': 22}
        
        
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
        if os.path.exists(get_db_path()):
            self.master_df = pd.read_csv(get_db_path(), sep=';', encoding='utf-8').fillna('')
            
            if 'Status_Flag' not in self.master_df.columns:
                self.master_df['Status_Flag'] = 'NEW'
            
            # Pre-calculate columns for faster sorting
            self.master_df['temp_sort_date'] = pd.to_datetime(self.master_df['Original_Release_Date'], errors='coerce', dayfirst=True)
            self.master_df['temp_sort_title'] = self.master_df['Clean_Title'].str.lower()
        else:
            # Initialize empty DataFrame if DB doesn't exist
            self.master_df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
            self.master_df['temp_sort_date'] = pd.to_datetime([])
            self.master_df['temp_sort_title'] = []
            
        # Populate dynamic filters
        self.populate_dynamic_filters()
            
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
        
        # Initial display
        self.request_filter_update()

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet("""
            QMenuBar {
                font-size: 16px;
            }
            QMenu {
                font-size: 16px;
            }
        """)
        
        # --- File ---
        file_menu = menu_bar.addMenu("File")
        
        action_select_lib = QAction("Switch/New Library...", self)
        action_select_lib.triggered.connect(self.select_library)
        file_menu.addAction(action_select_lib)
        
        action_save = QAction("Save", self)
        action_save.setShortcut("Ctrl+S")
        action_save.triggered.connect(self.save_database)
        file_menu.addAction(action_save)
        
        file_menu.addSeparator()
        
        action_settings = QAction("Settings", self)
        action_settings.triggered.connect(self.open_settings)
        file_menu.addAction(action_settings)

        file_menu.addSeparator()
        
        action_quit = QAction("Exit", self)
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)
        
        # --- Library ---
        lib_menu = menu_bar.addMenu("Library")
        
        action_full_scan = QAction("Full Scan", self)
        lib_menu.addAction(action_full_scan)
        
        lib_menu.addSeparator()
        
        action_sync_gog = QAction("Sync GOG", self)
        lib_menu.addAction(action_sync_gog)
        
        action_scan_local = QAction("Scan Local Folders", self)
        lib_menu.addAction(action_scan_local)
        
        lib_menu.addSeparator()
        
        action_clean = QAction("Clean Library", self)
        lib_menu.addAction(action_clean)
        
        # --- Tools ---
        tools_menu = menu_bar.addMenu("Tools")
        
        action_media = QAction("Media Manager", self)
        tools_menu.addAction(action_media)
        
        action_platforms = QAction("Platform Manager", self)
        tools_menu.addAction(action_platforms)
        
        action_stats = QAction("Statistics / Report", self)
        tools_menu.addAction(action_stats)
        
        # --- Help ---
        help_menu = menu_bar.addMenu("Help")
        
        action_about = QAction("About", self)
        help_menu.addAction(action_about)

    def update_library_info(self):
        """Updates window title and sidebar label with current library name."""
        lib_name = os.path.basename(get_db_path()).replace('.csv', '')
        self.setWindowTitle(f"ViGaVault Library - [{lib_name}]")
        self.sidebar.lbl_lib_name.setText(f"[{lib_name}]")

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

        # 1. Load new master dataframe
        db_path = get_db_path()
        if os.path.exists(db_path):
            self.master_df = pd.read_csv(db_path, sep=';', encoding='utf-8').fillna('')
            if 'Status_Flag' not in self.master_df.columns: self.master_df['Status_Flag'] = 'NEW'
            self.master_df['temp_sort_date'] = pd.to_datetime(self.master_df['Original_Release_Date'], errors='coerce', dayfirst=True)
            self.master_df['temp_sort_title'] = self.master_df['Clean_Title'].str.lower()
        else:
            self.master_df = pd.DataFrame(columns=['Clean_Title', 'Platforms', 'Original_Release_Date', 'Status_Flag', 'Path_Root', 'Folder_Name'])
            self.master_df['temp_sort_date'] = pd.to_datetime([])
            self.master_df['temp_sort_title'] = []

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
        self.sidebar.btn_scan_new.blockSignals(True)

        self.sort_desc = lib_settings.get("sort_desc", True)
        self.sidebar.combo_sort.setCurrentIndex(lib_settings.get("sort_index", 1))
        self.sidebar.search_bar.setText(lib_settings.get("search_text", ""))
        self.sidebar.btn_scan_new.setChecked(lib_settings.get("scan_new", False))

        self.sidebar.combo_sort.blockSignals(False)
        self.sidebar.btn_scan_new.blockSignals(False)

        # 5. Update window title and GOG button state
        self.update_library_info()
        enable_gog = lib_settings.get("enable_gog_db", True)
        self.sidebar.btn_sync_gog.setEnabled(enable_gog)
        self.sidebar.btn_sync_gog.setToolTip("GOG Sync is disabled in Settings" if not enable_gog else "")

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
            
            backups = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".csv.bak")]
            backups.sort(key=os.path.getctime)
            while len(backups) >= MAX_FILES:
                os.remove(backups.pop(0))

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_filename = os.path.basename(db_path)
            backup_file = os.path.join(BACKUP_DIR, f"{os.path.splitext(db_filename)[0]}_{timestamp}.csv.bak")
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
        is_expanded = saved_expansion.get("Platforms", False) if saved_expansion is not None else False
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
                is_expanded = saved_expansion.get(type_name, False) if saved_expansion is not None else False
                self.add_filter_group(type_name, col_name, self.sidebar.filters_layout, is_expanded)
        
        # Add a stretch at the end to push groups up
        self.sidebar.filters_layout.addStretch(1)

        # Restore state if provided
        # If saved_state is None, the default (checked=True) will apply.
        if saved_state is not None:
            for col, checkboxes in self.dynamic_filters.items():
                if col in saved_state:
                    for chk in checkboxes:
                        chk.setChecked(chk.text() in saved_state.get(col, []))

    def add_filter_group(self, title, col_name, parent_layout, is_expanded=False):
        group = CollapsibleFilterGroup(title, parent_layout)
        group.toggle_btn.setChecked(is_expanded)
        
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
            chk.stateChanged.connect(self.request_filter_update)
            group.checkbox_layout.addWidget(chk, row, col)
            checkboxes.append(chk)
            col += 1
            if col > 1: # 2 columns
                col = 0
                row += 1
        
        self.dynamic_filters[col_name] = checkboxes
        parent_layout.addWidget(group)

    def set_filter_group_state(self, col_name, state):
        if col_name in self.dynamic_filters:
            for chk in self.dynamic_filters[col_name]:
                chk.blockSignals(True)
                chk.setChecked(state)
                chk.blockSignals(False)
            self.request_filter_update()

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
        self.sidebar.btn_scan_new.setEnabled(False)
        self.set_filters_ui_state(False)

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
            self.set_filters_ui_state(True)
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
        self.sidebar.btn_scan_new.setEnabled(True)
        self.refresh_data()

    def start_local_scan(self):
        if self.gog_sync_in_progress or self.local_scan_in_progress or self.full_scan_in_progress:
            QMessageBox.information(self, "Info", "Another task is already in progress.")
            return

        self.local_scan_in_progress = True
        self.sidebar.btn_scan_local.setEnabled(False)
        self.sidebar.btn_scan_local.setText("Scanning")
        self.sidebar.btn_full_scan.setEnabled(False)
        self.sidebar.btn_sync_gog.setEnabled(False)
        self.sidebar.btn_scan_new.setEnabled(False)
        self.set_filters_ui_state(False)

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
        self.local_scan_worker = LocalScanWorker(retry_failures=False)
        self.local_scan_worker.finished.connect(self.finish_local_scan)
        self.local_scan_worker.start()

    def stop_local_scan(self):
        """Requests interruption of the local scan thread and closes the panel."""
        if self.local_scan_in_progress and hasattr(self, 'local_scan_worker'):
            logging.info("--- Scan interrupted by user. ---")
            self.local_scan_worker.requestInterruption()
            self.sidebar.scan_panel.hide()
            self.set_filters_ui_state(True)
            self.restore_scan_panel()

    def finish_local_scan(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        
        self.local_scan_in_progress = False
        self.sidebar.btn_scan_local.setEnabled(True)
        self.sidebar.btn_scan_local.setText("Scan Local")
        self.sidebar.btn_full_scan.setEnabled(True)
        self.sidebar.btn_sync_gog.setEnabled(True)
        self.sidebar.btn_scan_new.setEnabled(True)

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
        self.sidebar.btn_scan_new.setEnabled(False)
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
        self.full_scan_worker = FullScanWorker(retry_failures=False)
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
        self.sidebar.btn_full_scan.setText("Full Scan (GOG + Local)")
        self.sidebar.btn_sync_gog.setEnabled(True)
        self.sidebar.btn_scan_local.setEnabled(True)
        self.sidebar.btn_scan_new.setEnabled(True)

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
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        
        game_obj = manager.games.get(folder_name)
        if not game_obj:
            QMessageBox.critical(self, "Error", f"Game '{folder_name}' not found in the database for this library.")
            return

        # Updates game data
        for key, value in new_data.items():
            game_obj.data[key] = value
        
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
                    pass # Silently ignore image errors to avoid blocking
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
        self.set_filters_ui_state(True)
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
                    break # Exit loop on success
                except PermissionError:
                    reply = QMessageBox.warning(self, "File Locked",
                                        f"The file {get_db_path()} is open in another program (e.g., Excel).\n\n"
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
            "scan_new": self.sidebar.btn_scan_new.isChecked(),
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
            self.sidebar.btn_scan_new.blockSignals(True)
            
            if hasattr(self, 'dynamic_filters'):
                for checkboxes in self.dynamic_filters.values():
                    for chk in checkboxes:
                        chk.blockSignals(True)

            self.sidebar.btn_scan_new.setChecked(lib_settings.get("scan_new", False))

            # Restore filter selections
            filter_states = lib_settings.get("filter_states") # Can be None
            if hasattr(self, 'dynamic_filters'):
                if filter_states is not None:
                    for col, checkboxes in self.dynamic_filters.items():
                        if col in filter_states:
                            saved_checked = filter_states.get(col, [])
                            for chk in checkboxes:
                                chk.setChecked(chk.text() in saved_checked)
                elif "checked_platforms" in lib_settings: # Legacy fallback
                    for chk in self.dynamic_filters.get("Platforms", []):
                        chk.setChecked(chk.text() in lib_settings["checked_platforms"])
            
            self.sidebar.combo_sort.blockSignals(False)
            if hasattr(self, 'dynamic_filters'):
                for checkboxes in self.dynamic_filters.values():
                    for chk in checkboxes:
                        chk.blockSignals(False)
            
            self.sidebar.btn_scan_new.blockSignals(False)

            return lib_settings.get("scroll_value", 0)
        except Exception as e:
            print(f"Error loading settings: {e}")
            return 0

    def refresh_data(self):
        # Check GOG setting to enable/disable buttons
        settings_path = get_library_settings_file()
        enable_gog = True
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding='utf-8') as f:
                enable_gog = json.load(f).get("enable_gog_db", True)
        
        self.sidebar.btn_sync_gog.setEnabled(enable_gog)
        if not enable_gog:
            self.sidebar.btn_sync_gog.setToolTip("GOG Sync is disabled in Settings")
        else:
            self.sidebar.btn_sync_gog.setToolTip("")

        """Reloads the CSV and updates the display"""
        # Capture current filter state before rebuilding UI
        saved_filters = {}
        saved_expansion = {}
        if hasattr(self, 'dynamic_filters'):
            for col, checkboxes in self.dynamic_filters.items():
                saved_filters[col] = {chk.text() for chk in checkboxes if chk.isChecked()}
        
        # Capture expansion state
        layout = self.sidebar.filters_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), CollapsibleFilterGroup):
                group = item.widget()
                saved_expansion[group.title] = group.toggle_btn.isChecked()

        if os.path.exists(get_db_path()):
            self.master_df = pd.read_csv(get_db_path(), sep=';', encoding='utf-8').fillna('')
            
            if 'Status_Flag' not in self.master_df.columns:
                self.master_df['Status_Flag'] = 'NEW'
            
            # Re-add temporary sorting columns after reloading
            self.master_df['temp_sort_date'] = pd.to_datetime(self.master_df['Original_Release_Date'], errors='coerce', dayfirst=True)
            self.master_df['temp_sort_title'] = self.master_df['Clean_Title'].str.lower()
            
            # Rebuild filters based on new data, passing the saved state
            self.populate_dynamic_filters(saved_filters, saved_expansion)
            self.update_library_info()
            
            self.request_filter_update()

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
            'sort_col': sort_col_map[self.sidebar.combo_sort.currentText()],
            'sort_desc': self.sort_desc,
            'scan_new': self.sidebar.btn_scan_new.isChecked(),
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