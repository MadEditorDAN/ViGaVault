# WHY: Single Responsibility Principle - Handles ONLY the manual editing of game metadata.
import os
import re
import requests
import logging
import shutil
import webbrowser
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QWidget, QGroupBox, QFormLayout, 
                               QCheckBox, QLineEdit, QTextEdit, QLabel, QPushButton, QFileDialog, 
                               QMessageBox, QApplication)
from PySide6.QtCore import Qt
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices

from backend.library import LibraryManager
from ViGaVault_utils import BASE_DIR, get_image_path, build_scanner_config, translator, get_safe_filename, DIALOG_STD_SIZE, center_window

# WHY: Use a relative import to access the Merge tool from within the same package safely.
from .merge_tool_dialogs import MergeSelectionDialog
from .trailer_search_dialog import TrailerSearchDialog

class ActionDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(translator.tr(title))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        self.original_data = data.copy()
        self.updated_data = {}

        super_main_layout = QVBoxLayout(self)

        # --- Left Column (Form) ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
 
        metadata_group = QGroupBox(translator.tr("dialog_edit_metadata_group"))
        self.form_layout = QFormLayout(metadata_group)
        self.inputs = {}
        
        # Status & DLC Checkboxes
        checkbox_layout = QHBoxLayout()
        self.chk_locked = QCheckBox(translator.tr("dialog_edit_locked"))
        self.chk_locked.setChecked(self.original_data.get('Status_Flag') == 'LOCKED')
        
        self.chk_dlc = QCheckBox(translator.tr("batch_edit_mark_dlc"))
        is_dlc = str(self.original_data.get('Is_DLC', False)).lower() in ['true', '1']
        self.chk_dlc.setChecked(is_dlc)
        
        self.chk_ok = QCheckBox(translator.tr("dialog_edit_status_ok"))
        self.chk_ok.setChecked(self.original_data.get('Status_Flag') == 'OK')
        
        self.chk_locked.stateChanged.connect(lambda: self.chk_ok.setChecked(False) if self.chk_locked.isChecked() else None)
        self.chk_ok.stateChanged.connect(lambda: self.chk_locked.setChecked(False) if self.chk_ok.isChecked() else None)
        
        checkbox_layout.addWidget(self.chk_locked)
        checkbox_layout.addWidget(self.chk_ok)
        checkbox_layout.addWidget(self.chk_dlc)
        # WHY: Wrap all checkboxes inside a horizontal layout so they render flawlessly side-by-side.
        self.form_layout.addRow(checkbox_layout)
        
        fields_to_disable = ['Folder_Name', 'Status_Flag', 'Image_Link', 'Platforms']
        # WHY: Explicitly exclude internal system flags and media paths so they don't clutter the generic text zone.
        fields_to_exclude = ['Trailer_Link', 'game_ID', 'Image_Link', 'temp_sort_date', 'temp_sort_title', 'temp_sort_index', 'Path_Root', 'Year_Folder', 'Is_Local', 'Has_Image', 'Has_Video', 'Cover_URL', 'Path_Video', 'Is_DLC', 'Is_Excluded']
        fmt_str = getattr(self.parent_window, 'date_format_str', 'DD/MM/YYYY')

        for field, value in self.original_data.items():
            if field in fields_to_exclude or field.startswith('platform_ID_'):
                continue
            label_text = field.replace('_', ' ').title()
            if field == "Summary":
                inp = QTextEdit(str(value))
            else:
                display_value = str(value)
                if field == 'Original_Release_Date':
                    from ViGaVault_utils import format_date_for_ui
                    display_value = format_date_for_ui(display_value, fmt_str)
                inp = QLineEdit(display_value)
                if field == 'Original_Release_Date':
                    # WHY: Provide UI guidance so the user doesn't manually enter a conflicting date format.
                    inp.setPlaceholderText(fmt_str)
            if field in fields_to_disable:
                inp.setEnabled(False)
                inp.setStyleSheet("background-color: palette(window);")
            else:
                if isinstance(inp, QLineEdit):
                    inp.textEdited.connect(self.on_field_edited)
                elif isinstance(inp, QTextEdit):
                    inp.textChanged.connect(self.on_field_edited)
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
        # WHY: With the video section removed, we can massively expand the Cover preview to 225x300.
        self.cover_image_label.setFixedSize(225, 300)
        
        path_layout_img = QHBoxLayout()
        path_layout_img.addWidget(QLabel(translator.tr("dialog_edit_path_label")))
        self.img_path_edit = QLineEdit()
        self.img_path_edit.setReadOnly(True)
        path_layout_img.addWidget(self.img_path_edit, 1)
        btn_select_image = QPushButton(translator.tr("dialog_edit_select_btn"))
        btn_select_image.clicked.connect(self.select_new_image)
        path_layout_img.addWidget(btn_select_image)

        from backend.steamgriddb.login_steamgriddb import is_steamgriddb_connected
        if is_steamgriddb_connected():
            btn_sgdb = QPushButton("SteamGridDB...")
            btn_sgdb.clicked.connect(self.select_steamgriddb_cover)
            path_layout_img.addWidget(btn_sgdb)

        self.btn_view_image = QPushButton(translator.tr("dialog_edit_view_full_size_btn"))
        self.btn_view_image.clicked.connect(self.view_full_image)

        cover_layout.addWidget(self.cover_image_label, 0, Qt.AlignHCenter)
        cover_layout.addLayout(path_layout_img)
        cover_layout.addWidget(self.btn_view_image)
        right_layout.addWidget(cover_group)
        
        self.update_cover_display()

        # Section 3: Trailer
        self.trailer_group = QGroupBox(translator.tr("dialog_edit_trailer_group"))
        self.trailer_layout = QVBoxLayout(self.trailer_group)
        self.trailer_thumbnail_label = QLabel("No Trailer")
        self.trailer_thumbnail_label.setAlignment(Qt.AlignCenter)
        # WHY: With the video section removed, we can heavily expand the Trailer preview to 384x216.
        self.trailer_thumbnail_label.setFixedSize(384, 216)

        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel(translator.tr("dialog_edit_trailer_url_label")))
        self.url_line_edit = QLineEdit()
        self.url_line_edit.textEdited.connect(self.on_field_edited)
        url_layout.addWidget(self.url_line_edit, 1)
        
        btn_import = QPushButton("Import")
        btn_import.clicked.connect(self.search_youtube_trailer)
        url_layout.addWidget(btn_import)
        
        copy_btn = QPushButton(translator.tr("dialog_edit_trailer_copy_btn"))
        copy_btn.clicked.connect(self.copy_trailer_url)
        url_layout.addWidget(copy_btn)

        self.btn_play_trailer = QPushButton(translator.tr("dialog_edit_trailer_play_btn"))

        self.trailer_layout.addWidget(self.trailer_thumbnail_label, 0, Qt.AlignHCenter)
        self.trailer_layout.addLayout(url_layout)
        self.trailer_layout.addWidget(self.btn_play_trailer)

        self.setup_trailer_section()
        
        # WHY: Adding stretches evenly BETWEEN the groups causes them to perfectly distribute
        # vertically to match the dynamic height of the left metadata column.
        right_layout.addWidget(cover_group)
        right_layout.addStretch()
        right_layout.addWidget(self.trailer_group)

        columns_layout = QHBoxLayout()
        columns_layout.addWidget(left_widget, 2)
        columns_layout.addWidget(right_widget, 1)
        super_main_layout.addLayout(columns_layout)

        # --- Bottom Buttons ---
        button_box = QHBoxLayout()
        btn_merge = QPushButton(translator.tr("dialog_edit_btn_merge"))
        btn_merge.clicked.connect(self.start_merge)
        button_box.addWidget(btn_merge)
        
        btn_delete = QPushButton(translator.tr("dialog_edit_btn_delete"))
        btn_delete.setStyleSheet("color: #C62828; font-weight: bold;")
        btn_delete.clicked.connect(self.request_delete)
        button_box.addWidget(btn_delete)
        
        button_box.addStretch()
        
        btn_save = QPushButton(translator.tr("dialog_edit_save_btn"))
        btn_save.setDefault(True)
        btn_cancel = QPushButton(translator.tr("dialog_edit_cancel_btn"))
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        button_box.addWidget(btn_cancel)
        button_box.addWidget(btn_save)
        super_main_layout.addLayout(button_box)

    def on_field_edited(self):
        # WHY: Automatically lock the game if the user manually edits any metadata.
        if not self.chk_locked.isChecked():
            self.chk_locked.setChecked(True)

    def start_merge(self):
        dlg = MergeSelectionDialog(self.original_data, self.parent_window.master_df, self)
        if dlg.exec():
            selected_game = dlg.get_selected()
            if selected_game:
                if self.parent_window.execute_merge(self.original_data['Folder_Name'], selected_game['Folder_Name']):
                    # WHY: Reject gracefully closes the window without triggering the GameCard's secondary save routine.
                    self.reject()

    def request_delete(self):
        """Asks for confirmation and delegates total deletion to the library controller."""
        reply = QMessageBox.warning(
            self, 
            translator.tr("dialog_delete_confirm_title"),
            translator.tr("dialog_delete_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if hasattr(self.parent_window, 'delete_game'):
                self.parent_window.delete_game(self.original_data['Folder_Name'])
                self.accept()

    def update_cover_display(self):
        img_name = self.updated_data.get('Image_Link') or self.original_data.get('Image_Link', '')
        img_path = os.path.join(get_image_path(), os.path.basename(img_name)) if img_name else ''
        self.img_path_edit.setText(img_path)
        self.img_path_edit.setCursorPosition(0)
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path).scaled(225, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_image_label.setPixmap(pixmap)
            self.cover_image_label.setStyleSheet("")
            self.btn_view_image.setEnabled(True)
        else:
            self.cover_image_label.setText("No Cover Image")
            self.cover_image_label.setStyleSheet("border: 1px solid #555;")
            self.btn_view_image.setEnabled(False)

    def select_new_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Image Files (*.png *.jpg *.jpeg *.webp)")
        if not file_path: return
        safe_filename_base = get_safe_filename(self.original_data.get('Folder_Name', ''))
        _, ext = os.path.splitext(file_path)
        new_filename = f"{safe_filename_base}{ext}"
        
        manager = LibraryManager(build_scanner_config())
        dest_dir = manager.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        dest_path = os.path.join(dest_dir, new_filename)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.abspath(file_path) != os.path.abspath(dest_path):
                shutil.copy(file_path, dest_path)
            self.updated_data['Image_Link'] = new_filename
            self.updated_data['Has_Image'] = True
            self.update_cover_display()
            self.on_field_edited()
        except Exception as e:
            logging.error(f"Failed to copy new image: {e}")
            QMessageBox.critical(self, "Error", f"Could not copy the image: {e}")

    def select_steamgriddb_cover(self):
        from dialogs.steamgriddb_picker_dialog import SteamGridDBPickerDialog
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt
        
        # Get clean title
        title_to_search = ""
        clean_title_input = self.inputs.get('Clean_Title')
        if clean_title_input:
            title_to_search = clean_title_input.text().strip()
        if not title_to_search:
            title_to_search = self.original_data.get('Clean_Title', '')
        if not title_to_search:
            title_to_search = self.original_data.get('Folder_Name', '')

        dlg = SteamGridDBPickerDialog(title_to_search, self)
        if dlg.exec():
            selected_url = dlg.selected_url
            if not selected_url:
                return
            
            # Overwrite confirmation if image exists
            img_name = self.updated_data.get('Image_Link') or self.original_data.get('Image_Link', '')
            if img_name:
                reply = QMessageBox.question(
                    self,
                    translator.tr("dialog_sgdb_overwrite_title"),
                    translator.tr("dialog_sgdb_overwrite_msg"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

            safe_filename_base = get_safe_filename(self.original_data.get('Folder_Name', ''))
            import urllib.parse
            parsed_url = urllib.parse.urlparse(selected_url)
            _, ext = os.path.splitext(parsed_url.path)
            if not ext:
                ext = ".jpg"
            
            new_filename = f"{safe_filename_base}{ext}"
            
            manager = LibraryManager(build_scanner_config())
            dest_dir = manager.config.get('image_path', os.path.join(BASE_DIR, 'images'))
            dest_path = os.path.join(dest_dir, new_filename)
            
            progress = QProgressDialog(translator.tr("dialog_sgdb_downloading_progress"), translator.tr("dialog_sgdb_btn_cancel"), 0, 0, self)
            progress.setWindowTitle(translator.tr("dialog_sgdb_downloading_title"))
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            QApplication.processEvents()
            
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                response = requests.get(selected_url, stream=True, timeout=15, headers=headers)
                if response.status_code == 200:
                    os.makedirs(dest_dir, exist_ok=True)
                    with open(dest_path, 'wb') as f:
                        shutil.copyfileobj(response.raw, f)
                    
                    self.updated_data['Image_Link'] = new_filename
                    self.updated_data['Has_Image'] = True
                    self.update_cover_display()
                    self.on_field_edited()
                else:
                    QMessageBox.warning(self, translator.tr("dialog_sgdb_download_failed"), translator.tr("dialog_sgdb_download_failed_msg", code=response.status_code))
            except Exception as e:
                logging.error(f"Failed to download SteamGridDB cover: {e}")
                QMessageBox.critical(self, translator.tr("dialog_sgdb_warning_title"), translator.tr("dialog_sgdb_download_error", error=str(e)))
            finally:
                progress.close()

    def view_full_image(self):
        img_name = self.updated_data.get('Image_Link') or self.original_data.get('Image_Link', '')
        img_path = os.path.join(get_image_path(), os.path.basename(img_name)) if img_name else ''
        if img_path and os.path.exists(img_path):
            try: os.startfile(img_path)
            except Exception as e: QMessageBox.critical(self, "Error", f"Could not open image file:\n{e}")

    def copy_trailer_url(self):
        if self.trailer_link:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.trailer_link)
            logging.info(f"URL copied to clipboard: {self.trailer_link}")

    def setup_trailer_section(self):
        self.trailer_link = self.url_line_edit.text() if self.url_line_edit.text() else self.original_data.get('Trailer_Link', '')
        self.url_line_edit.setText(self.trailer_link)

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
                except Exception as e: pass
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
            self.trailer_thumbnail_label.setPixmap(pixmap.scaled(384, 216, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.trailer_thumbnail_label.setText("Trailer Available")
            self.trailer_thumbnail_label.setStyleSheet("border: 1px solid #555;")

    def play_trailer(self):
        url = self.url_line_edit.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))
            
    def search_youtube_trailer(self):
        game_title = self.updated_data.get('Title') or self.original_data.get('Title') or self.original_data.get('Folder_Name', 'Unknown')
        dialog = TrailerSearchDialog(game_title, self)
        if dialog.exec():
            selected_url = dialog.get_selected_url()
            if selected_url:
                self.url_line_edit.setText(selected_url)
                self.updated_data['Trailer_Link'] = selected_url
                self.setup_trailer_section()
                self.on_field_edited()

    def get_data(self):
        new_data = {}
        for field, inp in self.inputs.items():
            if inp.isEnabled():
                if isinstance(inp, QTextEdit):
                    new_data[field] = inp.toPlainText()
                else:
                    val = inp.text().strip()
                    if field == 'Original_Release_Date':
                        from ViGaVault_utils import parse_date_from_ui
                        fmt_str = getattr(self.parent_window, 'date_format_str', 'DD/MM/YYYY')
                        val = parse_date_from_ui(val, fmt_str)
                    new_data[field] = val
        new_data.update(self.updated_data)
        
        if self.chk_locked.isChecked():
            new_data['Status_Flag'] = 'LOCKED'
        elif self.chk_ok.isChecked():
            new_data['Status_Flag'] = 'OK'
        else:
            # WHY: If neither are checked, retain the original status (or default to NEEDS_ATTENTION if it wasn't OK/LOCKED)
            orig = self.original_data.get('Status_Flag', '')
            new_data['Status_Flag'] = orig if orig not in ['OK', 'LOCKED'] else 'NEEDS_ATTENTION'
            
        new_data['Is_DLC'] = self.chk_dlc.isChecked()
        new_data['Trailer_Link'] = self.url_line_edit.text().strip()
        return new_data