# WHY: Single Responsibility Principle - Dedicated view strictly for Batch Game Management and Exclusion List configuration.
import os
import re
import pandas as pd
import shutil
import re
import requests
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QTableView, QLineEdit, QLabel, QGroupBox, QAbstractItemView,
                               QHeaderView, QCheckBox, QFormLayout, QMessageBox, QStyledItemDelegate, QFileDialog, QComboBox, QSizePolicy)
from PySide6.QtCore import Qt, QAbstractTableModel, QTimer, Signal
from PySide6.QtGui import QPixmap
from ViGaVault_utils import translator, get_library_settings_file, center_window, load_encrypted_json, save_encrypted_json, BASE_DIR, get_safe_filename
from widgets import CheckableComboBox

class ReadOnlyTextDelegate(QStyledItemDelegate):
    """WHY: Single Responsibility - Provides a read-only text editor to allow users to select and copy partial text without risking accidental modifications."""
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setReadOnly(True)
        return editor

class BatchEditDialog(QDialog):
    """WHY: Single Responsibility Principle - A dedicated popup strictly for applying blank-safe batched metadata changes."""
    def __init__(self, count, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("game_manager_batch_edit_title"))
        self.resize(500, 300)
        center_window(self, parent)

        layout = QVBoxLayout(self)
        
        # WHY: Wrap the description text inside its own native QGroupBox to create a bounding frame.
        desc_group = QGroupBox()
        desc_layout = QVBoxLayout(desc_group)
        # WHY: Drastically reduce the top and bottom margins to eliminate empty space around the text block.
        desc_layout.setContentsMargins(10, 5, 10, 5)
        lbl_desc = QLabel(translator.tr("game_manager_batch_edit_desc", count=count))
        lbl_desc.setAlignment(Qt.AlignCenter)
        desc_layout.addWidget(lbl_desc)
        layout.addWidget(desc_group)

        form_group = QGroupBox()
        self.form_layout = QFormLayout(form_group)
        self.inputs = {}
        
        # WHY: Explicitly allowed batched fields.
        fields = ['Developer', 'Publisher', 'Genre', 'Collection', 'Original_Release_Date']
        for field in fields:
            label_text = field.replace('_', ' ').replace('Original ', '').title()
            inp = QLineEdit()
            self.form_layout.addRow(label_text, inp)
            self.inputs[field] = inp
            
        self.chk_ok = QCheckBox("Set as OK")
        self.chk_new = QCheckBox("Set as NEW")
        
        self.chk_ok.toggled.connect(lambda checked: self.chk_new.setChecked(False) if checked else None)
        self.chk_new.toggled.connect(lambda checked: self.chk_ok.setChecked(False) if checked else None)

        # WHY: Use a tristate checkbox so the user can explicitly choose to mark, unmark, or completely ignore the DLC status during batch edits.
        self.chk_dlc = QCheckBox(translator.tr("batch_edit_mark_dlc"))
        self.chk_dlc.setTristate(True)
        self.chk_dlc.setCheckState(Qt.PartiallyChecked)
        
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.chk_ok)
        status_layout.addWidget(self.chk_new)
        status_layout.addWidget(self.chk_dlc)
        status_layout.addStretch()
        
        self.form_layout.addRow(status_layout)
        
        layout.addWidget(form_group)

        btn_box = QHBoxLayout()
        btn_save = QPushButton(translator.tr("settings_btn_save"))
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    def get_data(self):
        # WHY: Smart filtering mathematically drops completely blank inputs so they safely skip the backend logic.
        data = {field: inp.text().strip() for field, inp in self.inputs.items() if inp.text().strip()}
        
        # WHY: Interpret the tristate checkbox to cleanly apply or revoke the DLC flag, while safely ignoring it if left partially checked.
        if self.chk_dlc.checkState() == Qt.Checked:
            data['Is_DLC'] = True
        elif self.chk_dlc.checkState() == Qt.Unchecked:
            data['Is_DLC'] = False
            
        if self.chk_ok.isChecked():
            data['Status_Flag'] = 'OK'
        elif self.chk_new.isChecked():
            data['Status_Flag'] = 'NEW'
            
        return data

class GameManagerModel(QAbstractTableModel):
    def __init__(self, df, display_cols, date_format_str="DD/MM/YYYY"):
        super().__init__()
        self._df = df
        self.display_cols = display_cols
        self.date_format_str = date_format_str

    def rowCount(self, parent=None):
        return len(self._df)

    def columnCount(self, parent=None):
        return len(self.display_cols)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = super().flags(index)
        # WHY: Enable native OS checkboxes purely for the first _selected column without triggering text edit modes.
        if self.display_cols[index.column()] == '_selected':
            flags |= Qt.ItemIsUserCheckable
        else:
            # WHY: Enable edit mode on metadata cells so users can double-click to select and copy partial text safely.
            flags |= Qt.ItemIsEditable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
            
        col_name = self.display_cols[index.column()]
        if role == Qt.CheckStateRole and col_name == '_selected':
            return Qt.Checked if self._df.iloc[index.row()]['_selected'] else Qt.Unchecked
            
        if role == Qt.DisplayRole:
            # WHY: Hide the string value "True/False" from displaying next to the checkbox.
            if col_name == '_selected': return ""
            if col_name == '_edit': return "⚙️"
            if col_name == '_has_img': return "✔" if self._df.iloc[index.row()][col_name] else "❌"
            if col_name == '_has_trl': return "✔" if self._df.iloc[index.row()][col_name] else "❌"
            if col_name == 'Original_Release_Date':
                from ViGaVault_utils import format_date_for_ui
                return format_date_for_ui(str(self._df.iloc[index.row()][col_name]), self.date_format_str)
            return str(self._df.iloc[index.row()][col_name])
            
        if role == Qt.TextAlignmentRole and col_name in ['_edit', '_has_img', '_has_trl']:
            return int(Qt.AlignCenter)
        
        if role == Qt.ForegroundRole:
            from PySide6.QtGui import QColor
            if col_name in ['_has_img', '_has_trl']:
                return QColor("green") if self._df.iloc[index.row()][col_name] else QColor("red")
            
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.CheckStateRole and self.display_cols[index.column()] == '_selected':
            # WHY: Safely evaluate PySide6 CheckState variables natively to avoid Enum comparison failures.
            is_checked = value in (2, Qt.CheckState.Checked, Qt.Checked, True)
            col_idx = self._df.columns.get_loc('_selected')
            self._df.iat[index.row(), col_idx] = is_checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                col_name = self.display_cols[section]
                if col_name == '_selected': return ""
                if col_name == '_edit': return ""
                if col_name == '_has_img': return translator.tr("media_manager_col_image")
                if col_name == '_has_trl': return translator.tr("media_manager_col_trailer")
                # WHY: DRY Principle - Centralized mapping to apply dynamic JSON translations to the raw Pandas column headers.
                headers_map = {
                    'Original_Release_Date': translator.tr("game_manager_col_rel_date"),
                    'Clean_Title': translator.tr("game_manager_col_name"),
                    'Platforms': translator.tr("gamecard_info_platforms"),
                    'Genre': translator.tr("gamecard_info_genre"),
                    'Developer': translator.tr("gamecard_info_developer"),
                    'Publisher': translator.tr("gamecard_info_publisher"),
                    'Collection': translator.tr("gamecard_info_collection"),
                    'Year_Folder': translator.tr("tools_stats_col_year")
                }
                return headers_map.get(col_name, str(col_name))
            else:
                return str(section)
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        # WHY: Enables native PySide6 column header sorting directly on the Pandas DataFrame.
        self.layoutAboutToBeChanged.emit()
        col_name = self.display_cols[column]
        
        # WHY: Sort dates chronologically instead of alphabetically by dynamically targeting the hidden parsed datetime column.
        sort_col = 'temp_sort_date' if col_name == 'Original_Release_Date' and 'temp_sort_date' in self._df.columns else col_name
        
        # WHY: Prevent 'SettingWithCopyWarning' by reassigning the dataframe instead of using inplace=True on a memory slice.
        self._df = self._df.sort_values(
            by=sort_col, 
            ascending=(order == Qt.AscendingOrder), 
            na_position='last'
        )
        self.layoutChanged.emit()

class GameManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(translator.tr("game_manager_title"))
        
        # WHY: Enable native window controls (Maximize/Minimize) so the user can easily toggle out of fullscreen mode.
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        
        # WHY: Strictly enforce Application Modality so the main window is completely locked out while the Game Manager is open.
        self.setWindowModality(Qt.ApplicationModal)
        
        self.resize(1000, 700)
        center_window(self, parent)
        
        layout = QVBoxLayout(self)

        # Top Buttons
        btn_layout = QHBoxLayout()
        self.btn_batch_edit = QPushButton(translator.tr("game_manager_btn_batch_edit"))
        self.btn_batch_delete = QPushButton(translator.tr("game_manager_btn_batch_delete"))
        # WHY: Placeholders for batch logic implementation. Kept disabled until fully fleshed out.
        self.btn_batch_edit.setEnabled(False) 
        self.btn_batch_delete.setEnabled(False)
        
        btn_layout.addWidget(self.btn_batch_edit)
        btn_layout.addWidget(self.btn_batch_delete)
        
        self.btn_batch_edit.clicked.connect(self.request_batch_edit)
        self.btn_batch_delete.clicked.connect(self.request_batch_delete)
        
        self.btn_batch_sync = QPushButton(translator.tr("game_manager_btn_batch_sync"))
        self.btn_batch_sync.setEnabled(False)
        self.btn_batch_sync.clicked.connect(self.request_batch_sync)
        btn_layout.addWidget(self.btn_batch_sync)
        btn_layout.addStretch()
        
        lbl_show = QLabel("Show : ")
        btn_layout.addWidget(lbl_show)
        
        from widgets.custom_inputs import RightAlignedNumberDelegate
        self.combo_view_mode = QComboBox()
        self.combo_view_mode.setItemDelegate(RightAlignedNumberDelegate(self.combo_view_mode))
        for _ in range(3): self.combo_view_mode.addItem("")
        self.combo_view_mode.currentIndexChanged.connect(self.filter_table)
        btn_layout.addWidget(self.combo_view_mode)
        
        layout.addLayout(btn_layout)

        # Column Filters
        filter_row_layout = QHBoxLayout()
        # WHY: Remove spacing so the widgets perfectly snap to the QTableView columns below them.
        filter_row_layout.setSpacing(0)
        filter_row_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_edit_spacer = QLabel()
        self.lbl_edit_spacer.setMinimumWidth(0)
        
        self.chk_select_all = QCheckBox()
        # WHY: Add a tiny margin to roughly center the master checkbox horizontally over the table's checkbox column.
        self.chk_select_all.setStyleSheet("margin-left: 8px;")
        self.chk_select_all.toggled.connect(self.toggle_select_all)
        
        self.chk_missing_img = QCheckBox()
        self.chk_missing_img.setToolTip(translator.tr("sidebar_btn_toggle_no_img"))
        self.chk_missing_img.setStyleSheet("margin-left: 13px;")
        self.chk_missing_img.toggled.connect(self.filter_table)
        
        self.chk_missing_trl = QCheckBox()
        self.chk_missing_trl.setToolTip(translator.tr("sidebar_btn_toggle_no_trl"))
        self.chk_missing_trl.setStyleSheet("margin-left: 13px;")
        self.chk_missing_trl.toggled.connect(self.filter_table)
        
        self.combo_date = CheckableComboBox()
        self.combo_date.setPlaceholderText(translator.tr("game_manager_col_rel_date"))
        self.combo_date.selection_changed.connect(self.filter_table)
        
        self.combo_year = CheckableComboBox()
        self.combo_year.setPlaceholderText(translator.tr("tools_stats_col_year"))
        self.combo_year.selection_changed.connect(self.filter_table)

        self.search_name = QLineEdit()
        self.search_name.setPlaceholderText(translator.tr("game_manager_search_name"))
        
        # WHY: Smart Refresh - A debounce timer prevents GUI lag/stuttering when searching massive libraries quickly.
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.filter_table)
        self.search_name.textChanged.connect(self.search_timer.start)
        
        self.filter_widgets = [self.lbl_edit_spacer, self.chk_select_all, self.chk_missing_img, self.chk_missing_trl, self.combo_date, self.combo_year, self.search_name]
        self.filter_combos = {'Original_Release_Date': self.combo_date, 'Year_Folder': self.combo_year}
        
        # WHY: DRY Principle - Construct columns by merging requested permanent columns with active dynamic filters uniquely.
        core_left = ['Platforms']
        core_right = ['Developer', 'Publisher']
        
        active_filters = []
        if hasattr(self.parent_window, 'filter_controller'):
            active_filters = list(self.parent_window.filter_controller.dynamic_filters.keys())
            
        self.logical_columns = []
        for c in core_left:
            if c not in self.logical_columns: self.logical_columns.append(c)
        for c in active_filters:
            if c not in self.logical_columns and c not in core_right and c != 'Year_Folder': self.logical_columns.append(c)
        for c in core_right:
            if c not in self.logical_columns: self.logical_columns.append(c)
            
        for col in self.logical_columns:
            combo = CheckableComboBox()
            ph = col
            if col == 'Platforms': ph = translator.tr("gamecard_info_platforms")
            elif col == 'Genre': ph = translator.tr("gamecard_info_genre")
            elif col == 'Developer': ph = translator.tr("gamecard_info_developer")
            elif col == 'Publisher': ph = translator.tr("gamecard_info_publisher")
            elif col == 'Collection': ph = translator.tr("gamecard_info_collection")
            
            combo.setPlaceholderText(ph)
            combo.selection_changed.connect(self.filter_table)
            self.filter_combos[col] = combo
            self.filter_widgets.append(combo)
            
        for w in self.filter_widgets:
            filter_row_layout.addWidget(w)
        filter_row_layout.addStretch()

        layout.addLayout(filter_row_layout)
        

        # Table
        self.table = QTableView()
        self.table.clicked.connect(self.on_table_clicked)
        # WHY: Disabled standard row selection highlighting to remove the blue selection bar, 
        # as batch logic is strictly driven by the checkboxes now.
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        # WHY: Enable native sorting by clicking column headers.
        self.table.setSortingEnabled(True)
        
        # WHY: Disable the vertical row number header so the columns align perfectly flush-left with our custom filter row.
        self.table.verticalHeader().setVisible(False)
        
        # WHY: Attach the custom delegate to enforce safe text copying without accidental data modification.
        self.read_only_delegate = ReadOnlyTextDelegate(self.table)
        self.table.setItemDelegate(self.read_only_delegate)
        
        # WHY: Set to Interactive to allow programmatic mathematical shrinking AND manual user adjustments.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().sectionResized.connect(self.sync_filter_widths)
        # WHY: Explicitly set default sort indicator to column 2 (Clean_Title) since 0 is Checkbox and 1 is Date.
        self.table.horizontalHeader().setSortIndicator(2, Qt.AscendingOrder)
        
        layout.addWidget(self.table)

        # Inspector Panel
        self.inspector_group = QGroupBox(translator.tr("game_manager_inspector_title"))
        self.inspector_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.current_insp_folder = None
        insp_main_layout = QVBoxLayout(self.inspector_group)
        
        # GAME NAME (Full Width)
        self.lbl_insp_name = QLabel()
        self.lbl_insp_name.setStyleSheet("font-weight: bold; font-size: 14px;")
        insp_main_layout.addWidget(self.lbl_insp_name)
        
        # BOTTOM ROW: Image on Left, Controls/Trailer on Right
        bottom_row = QHBoxLayout()
        
        # Left: Cover Image
        self.lbl_preview_img = QLabel(translator.tr("dialog_edit_no_cover"))
        self.lbl_preview_img.setAlignment(Qt.AlignCenter)
        self.lbl_preview_img.setFixedSize(180, 270)
        self.lbl_preview_img.setStyleSheet("border: 1px solid #555; background-color: #1e1e1e;")
        bottom_row.addWidget(self.lbl_preview_img, 0, Qt.AlignTop)
        
        # Right: VBox for Controls and Trailer
        right_vbox = QVBoxLayout()
        
        # Right Top: Controls
        controls_layout = QHBoxLayout()
        url_layout = QHBoxLayout()
        
        self.btn_insp_local = QPushButton("Import")
        self.btn_insp_local.setToolTip(translator.tr("media_manager_choice_local"))
        self.btn_insp_local.clicked.connect(self.insp_select_local)
        controls_layout.addWidget(self.btn_insp_local)
        
        from backend.steamgriddb.login_steamgriddb import is_steamgriddb_connected
        if is_steamgriddb_connected():
            self.btn_insp_sgdb = QPushButton("SteamGridDB")
            self.btn_insp_sgdb.clicked.connect(self.insp_search_sgdb)
            controls_layout.addWidget(self.btn_insp_sgdb)
            
        self.btn_insp_yt = QPushButton("YouTube")
        self.btn_insp_yt.clicked.connect(self.insp_search_yt)
        controls_layout.addWidget(self.btn_insp_yt)
            
        self.insp_url = QLineEdit()
        self.insp_url.setPlaceholderText(translator.tr("media_manager_url_placeholder"))
        self.insp_url.setFixedWidth(360)
        url_layout.addWidget(self.insp_url)
        url_layout.addStretch()
        
        self.btn_insp_apply = QPushButton(translator.tr("media_manager_btn_apply"))
        self.btn_insp_apply.setEnabled(False)
        self.insp_url.textChanged.connect(lambda text: self.btn_insp_apply.setEnabled(bool(text.strip()) or bool(self.btn_insp_local.property("selected_file"))))
        self.btn_insp_apply.clicked.connect(self.insp_apply_media)
        controls_layout.addWidget(self.btn_insp_apply)
        controls_layout.addStretch()
        
        right_vbox.addLayout(controls_layout)
        right_vbox.addLayout(url_layout)
        
        # Spacer to push trailer to bottom
        right_vbox.addStretch()
        
        # Right Bottom: Trailer (Bottom Left Aligned)
        self.lbl_preview_trl = QLabel("No Trailer")
        self.lbl_preview_trl.setAlignment(Qt.AlignCenter)
        self.lbl_preview_trl.setFixedSize(360, 203)
        self.lbl_preview_trl.setStyleSheet("border: 1px solid #555; background-color: #1e1e1e;")
        right_vbox.addWidget(self.lbl_preview_trl, 0, Qt.AlignLeft)
        
        bottom_row.addLayout(right_vbox)
        insp_main_layout.addLayout(bottom_row)
        
        layout.addWidget(self.inspector_group)

        # Bottom: Exclusion Word List
        ex_group = QGroupBox(translator.tr("game_manager_exclusion_label"))
        ex_layout = QHBoxLayout(ex_group)
        self.exclusion_input = QLineEdit()
        self.btn_save_exclusions = QPushButton(translator.tr("game_manager_btn_save_exclusions"))
        self.btn_save_exclusions.clicked.connect(self.save_exclusions)
        ex_layout.addWidget(self.exclusion_input)
        ex_layout.addWidget(self.btn_save_exclusions)
        
        ex_layout.addStretch()
        self.btn_cleanup_images = QPushButton(translator.tr("game_manager_btn_cleanup_images"))
        self.btn_cleanup_images.clicked.connect(self.cleanup_images)
        self.btn_cleanup_images.setEnabled(True)

        ex_layout.addWidget(self.btn_cleanup_images)
        
        layout.addWidget(ex_group)
        
        self.load_exclusions()
        self.load_data()
        # WHY: User request to open the dialog fully maximized by default.
        self.showMaximized()

    def on_table_clicked(self, index):
        if not index.isValid(): return
        col_name = self.model.display_cols[index.column()]
        folder_name = self.model._df.iloc[index.row()]['Folder_Name']
        
        self.update_inspector(folder_name)
        
        if col_name == '_edit':
            if hasattr(self.parent_window, 'master_df'):
                game_data = self.parent_window.master_df[self.parent_window.master_df['Folder_Name'] == folder_name].iloc[0].to_dict()
                from dialogs import ActionDialog
                dlg = ActionDialog("dialog_edit_title", game_data, self.parent_window)
                if dlg.exec():
                    new_data = dlg.get_data()
                    if new_data:
                        self.parent_window.update_game_data(folder_name, new_data)
                        self.load_data()

    def get_selected_folders(self):
        """WHY: Securely maps the visually selected rows to their absolute target Folder_Names for backend execution."""
        if not hasattr(self, 'model') or '_selected' not in self.model._df.columns: return []
        selected_df = self.model._df[self.model._df['_selected']]
        # WHY: Use the Pandas index mapping to pull Folder_Name from the absolute base_df since it's hidden from the table.
        return self.base_df.loc[selected_df.index, 'Folder_Name'].tolist()

    def request_batch_delete(self):
        selected_folders = self.get_selected_folders()
        if not selected_folders: return
        
        reply = QMessageBox.warning(
            self,
            translator.tr("game_manager_delete_confirm_title"),
            translator.tr("game_manager_delete_confirm_msg", count=len(selected_folders)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if hasattr(self.parent_window, 'game_operations_controller'):
                self.parent_window.game_operations_controller.batch_delete_games(selected_folders)
            self.load_data()

    def request_batch_edit(self):
        selected_folders = self.get_selected_folders()
        if not selected_folders: return
        
        dlg = BatchEditDialog(len(selected_folders), self)
        if dlg.exec():
            new_data = dlg.get_data()
            if new_data and hasattr(self.parent_window, 'game_operations_controller'):
                self.parent_window.game_operations_controller.batch_update_games(selected_folders, new_data)
                self.load_data()

    def update_inspector(self, folder_name):
        self.current_insp_folder = folder_name
        if hasattr(self.parent_window, 'master_df'):
            df = self.parent_window.master_df
            matches = df[df['Folder_Name'] == folder_name]
            if not matches.empty:
                title = matches.iloc[0].get('Clean_Title', folder_name)
                row_data = matches.iloc[0]
                self.lbl_insp_name.setText(f"Name : {title}")
                
                # Image thumbnail
                img_name = row_data.get('Image_Link')
                if pd.notna(img_name) and str(img_name).strip():
                    from ViGaVault_utils import get_image_path
                    img_path = os.path.join(get_image_path(), os.path.basename(str(img_name)))
                    if os.path.exists(img_path):
                        pixmap = QPixmap(img_path).scaled(180, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.lbl_preview_img.setPixmap(pixmap)
                        self.lbl_preview_img.setText("")
                    else:
                        self.lbl_preview_img.clear()
                        self.lbl_preview_img.setText(translator.tr("dialog_edit_no_cover"))
                else:
                    self.lbl_preview_img.clear()
                    self.lbl_preview_img.setText(translator.tr("dialog_edit_no_cover"))
                    
                # Trailer thumbnail
                trailer_url = row_data.get('Trailer_Link')
                if pd.notna(trailer_url) and str(trailer_url).startswith('http'):
                    match = re.search(r'(?:v=|/)([0-9A-Za-z_-]{11}).*', str(trailer_url))
                    if match:
                        vid_id = match.group(1)
                        self.current_vid_id = vid_id
                        self.lbl_preview_trl.clear()
                        self.lbl_preview_trl.setText("Loading Thumbnail...")
                        from dialogs.trailer_search_dialog import ThumbnailDownloadWorker
                        if not hasattr(self, '_active_workers'):
                            self._active_workers = []
                        self._active_workers = [w for w in self._active_workers if w.isRunning()]
                        
                        worker = ThumbnailDownloadWorker(vid_id)
                        worker.finished.connect(self.on_thumb_ready)
                        self._active_workers.append(worker)
                        worker.start()
                    else:
                        self.lbl_preview_trl.clear()
                        self.lbl_preview_trl.setText("No Trailer")
                else:
                    self.lbl_preview_trl.clear()
                    self.lbl_preview_trl.setText("No Trailer")
                
                self.btn_insp_local.setProperty("selected_file", "")
                self.btn_insp_local.setStyleSheet("")
                self.insp_url.clear()

    def on_thumb_ready(self, vid_id, pixmap):
        if getattr(self, 'current_vid_id', None) != vid_id:
            return
        scaled = pixmap.scaled(360, 203, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.lbl_preview_trl.setPixmap(scaled)
        self.lbl_preview_trl.setText("")

    def insp_select_local(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            translator.tr("media_manager_import_dialog_title"), 
            "", 
            "Image Files (*.jpg *.jpeg *.png *.webp)"
        )
        if file_path:
            self.btn_insp_local.setProperty("selected_file", file_path)
            self.btn_insp_local.setStyleSheet("background-color: #4CAF50;")
            self.insp_apply_media()

    def insp_search_sgdb(self):
        if not self.current_insp_folder: return
        title_to_search = self.lbl_insp_name.text().replace("Name : ", "")
        from dialogs.steamgriddb_picker_dialog import SteamGridDBPickerDialog
        dlg = SteamGridDBPickerDialog(title_to_search, self)
        if dlg.exec():
            selected_url = dlg.selected_url
            if selected_url:
                self.insp_apply_media(direct_url=selected_url)

    def insp_search_yt(self):
        if not self.current_insp_folder: return
        title_to_search = self.lbl_insp_name.text().replace("Name : ", "")
        from dialogs.trailer_search_dialog import TrailerSearchDialog
        dlg = TrailerSearchDialog(title_to_search, self)
        if dlg.exec():
            selected_url = dlg.get_selected_url()
            if selected_url:
                self.insp_apply_media(direct_url=selected_url)

    def insp_apply_media(self, direct_url=None):
        if not isinstance(direct_url, str):
            direct_url = None
            
        folder_name = self.current_insp_folder
        if not folder_name: return
        
        local_file = self.btn_insp_local.property("selected_file")
        url = direct_url if direct_url else self.insp_url.text().strip()
        if not local_file and not url: return
            
        from backend.library import LibraryManager
        from ViGaVault_utils import build_scanner_config
        import logging
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game = manager.games.get(folder_name)
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
                dest_dir = manager.config.get('image_path', os.path.join(BASE_DIR, 'images'))
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
                    match = re.search(r'\.(jpg|jpeg|png|webp)\b', use_url, re.IGNORECASE)
                    ext = match.group(0).lower()
                    dest_dir = manager.config.get('image_path', os.path.join(BASE_DIR, 'images'))
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, f"{safe_filename}{ext}")
                    
                    headers = {'User-Agent': 'Mozilla/5.0'}
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
            logging.error(f"Inspector Media Error: {e}")
            QMessageBox.critical(self, "Error", str(e))
            
        if changes_made:
            manager.save_db()
            self.btn_insp_apply.setEnabled(False)
            new_data = game.to_dict()
            if hasattr(self.parent_window, 'library_controller'):
                self.parent_window.library_controller.patch_memory_df(folder_name, new_data)
            if hasattr(self.parent_window, 'list_controller'):
                self.parent_window.list_controller.update_single_card(folder_name, force_media_reload=True)
            self.load_data()
            self.update_inspector(folder_name)

    def request_batch_sync(self):
        selected_folders = self.get_selected_folders()
        if not selected_folders: return
        
        from backend.steamgriddb.login_steamgriddb import is_steamgriddb_connected
        if not is_steamgriddb_connected():
            QMessageBox.warning(self, "Error", translator.tr("msg_scan_disabled_igdb"))
            return
            
        reply = QMessageBox.question(self, "Batch Sync", f"This will open the SGDB picker sequentially for {len(selected_folders)} games. Continue?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        
        for folder in selected_folders:
            self.update_inspector(folder)
            title = self.lbl_insp_name.text()
            from dialogs.steamgriddb_picker_dialog import SteamGridDBPickerDialog
            dlg = SteamGridDBPickerDialog(title, self)
            if dlg.exec():
                if dlg.selected_url:
                    self.insp_url.setText(dlg.selected_url)
                    self.insp_apply_media()
        
        QMessageBox.information(self, "Done", "Batch Media Sync completed!")

    def cleanup_images(self):
        from ViGaVault_utils import get_image_path
        import os
        import shutil
        
        img_dir = get_image_path()
        if not os.path.exists(img_dir):
            QMessageBox.information(self, "Clean-Up", "Images directory not found.")
            return
            
        orphan_dir = os.path.join(img_dir, "_orphan")
        os.makedirs(orphan_dir, exist_ok=True)
        
        active_images = set(self.parent_window.master_df['Image_Link'].dropna().astype(str))
        active_images = {os.path.basename(img) for img in active_images if img.strip()}
        
        moved_count = 0
        for filename in os.listdir(img_dir):
            if filename.lower() == "_orphan": continue
            src = os.path.join(img_dir, filename)
            
            # Skip moving directories
            if os.path.isdir(src): continue
            
            if filename not in active_images:
                dst = os.path.join(orphan_dir, filename)
                try:
                    shutil.move(src, dst)
                    moved_count += 1
                except Exception as e:
                    print(f"Failed to move {filename}: {e}")
                    
        QMessageBox.information(self, "Clean-Up Complete", f"Moved {moved_count} unused images to the _orphan folder.")

    def load_exclusions(self):
        lib_settings_file = get_library_settings_file()
        settings = load_encrypted_json(lib_settings_file)
        words = settings.get("exclusion_words", [])
        self.exclusion_input.setText(", ".join(words))

    def save_exclusions(self):
        # WHY: Standardize exclusion list format. Convert to lowercase for reliable case-insensitive filtering.
        words = [w.strip().lower() for w in self.exclusion_input.text().split(',') if w.strip()]
        lib_settings_file = get_library_settings_file()
        settings = load_encrypted_json(lib_settings_file)
        settings["exclusion_words"] = words
        save_encrypted_json(lib_settings_file, settings)
        
        # WHY: Targeted update - Trigger a background reload to instantly drop the games from the main view and decrement the sidebar counter.
        if hasattr(self.parent_window, 'library_controller'):
            self.parent_window.library_controller.load_database_async()
        self.accept()

    def toggle_select_all(self, checked):
        # WHY: Targeted update - rapidly check/uncheck all rows in the currently filtered view.
        if hasattr(self, 'model'):
            self.model._df['_selected'] = checked
            self.model.layoutChanged.emit()
            self.update_batch_buttons()

    def update_batch_buttons(self):
        # WHY: Enable the batch buttons only if at least one game is selected in the active model.
        if hasattr(self, 'model') and '_selected' in self.model._df.columns:
            has_selection = self.model._df['_selected'].any()
            all_selected = self.model._df['_selected'].all() and not self.model._df.empty
            
            self.btn_batch_edit.setEnabled(has_selection)
            self.btn_batch_delete.setEnabled(has_selection)
            if hasattr(self, 'btn_batch_sync'): self.btn_batch_sync.setEnabled(has_selection)
            pass
            
            # WHY: Smart Refresh - Synchronize the master "Select All" checkbox state based on the actual table data. 
            # Signals are blocked to prevent triggering an accidental cascade that overwrites the user's manual selections.
            self.chk_select_all.blockSignals(True)
            self.chk_select_all.setChecked(all_selected)
            self.chk_select_all.blockSignals(False)

    def load_data(self):
        if hasattr(self.parent_window, 'master_df'):
            self.base_df = self.parent_window.master_df.copy()
            # WHY: Inject the _edit and _selected virtual columns for checkboxes.
            self.base_df.insert(0, '_selected', False)
            self.base_df.insert(0, '_edit', 'Edit')
            
            import pandas as pd
            has_img_series = self.base_df['Has_Image'] if 'Has_Image' in self.base_df.columns else pd.Series(False, index=self.base_df.index)
            trl_series = self.base_df['Trailer_Link'] if 'Trailer_Link' in self.base_df.columns else pd.Series("", index=self.base_df.index)
            
            self.base_df.insert(2, '_has_img', has_img_series.astype(str).str.lower().isin(['true', '1']))
            self.base_df.insert(3, '_has_trl', trl_series.astype(str).str.startswith('http'))
            
            # WHY: Populate each multi-select dropdown with the unique comma-separated elements from the target column.
            for col, combo in self.filter_combos.items():
                combo.blockSignals(True)
                combo.clear_items()
                # WHY: Extract unique values from the absolute master_df so dropdowns never lose options as filters shrink the list.
                if col in self.parent_window.master_df.columns:
                    unique_vals = set()
                    for val in self.parent_window.master_df[col].dropna().unique():
                        parts = [p.strip() for p in str(val).split(',') if p.strip()]
                        unique_vals.update(parts)
                    # WHY: Initialize to checked=False so the user opts-in to filtering.
                    for val in sorted(list(unique_vals), key=lambda x: x.lower()):
                        combo.add_item(val, checked=False)
                combo.blockSignals(False)

            self.update_view_mode_counts()
            self.filter_table()

    def update_view_mode_counts(self):
        if not hasattr(self.parent_window, 'master_df') or self.parent_window.master_df is None or self.parent_window.master_df.empty: return
        df = self.parent_window.master_df
        
        valid_mask = ~df['Is_DLC'] & ~df['Is_Excluded']
        valid_df = df[valid_mask]
        
        counts = [
            len(valid_df[valid_df['Status_Flag'].isin(['OK', 'LOCKED'])]),
            len(valid_df[valid_df['Status_Flag'].isin(['NEW', 'NEEDS_ATTENTION'])]),
            len(df[df['Is_DLC'] | df['Is_Excluded']])
        ]
        
        labels = [
            "Game Catalog",
            translator.tr("sidebar_btn_toggle_new"),
            translator.tr("sidebar_btn_toggle_dlc")
        ]
        
        self.combo_view_mode.blockSignals(True)
        for i in range(3):
            self.combo_view_mode.setItemText(i, labels[i])
            self.combo_view_mode.setItemData(i, counts[i], Qt.UserRole)
        self.combo_view_mode.blockSignals(False)

    def filter_table(self):
        if not hasattr(self, 'base_df'): return
        df = self.base_df.copy()
        text = self.search_name.text().lower()
        
        if text:
            df = df[df['Clean_Title'].str.lower().str.contains(text, na=False)]
            
        view_idx = self.combo_view_mode.currentIndex()
        if view_idx == 0:
            df = df[df['Status_Flag'].isin(['OK', 'LOCKED']) & ~df['Is_DLC'] & ~df['Is_Excluded']]
        elif view_idx == 1:
            df = df[df['Status_Flag'].isin(['NEW', 'NEEDS_ATTENTION']) & (df['Is_DLC'] != True) & (df['Is_Excluded'] != True)]
        elif view_idx == 2:
            df = df[(df['Is_DLC'] == True) | (df['Is_Excluded'] == True)]
            
        if self.chk_missing_img.isChecked():
            df = df[df['_has_img'] == False]
            
        if self.chk_missing_trl.isChecked():
            df = df[df['_has_trl'] == False]
            
        # WHY: Apply interdependent Excel-style filtering across all active dropdown columns.
        for col, combo in self.filter_combos.items():
            if col not in df.columns: continue
            
            checked_items = combo.get_checked_items()
            total_items = combo.model().rowCount()
            
            if len(checked_items) == total_items: continue
                
            if not checked_items:
                # WHY: If zero items are checked, treat as "Show All" and let the data pass completely unhindered.
                continue
                
            pattern = '|'.join([re.escape(i) for i in checked_items])
            df = df[df[col].astype(str).str.contains(pattern, case=False, na=False)]

        # WHY: Construct the Pandas display columns perfectly ordered to match the assembled UI widgets.
        cols = ['_edit', '_selected', '_has_img', '_has_trl', 'Original_Release_Date', 'Year_Folder', 'Clean_Title'] + self.logical_columns
        existing_cols = [c for c in cols if c in df.columns]
        
        # WHY: Preserve user sorting preferences dynamically when filters drastically alter the visible rows.
        header = self.table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        
        # WHY: Force default sorting to Name (Clean_Title) upon initial load or if uninitialized.
        if sort_col < 0 or sort_col >= len(existing_cols):
            sort_col = existing_cols.index('Clean_Title') if 'Clean_Title' in existing_cols else 0
            sort_order = Qt.AscendingOrder
            
        fmt_str = getattr(self.parent_window, 'date_format_str', 'DD/MM/YYYY')
        self.model = GameManagerModel(df.copy(), existing_cols, date_format_str=fmt_str)
        self.model.dataChanged.connect(self.update_batch_buttons)
        self.model.sort(sort_col, sort_order)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSortIndicator(sort_col, sort_order)
        
        # WHY: Apply the user-requested fixed and evenly-distributed column widths flawlessly using native Qt rules.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 30)
        
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 30)
        
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 40)
        
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 40)
        
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 110)
        
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 75)
        
        for i in range(6, header.count()):
            header.setSectionResizeMode(i, QHeaderView.Stretch)

        self.update_batch_buttons()
        # WHY: Smart Layout Update - Defer column calculation by 50ms so Qt has time to paint the geometry first.
        QTimer.singleShot(50, self.force_sync_widths)

    def force_sync_widths(self):
        header = self.table.horizontalHeader()
        for i in range(header.count()):
            self.sync_filter_widths(i, 0, header.sectionSize(i))

    def sync_filter_widths(self, logicalIndex, oldSize, newSize):
        """WHY: Single Responsibility - Binds the exact pixel width of the filter widgets to their corresponding table columns."""
        if logicalIndex < len(self.filter_widgets):
            widget = self.filter_widgets[logicalIndex]
            # WHY: Force minimum width to 0 to prevent the layout from resisting mathematical shrinking below default bounds.
            widget.setMinimumWidth(0)
            widget.setFixedWidth(newSize)