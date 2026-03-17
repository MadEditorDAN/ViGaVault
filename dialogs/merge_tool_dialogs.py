# WHY: Single Responsibility Principle - Handles ONLY the library merging and conflict resolution logic.
import os
import difflib
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton, QScrollArea, 
                               QWidget, QGridLayout, QFrame, QButtonGroup, QRadioButton, QTextEdit, QLineEdit)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from ViGaVault_utils import get_image_path, get_video_path, translator

class MergeSelectionDialog(QDialog):
    def __init__(self, current_data, master_df, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("dialog_merge_title"))
        self.resize(1150, 500) # WHY: Expanded to provide adequate room for the separated columns
        self.current_title = current_data.get('Clean_Title', '')
        self.current_folder = current_data.get('Folder_Name', '')
        self.master_df = master_df
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(translator.tr("dialog_merge_desc")))
        
        self.chk_show_all = QCheckBox(translator.tr("dialog_merge_show_all"))
        self.chk_show_all.toggled.connect(self.populate_list)
        layout.addWidget(self.chk_show_all)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(5)
        self.table_widget.setHorizontalHeaderLabels([
            translator.tr("dialog_merge_col_date"), 
            translator.tr("dialog_merge_col_name"), 
            translator.tr("dialog_merge_col_platform"), 
            translator.tr("dialog_merge_col_match"), 
            translator.tr("dialog_merge_col_path")
        ])
        # WHY: Force short text to fit perfectly while allocating all remaining stretch space purely to Title and Path.
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table_widget)
        
        # Pre-calculate textual resemblance for the default filtered view
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
            games = self.master_df.sort_values(by='Clean_Title').to_dict('records')
            for g in games:
                items_to_show.append((None, g))
        else:
            for ratio, g in self.resembling:
                items_to_show.append((ratio, g))

        target_row = -1
        for i, (ratio, g) in enumerate(items_to_show):
            row = self.table_widget.rowCount()
            self.table_widget.insertRow(row)
            
            date_val = str(g.get('Original_Release_Date') or g.get('Year_Folder', ''))
            name_val = str(g.get('Clean_Title', ''))
            plat_val = str(g.get('Platforms', ''))
            path_val = str(g.get('Path_Root', ''))
            match_val = f"{int(ratio*100)}%" if ratio is not None else ""
                
            if g.get('Folder_Name') == self.current_folder:
                name_val = f">>> {name_val} <<<"
                target_row = row
                
            item_date = QTableWidgetItem(date_val)
            item_date.setData(Qt.UserRole, g)
            
            self.table_widget.setItem(row, 0, item_date)
            self.table_widget.setItem(row, 1, QTableWidgetItem(name_val))
            self.table_widget.setItem(row, 2, QTableWidgetItem(plat_val))
            
            item_match = QTableWidgetItem(match_val)
            item_match.setTextAlignment(Qt.AlignCenter)
            self.table_widget.setItem(row, 3, item_match)
            
            path_item = QTableWidgetItem(path_val)
            path_item.setToolTip(path_val) # WHY: Ensures the path is always viewable on hover, even if the user resizes the window down.
            self.table_widget.setItem(row, 4, path_item)
            
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
        
        self.grid = QGridLayout(container)
        
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        self.grid.addWidget(vline, 0, 3, len(conflicts) + 1, 1)

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
            rb_a.setChecked(True)
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
        if field == 'Image_Link' and val:
            full_path = os.path.join(get_image_path(), os.path.basename(val))
            if os.path.exists(full_path):
                lbl = QLabel()
                lbl.setPixmap(QPixmap(full_path).scaled(150, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                lbl.setAlignment(Qt.AlignCenter)
                return lbl
        elif field == 'Path_Video' and val:
            full_path = os.path.join(get_video_path(), os.path.basename(val))
            if os.path.exists(full_path):
                btn = QPushButton(translator.tr("dialog_conflict_btn_play"))
                btn.clicked.connect(lambda _, v=full_path: os.startfile(v))
                return btn
        elif field == 'Summary':
            txt = QTextEdit(val)
            txt.setReadOnly(True)
            txt.setMaximumHeight(80)
            return txt
        else:
            txt = QLineEdit(val)
            txt.setReadOnly(True)
            txt.setCursorPosition(0) 
            return txt

    def get_resolutions(self):
        for field, bg in self.bgs.items():
            winner_idx = bg.checkedId()
            self.resolutions[field] = self.conflicts[field]['A'] if winner_idx == 0 else self.conflicts[field]['B']
        return self.resolutions