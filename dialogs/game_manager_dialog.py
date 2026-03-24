# WHY: Single Responsibility Principle - Dedicated view strictly for Batch Game Management and Exclusion List configuration.
import os
import json
import re
import pandas as pd
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QTableView, QLineEdit, QLabel, QGroupBox, QAbstractItemView,
                               QHeaderView, QCheckBox, QFormLayout, QMessageBox, QStyledItemDelegate)
from PySide6.QtCore import Qt, QAbstractTableModel, QTimer, Signal
from ViGaVault_utils import translator, get_library_settings_file, center_window
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
            
        # WHY: Use a tristate checkbox so the user can explicitly choose to mark, unmark, or completely ignore the DLC status during batch edits.
        self.chk_dlc = QCheckBox(translator.tr("batch_edit_mark_dlc"))
        self.chk_dlc.setTristate(True)
        self.chk_dlc.setCheckState(Qt.PartiallyChecked)
        self.form_layout.addRow(self.chk_dlc)
        
        layout.addWidget(form_group)

        btn_box = QHBoxLayout()
        btn_save = QPushButton(translator.tr("settings_btn_save"))
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def get_data(self):
        # WHY: Smart filtering mathematically drops completely blank inputs so they safely skip the backend logic.
        data = {field: inp.text().strip() for field, inp in self.inputs.items() if inp.text().strip()}
        
        # WHY: Interpret the tristate checkbox to cleanly apply or revoke the DLC flag, while safely ignoring it if left partially checked.
        if self.chk_dlc.checkState() == Qt.Checked:
            data['Is_DLC'] = True
        elif self.chk_dlc.checkState() == Qt.Unchecked:
            data['Is_DLC'] = False
            
        return data

class GameManagerModel(QAbstractTableModel):
    def __init__(self, df, display_cols):
        super().__init__()
        self._df = df
        self.display_cols = display_cols

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
            return str(self._df.iloc[index.row()][col_name])
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
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Column Filters
        filter_row_layout = QHBoxLayout()
        # WHY: Remove spacing so the widgets perfectly snap to the QTableView columns below them.
        filter_row_layout.setSpacing(0)
        filter_row_layout.setContentsMargins(0, 0, 0, 0)
        
        self.chk_select_all = QCheckBox()
        # WHY: Add a tiny margin to roughly center the master checkbox horizontally over the table's checkbox column.
        self.chk_select_all.setStyleSheet("margin-left: 8px;")
        self.chk_select_all.toggled.connect(self.toggle_select_all)
        
        self.combo_date = CheckableComboBox()
        self.combo_date.setPlaceholderText(translator.tr("game_manager_col_rel_date"))
        self.combo_date.selection_changed.connect(self.filter_table)

        self.search_name = QLineEdit()
        self.search_name.setPlaceholderText(translator.tr("game_manager_search_name"))
        
        # WHY: Smart Refresh - A debounce timer prevents GUI lag/stuttering when searching massive libraries quickly.
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.filter_table)
        self.search_name.textChanged.connect(self.search_timer.start)
        
        self.filter_widgets = [self.chk_select_all, self.combo_date, self.search_name]
        self.filter_combos = {'Original_Release_Date': self.combo_date}
        
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
            if c not in self.logical_columns and c not in core_right: self.logical_columns.append(c)
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
            elif col == 'Year_Folder': ph = translator.tr("tools_stats_col_year")
            
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

        # Bottom: Exclusion Word List
        ex_group = QGroupBox(translator.tr("game_manager_exclusion_label"))
        ex_layout = QHBoxLayout(ex_group)
        self.exclusion_input = QLineEdit()
        self.btn_save_exclusions = QPushButton(translator.tr("game_manager_btn_save_exclusions"))
        self.btn_save_exclusions.clicked.connect(self.save_exclusions)
        ex_layout.addWidget(self.exclusion_input)
        ex_layout.addWidget(self.btn_save_exclusions)
        layout.addWidget(ex_group)
        
        self.load_exclusions()
        self.load_data()
        # WHY: User request to open the dialog fully maximized by default.
        self.showMaximized()

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

    def load_exclusions(self):
        lib_settings_file = get_library_settings_file()
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    settings = json.load(f)
                    words = settings.get("exclusion_words", [])
                    self.exclusion_input.setText(", ".join(words))
            except:
                pass

    def save_exclusions(self):
        # WHY: Standardize exclusion list format. Convert to lowercase for reliable case-insensitive filtering.
        words = [w.strip().lower() for w in self.exclusion_input.text().split(',') if w.strip()]
        lib_settings_file = get_library_settings_file()
        settings = {}
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    settings = json.load(f)
            except:
                pass
        settings["exclusion_words"] = words
        try:
            with open(lib_settings_file, "w", encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except:
            pass
        
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
            
            # WHY: Smart Refresh - Synchronize the master "Select All" checkbox state based on the actual table data. 
            # Signals are blocked to prevent triggering an accidental cascade that overwrites the user's manual selections.
            self.chk_select_all.blockSignals(True)
            self.chk_select_all.setChecked(all_selected)
            self.chk_select_all.blockSignals(False)

    def load_data(self):
        if hasattr(self.parent_window, 'master_df'):
            self.base_df = self.parent_window.master_df.copy()
            # WHY: Inject the _selected virtual column for checkboxes.
            self.base_df.insert(0, '_selected', False)
            
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
                    for val in sorted(list(unique_vals)):
                        combo.add_item(val, checked=False)
                combo.blockSignals(False)

            self.filter_table()

    def filter_table(self):
        if not hasattr(self, 'base_df'): return
        df = self.base_df.copy()
        text = self.search_name.text().lower()
        
        if text:
            df = df[df['Clean_Title'].str.lower().str.contains(text, na=False)]
            
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
        cols = ['_selected', 'Original_Release_Date', 'Clean_Title'] + self.logical_columns
        existing_cols = [c for c in cols if c in df.columns]
        
        # WHY: Preserve user sorting preferences dynamically when filters drastically alter the visible rows.
        header = self.table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        
        # WHY: Force default sorting to Name (Clean_Title) upon initial load or if uninitialized.
        if sort_col < 0 or sort_col >= len(existing_cols):
            sort_col = existing_cols.index('Clean_Title') if 'Clean_Title' in existing_cols else 0
            sort_order = Qt.AscendingOrder
            
        # WHY: Pass the full dataframe (as a hard copy) and the display column list separately 
        # so the model can access hidden sorting metrics without breaking the visual table layout.
        self.model = GameManagerModel(df.copy(), existing_cols)
        self.model.dataChanged.connect(self.update_batch_buttons)
        self.model.sort(sort_col, sort_order)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSortIndicator(sort_col, sort_order)
        
        # WHY: Apply the user-requested fixed and evenly-distributed column widths flawlessly using native Qt rules.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 30)
        
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        # WHY: Increased fixed width from 90 to 110 to ensure the full date format (DD/MM/YYYY) and combobox UI elements are completely visible.
        self.table.setColumnWidth(1, 110)
        
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        for i in range(3, header.count()):
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