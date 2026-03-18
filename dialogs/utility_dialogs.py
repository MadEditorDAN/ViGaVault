# WHY: Single Responsibility Principle - A place for minor, utility-level popups and informational dialogs.
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QTextBrowser, QFrame, QGroupBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ViGaVault_utils import translator, DIALOG_STD_SIZE, center_window

class PlatformManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("tools_platform_title"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        layout = QVBoxLayout(self)
        
        group = QGroupBox()
        g_layout = QVBoxLayout(group)
        lbl = QLabel(translator.tr("tools_platform_header"))
        lbl.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl.setFont(font)
        
        g_layout.addStretch()
        g_layout.addWidget(lbl)
        g_layout.addWidget(QLabel(translator.tr("tools_platform_desc"), alignment=Qt.AlignCenter))
        g_layout.addWidget(QLabel(translator.tr("tools_platform_soon"), alignment=Qt.AlignCenter))
        g_layout.addStretch()
        layout.addWidget(group)
        
        btn_close = QPushButton(translator.tr("btn_close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

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