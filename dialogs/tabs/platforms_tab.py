# WHY: Single Responsibility Principle - Strictly manages cloud integration UI, 
# WebEngine auth invocation, and OAuth token signaling.
import re
import webbrowser
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTableWidget, 
                               QHeaderView, QAbstractItemView, QLabel, QPushButton, 
                               QMessageBox, QInputDialog)
from PySide6.QtCore import Qt, QTimer, Signal

from ViGaVault_utils import translator

class PlatformsTabWidget(QWidget):
    changed = Signal()
    connection_changed = Signal(str, bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox(translator.tr("tools_platform_header"))
        g_layout = QVBoxLayout(group)
        
        self.platform_table = QTableWidget()
        self.platform_table.setColumnCount(2)
        self.platform_table.horizontalHeader().setVisible(False)
        self.platform_table.verticalHeader().setVisible(False)
        self.platform_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.platform_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.platform_table.setShowGrid(False)
        self.platform_table.setAlternatingRowColors(True)
        self.platform_table.setStyleSheet("QTableWidget { alternate-background-color: palette(alternate-base); }")
        
        self.platform_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.platform_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        
        platforms = [
            ("gog", "GOG", "© CD Projekt"), ("epic", "Epic Games Store", "© Epic Games"), 
            ("steam", "Steam", "© Valve Corporation"), ("amazon", "Amazon", "© Amazon.com, Inc."), 
            ("uplay", "Uplay", "© Ubisoft"), ("battlenet", "Battle.net", "© Blizzard Entertainment"),
            ("origin", "Origin", "© Electronic Arts"), ("itch", "itch.io", "© Itch Corp"), 
            ("xbox", "Xbox", "© Microsoft"), ("psn", "PSN", "© Sony Interactive Entertainment")
        ]
        
        self.platform_table.setRowCount(len(platforms))
        self.platform_table.verticalHeader().setDefaultSectionSize(55)
        
        for row, (p_id, p_name, p_copy) in enumerate(platforms):
            lbl_name = QLabel(f"<b>{p_name}</b> &nbsp;&nbsp;<span style='color:gray; font-size:10px;'>{p_copy}</span>")
            lbl_name.setTextFormat(Qt.RichText)
            lbl_name.setContentsMargins(15, 0, 0, 0)
            self.platform_table.setCellWidget(row, 0, lbl_name)
            
            is_connected = False
            if p_id == "gog":
                try:
                    from backend.gog.login_gog import is_gog_connected
                    is_connected = is_gog_connected()
                except ImportError: pass
            elif p_id == "epic":
                try:
                    from backend.epic.login_epic import is_epic_connected
                    is_connected = is_epic_connected()
                except ImportError: pass
            
            btn_connect = QPushButton()
            self.update_platform_btn_ui(btn_connect, is_connected)
            btn_connect.clicked.connect(lambda _, pid=p_id, b=btn_connect: self.handle_platform_action(pid, b))
            btn_connect.setFixedWidth(120)
            
            btn_container = QWidget()
            btn_layout = QHBoxLayout(btn_container)
            btn_layout.setContentsMargins(0, 5, 15, 5) 
            btn_layout.addWidget(btn_connect)
            self.platform_table.setCellWidget(row, 1, btn_container)
            
        g_layout.addWidget(self.platform_table)
        layout.addWidget(group)

    def update_platform_btn_ui(self, btn, is_connected):
        if is_connected:
            btn.setText(translator.tr("tools_platform_btn_disconnect"))
            btn.setStyleSheet("color: #C62828; font-weight: bold;")
        else:
            btn.setText(translator.tr("tools_platform_btn_connect"))
            btn.setStyleSheet("")

    def handle_platform_action(self, platform_id, btn):
        if platform_id == "gog":
            try: from dialogs.login_browser_dialog import LoginBrowserDialog 
            except ImportError:
                QMessageBox.critical(self, "Missing Dependency", "Please install PySide6-WebEngine to use platform connections:\n\npip install PySide6-WebEngine")
                return
                
            from backend.gog.login_gog import is_gog_connected, disconnect_gog, save_gog_session, exchange_code_for_token
            if is_gog_connected():
                disconnect_gog()
                self.update_platform_btn_ui(btn, False)
                self.connection_changed.emit("gog", False)
            else:
                oauth_url = "https://auth.gog.com/auth?client_id=46899977096215655&redirect_uri=https://embed.gog.com/on_login_success%3Forigin%3Dclient&response_type=code&layout=client2"
                dlg = LoginBrowserDialog(oauth_url, success_url="on_login_success", parent=self)
                
                def on_gog_finished(result):
                    def handle_gog_result():
                        if dlg.success_triggered and dlg.auth_code:
                            token_data = exchange_code_for_token(dlg.auth_code)
                            if token_data and 'access_token' in token_data:
                                save_gog_session(token_data)
                                self.update_platform_btn_ui(btn, True)
                                self.connection_changed.emit("gog", True)
                            else: QMessageBox.warning(self, "Login Failed", "Failed to negotiate OAuth token with GOG.")
                        else: QMessageBox.warning(self, "Login Failed", translator.tr("msg_login_failed"))
                        dlg.deleteLater()
                    QTimer.singleShot(100, handle_gog_result)
                dlg.finished.connect(on_gog_finished)
                dlg.open()
                
        elif platform_id == "epic":
            from backend.epic.login_epic import is_epic_connected, disconnect_epic, exchange_code_for_token, save_epic_session
            if is_epic_connected():
                disconnect_epic()
                self.update_platform_btn_ui(btn, False)
                self.connection_changed.emit("epic", False)
            else:
                instruction_msg = translator.tr("msg_epic_login_instructions")
                reply = QMessageBox.information(self, translator.tr("msg_epic_login_title"), instruction_msg, QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Ok:
                    oauth_url = "https://www.epicgames.com/id/login?redirectUrl=https%3A%2F%2Fwww.epicgames.com%2Fid%2Fapi%2Fredirect%3FclientId%3D34a02cf8f4414e29b15921876da36f9a%26responseType%3Dcode"
                    webbrowser.open(oauth_url)
                    def prompt_token():
                        code_input, ok = QInputDialog.getText(self, translator.tr("msg_epic_input_title"), translator.tr("msg_epic_input_prompt"))
                        if ok and code_input:
                            match = re.search(r'([a-fA-F0-9]{32})', code_input)
                            if match:
                                auth_code = match.group(1)
                                token_data = exchange_code_for_token(auth_code)
                                if token_data and 'access_token' in token_data:
                                    save_epic_session(token_data)
                                    self.update_platform_btn_ui(btn, True)
                                    self.connection_changed.emit("epic", True)
                                else: QMessageBox.warning(self, "Login Failed", translator.tr("msg_epic_token_failed"))
                            else: QMessageBox.warning(self, "Login Failed", translator.tr("msg_epic_invalid_code"))
                    QTimer.singleShot(200, prompt_token)
        else:
            QMessageBox.information(self, "Info", translator.tr("tools_platform_not_impl"))