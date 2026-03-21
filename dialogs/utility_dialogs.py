# WHY: Single Responsibility Principle - A place for minor, utility-level popups and informational dialogs.
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, 
                               QListWidgetItem, QTextBrowser, QFrame, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QIcon

from ViGaVault_utils import translator, DIALOG_STD_SIZE, center_window, DEFAULT_DISPLAY_SETTINGS

class PlatformManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("tools_platform_title"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        layout = QVBoxLayout(self)
        
        group = QGroupBox(translator.tr("tools_platform_header"))
        g_layout = QVBoxLayout(group)
        
        # WHY: Fetch the configured button size to dynamically scale the platform icons.
        btn_size = getattr(parent, 'display_settings', DEFAULT_DISPLAY_SETTINGS).get('button', DEFAULT_DISPLAY_SETTINGS['button']) if parent else DEFAULT_DISPLAY_SETTINGS['button']
        
        self.table = QTableWidget()
        # WHY: Added 5 columns to introduce physical 30px spacers before AND after the icon.
        self.table.setColumnCount(5)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { alternate-background-color: palette(alternate-base); }")
        self.table.setIconSize(QSize(btn_size, btn_size))
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)             # Spacer Left
        self.table.setColumnWidth(0, 30)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents) # Icon
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)             # Spacer Right
        self.table.setColumnWidth(2, 30)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)          # Name
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents) # Button
        
        platforms = [
            ("gog", "GOG"), ("epic", "Epic Games Store"), ("steam", "Steam"),
            ("amazon", "Amazon"), ("uplay", "Uplay"), ("battlenet", "Battle.net"),
            ("origin", "Origin"), ("itch", "itch.io"), ("xbox", "Xbox"), ("psn", "PSN")
        ]
        
        self.table.setRowCount(len(platforms))
        self.table.verticalHeader().setDefaultSectionSize(max(80, btn_size + 20))
        
        for row, (p_id, p_name) in enumerate(platforms):
            # WHY: Inject left-side spacer.
            item_spacer_left = QTableWidgetItem("")
            item_spacer_left.setFlags(Qt.NoItemFlags)
            self.table.setItem(row, 0, item_spacer_left)
            
            item_icon = QTableWidgetItem()
            # WHY: Explicitly center the item contents (both text and icon) perfectly within the cell.
            item_icon.setTextAlignment(Qt.AlignCenter)
            icon_path = os.path.join("assets", f"{p_id}.png")
            if os.path.exists(icon_path):
                item_icon.setIcon(QIcon(icon_path))
            else:
                item_icon.setText("🎮")
                font_emoji = QFont()
                font_emoji.setPixelSize(btn_size)
                item_icon.setFont(font_emoji)
            self.table.setItem(row, 1, item_icon)
            
            # WHY: Inject right-side spacer.
            item_spacer_right = QTableWidgetItem("")
            item_spacer_right.setFlags(Qt.NoItemFlags)
            self.table.setItem(row, 2, item_spacer_right)
            
            item_name = QTableWidgetItem(p_name)
            font_bold = QFont()
            font_bold.setBold(True)
            font_bold.setPixelSize(32)
            item_name.setFont(font_bold)
            self.table.setItem(row, 3, item_name)
            
            # WHY: Dynamically read connection state on boot to properly render the button.
            is_connected = False
            if p_id == "gog":
                from backend.gog.login_gog import is_gog_connected
                is_connected = is_gog_connected()
            
            btn_connect = QPushButton()
            btn_font = QFont()
            btn_font.setPixelSize(32)
            btn_connect.setFont(btn_font)
            self.update_btn_ui(btn_connect, is_connected)
            
            btn_connect.clicked.connect(lambda _, pid=p_id, b=btn_connect: self.handle_platform_action(pid, b))
            btn_connect.setFixedWidth(250)
            btn_connect.setMinimumHeight(btn_size)
            self.table.setCellWidget(row, 4, btn_connect)
            
        g_layout.addWidget(self.table)
        layout.addWidget(group)

    def update_btn_ui(self, btn, is_connected):
        """WHY: Smart Refresh - Instantly toggles the UI state of a single button without redrawing the table."""
        if is_connected:
            btn.setText(translator.tr("tools_platform_btn_disconnect"))
            btn.setStyleSheet("color: #C62828; font-weight: bold;")
        else:
            btn.setText(translator.tr("tools_platform_btn_connect"))
            btn.setStyleSheet("")

    def handle_platform_action(self, platform_id, btn):
        try:
            # Check if WebEngine was successfully loaded in __init__.py
            from dialogs.login_browser_dialog import LoginBrowserDialog 
        except ImportError:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Missing Dependency", "Please install PySide6-WebEngine to use platform connections:\n\npip install PySide6-WebEngine")
            return
            
        if platform_id == "gog":
            from backend.gog.login_gog import is_gog_connected, disconnect_gog, save_gog_session, exchange_code_for_token
            
            if is_gog_connected():
                disconnect_gog()
                self.update_btn_ui(btn, False)
            else:
                # WHY: Use GOG's official OAuth authorization endpoint instead of the raw website login.
                oauth_url = "https://auth.gog.com/auth?client_id=46899977096215655&redirect_uri=https://embed.gog.com/on_login_success%3Forigin%3Dclient&response_type=code&layout=client2"
                dlg = LoginBrowserDialog(oauth_url, success_url="on_login_success", parent=self)
                dlg.exec()
                
                # WHY: If the browser captured the OAuth code, exchange it securely for a permanent Bearer token.
                if dlg.success_triggered and dlg.auth_code:
                    token_data = exchange_code_for_token(dlg.auth_code)
                    if token_data and 'access_token' in token_data:
                        save_gog_session(token_data)
                        self.update_btn_ui(btn, True)
                    else:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "Login Failed", "Failed to negotiate OAuth token with GOG.")
                else:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Login Failed", translator.tr("msg_login_failed"))
                    
                # WHY: Safely queue the decoupled browser for C++ memory deletion in the background.
                dlg.deleteLater()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Info", translator.tr("tools_platform_not_impl"))

class SelectionDialog(QDialog):
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        # WHY: Hardcoded strings have been successfully extracted to the JSON translation files.
        self.setWindowTitle(translator.tr("dialog_select_title"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        layout = QVBoxLayout(self)
        group = QGroupBox()
        g_layout = QVBoxLayout(group)
        g_layout.addWidget(QLabel(translator.tr("dialog_select_desc")))
        
        self.list_widget = QListWidget()
        for g in candidates:
            item = QListWidgetItem(g.get('name', 'Unknown'))
            item.setData(Qt.UserRole, g) 
            self.list_widget.addItem(item)
            
        g_layout.addWidget(self.list_widget)
        layout.addWidget(group)
        
        btn_confirm = QPushButton(translator.tr("dialog_select_confirm"))
        btn_confirm.clicked.connect(self.accept)
        layout.addWidget(btn_confirm)
        
    def get_selected_candidate(self):
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return None

class DocumentationDialog(QDialog):
    def __init__(self, html_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("menu_help_docs"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        # WHY: Use a dedicated QTextBrowser to provide a comfortable, scrollable reading experience 
        # that fully supports rich HTML table structures.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox()
        g_layout = QVBoxLayout(group)
        browser = QTextBrowser()
        browser.setHtml(html_content)
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QFrame.NoFrame)
        g_layout.addWidget(browser)
        layout.addWidget(group)
        
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(10, 10, 10, 10)
        btn_close = QPushButton(translator.tr("btn_close"))
        btn_close.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)