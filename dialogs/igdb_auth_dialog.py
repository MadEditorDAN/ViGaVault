# WHY: Single Responsibility - Provides a dedicated, localized UI for users to input and validate their own IGDB API Keys safely.
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QMessageBox, QGroupBox, QFormLayout)
from PySide6.QtCore import Qt

from ViGaVault_utils import translator, center_window
from backend.igdb.login_igdb import validate_igdb_keys, save_igdb_keys

class IGDBAuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("tools_platform_igdb"))
        # WHY: Expanded geometry from 500x300 to 550x420 to comfortably fit the detailed Twitch form instructions.
        self.setFixedSize(550, 420)
        center_window(self, parent)
        
        layout = QVBoxLayout(self)
        
        info_group = QGroupBox()
        info_layout = QVBoxLayout(info_group)
        lbl_info = QLabel(translator.tr("msg_igdb_instructions"))
        lbl_info.setWordWrap(True)
        lbl_info.setTextFormat(Qt.RichText)
        lbl_info.setOpenExternalLinks(True)
        info_layout.addWidget(lbl_info)
        layout.addWidget(info_group)
        
        form_group = QGroupBox()
        form_layout = QFormLayout(form_group)
        self.client_id_input = QLineEdit()
        self.client_secret_input = QLineEdit()
        self.client_secret_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("Client ID:", self.client_id_input)
        form_layout.addRow("Client Secret:", self.client_secret_input)
        layout.addWidget(form_group)
        
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton(translator.tr("settings_btn_apply"))
        self.btn_apply.clicked.connect(self.validate_and_save)
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
    def validate_and_save(self):
        # WHY: Target Update - Prevents the UI from freezing while validating with the external server.
        self.btn_apply.setEnabled(False)
        client_id = self.client_id_input.text().strip()
        client_secret = self.client_secret_input.text().strip()
        
        if not client_id or not client_secret:
            QMessageBox.warning(self, "Error", translator.tr("msg_igdb_invalid_keys"))
            self.btn_apply.setEnabled(True)
            return
            
        if validate_igdb_keys(client_id, client_secret):
            save_igdb_keys(client_id, client_secret)
            self.accept()
        else:
            QMessageBox.warning(self, "Error", translator.tr("msg_igdb_invalid_keys"))
            self.btn_apply.setEnabled(True)