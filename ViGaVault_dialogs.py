# WHY: Modularized application by extracting all QDialog-based classes from 
# ViGaVault_UI.py into their own dedicated file. This prevents the main UI script 
# from becoming too large and improves code organization.
import os
import re
import requests
import json
import logging
import subprocess
import shutil
import webbrowser
import pandas as pd
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton, QStackedLayout, QFileDialog, QScrollArea,
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox, QFrame, QAbstractItemView, QCheckBox, QSlider, QStyle, QGroupBox, QProgressBar, QButtonGroup, QRadioButton,
                             QTabWidget, QMenuBar, QMenu, QSizePolicy, QStyleFactory, QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate, QStyleOptionProgressBar)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent, QUrl, QThread, Signal, QObject, Slot, QThreadPool, QRunnable
from PySide6.QtGui import QPixmap, QIcon, QAction, QPalette, QColor, QFont, QImage

from ViGaVault_Scan import LibraryManager, get_safe_filename, normalize_genre
from ViGaVault_utils import (BASE_DIR, LOG_DIR, get_db_path, get_library_settings_file, 
                             get_video_path, get_root_path, get_platform_config, 
                             get_local_scan_config, build_scanner_config, setup_logging, 
                             translator, apply_theme)

# --- Dialog Windows for Editing and Scanning ---
# Dialog for manual editing of game metadata.
class ActionDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.parent_window = parent # WHY: Store reference to main window to access master_df for merging
        self.setWindowTitle(translator.tr(title))
        self.setMinimumWidth(1300) # WHY: Simulated 16:9 aspect ratio width to widen the metadata text area
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
        
        path_layout_img = QHBoxLayout()
        path_layout_img.addWidget(QLabel(translator.tr("dialog_edit_path_label")))
        self.img_path_edit = QLineEdit()
        self.img_path_edit.setReadOnly(True)
        path_layout_img.addWidget(self.img_path_edit, 1)
        btn_select_image = QPushButton(translator.tr("dialog_edit_select_btn"))
        btn_select_image.clicked.connect(self.select_new_image)
        path_layout_img.addWidget(btn_select_image)

        self.btn_view_image = QPushButton(translator.tr("dialog_edit_view_full_size_btn"))
        self.btn_view_image.clicked.connect(self.view_full_image)

        cover_layout.addWidget(self.cover_image_label, 0, Qt.AlignHCenter)
        cover_layout.addLayout(path_layout_img)
        cover_layout.addWidget(self.btn_view_image)
        right_layout.addWidget(cover_group)
        
        self.update_cover_display() # WHY: Moved here to safely access newly created line edit and view button

        # Section 2: Video File (NEW)
        video_group = QGroupBox(translator.tr("dialog_edit_video_group"))
        video_layout = QVBoxLayout(video_group)
        
        path_layout_vid = QHBoxLayout()
        path_layout_vid.addWidget(QLabel(translator.tr("dialog_edit_path_label")))
        self.vid_path_edit = QLineEdit()
        self.vid_path_edit.setReadOnly(True)
        path_layout_vid.addWidget(self.vid_path_edit, 1)
        self.btn_select_video = QPushButton(translator.tr("dialog_edit_select_btn"))
        self.btn_select_video.clicked.connect(self.select_new_video)
        path_layout_vid.addWidget(self.btn_select_video)
        
        self.btn_play_video = QPushButton(translator.tr("dialog_edit_video_play_btn"))
        self.btn_play_video.clicked.connect(self.play_video)
        
        video_layout.addLayout(path_layout_vid)
        video_layout.addWidget(self.btn_play_video)
        right_layout.addWidget(video_group)
        
        self.update_video_display() # Needs to be called AFTER btn_play_video is instantiated so it can be disabled
        
        # Section 3: Trailer
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

        self.btn_play_trailer = QPushButton(translator.tr("dialog_edit_trailer_play_btn"))
        self.trailer_layout.addWidget(self.btn_play_trailer)

        self.trailer_layout.addWidget(self.trailer_thumbnail_label, 0, Qt.AlignHCenter)
        self.trailer_layout.addLayout(url_layout)
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
        self.img_path_edit.setText(img_path)
        self.img_path_edit.setCursorPosition(0)
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path).scaled(200, 266, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_image_label.setPixmap(pixmap)
            self.cover_image_label.setStyleSheet("")
            self.btn_view_image.setEnabled(True)
        else:
            self.cover_image_label.setText("No Cover Image")
            self.cover_image_label.setStyleSheet("border: 1px solid #555;")
            self.btn_view_image.setEnabled(False)

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

    def update_video_display(self):
        vid_path = self.updated_data.get('Path_Video') or self.original_data.get('Path_Video', '')
        self.vid_path_edit.setText(vid_path)
        self.vid_path_edit.setCursorPosition(0)
        if vid_path and os.path.exists(vid_path):
            self.btn_play_video.setEnabled(True)
        else:
            self.btn_play_video.setEnabled(False)

    def select_new_video(self):
        file_path, _ = QFileDialog.getOpenFileName(self, translator.tr("dialog_edit_select_video_btn"), "", "Video Files (*.mp4 *.mkv *.avi *.wmv *.webm)")
        if not file_path:
            return
        safe_filename_base = get_safe_filename(self.original_data.get('Folder_Name', ''))
        _, ext = os.path.splitext(file_path)
        new_filename = f"{safe_filename_base}{ext}"
        
        # WHY: Instantiate LibraryManager logic via configs to know the correct video destination dynamically.
        manager = LibraryManager(build_scanner_config())
        dest_dir = manager.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
        dest_path = os.path.join(dest_dir, new_filename)
        
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(file_path, dest_path)
            logging.info(f"Video manually changed. New video at: {dest_path}")
            self.updated_data['Path_Video'] = dest_path
            self.updated_data['Has_Video'] = True
            self.update_video_display()
        except Exception as e:
            logging.error(f"Failed to copy new video: {e}")
            QMessageBox.critical(self, "Error", f"Could not copy the video: {e}")
            
    def play_video(self):
        # WHY: Play the video externally using os.startfile, identically to GameCard's logic.
        vid_path = self.updated_data.get('Path_Video') or self.original_data.get('Path_Video', '')
        if vid_path and os.path.exists(vid_path):
            try:
                os.startfile(vid_path)
            except Exception as e:
                logging.error(f"Could not open local video from edit dialog: {e}")
                QMessageBox.critical(self, "Error", f"Could not open video file:\n{e}")

    def view_full_image(self):
        # WHY: View the image externally using os.startfile.
        img_path = self.updated_data.get('Image_Link') or self.original_data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            try:
                os.startfile(img_path)
            except Exception as e:
                logging.error(f"Could not open image from edit dialog: {e}")
                QMessageBox.critical(self, "Error", f"Could not open image file:\n{e}")

    def copy_trailer_url(self):
        if self.trailer_link:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.trailer_link)
            logging.info(f"URL copied to clipboard: {self.trailer_link}")

    def setup_trailer_section(self):
        self.trailer_link = self.original_data.get('Trailer_Link', '')
        self.url_line_edit.setText(self.trailer_link)

        # WHY: UI Safeguard to ensure text placeholders aren't treated as playable URLs.
        if not self.trailer_link or not self.trailer_link.startswith('http'):
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
            # WHY: Corrected the exact database string matching from 'local files' to 'local copy' as discovered in the data.
            local_copy_count = len(self.df[self.df['Platforms'].astype(str).str.lower() == 'local copy'])
            local_copy_pct = round((local_copy_count / total_games * 100) if total_games else 0, 1)
            stats_data.append(("tools_stats_local_copy_ratio", f"{local_copy_pct}% ({local_copy_count})"))

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

class MediaManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # WHY: Store reference to main window to refresh lists upon database changes
        self.parent_window = parent
        self.global_changes_made = False # WHY: Track if any changes happened across the entire session to trigger a single refresh on close
        self.setWindowTitle(translator.tr("menu_tools_media_manager"))
        self.resize(1100, 600)
        
        # WHY: Constructing vertical layout for overall grouping
        main_layout = QVBoxLayout(self)
        
        # --- Top section (Scan button and notice) ---
        top_layout = QHBoxLayout()
        
        self.btn_scan = QPushButton(translator.tr("media_manager_scan_btn"))
        self.btn_scan.setMinimumHeight(80) # WHY: Make it tall enough to match the 3 checkboxes
        self.btn_scan.setMinimumWidth(150)
        font = QFont()
        font.setBold(True)
        font.setPointSize(16)
        self.btn_scan.setFont(font)
        self.btn_scan.clicked.connect(self.scan_media)
        
        # WHY: Using QGridLayout to align checkboxes and their missing count labels vertically and cleanly.
        checkbox_layout = QGridLayout()
        
        self.chk_image = QCheckBox(translator.tr("media_manager_col_image"))
        self.chk_video = QCheckBox(translator.tr("media_manager_col_video"))
        self.chk_trailer = QCheckBox(translator.tr("media_manager_col_trailer"))
        self.chk_image.setChecked(True)
        self.chk_video.setChecked(True)
        self.chk_trailer.setChecked(True)
        
        # WHY: Labels initialized empty, waiting for the first scan to display numbers.
        self.lbl_missing_img = QLabel("")
        self.lbl_missing_vid = QLabel("")
        self.lbl_missing_trl = QLabel("")
        # WHY: Removed the hardcoded orange color so it renders in the standard text color.
        label_style = "font-style: italic;"
        self.lbl_missing_img.setStyleSheet(label_style)
        self.lbl_missing_vid.setStyleSheet(label_style)
        self.lbl_missing_trl.setStyleSheet(label_style)
        
        checkbox_layout.addWidget(self.chk_image, 0, 0)
        checkbox_layout.addWidget(self.lbl_missing_img, 0, 1)
        checkbox_layout.addWidget(self.chk_video, 1, 0)
        checkbox_layout.addWidget(self.lbl_missing_vid, 1, 1)
        checkbox_layout.addWidget(self.chk_trailer, 2, 0)
        checkbox_layout.addWidget(self.lbl_missing_trl, 2, 1)
        
        # Notice about acceptable file URLs
        lbl_notice = QLabel(translator.tr("media_manager_notice"))
        lbl_notice.setWordWrap(True)
        lbl_notice.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        top_layout.addWidget(self.btn_scan)
        top_layout.addLayout(checkbox_layout)
        top_layout.addStretch(2) # WHY: Adds a spacer taking up 2 parts of the remaining layout space
        top_layout.addWidget(lbl_notice, 1) # WHY: Gives exactly 1 part (1/3) of the stretchy space to the notice, aligning left without squeezing
        
        main_layout.addLayout(top_layout)
        
        # --- Table section ---
        self.table = QTableWidget()
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        
        main_layout.addWidget(self.table)
        
        # WHY: Instantiate LibraryManager using DRY config generator to query & interact with DB smoothly
        self.manager = LibraryManager(build_scanner_config())
        self.manager.load_db()

    def scan_media(self):
        """Scans the entire database for games missing selected media types."""
        self.table.setRowCount(0)
        
        check_img = self.chk_image.isChecked()
        check_vid = self.chk_video.isChecked()
        check_trl = self.chk_trailer.isChecked()
        
        # WHY: Dynamic headers based on checkboxes
        headers = [translator.tr("media_manager_col_game"), translator.tr("media_manager_col_copy")]
        if check_img: headers.append(translator.tr("media_manager_col_image"))
        if check_vid: headers.append(translator.tr("media_manager_col_video"))
        if check_trl: headers.append(translator.tr("media_manager_col_trailer"))
        headers.extend([translator.tr("media_manager_col_import"), "URL", ""]) # URL and Apply columns
        
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        # WHY: Game Name shrinks to contents, only URL explicitly stretches to fill remaining space
        header = self.table.horizontalHeader()
        for i in range(len(headers) - 2):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        
        header.setSectionResizeMode(len(headers) - 2, QHeaderView.Stretch) # URL
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeToContents) # Apply
        
        missing_img_count = 0
        missing_vid_count = 0
        missing_trl_count = 0
        
        missing_games = []
        for folder, game in self.manager.games.items():
            trailer_link = game.data.get('Trailer_Link', '')
            
            # WHY: Restore missing variable definitions, leveraging the fast memory flags instead of disk checks.
            has_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            has_vid = str(game.data.get('Has_Video')).lower() in ['true', '1']
            has_trl = bool(trailer_link and trailer_link.startswith('http'))
            
            # WHY: Calculate actual totals of missing media across the entire database
            if not has_img: missing_img_count += 1
            if not has_vid: missing_vid_count += 1
            if not has_trl: missing_trl_count += 1
            
            is_missing = False
            if check_img and not has_img: is_missing = True
            if check_vid and not has_vid: is_missing = True
            if check_trl and not has_trl: is_missing = True
            
            if is_missing:
                missing_games.append({
                    'folder': folder,
                    'title': game.data.get('Clean_Title', folder),
                    'has_img': has_img,
                    'has_vid': has_vid,
                    'has_trl': has_trl,
                    'game_obj': game
                })
        
        # Update missing count labels
        self.lbl_missing_img.setText(translator.tr("media_manager_missing_count", count=missing_img_count))
        self.lbl_missing_vid.setText(translator.tr("media_manager_missing_count", count=missing_vid_count))
        self.lbl_missing_trl.setText(translator.tr("media_manager_missing_count", count=missing_trl_count))
        
        # Sorting titles alphabetically to keep list organized
        for game_info in sorted(missing_games, key=lambda x: x['title'].lower()):
            self.add_table_row(game_info, check_img, check_vid, check_trl)
            
    def add_table_row(self, game_info, check_img, check_vid, check_trl):
        """Adds a single row describing the missing files directly to the media manager table."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        col_idx = 0
        
        # WHY: Using native text rendering restores Qt's built-in type-ahead search automatically.
        item_name = QTableWidgetItem(game_info['title'])
        item_name.setData(Qt.UserRole, game_info['folder']) # Keeping DB reference hidden inside item
        self.table.setItem(row, col_idx, item_name)
        col_idx += 1
        
        # WHY: Add the copy button in its own dedicated column for cleaner layout and to avoid custom cell widgets.
        btn_copy = QPushButton("📋")
        btn_copy.setFixedWidth(30)
        btn_copy.clicked.connect(lambda _, t=game_info['title']: QApplication.clipboard().setText(t))
        self.table.setCellWidget(row, col_idx, btn_copy)
        col_idx += 1
        
        if check_img:
            item_img = QTableWidgetItem("✔" if game_info['has_img'] else "❌")
            item_img.setTextAlignment(Qt.AlignCenter)
            item_img.setForeground(QColor("green") if game_info['has_img'] else QColor("red"))
            self.table.setItem(row, col_idx, item_img)
            col_idx += 1
        
        if check_vid:
            item_vid = QTableWidgetItem("✔" if game_info['has_vid'] else "❌")
            item_vid.setTextAlignment(Qt.AlignCenter)
            item_vid.setForeground(QColor("green") if game_info['has_vid'] else QColor("red"))
            self.table.setItem(row, col_idx, item_vid)
            col_idx += 1
            
        if check_trl:
            item_trl = QTableWidgetItem("✔" if game_info['has_trl'] else "❌")
            item_trl.setTextAlignment(Qt.AlignCenter)
            item_trl.setForeground(QColor("green") if game_info['has_trl'] else QColor("red"))
            self.table.setItem(row, col_idx, item_trl)
            col_idx += 1
        
        btn_import = QPushButton()
        # WHY: Replacing text with an explorer icon to save horizontal space
        icon_path = "assets/folder.png"
        if os.path.exists(icon_path):
            btn_import.setIcon(QIcon(icon_path))
        else:
            btn_import.setText("📁")
            
        btn_import.setProperty("selected_file", "") # Local property preventing creating hidden columns
        btn_import.clicked.connect(lambda _, r=row, b=btn_import: self.import_local_file(r, b))
        self.table.setCellWidget(row, col_idx, btn_import)
        import_col_idx = col_idx
        col_idx += 1
        
        url_input = QLineEdit()
        url_input.setPlaceholderText(translator.tr("media_manager_url_placeholder"))
        self.table.setCellWidget(row, col_idx, url_input)
        url_col_idx = col_idx
        col_idx += 1
        
        btn_apply = QPushButton(translator.tr("media_manager_btn_apply"))
        btn_apply.clicked.connect(lambda _, r=row, f=game_info['folder'], i_c=import_col_idx, u_c=url_col_idx: self.apply_media(r, f, i_c, u_c, check_img, check_vid, check_trl))
        self.table.setCellWidget(row, col_idx, btn_apply)

    def import_local_file(self, row, btn):
        """Opens a file dialog for the user to select an image or video manually."""
        # WHY: Custom explicit dialog title for better UX
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            translator.tr("media_manager_import_dialog_title"), 
            "", 
            "Media Files (*.jpg *.jpeg *.png *.webp *.mp4 *.mkv *.avi *.wmv *.webm)"
        )
        if file_path:
            btn.setProperty("selected_file", file_path)
            btn.setStyleSheet("background-color: #4CAF50;")

    def apply_media(self, row, folder_name, import_col, url_col, check_img, check_vid, check_trl):
        """Processes inputs, handles media downloads/copies, and merges results cleanly."""
        btn_import = self.table.cellWidget(row, import_col)
        url_input = self.table.cellWidget(row, url_col)
        
        local_file = btn_import.property("selected_file")
        url = url_input.text().strip()
        
        if not local_file and not url:
            return
            
        game = self.manager.games.get(folder_name)
        if not game:
            return
            
        img_exts = ['.jpg', '.jpeg', '.png', '.webp']
        vid_exts = ['.mp4', '.mkv', '.avi', '.wmv', '.webm']
        
        # WHY: Check if URL is a YouTube streaming URL
        is_youtube = False
        if url and ('youtube.com' in url or 'youtu.be' in url):
            is_youtube = True
            
        # Determining media types (intelligent auto-mapping)
        local_type = None
        if local_file:
            ext = os.path.splitext(local_file)[1].lower()
            if ext in img_exts: local_type = 'image'
            elif ext in vid_exts: local_type = 'video'
            
        url_type = None
        if url:
            # WHY: Prevents 'No connection adapters' crashes by enforcing a valid web URL scheme before doing anything else.
            if not url.startswith('http://') and not url.startswith('https://'):
                QMessageBox.warning(self, "Error", translator.tr("media_manager_err_invalid_url"))
                return
                
            if is_youtube:
                url_type = 'trailer'
            else:
                import re
                # WHY: Dynamic regex search detects the exact extension regardless of following URL queries (like Wikia formats)
                match = re.search(r'\.(jpg|jpeg|png|webp|mp4|mkv|avi|wmv|webm)\b', url, re.IGNORECASE)
                if match:
                    ext = match.group(0).lower()
                    if ext in img_exts: url_type = 'image'
                    elif ext in vid_exts: url_type = 'video'
                else:
                    QMessageBox.warning(self, "Error", translator.tr("media_manager_err_invalid_ext"))
                    return
        
        use_local = local_file
        use_url = url
        
        # WHY: Handles conflict logically when a user provides both types for the identical slot
        if local_file and url and local_type == url_type and local_type is not None:
            msg = QMessageBox(self)
            msg.setWindowTitle(translator.tr("media_manager_choice_title"))
            msg.setText(translator.tr("media_manager_choice_msg"))
            btn_loc = msg.addButton(translator.tr("media_manager_choice_local"), QMessageBox.AcceptRole)
            btn_net = msg.addButton(translator.tr("media_manager_choice_url"), QMessageBox.AcceptRole)
            msg.exec()
            
            if msg.clickedButton() == btn_loc:
                use_url = None
            else:
                use_local = None

        safe_filename = get_safe_filename(game.data.get('Folder_Name', ''))
        changes_made = False
        
        try:
            # Process local file
            if use_local:
                ext = os.path.splitext(use_local)[1].lower()
                is_img = ext in img_exts
                dest_dir = os.path.join(BASE_DIR, "images") if is_img else self.manager.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, f"{safe_filename}{ext}")
                
                shutil.copy2(use_local, dest_path)
                if is_img: 
                    game.data['Image_Link'] = dest_path
                    game.data['Has_Image'] = True
                else: 
                    # WHY: Added missing else block to correctly update DB when importing a local video file
                    game.data['Path_Video'] = dest_path
                    game.data['Has_Video'] = True
                changes_made = True
                
            # Process URL download
            if use_url:
                if is_youtube:
                    # WHY: If YouTube, just save the link dynamically to DB without a download routine
                    game.data['Trailer_Link'] = use_url
                    changes_made = True
                else:
                    import re
                    # WHY: Doing the regex again exclusively to dictate how it's named into the local files folder
                    match = re.search(r'\.(jpg|jpeg|png|webp|mp4|mkv|avi|wmv|webm)\b', use_url, re.IGNORECASE)
                    ext = match.group(0).lower()
                    is_img = ext in img_exts
                    dest_dir = os.path.join(BASE_DIR, "images") if is_img else self.manager.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, f"{safe_filename}{ext}")
                    
                    # WHY: Provide a standard browser User-Agent to bypass 403 Forbidden errors from host firewalls (like Wikia/Cloudflare).
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                    response = requests.get(use_url, stream=True, timeout=10, headers=headers)
                    if response.status_code == 200:
                        with open(dest_path, 'wb') as f:
                            shutil.copyfileobj(response.raw, f)
                        if is_img: 
                            game.data['Image_Link'] = dest_path
                            game.data['Has_Image'] = True
                        else: 
                            game.data['Path_Video'] = dest_path
                            game.data['Has_Video'] = True
                        changes_made = True
                    else:
                        QMessageBox.warning(self, "Download Failed", f"HTTP {response.status_code}")
        except Exception as e:
            logging.error(f"Media Manager Error: {e}")
            QMessageBox.critical(self, "Error", str(e))
            
        if changes_made:
            self.manager.save_db()
            self.global_changes_made = True # WHY: Flag that a change was made without forcing an immediate UI refresh
            
            # Check to see what resolved dynamically instead of full redraw
            has_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            has_vid = str(game.data.get('Has_Video')).lower() in ['true', '1']
            trailer_link = game.data.get('Trailer_Link', '')
            has_trl = bool(trailer_link and trailer_link.startswith('http'))
            
            col_idx = 2 # WHY: Index 0 is Name, Index 1 is Copy Button
            if check_img:
                item_img = self.table.item(row, col_idx) # Fixed missing assignment bug during live UI update
                item_img.setText("✔" if has_img else "❌")
                item_img.setForeground(QColor("green") if has_img else QColor("red"))
                col_idx += 1
                
            if check_vid:
                item_vid = self.table.item(row, col_idx)
                item_vid.setText("✔" if has_vid else "❌")
                item_vid.setForeground(QColor("green") if has_vid else QColor("red"))
                col_idx += 1
                
            if check_trl:
                item_trl = self.table.item(row, col_idx)
                item_trl.setText("✔" if has_trl else "❌")
                item_trl.setForeground(QColor("green") if has_trl else QColor("red"))
                col_idx += 1
            
            btn_import.setProperty("selected_file", "")
            btn_import.setStyleSheet("")
            url_input.clear()