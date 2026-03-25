# WHY: Single Responsibility - Provides a dedicated, localized UI for users to input and validate their own Steam Web API Keys safely.
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QMessageBox, QGroupBox, QFormLayout)
from PySide6.QtCore import Qt

from ViGaVault_utils import translator, center_window
from backend.steam.login_steam import validate_steam_keys, save_steam_session

class SteamAuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam")
        self.setFixedSize(550, 420)
        center_window(self, parent)
        
        layout = QVBoxLayout(self)
        
        info_group = QGroupBox()
        info_layout = QVBoxLayout(info_group)
        lbl_info = QLabel(translator.tr("msg_steam_instructions"))
        lbl_info.setWordWrap(True)
        lbl_info.setTextFormat(Qt.RichText)
        lbl_info.setOpenExternalLinks(True)
        info_layout.addWidget(lbl_info)
        layout.addWidget(info_group)
        
        form_group = QGroupBox()
        form_layout = QFormLayout(form_group)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.steam_id_input = QLineEdit()
        form_layout.addRow("Steam Web API Key:", self.api_key_input)
        form_layout.addRow("Profile URL or SteamID:", self.steam_id_input)
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
        self.btn_apply.setEnabled(False)
        api_key = self.api_key_input.text().strip()
        steam_input = self.steam_id_input.text().strip()
        
        if not api_key or not steam_input:
            QMessageBox.warning(self, "Error", translator.tr("msg_steam_invalid_keys"))
            self.btn_apply.setEnabled(True)
            return
            
        resolved_id = validate_steam_keys(api_key, steam_input)
        if resolved_id:
            save_steam_session({"api_key": api_key, "steam_id": resolved_id})
            self.accept()
        else:
            QMessageBox.warning(self, "Error", translator.tr("msg_steam_invalid_keys"))
            self.btn_apply.setEnabled(True)