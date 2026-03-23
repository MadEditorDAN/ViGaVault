# WHY: Single Responsibility Principle - Handles ONLY the Media Manager utility logic.
import os
import re
import requests
import logging
import shutil
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QGridLayout, QCheckBox, 
                               QLabel, QTableWidget, QAbstractItemView, QTableWidgetItem, QHeaderView, 
                               QLineEdit, QFileDialog, QMessageBox, QApplication, QGroupBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon

from backend.library import LibraryManager
from ViGaVault_utils import BASE_DIR, build_scanner_config, translator, get_safe_filename, DIALOG_STD_SIZE, center_window

class MediaManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.global_changes_made = False
        self.setWindowTitle(translator.tr("menu_tools_media_manager"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        main_layout = QVBoxLayout(self)
        
        top_group = QGroupBox()
        top_layout = QHBoxLayout(top_group)
        
        self.btn_scan = QPushButton(translator.tr("media_manager_scan_btn"))
        self.btn_scan.setMinimumHeight(80)
        self.btn_scan.setMinimumWidth(150)
        font = QFont()
        font.setBold(True)
        font.setPointSize(16)
        self.btn_scan.setFont(font)
        self.btn_scan.clicked.connect(self.scan_media)
        
        checkbox_layout = QGridLayout()
        
        self.chk_image = QCheckBox(translator.tr("media_manager_col_image"))
        self.chk_trailer = QCheckBox(translator.tr("media_manager_col_trailer"))
        self.chk_hidden = QCheckBox(translator.tr("media_manager_chk_show_hidden"))
        self.chk_image.setChecked(True)
        self.chk_trailer.setChecked(True)
        self.chk_hidden.setChecked(False)
        
        self.lbl_missing_img = QLabel("")
        self.lbl_missing_trl = QLabel("")
        label_style = "font-style: italic;"
        self.lbl_missing_img.setStyleSheet(label_style)
        self.lbl_missing_trl.setStyleSheet(label_style)
        
        checkbox_layout.addWidget(self.chk_image, 0, 0)
        checkbox_layout.addWidget(self.lbl_missing_img, 0, 1)
        checkbox_layout.addWidget(self.chk_trailer, 1, 0)
        checkbox_layout.addWidget(self.lbl_missing_trl, 1, 1)
        # WHY: Inject the new checkbox immediately below the media options to control the dataset scope.
        checkbox_layout.addWidget(self.chk_hidden, 2, 0)
        
        lbl_notice = QLabel(translator.tr("media_manager_notice"))
        lbl_notice.setWordWrap(True)
        lbl_notice.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        top_layout.addWidget(self.btn_scan)
        top_layout.addLayout(checkbox_layout)
        top_layout.addStretch(2)
        top_layout.addWidget(lbl_notice, 1)
        
        main_layout.addWidget(top_group)
        
        table_group = QGroupBox()
        table_layout = QVBoxLayout(table_group)
        self.table = QTableWidget()
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        table_layout.addWidget(self.table)
        
        main_layout.addWidget(table_group)
        
        self.manager = LibraryManager(build_scanner_config())
        self.manager.load_db()

    def scan_media(self):
        self.table.setRowCount(0)
        
        check_img = self.chk_image.isChecked()
        check_trl = self.chk_trailer.isChecked()
        check_hidden = self.chk_hidden.isChecked()
        
        headers = [translator.tr("media_manager_col_game"), translator.tr("media_manager_col_copy")]
        if check_img: headers.append(translator.tr("media_manager_col_image"))
        if check_trl: headers.append(translator.tr("media_manager_col_trailer"))
        headers.extend([translator.tr("media_manager_col_import"), "URL", ""])
        
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        header = self.table.horizontalHeader()
        for i in range(len(headers) - 2):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        
        header.setSectionResizeMode(len(headers) - 2, QHeaderView.Stretch)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeToContents)
        
        missing_img_count = 0
        missing_trl_count = 0
        
        missing_games = []
        
        # WHY: DRY Principle - Read the pre-calculated Is_DLC and Is_Excluded flags natively from the memory DataFrame 
        # to guarantee the Media Manager respects the exact same exclusion rules as the main interface without re-parsing settings.json.
        hidden_folders = set()
        if hasattr(self.parent_window, 'master_df'):
            df = self.parent_window.master_df
            if not df.empty:
                has_dlc = 'Is_DLC' in df.columns
                has_excl = 'Is_Excluded' in df.columns
                if has_dlc and has_excl:
                    hidden_folders = set(df[(df['Is_DLC'] == True) | (df['Is_Excluded'] == True)]['Folder_Name'])
                elif has_dlc:
                    hidden_folders = set(df[df['Is_DLC'] == True]['Folder_Name'])
                elif has_excl:
                    hidden_folders = set(df[df['Is_Excluded'] == True]['Folder_Name'])
                    
        for folder, game in self.manager.games.items():
            if not check_hidden and folder in hidden_folders:
                continue
                
            trailer_link = game.data.get('Trailer_Link', '')
            
            has_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            has_trl = bool(trailer_link and trailer_link.startswith('http'))
            
            if not has_img: missing_img_count += 1
            if not has_trl: missing_trl_count += 1
            
            is_missing = False
            if check_img and not has_img: is_missing = True
            if check_trl and not has_trl: is_missing = True
            
            if is_missing:
                missing_games.append({
                    'folder': folder,
                    'title': game.data.get('Clean_Title', folder),
                    'has_img': has_img,
                    'has_trl': has_trl,
                    'game_obj': game
                })
        
        self.lbl_missing_img.setText(translator.tr("media_manager_missing_count", count=missing_img_count))
        self.lbl_missing_trl.setText(translator.tr("media_manager_missing_count", count=missing_trl_count))
        
        # WHY: Smart Refresh - Freeze layout, pre-allocate rows, and cache disk items to prevent a repaint avalanche.
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(missing_games))
        folder_icon = QIcon("assets/folder.png") if os.path.exists("assets/folder.png") else None
        
        for row, game_info in enumerate(sorted(missing_games, key=lambda x: x['title'].lower())):
            self.add_table_row(row, game_info, check_img, check_trl, folder_icon)
            
        self.table.setUpdatesEnabled(True)
            
    def add_table_row(self, row, game_info, check_img, check_trl, folder_icon):
        col_idx = 0
        item_name = QTableWidgetItem(game_info['title'])
        item_name.setData(Qt.UserRole, game_info['folder'])
        self.table.setItem(row, col_idx, item_name)
        col_idx += 1
        
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
        
        if check_trl:
            item_trl = QTableWidgetItem("✔" if game_info['has_trl'] else "❌")
            item_trl.setTextAlignment(Qt.AlignCenter)
            item_trl.setForeground(QColor("green") if game_info['has_trl'] else QColor("red"))
            self.table.setItem(row, col_idx, item_trl)
            col_idx += 1
        
        btn_import = QPushButton()
        # WHY: DRY Principle - Uses the pre-cached icon instead of querying the hard drive for every single row.
        if folder_icon: btn_import.setIcon(folder_icon)
        else: btn_import.setText("📁")
            
        btn_import.setProperty("selected_file", "")
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
        btn_apply.setEnabled(False)
        url_input.textChanged.connect(lambda text, b=btn_apply, btn=btn_import: b.setEnabled(bool(text.strip()) or bool(btn.property("selected_file"))))
        btn_import.clicked.connect(lambda _, r=row, b=btn_import, ab=btn_apply: self.import_local_file(r, b, ab))
        btn_apply.clicked.connect(lambda _, r=row, f=game_info['folder'], i_c=import_col_idx, u_c=url_col_idx, ab=btn_apply: self.apply_media(r, f, i_c, u_c, check_img, check_trl, ab))
        self.table.setCellWidget(row, col_idx, btn_apply)

    def import_local_file(self, row, btn, apply_btn):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            translator.tr("media_manager_import_dialog_title"), 
            "", 
            "Image Files (*.jpg *.jpeg *.png *.webp)"
        )
        if file_path:
            btn.setProperty("selected_file", file_path)
            btn.setStyleSheet("background-color: #4CAF50;")
            apply_btn.setEnabled(True)

    def apply_media(self, row, folder_name, import_col, url_col, check_img, check_trl, btn_apply=None):
        btn_import = self.table.cellWidget(row, import_col)
        url_input = self.table.cellWidget(row, url_col)
        
        local_file = btn_import.property("selected_file")
        url = url_input.text().strip()
        
        if not local_file and not url: return
            
        game = self.manager.games.get(folder_name)
        if not game: return
            
        img_exts = ['.jpg', '.jpeg', '.png', '.webp']
        
        is_youtube = False
        if url and ('youtube.com' in url or 'youtu.be' in url): is_youtube = True
            
        local_type = None
        if local_file:
            ext = os.path.splitext(local_file)[1].lower()
            if ext in img_exts: local_type = 'image'
            
        url_type = None
        if url:
            if not url.startswith('http://') and not url.startswith('https://'):
                QMessageBox.warning(self, "Error", translator.tr("media_manager_err_invalid_url"))
                return
                
            if is_youtube:
                url_type = 'trailer'
            else:
                import re
                match = re.search(r'\.(jpg|jpeg|png|webp)\b', url, re.IGNORECASE)
                if match:
                    ext = match.group(0).lower()
                    if ext in img_exts: url_type = 'image'
                else:
                    QMessageBox.warning(self, "Error", translator.tr("media_manager_err_invalid_ext"))
                    return
        
        use_local = local_file
        use_url = url
        
        if local_file and url and local_type == url_type and local_type is not None:
            msg = QMessageBox(self)
            msg.setWindowTitle(translator.tr("media_manager_choice_title"))
            msg.setText(translator.tr("media_manager_choice_msg"))
            btn_loc = msg.addButton(translator.tr("media_manager_choice_local"), QMessageBox.AcceptRole)
            btn_net = msg.addButton(translator.tr("media_manager_choice_url"), QMessageBox.AcceptRole)
            msg.exec()
            
            if msg.clickedButton() == btn_loc: use_url = None
            else: use_local = None

        safe_filename = get_safe_filename(game.data.get('Folder_Name', ''))
        changes_made = False
        
        try:
            if use_local:
                ext = os.path.splitext(use_local)[1].lower()
                dest_dir = self.manager.config.get('image_path', os.path.join(BASE_DIR, 'images'))
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, f"{safe_filename}{ext}")
                
                shutil.copy2(use_local, dest_path)
                game.data['Image_Link'] = f"{safe_filename}{ext}"
                game.data['Has_Image'] = True
                changes_made = True
                
            if use_url:
                if is_youtube:
                    game.data['Trailer_Link'] = use_url
                    changes_made = True
                else:
                    import re
                    match = re.search(r'\.(jpg|jpeg|png|webp)\b', use_url, re.IGNORECASE)
                    ext = match.group(0).lower()
                    dest_dir = self.manager.config.get('image_path', os.path.join(BASE_DIR, 'images'))
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, f"{safe_filename}{ext}")
                    
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                    response = requests.get(use_url, stream=True, timeout=10, headers=headers)
                    if response.status_code == 200:
                        with open(dest_path, 'wb') as f:
                            shutil.copyfileobj(response.raw, f)
                        game.data['Image_Link'] = f"{safe_filename}{ext}"
                        game.data['Has_Image'] = True
                        changes_made = True
                    else:
                        QMessageBox.warning(self, "Download Failed", f"HTTP {response.status_code}")
        except Exception as e:
            logging.error(f"Media Manager Error: {e}")
            QMessageBox.critical(self, "Error", str(e))
            
        if changes_made:
            self.manager.save_db()
            self.global_changes_made = True # WHY: Flag that a change was made without forcing an immediate UI refresh
            if btn_apply: btn_apply.setEnabled(False)

            # WHY: Target update without reloading the entire UI.
            new_data = game.to_dict()
            if hasattr(self.parent_window, 'library_controller'):
                self.parent_window.library_controller.patch_memory_df(folder_name, new_data)
                
            if hasattr(self.parent_window, 'list_controller'):
                self.parent_window.list_controller.update_single_card(folder_name, force_media_reload=True)
            
            has_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
            trailer_link = game.data.get('Trailer_Link', '')
            has_trl = bool(trailer_link and trailer_link.startswith('http'))
            
            col_idx = 2
            if check_img:
                item_img = self.table.item(row, col_idx)
                item_img.setText("✔" if has_img else "❌")
                item_img.setForeground(QColor("green") if has_img else QColor("red"))
                col_idx += 1
                
            if check_trl:
                item_trl = self.table.item(row, col_idx)
                item_trl.setText("✔" if has_trl else "❌")
                item_trl.setForeground(QColor("green") if has_trl else QColor("red"))
                col_idx += 1
            
            btn_import.setProperty("selected_file", "")
            btn_import.setStyleSheet("")
            url_input.clear()