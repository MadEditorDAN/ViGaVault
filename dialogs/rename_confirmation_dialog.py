import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QCheckBox, QWidget)
from PySide6.QtCore import Qt
from ViGaVault_utils import translator

class RenameConfirmationDialog(QDialog):
    def __init__(self, proposed_renames, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Folder Renames")
        self.resize(800, 500)
        self.proposed_renames = proposed_renames
        self.approved_renames = []
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel(
            "The following local game folders have been successfully scraped.\n"
            "Would you like to automatically rename them to their standard canonical names?\n"
            "Uncheck any folders you prefer to leave as they are."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        self.table = QTableWidget(len(self.proposed_renames), 3)
        self.table.setHorizontalHeaderLabels(["Rename", "Current Folder Name", "Proposed Standard Name"])
        
        # Adjust column widths for optimal readability
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setAlternatingRowColors(True)
        
        self.checkboxes = []
        
        for row, rename_data in enumerate(self.proposed_renames):
            # Checkbox
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(True)
            chk_layout.addWidget(chk)
            self.table.setCellWidget(row, 0, chk_widget)
            self.checkboxes.append(chk)
            
            # Old Name
            old_item = QTableWidgetItem(rename_data['old_folder'])
            old_item.setFlags(old_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, old_item)
            
            # New Name
            new_item = QTableWidgetItem(rename_data['new_folder'])
            new_item.setFlags(new_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, new_item)
            
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("Cancel All")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_confirm = QPushButton("Apply Selected Renames")
        self.btn_confirm.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_confirm.clicked.connect(self.process_approvals)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        
        layout.addLayout(btn_layout)

    def process_approvals(self):
        for i, chk in enumerate(self.checkboxes):
            if chk.isChecked():
                self.approved_renames.append(self.proposed_renames[i])
        self.accept()

    def get_approved_renames(self):
        return self.approved_renames
