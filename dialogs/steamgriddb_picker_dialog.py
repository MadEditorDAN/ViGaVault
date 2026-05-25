# WHY: Single Responsibility Principle - Displays alternative covers fetched from SteamGridDB and allows manual selection.
import os
import requests
import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, 
                               QPushButton, QListWidget, QListWidgetItem, QLabel, 
                               QMessageBox, QWidget, QProgressDialog, QApplication)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QIcon, QPixmap

from backend.steamgriddb.steamgriddb_client import fetch_steamgriddb_covers_list
from ViGaVault_utils import center_window, translator, DIALOG_STD_SIZE

class SteamGridDBLoadWorker(QThread):
    list_loaded = Signal(list)
    image_loaded = Signal(int, bytes)
    finished_loading = Signal()
    error_occurred = Signal(str)

    def __init__(self, search_term, parent=None):
        super().__init__(parent)
        self.search_term = search_term

    def run(self):
        try:
            covers = fetch_steamgriddb_covers_list(self.search_term)
            if not covers:
                self.error_occurred.emit(translator.tr("dialog_sgdb_err_no_covers"))
                return
            
            self.list_loaded.emit(covers)
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            for idx, item in enumerate(covers):
                thumb_url = item.get("thumb")
                if not thumb_url:
                    continue
                try:
                    resp = requests.get(thumb_url, timeout=10, headers=headers)
                    if resp.status_code == 200:
                        self.image_loaded.emit(idx, resp.content)
                except Exception as e:
                    logging.warning(f"Failed to download thumbnail {thumb_url}: {e}")
            self.finished_loading.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))

class SteamGridDBPickerDialog(QDialog):
    def __init__(self, initial_search, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("dialog_sgdb_title"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        self.selected_url = None
        self.cover_items = []
        self.worker = None

        layout = QVBoxLayout(self)
        
        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(initial_search)
        self.search_input.setPlaceholderText(translator.tr("dialog_sgdb_placeholder"))
        self.search_input.returnPressed.connect(self.start_search)
        search_layout.addWidget(self.search_input, 1)
        
        self.btn_search = QPushButton(translator.tr("dialog_sgdb_btn_search"))
        self.btn_search.clicked.connect(self.start_search)
        search_layout.addWidget(self.btn_search)
        layout.addLayout(search_layout)

        # Status label
        self.status_label = QLabel(translator.tr("dialog_sgdb_status_ready"))
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        # List Widget in Grid Mode
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(QSize(150, 225))
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setGridSize(QSize(170, 260))
        self.list_widget.setSpacing(10)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.doubleClicked.connect(self.select_current_item)
        layout.addWidget(self.list_widget, 1)

        # Action Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.btn_select = QPushButton(translator.tr("dialog_sgdb_btn_select"))
        self.btn_select.setEnabled(False)
        self.btn_select.clicked.connect(self.select_current_item)
        button_layout.addWidget(self.btn_select)
        
        btn_cancel = QPushButton(translator.tr("dialog_sgdb_btn_cancel"))
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        layout.addLayout(button_layout)

        # Start search automatically if search term is provided
        if initial_search:
            self.start_search()

    def start_search(self):
        term = self.search_input.text().strip()
        if not term:
            QMessageBox.warning(self, translator.tr("dialog_sgdb_warning_title"), translator.tr("dialog_sgdb_warning_empty_search"))
            return

        # Cancel any active search
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()

        self.list_widget.clear()
        self.cover_items = []
        self.btn_select.setEnabled(False)
        self.status_label.setText(translator.tr("dialog_sgdb_status_searching"))
        self.btn_search.setEnabled(False)

        self.worker = SteamGridDBLoadWorker(term, self)
        self.worker.list_loaded.connect(self.on_list_loaded)
        self.worker.image_loaded.connect(self.on_image_loaded)
        self.worker.finished_loading.connect(self.on_finished_loading)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def on_list_loaded(self, covers):
        self.cover_items = covers
        self.status_label.setText(translator.tr("dialog_sgdb_status_previews", count=len(covers)))
        
        for idx, item in enumerate(covers):
            list_item = QListWidgetItem(f"Proposal #{idx + 1}")
            list_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            # Create a blank fallback gray pixmap initially
            pixmap = QPixmap(150, 225)
            pixmap.fill(Qt.lightGray)
            list_item.setIcon(QIcon(pixmap))
            self.list_widget.addItem(list_item)

    def on_image_loaded(self, idx, data):
        if idx < self.list_widget.count():
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            self.list_widget.item(idx).setIcon(QIcon(pixmap))

    def on_finished_loading(self):
        self.status_label.setText(translator.tr("dialog_sgdb_status_loaded"))
        self.btn_search.setEnabled(True)
        self.btn_select.setEnabled(True)

    def on_error(self, message):
        self.status_label.setText(translator.tr("dialog_sgdb_status_error"))
        self.btn_search.setEnabled(True)
        QMessageBox.information(self, translator.tr("dialog_sgdb_search_msg_box_title"), message)

    def select_current_item(self):
        selected = self.list_widget.selectedItems()
        if not selected:
            return
        row = self.list_widget.row(selected[0])
        if row >= 0 and row < len(self.cover_items):
            self.selected_url = self.cover_items[row].get("url")
            self.accept()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        super().closeEvent(event)
