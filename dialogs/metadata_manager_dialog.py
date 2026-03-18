# WHY: Single Responsibility Principle - Handles ONLY the batch deletion of metadata categories.
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QWidget, QCheckBox,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton, QMessageBox, QLabel, QLineEdit, QGroupBox)
from PySide6.QtCore import Qt, QTimer
from ViGaVault_utils import translator, DIALOG_STD_SIZE, center_window

class CheckboxCellWidget(QWidget):
    """WHY: Intercepts clicks anywhere on the cell background and mathematically toggles the target checkbox."""
    def __init__(self, checkbox, parent=None):
        super().__init__(parent)
        self.checkbox = checkbox
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.checkbox.toggle()
        super().mouseReleaseEvent(event)

class MetadataManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(translator.tr("dialog_meta_title"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        # WHY: Persistent state lists to prevent checkboxes from un-checking while typing in the search bar.
        self.all_values = []
        self.checked_values = set()
        
        layout = QVBoxLayout(self)
        
        top_group = QGroupBox()
        top_layout = QFormLayout(top_group)
        self.combo_field = QComboBox()
        self.combo_field.addItems(["Platforms", "Genre", "Collection", "Developer", "Publisher"])
        self.combo_field.currentTextChanged.connect(self.populate_list)
        top_layout.addRow(translator.tr("dialog_meta_target_field"), self.combo_field)
        
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText(translator.tr("dialog_meta_search_placeholder"))
        self.search_filter.setClearButtonEnabled(True)
        self.search_filter.textChanged.connect(self.on_filter_changed)
        top_layout.addRow(translator.tr("dialog_meta_search_label"), self.search_filter)
        layout.addWidget(top_group)
        
        table_group = QGroupBox()
        table_layout = QVBoxLayout(table_group)
        # WHY: Upgraded from QListWidget to QTableWidget to enforce a rigid 2-column grid layout natively.
        self.table_widget = QTableWidget()
        # WHY: Upgraded to 4 columns to perfectly utilize the 1280px width without leaving gaps.
        self.table_widget.setColumnCount(4)
        self.table_widget.horizontalHeader().setVisible(False)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_widget.setShowGrid(False)
        table_layout.addWidget(self.table_widget)
        layout.addWidget(table_group)
        
        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton(translator.tr("dialog_meta_btn_delete"))
        self.btn_delete.setStyleSheet("color: #C62828; font-weight: bold;")
        self.btn_delete.clicked.connect(self.delete_selected)
        btn_close = QPushButton(translator.tr("btn_close"))
        btn_close.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
        
        self.populate_list()
        
    def populate_list(self):
        self.checked_values.clear()
        field = self.combo_field.currentText()
        df = self.parent_window.master_df
        
        if field not in df.columns:
            self.all_values = []
            self.render_table()
            return
            
        values = set()
        for val_list in df[field].dropna().unique():
            for val in str(val_list).split(','):
                v = val.strip()
                if v: values.add(v)
                
        self.all_values = sorted(list(values))
        self.render_table()
        
    def update_checked_state(self, val, checked):
        if checked: self.checked_values.add(val)
        else: self.checked_values.discard(val)

    def on_filter_changed(self):
        self.render_table()

    def render_table(self):
        self.table_widget.setRowCount(0)
        search_text = self.search_filter.text().lower()
        
        # WHY: Strictly search from the beginning of the string as requested.
        filtered_values = [v for v in self.all_values if v.lower().startswith(search_text)]
        
        for i, val in enumerate(filtered_values):
            row = i // 4
            col = i % 4
            if col == 0:
                self.table_widget.insertRow(row)
                
            chk = QCheckBox()
            
            # WHY: Wraps the cell in our custom event-intercepting widget to make the entire zone clickable.
            cell_widget = CheckboxCellWidget(chk)
            # WHY: Use an ID selector to prevent the background color and margins from cascading into the child QCheckBox and causing a "ghost" box.
            cell_widget.setObjectName("cell")
            cell_widget.setStyleSheet("QWidget#cell { background-color: palette(alternate-base); border-radius: 4px; margin: 2px; }")
            cell_layout = QHBoxLayout(cell_widget)
            cell_layout.setContentsMargins(8, 4, 8, 4)
            
            lbl = QLabel(val)
            lbl.setStyleSheet("background: transparent; padding-left: 5px;")
            
            if val in self.checked_values: chk.setChecked(True)
            chk.toggled.connect(lambda checked, v=val: self.update_checked_state(v, checked))
            
            cell_layout.addWidget(lbl)
            cell_layout.addStretch()
            cell_layout.addWidget(chk)
            
            self.table_widget.setCellWidget(row, col, cell_widget)
            
    def delete_selected(self):
        items_to_delete = list(self.checked_values)
                
        if not items_to_delete:
            return
        
        reply = QMessageBox.warning(
            self, 
            translator.tr("dialog_meta_confirm_title"),
            f"{translator.tr('dialog_meta_confirm_msg')}\n\nSelected items: {len(items_to_delete)}",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            field = self.combo_field.currentText()
            if hasattr(self.parent_window, 'library_controller'):
                self.parent_window.library_controller.batch_delete_metadata(field, items_to_delete)
            self.populate_list()