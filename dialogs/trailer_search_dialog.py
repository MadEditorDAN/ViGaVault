import json
import subprocess
import requests
import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QPushButton, 
    QWidget, QCheckBox, QHBoxLayout, QMessageBox, QProgressDialog, QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QPixmap, QDesktopServices, QIcon
from PySide6.QtCore import QUrl

from ViGaVault_utils import translator, center_window, DIALOG_STD_SIZE

class TrailerSearchWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            query = self.query
            if not query.lower().endswith("trailer"):
                query += " trailer"
            # Fetch 18 results to allow multiple pages
            command = [
                sys.executable,
                '-m', 'yt_dlp', 
                f'ytsearch18:{query}', 
                '--dump-json', 
                '--no-playlist', 
                '--flat-playlist'
            ]
            
            # Windows creation flags to hide console window
            creationflags = 0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            
            result = subprocess.run(command, capture_output=True, text=True, creationflags=creationflags)
            
            if result.returncode != 0 and not result.stdout:
                self.error.emit(f"Search failed: {result.stderr}")
                return

            videos = []
            for line in result.stdout.strip().split('\n'):
                if not line: continue
                try:
                    data = json.loads(line)
                    videos.append({
                        'id': data.get('id'),
                        'title': data.get('title'),
                        'url': data.get('url') or f"https://www.youtube.com/watch?v={data.get('id')}",
                        'thumbnail': None # Will be fetched/inferred
                    })
                except json.JSONDecodeError:
                    continue
            
            self.finished.emit(videos)
        except Exception as e:
            self.error.emit(str(e))


class ThumbnailDownloadWorker(QThread):
    finished = Signal(str, QPixmap)
    
    def __init__(self, video_id):
        super().__init__()
        self.video_id = video_id
        
    def run(self):
        # High quality thumbnail standard URL format
        url = f"https://img.youtube.com/vi/{self.video_id}/maxresdefault.jpg"
        fallback_url = f"https://img.youtube.com/vi/{self.video_id}/hqdefault.jpg"
        
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                resp = requests.get(fallback_url, timeout=5)
                
            if resp.status_code == 200:
                pixmap = QPixmap()
                pixmap.loadFromData(resp.content)
                self.finished.emit(self.video_id, pixmap)
        except:
            pass # Ignore and let it show default 'No Image'


class VideoCard(QWidget):
    # Emits URL when selected
    selected = Signal(str)
    
    def __init__(self, video_data):
        super().__init__()
        self.video_data = video_data
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Container for thumbnail + absolute checkbox
        self.thumb_container = QWidget()
        self.thumb_container.setFixedSize(320, 180)
        self.thumb_container.setCursor(Qt.PointingHandCursor)
        
        self.lbl_thumb = QLabel(self.thumb_container)
        self.lbl_thumb.setFixedSize(320, 180)
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setStyleSheet("background-color: #1e1e1e; color: #888; border: 1px solid #333;")
        self.lbl_thumb.setText("Loading Thumbnail...")
        
        # Overlay checkbox at top right
        self.chk_select = QCheckBox(self.thumb_container)
        self.chk_select.setStyleSheet("""
            QCheckBox::indicator { width: 24px; height: 24px; }
            QCheckBox { background: rgba(0,0,0,0.5); border-radius: 4px; }
        """)
        self.chk_select.move(290, 5)
        self.chk_select.toggled.connect(self.on_checked)
        
        # Title
        self.lbl_title = QLabel(video_data['title'])
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.lbl_title.setFixedHeight(40)
        self.lbl_title.setToolTip(video_data['title'])
        
        layout.addWidget(self.thumb_container)
        layout.addWidget(self.lbl_title)
        
        # Set background to appear as a card
        self.setStyleSheet("""
            VideoCard {
                background-color: #2a2a2a;
                border-radius: 8px;
            }
            VideoCard:hover {
                background-color: #333333;
            }
        """)
        
        self.fetch_thumbnail()

    def fetch_thumbnail(self):
        self.worker = ThumbnailDownloadWorker(self.video_data['id'])
        self.worker.finished.connect(self.on_thumbnail_ready)
        self.worker.start()

    def on_thumbnail_ready(self, vid_id, pixmap):
        scaled = pixmap.scaled(320, 180, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.lbl_thumb.setPixmap(scaled)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            QDesktopServices.openUrl(QUrl(self.video_data['url']))

    def on_checked(self, checked):
        if checked:
            self.selected.emit(self.video_data['url'])


class TrailerSearchDialog(QDialog):
    def __init__(self, game_title, parent=None):
        super().__init__(parent)
        self.game_title = game_title
        self.selected_url = None
        self.videos = []
        self.current_page = 0
        self.cards = []
        
        self.setWindowTitle(translator.tr("dialog_meta_title").replace("Metadata", "Trailer Search"))
        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        main_layout = QVBoxLayout(self)
        
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search Query:"))
        self.txt_search = QLineEdit(f"{self.game_title} trailer")
        self.txt_search.textChanged.connect(self.on_search_text_changed)
        search_layout.addWidget(self.txt_search, 1)
        
        self.btn_search = QPushButton("Search")
        self.btn_search.setEnabled(False)
        self.btn_search.clicked.connect(self.start_manual_search)
        search_layout.addWidget(self.btn_search)
        main_layout.addLayout(search_layout)
        
        self.lbl_status = QLabel("Initializing search...")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.lbl_status)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        main_layout.addWidget(self.grid_container, 1)
        
        btn_layout = QHBoxLayout()
        self.btn_more = QPushButton("Load More")
        self.btn_more.clicked.connect(self.load_next_page)
        self.btn_more.hide()
        
        self.btn_cancel = QPushButton(translator.tr("dialog_edit_cancel_btn"))
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("Import Selected")
        self.btn_save.setDefault(True)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.btn_more)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        
        main_layout.addLayout(btn_layout)
        
        self.start_manual_search()

    def on_search_text_changed(self, text):
        self.btn_search.setEnabled(True)

    def start_manual_search(self):
        self.btn_search.setEnabled(False)
        self.lbl_status.show()
        self.lbl_status.setText(f"Searching YouTube for '{self.txt_search.text()}'...")
        
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards.clear()
        self.current_page = 0
        
        self.worker = TrailerSearchWorker(self.txt_search.text())
        self.worker.finished.connect(self.on_search_finished)
        self.worker.error.connect(self.on_search_error)
        self.worker.start()

    def on_search_error(self, err):
        self.lbl_status.setText(f"Error: {err}")

    def on_search_finished(self, videos):
        self.videos = videos
        if not self.videos:
            self.lbl_status.setText("No trailers found.")
            return
            
        self.lbl_status.hide()
        self.render_page()

    def render_page(self):
        # Clear layout
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.cards.clear()
        
        start_idx = self.current_page * 6
        end_idx = min(start_idx + 6, len(self.videos))
        page_videos = self.videos[start_idx:end_idx]
        
        row, col = 0, 0
        for video in page_videos:
            card = VideoCard(video)
            card.selected.connect(self.on_card_selected)
            self.cards.append(card)
            self.grid_layout.addWidget(card, row, col)
            
            col += 1
            if col > 1: # 2 columns (0, 1)
                col = 0
                row += 1
                
        if end_idx < len(self.videos):
            self.btn_more.show()
        else:
            self.btn_more.hide()

    def load_next_page(self):
        self.current_page += 1
        self.render_page()

    def on_card_selected(self, url):
        self.selected_url = url
        # Uncheck others
        for card in self.cards:
            if card.video_data['url'] != url:
                card.chk_select.blockSignals(True)
                card.chk_select.setChecked(False)
                card.chk_select.blockSignals(False)
                
        self.btn_save.setEnabled(True)

    def get_selected_url(self):
        return self.selected_url
