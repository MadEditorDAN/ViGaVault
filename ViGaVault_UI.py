import sys
import pandas as pd
import os
import re
import requests
import json
import logging
import subprocess
from ViGaVault_Scan import LibraryManager
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QStackedLayout,
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox, QFrame, QAbstractItemView, QCheckBox, QSlider, QStyle)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent, QUrl, QThread, Signal, QObject
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

DB_FILE = "VGVDB.csv"

# --- Custom Logging Handler for UI ---
class QtLogSignal(QObject):
    message_written = Signal(str)

class QtLogHandler(logging.Handler):
    def __init__(self, signal_emitter, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_emitter = signal_emitter
        # Set a simple formatter for the UI log, without timestamp/level
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record):
        msg = self.format(record)
        self.signal_emitter.message_written.emit(msg)

# --- Worker Thread for GOG Sync ---
class GogSyncWorker(QThread):
    def run(self):
        """Runs the GOG sync process."""
        try:
            # We create the manager inside the thread
            manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
            manager.load_db()
            manager.sync_gog()
        except Exception as e:
            # Log any exceptions that happen inside the thread
            logging.error(f"Erreur critique dans le thread de synchronisation GOG : {e}")

class LocalScanWorker(QThread):
    def run(self):
        """Runs the local folder scan process."""
        try:
            # We create the manager inside the thread
            manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
            manager.load_db()
            manager.scan()
        except Exception as e:
            # Log any exceptions that happen inside the thread
            logging.error(f"Erreur critique dans le thread de scan local : {e}")


# --- Fenêtres de dialogue pour Editer et Scanner ---
class ActionDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.layout = QFormLayout(self)
        self.inputs = {}
        
        # Liste des champs à afficher en lecture seule
        fields_to_disable = [
            'Folder_Name', 'Path_Root', 'Path_Video', 'Status_Flag', 'Image_Link', 
            'Year_Folder', 'Platforms'
        ]
        
        for field, value in data.items():
            # Création des champs
            if field == "Summary":
                inp = QTextEdit(str(value))
            else:
                inp = QLineEdit(str(value))
            
            # Griser les champs non modifiables
            if field in fields_to_disable:
                inp.setEnabled(False)
            
            self.layout.addRow(field, inp)
            self.inputs[field] = inp
            
        btn_save = QPushButton("Valider")
        btn_save.clicked.connect(self.accept)
        self.layout.addRow(btn_save)

    def get_data(self):
        new_data = {}
        for field, inp in self.inputs.items():
            if inp.isEnabled(): # On ne récupère que les données des champs modifiables
                if isinstance(inp, QTextEdit):
                    new_data[field] = inp.toPlainText()
                else:
                    new_data[field] = inp.text()
        return new_data

class VideoPlayerDialog(QDialog):
    def __init__(self, video_path, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1600, 900)
        # Fenêtre sans bordure
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setStyleSheet("background-color: black; color: white;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget, 1) # Add stretch factor to make video area expand
        
        # --- CONTROLES ---
        controls_widget = QWidget()
        controls_widget.setStyleSheet("background-color: #222; border-top: 1px solid #444;")
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(10, 2, 10, 2)
        
        # Play/Pause
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(24, 24)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.btn_play.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.btn_play)
        
        # Stop
        self.btn_stop = QPushButton()
        self.btn_stop.setFixedSize(24, 24)
        self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.clicked.connect(self.stop_video)
        controls_layout.addWidget(self.btn_stop)
        
        # Slider (Barre de temps)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.sliderPressed.connect(self.pause_for_seek)
        self.slider.sliderReleased.connect(self.resume_after_seek)
        controls_layout.addWidget(self.slider)
        
        # Fermer
        self.btn_close = QPushButton("✖")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setStyleSheet("font-weight: bold; color: #aaa; border: none;")
        self.btn_close.clicked.connect(self.accept)
        controls_layout.addWidget(self.btn_close)
        
        layout.addWidget(controls_widget)
        
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.audio.setVolume(1.0)
        
        # Connexions signaux lecteur
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        
        self.is_seeking = False
        self.player.play()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def stop_video(self):
        self.player.stop()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.slider.setValue(0)

    def position_changed(self, position):
        if not self.is_seeking:
            self.slider.setValue(position)

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)

    def set_position(self, position):
        self.player.setPosition(position)

    def pause_for_seek(self):
        self.is_seeking = True
        self.was_playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.player.pause()

    def resume_after_seek(self):
        self.set_position(self.slider.value())
        self.is_seeking = False
        if self.was_playing:
            self.player.play()
            
    def media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
             self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, 'drag_pos'):
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)

class Sidebar(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.setFixedWidth(350)
        self.layout = QVBoxLayout(self)
        
        # --- PANNEAU FILTRES ---
        self.filter_panel = QWidget()
        self.filter_layout = QVBoxLayout(self.filter_panel)
        
        label_style = "font-weight: bold; font-size: 16px;"
        
        # 1. Header (Recherche + Compteur)
        header_layout = QHBoxLayout()
        lbl_search = QLabel("Recherche")
        lbl_search.setStyleSheet(label_style)
        header_layout.addWidget(lbl_search)
        header_layout.addStretch()
        self.lbl_counter = QLabel("0/0")
        self.lbl_counter.setStyleSheet("font-weight: bold; font-size: 20px; color: white;")
        header_layout.addWidget(self.lbl_counter)
        self.filter_layout.addLayout(header_layout)
        
        self.search_bar = QLineEdit() # Défini avec self.
        self.search_bar.setPlaceholderText("Nom du jeu...")
        self.search_bar.setClearButtonEnabled(True)
        self.filter_layout.addWidget(self.search_bar)
        
        # 2. Plateforme
        lbl_plat = QLabel("Plateforme")
        lbl_plat.setStyleSheet(label_style)
        self.filter_layout.addWidget(lbl_plat)
        self.combo_platform = QComboBox() # Défini avec self.
        self.filter_layout.addWidget(self.combo_platform)
        
        # 3. Tri
        lbl_sort = QLabel("Trier par")
        lbl_sort.setStyleSheet(label_style)
        self.filter_layout.addWidget(lbl_sort)
        self.combo_sort = QComboBox() # Défini avec self.
        self.combo_sort.addItems(["Nom", "Date de sortie", "Développeur"])
        self.filter_layout.addWidget(self.combo_sort)
        
        self.btn_toggle_sort = QPushButton("⇅ Inverser l'ordre")
        self.filter_layout.addWidget(self.btn_toggle_sort)

        # --- FILTRES RAPIDES ---
        quick_filters_layout = QHBoxLayout()
        self.chk_new = QCheckBox("NEW")
        self.chk_a_tester = QCheckBox("A TESTER")
        self.chk_vr = QCheckBox("VR")
        
        quick_filters_layout.addWidget(self.chk_new)
        quick_filters_layout.addWidget(self.chk_a_tester)
        quick_filters_layout.addWidget(self.chk_vr)
        self.filter_layout.addLayout(quick_filters_layout)

        # --- BOUTON SYNC GOG ---
        self.btn_sync_gog = QPushButton("Synchroniser GOG")
        self.filter_layout.addWidget(self.btn_sync_gog)

        # --- BOUTON SCAN LOCAL ---
        self.btn_scan_local = QPushButton("Scanner les dossiers locaux")
        self.filter_layout.addWidget(self.btn_scan_local)

        # --- PANNEAU SCAN ---
        self.scan_panel = QWidget()
        self.scan_layout = QVBoxLayout(self.scan_panel)
        
        # Ligne de séparation
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.scan_layout.addWidget(line)
        
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Nom du jeu à chercher...")
        self.scan_btn = QPushButton("Rechercher")
        self.scan_results = QListWidget()
        self.scan_results.setIconSize(QSize(50, 70)) # Définit une taille visible pour les covers
        
        self.btns_layout = QHBoxLayout()
        self.btn_confirm = QPushButton("Valider le choix")
        self.btn_cancel = QPushButton("Annuler")
        self.btns_layout.addWidget(self.btn_confirm)
        self.btns_layout.addWidget(self.btn_cancel)
        
        self.scan_layout.addWidget(QLabel("Scan Manuel"))
        self.scan_layout.addWidget(self.scan_input)
        self.scan_layout.addWidget(self.scan_btn)
        self.scan_layout.addWidget(self.scan_results)
        self.scan_layout.addLayout(self.btns_layout)
        
        self.filter_layout.addWidget(self.scan_panel, 1)
        self.filter_layout.addStretch()
        self.layout.addWidget(self.filter_panel)
        self.scan_panel.hide() 
        
        # --- CONNEXIONS ---
        self.search_bar.textChanged.connect(self.parent.on_search_changed)
        self.combo_platform.currentIndexChanged.connect(self.parent.apply_filters)
        self.combo_sort.currentIndexChanged.connect(self.parent.apply_filters)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        self.btn_sync_gog.clicked.connect(self.parent.start_gog_sync)
        self.btn_scan_local.clicked.connect(self.parent.start_local_scan)

        # Connexions Filtres Rapides
        self.chk_new.stateChanged.connect(self.parent.apply_filters)
        self.chk_a_tester.stateChanged.connect(self.parent.apply_filters)
        self.chk_vr.stateChanged.connect(self.parent.apply_filters)
        
        # Connexions Scan
        self.scan_btn.clicked.connect(self.parent.on_manual_search_trigger)
        self.scan_input.returnPressed.connect(self.parent.on_manual_search_trigger)
        self.btn_confirm.clicked.connect(self.parent.apply_inline_selection)
        self.btn_cancel.clicked.connect(self.parent.cancel_inline_scan)
        self.scan_results.itemDoubleClicked.connect(self.parent.apply_inline_selection)

class SelectionDialog(QDialog):
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choisir le bon jeu")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Plusieurs résultats trouvés. Sélectionnez le bon :"))
        
        self.list_widget = QListWidget()
        for g in candidates:
            # On crée un item pour la liste
            item = QListWidgetItem(g.get('name', 'Unknown'))
            # On stocke l'objet jeu complet (g) dans les données de l'item (rôle 1)
            item.setData(Qt.UserRole, g) 
            self.list_widget.addItem(item)
            
        layout.addWidget(self.list_widget)
        
        btn_valider = QPushButton("Valider")
        btn_valider.clicked.connect(self.accept)
        layout.addWidget(btn_valider)
        
    def get_selected_candidate(self):
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.UserRole) # Récupère l'objet stocké
        return None

class GameCard(QWidget):
    def __init__(self, game_data, parent_window, item): # <--- On ajoute parent_window ici
        super().__init__()
        self.data = game_data
        self.parent_window = parent_window # <--- On le stocke
        self.item = item
        
        main_layout = QHBoxLayout(self)
        
        # Image
        self.img_label = QLabel()
        self.img_label.setFixedSize(200, 266)
        self.img_label.setAlignment(Qt.AlignCenter)
        img_path = game_data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            # Optimisation : FastTransformation est beaucoup plus rapide que SmoothTransformation
            pixmap = QPixmap(img_path).scaled(200, 266, Qt.KeepAspectRatio, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)
        else:
            self.img_label.setText("Pas d'image")
            self.img_label.setStyleSheet("border: 1px solid #555;")
        self.img_label.installEventFilter(self)
        main_layout.addWidget(self.img_label)
        
        # Details
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0) 
        details_layout.setSpacing(2)
        
        header_layout = QHBoxLayout()
        
        title_layout = QVBoxLayout()
        title_layout.setSpacing(0) # Rapproche le titre et le chemin
        
        title = QLabel(game_data.get('Clean_Title', 'Unknown'))
        title.setStyleSheet("font-weight: bold; font-size: 22px;")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.installEventFilter(self)
        title_layout.addWidget(title)
        
        path_lbl = QLabel(f"({game_data.get('Path_Root', '')})")
        path_lbl.setStyleSheet("font-size: 11px; color: gray;")
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_lbl.installEventFilter(self)
        title_layout.addWidget(path_lbl)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        # Boutons
        self.video_path = game_data.get('Path_Video', '')
        
        btn_folder = QPushButton("📁")
        btn_edit = QPushButton("✏️")
        btn_scan = QPushButton("🔍")
        
        buttons = [btn_folder, btn_edit, btn_scan]
        if self.video_path and os.path.exists(self.video_path):
            btn_play = QPushButton("▶")
            btn_play.clicked.connect(self.start_video)
            buttons.insert(0, btn_play)
            
        for btn in buttons:
            btn.setFixedSize(45, 45)
            btn.setStyleSheet("font-size: 28px; padding: 0px;")
            btn.installEventFilter(self)
            header_layout.addWidget(btn)
        
        btn_folder.clicked.connect(self.open_folder)
        btn_edit.clicked.connect(self.edit_game)
        btn_scan.clicked.connect(self.scan_game)
        
        details_layout.addLayout(header_layout)
        
        # Info
        for field in ['Original_Release_Date', 'Platforms', 'Developer']:
            label = QLabel(f"{field.replace('_', ' ')}: {game_data.get(field, '')}")
            label.setStyleSheet("font-weight: bold; font-size: 16px;")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.installEventFilter(self)
            details_layout.addWidget(label)
        
        summary = QLabel(f"Summary: {game_data.get('Summary', '')}")
        summary.setWordWrap(True)
        summary.setStyleSheet("font-size: 14px;") # You can change 14px to your desired size
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary.installEventFilter(self)
        details_layout.addWidget(summary)
        main_layout.addLayout(details_layout)

    def mousePressEvent(self, event):
        self.item.listWidget().setCurrentItem(self.item)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            self.item.listWidget().setCurrentItem(self.item)
        return super().eventFilter(obj, event)

    def start_video(self):
        if not self.video_path: return
        print(f"Lancement vidéo : {self.video_path}")
        
        # Ouvre le lecteur dans une fenêtre dédiée
        dlg = VideoPlayerDialog(self.video_path, self.data.get('Clean_Title', 'Vidéo'), self.window())
        dlg.exec()

    def open_folder(self):
        if os.path.exists(self.data.get('Path_Root', '')):
            os.startfile(self.data.get('Path_Root', ''))

    def edit_game(self):
        dlg = ActionDialog("Éditer le jeu", self.data)
        if dlg.exec():
            new_data = dlg.get_data()
            if new_data:
                self.parent_window.update_game_data(self.data['Folder_Name'], new_data)

    def scan_game(self):
        # Utilise parent_window pour appeler la méthode de la MainWindow
        if hasattr(self.parent_window, 'start_inline_scan'):
            # Appelle la méthode principale qui va gérer l'affichage ET le lancement
            self.parent_window.start_inline_scan(self.data)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ViGaVault Library")
        self.resize(1200, 800)
        self.sort_desc = True
        
        # Variables pour le chargement progressif (Lazy Loading)
        self.batch_size = 30
        self.current_df = pd.DataFrame()
        self.loaded_count = 0
        
        # Timer pour le chargement en arrière-plan
        self.background_loader = QTimer()
        self.background_loader.setInterval(100) # Charge un batch toutes les 100ms
        self.background_loader.timeout.connect(self.load_more_items)
        
        # Timer pour éviter de recharger la liste à chaque lettre tapée (Debounce)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300) # Attend 300ms après la dernière frappe
        self.search_timer.timeout.connect(self.apply_filters)

        self.current_scan_game = None
        self.gog_sync_in_progress = False # Flag to prevent multiple syncs
        self.local_scan_in_progress = False
        
        # 1. Mise en place du layout principal (Horizontal)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 2. Liste des jeux (à gauche, occupe 3/4 de l'espace)
        self.list_widget = QListWidget()
        # Assure un défilement fluide pixel par pixel au lieu de sauter d'item en item
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.verticalScrollBar().setSingleStep(25)
        # Connexion pour le chargement infini
        self.list_widget.verticalScrollBar().valueChanged.connect(self.check_scroll_load)
        main_layout.addWidget(self.list_widget, stretch=3)
        
        # 3. Sidebar (à droite, occupe 1/4 de l'espace)
        # Tout le design (filtres + scan) est géré dans la classe Sidebar
        self.sidebar = Sidebar(self)
        main_layout.addWidget(self.sidebar, stretch=1)
        
        # 4. Chargement des données
        if os.path.exists(DB_FILE):
            self.master_df = pd.read_csv(DB_FILE, sep=';', encoding='utf-8').fillna('')
            
            # Remplir les plateformes dans la sidebar
            platforms = ["Toutes"] + sorted(list(set(self.master_df['Platforms'].dropna().unique())))
            self.sidebar.combo_platform.addItems([p for p in platforms if p])
            
            # --- RESTAURATION ---
            saved_scroll = 0
            if os.path.exists("settings.json"):
                saved_scroll = self.load_settings()
            else:
                # Tri par défaut sur "Date de sortie"
                self.sidebar.combo_sort.setCurrentIndex(1)
            
            # Affichage initial
            self.apply_filters()
            
            # Restauration du scroll
            if saved_scroll:
                self.pending_scroll = saved_scroll
                QTimer.singleShot(100, self.restore_scroll_position)

    def start_gog_sync(self):
        if self.gog_sync_in_progress or self.local_scan_in_progress:
            QMessageBox.information(self, "Info", "Une autre tâche est déjà en cours.")
            return

        # Check if GOG Galaxy is running
        try:
            # Vérification silencieuse des processus
            output = subprocess.check_output('tasklist', shell=True).decode(errors='ignore')
            if "GalaxyClient.exe" in output:
                reply = QMessageBox.question(self, "GOG Galaxy détecté", 
                                            "GOG Galaxy est en cours d'exécution. Il doit être fermé pour accéder à la base de données.\n\nVeuillez le fermer et cliquer sur Oui.",
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No: return
        except: pass

        self.gog_sync_in_progress = True
        self.sidebar.btn_sync_gog.setEnabled(False)
        self.sidebar.btn_sync_gog.setText("Synchronisation...")
        self.sidebar.btn_scan_local.setEnabled(False)

        # Show the scan panel as a log viewer
        self.sidebar.scan_panel.show()
        self.sidebar.scan_input.hide()
        self.sidebar.scan_btn.hide()
        self.sidebar.btn_confirm.hide()
        self.sidebar.btn_cancel.setText("Fermer")
        self.sidebar.scan_results.clear()
        self.sidebar.scan_results.addItem("Démarrage de la synchronisation GOG...")

        # Setup logging to UI
        self.log_signal = QtLogSignal()
        self.log_signal.message_written.connect(self.update_sync_log)
        self.qt_log_handler = QtLogHandler(self.log_signal)
        logging.getLogger().addHandler(self.qt_log_handler)

        # Setup and start worker thread
        self.gog_worker = GogSyncWorker()
        self.gog_worker.finished.connect(self.finish_gog_sync)
        self.gog_worker.start()

    def update_sync_log(self, message):
        self.sidebar.scan_results.addItem(message)
        self.sidebar.scan_results.scrollToBottom()

    def finish_gog_sync(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        self.sidebar.scan_results.addItem("--- Synchronisation terminée ! ---")
        self.sidebar.scan_results.scrollToBottom()
        
        self.gog_sync_in_progress = False
        self.sidebar.btn_sync_gog.setEnabled(True)
        self.sidebar.btn_sync_gog.setText("Synchroniser GOG")
        self.sidebar.btn_scan_local.setEnabled(True)

        # Fermeture automatique du panneau après 2 secondes
        QTimer.singleShot(2000, lambda: [self.sidebar.scan_panel.hide(), self.restore_scan_panel()])
        self.refresh_data()

    def start_local_scan(self):
        if self.gog_sync_in_progress or self.local_scan_in_progress:
            QMessageBox.information(self, "Info", "Une autre tâche est déjà en cours.")
            return

        self.local_scan_in_progress = True
        self.sidebar.btn_scan_local.setEnabled(False)
        self.sidebar.btn_scan_local.setText("Scan en cours...")
        self.sidebar.btn_sync_gog.setEnabled(False)

        # Show the scan panel as a log viewer
        self.sidebar.scan_panel.show()
        self.sidebar.scan_input.hide()
        self.sidebar.scan_btn.hide()
        self.sidebar.btn_confirm.hide()
        self.sidebar.btn_cancel.setText("Fermer")
        self.sidebar.scan_results.clear()
        self.sidebar.scan_results.addItem("Démarrage du scan des dossiers locaux...")

        # Setup logging to UI
        self.log_signal = QtLogSignal()
        self.log_signal.message_written.connect(self.update_sync_log)
        self.qt_log_handler = QtLogHandler(self.log_signal)
        logging.getLogger().addHandler(self.qt_log_handler)

        # Setup and start worker thread
        self.local_scan_worker = LocalScanWorker()
        self.local_scan_worker.finished.connect(self.finish_local_scan)
        self.local_scan_worker.start()

    def finish_local_scan(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        self.sidebar.scan_results.addItem("--- Scan des dossiers terminé ! ---")
        self.sidebar.scan_results.scrollToBottom()
        
        self.local_scan_in_progress = False
        self.sidebar.btn_scan_local.setEnabled(True)
        self.sidebar.btn_scan_local.setText("Scanner les dossiers locaux")
        self.sidebar.btn_sync_gog.setEnabled(True)

        self.restore_scan_panel()
        QMessageBox.information(self, "Succès", "Le scan des dossiers est terminé. La liste va être rafraîchie.")
        self.sidebar.scan_panel.hide()
        self.refresh_data()

    def start_inline_scan(self, game_data):
        self.current_scan_game = game_data
        # On ne touche plus à filter_panel.hide() !
        self.sidebar.scan_panel.show() 
        
        # Nettoyage du nom de dossier pour la recherche
        raw_name = game_data.get('Folder_Name', '')
        # 1. Retire l'année au début (ex: "1992 - Dune" -> "Dune")
        clean_name = re.sub(r'^\d{4}\s*-\s*', '', raw_name)
        # 2. Retire la dernière paire de parenthèses (ex: "Portal (Steam)" -> "Portal")
        clean_name = re.sub(r'\s*\([^)]*\)$', '', clean_name).strip()
        self.sidebar.scan_input.setText(clean_name)
        
        self.sidebar.scan_results.clear()
        
        # Message d'attente visuel
        item = QListWidgetItem("Recherche sur IGDB en cours...")
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        self.sidebar.scan_results.addItem(item)
        
        self.sidebar.scan_input.setFocus()

        # On diffère légèrement le lancement pour laisser l'interface s'afficher (message d'attente)
        # Cette logique est maintenant ici pour garantir que le contexte est toujours le bon.
        if hasattr(self, 'run_inline_search'):
            QTimer.singleShot(50, self.run_inline_search)

    def update_game_data(self, folder_name, new_data):
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        
        game_obj = manager.games.get(folder_name)
        if not game_obj:
            QMessageBox.critical(self, "Erreur", f"Jeu '{folder_name}' non trouvé dans la base de données.")
            return

        # Met à jour les données du jeu
        for key, value in new_data.items():
            game_obj.data[key] = value
        
        # Sauvegarde dans le CSV
        while True:
            try:
                manager.save_db()
                break
            except PermissionError:
                reply = QMessageBox.warning(self, "Fichier verrouillé", 
                                    f"Le fichier {DB_FILE} est ouvert dans un autre programme (ex: Excel).\n\n"
                                    "Veuillez le fermer, puis cliquez sur OK pour réessayer.",
                                    QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Cancel:
                    return
        
        QMessageBox.information(self, "Succès", "Les modifications ont été enregistrées.")
        
        # Rafraîchit l'interface pour afficher les changements
        # Le système d'ancrage existant se chargera de repositionner la vue
        self.refresh_data()

    def on_manual_search_trigger(self):
        self.sidebar.scan_results.clear()
        item = QListWidgetItem("Recherche sur IGDB en cours...")
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        self.sidebar.scan_results.addItem(item)
        QTimer.singleShot(50, self.run_inline_search)

    def run_inline_search(self):
        term = self.sidebar.scan_input.text()
        if not term: return # Sécurité
        
        if not self.current_scan_game:
            QMessageBox.warning(self, "Erreur", "Aucun jeu sélectionné pour le scan. Veuillez cliquer sur l'icône de scan d'un jeu.")
            return
        
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        token = manager.get_access_token()
        
        candidates = manager.fetch_candidates(token, term)
        
        self.sidebar.scan_results.clear()
        for g in candidates:
            item = QListWidgetItem(g.get('name'))
            item.setData(Qt.UserRole, g)
            
            # Récupération et affichage de la cover
            if 'cover' in g and 'url' in g['cover']:
                try:
                    # URL IGDB commence par //, on ajoute https: et on prend une taille adaptée
                    img_url = "https:" + g['cover']['url'].replace("t_thumb", "t_cover_small")
                    data = requests.get(img_url, timeout=1).content
                    pix = QPixmap()
                    pix.loadFromData(data)
                    item.setIcon(QIcon(pix))
                except Exception:
                    pass # On ignore silencieusement les erreurs d'image pour ne pas bloquer
            
            self.sidebar.scan_results.addItem(item)
            
        if not candidates:
            item = QListWidgetItem("Aucun résultat trouvé.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled) # Grise l'élément pour le rendre non-sélectionnable
            self.sidebar.scan_results.addItem(item)

    def restore_scan_panel(self):
        """Resets the scan panel to its default state for manual scanning."""
        self.sidebar.scan_input.show()
        self.sidebar.scan_btn.show()
        self.sidebar.btn_confirm.show()
        self.sidebar.btn_cancel.setText("Annuler")

    def cancel_inline_scan(self):
        self.sidebar.scan_panel.hide()
        self.sidebar.scan_results.clear()
        self.sidebar.scan_input.clear()
        self.restore_scan_panel() # Ensure it's reset for next time

    def apply_inline_selection(self):
        item = self.sidebar.scan_results.currentItem()
        if not item: return
        
        chosen_game = item.data(Qt.UserRole)
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        game_obj = manager.games.get(self.current_scan_game.get('Folder_Name'))
        
        if game_obj.apply_candidate_data(chosen_game):
            while True:
                try:
                    manager.save_db()
                    break
                except PermissionError:
                    reply = QMessageBox.warning(self, "Fichier verrouillé", 
                                        f"Le fichier {DB_FILE} est ouvert dans un autre programme (ex: Excel).\n\n"
                                        "Veuillez le fermer, puis cliquez sur OK pour réessayer.",
                                        QMessageBox.Ok | QMessageBox.Cancel)
                    if reply == QMessageBox.Cancel:
                        return

            self.refresh_data()
            
            # Positionner la liste sur le jeu modifié
            target_folder = self.current_scan_game.get('Folder_Name')
            
            # On cherche la position du jeu dans la liste complète des données
            folders_list = self.current_df['Folder_Name'].tolist()
            if target_folder in folders_list:
                row_index = folders_list.index(target_folder)
                
                # On force le chargement des items jusqu'à atteindre cette ligne
                while self.loaded_count <= row_index:
                    self.load_more_items()
                
                # Maintenant que l'item est créé, on peut le sélectionner
                list_item = self.list_widget.item(row_index)
                if list_item:
                    self.list_widget.scrollToItem(list_item)
                    self.list_widget.setCurrentItem(list_item)
            
            # Feedback visuel dans la liste au lieu du popup
            self.sidebar.scan_results.clear()
            item = QListWidgetItem("Mise à jour terminée !")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.sidebar.scan_results.addItem(item)
            
            # Fermeture automatique du panneau après 2 secondes
            QTimer.singleShot(2000, self.cancel_inline_scan)

    def closeEvent(self, event):
        self.save_settings()
        event.accept()

    def save_settings(self):
        settings = {
            "geometry": self.saveGeometry().toBase64().data().decode(),
            "sort_desc": self.sort_desc,
            "sort_index": self.sidebar.combo_sort.currentIndex(),
            "platform_text": self.sidebar.combo_platform.currentText(),
            "search_text": self.sidebar.search_bar.text(),
            "scroll_value": self.list_widget.verticalScrollBar().value(),
            "chk_new": self.sidebar.chk_new.isChecked(),
            "chk_a_tester": self.sidebar.chk_a_tester.isChecked(),
            "chk_vr": self.sidebar.chk_vr.isChecked()
        }
        try:
            with open("settings.json", "w") as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Erreur sauvegarde settings: {e}")

    def load_settings(self):
        try:
            with open("settings.json", "r") as f:
                settings = json.load(f)
            
            if "geometry" in settings:
                self.restoreGeometry(QByteArray.fromBase64(settings["geometry"].encode()))
                
            self.sort_desc = settings.get("sort_desc", True)
            
            # Bloquer les signaux pour éviter de déclencher apply_filters plusieurs fois
            self.sidebar.combo_sort.blockSignals(True)
            self.sidebar.combo_platform.blockSignals(True)
            self.sidebar.search_bar.blockSignals(True)
            self.sidebar.chk_new.blockSignals(True)
            self.sidebar.chk_a_tester.blockSignals(True)
            self.sidebar.chk_vr.blockSignals(True)
            
            idx = settings.get("sort_index", 1)
            if 0 <= idx < self.sidebar.combo_sort.count():
                self.sidebar.combo_sort.setCurrentIndex(idx)
                
            plat_text = settings.get("platform_text", "Toutes")
            index = self.sidebar.combo_platform.findText(plat_text)
            if index >= 0:
                self.sidebar.combo_platform.setCurrentIndex(index)
                
            self.sidebar.search_bar.setText(settings.get("search_text", ""))
            
            self.sidebar.chk_new.setChecked(settings.get("chk_new", False))
            self.sidebar.chk_a_tester.setChecked(settings.get("chk_a_tester", False))
            self.sidebar.chk_vr.setChecked(settings.get("chk_vr", False))
            
            self.sidebar.combo_sort.blockSignals(False)
            self.sidebar.combo_platform.blockSignals(False)
            self.sidebar.search_bar.blockSignals(False)
            self.sidebar.chk_new.blockSignals(False)
            self.sidebar.chk_a_tester.blockSignals(False)
            self.sidebar.chk_vr.blockSignals(False)

            return settings.get("scroll_value", 0)
        except Exception as e:
            print(f"Erreur chargement settings: {e}")
            return 0

    def refresh_data(self):
        """Recharge le CSV et met à jour l'affichage"""
        if os.path.exists(DB_FILE):
            self.master_df = pd.read_csv(DB_FILE, sep=';', encoding='utf-8').fillna('')
            self.apply_filters() # Applique les filtres actuels pour garder la recherche/tri

    def load_data(self):
        # ... (ton code existant)
        for _, row in df.iterrows():
            item = QListWidgetItem(self.list_widget)
            # ICI : On passe 'self' (la MainWindow) en deuxième argument
            card = GameCard(row.to_dict(), self) 
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

    def toggle_sort_order(self):
        self.sort_desc = not self.sort_desc
        self.apply_filters()
        
    def on_search_changed(self, text):
        self.search_timer.start()

    def check_scroll_load(self, value):
        # Si on est proche du bas (85%), on charge la suite
        maximum = self.list_widget.verticalScrollBar().maximum()
        if maximum > 0 and value >= maximum * 0.85:
            self.load_more_items()

    def load_more_items(self):
        if self.loaded_count >= len(self.current_df):
            self.background_loader.stop()
            return
            
        # Détermine la fin du batch
        end_index = min(self.loaded_count + self.batch_size, len(self.current_df))
        batch_df = self.current_df.iloc[self.loaded_count:end_index]
        
        for _, row in batch_df.iterrows():
            item = QListWidgetItem(self.list_widget)
            card = GameCard(row.to_dict(), self, item)
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, row['Folder_Name'])
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
            
        self.loaded_count = end_index

    def apply_filters(self):
        if not hasattr(self, 'master_df'): return
        
        # Arrête le chargement précédent s'il est en cours
        self.background_loader.stop()
        
        # --- ANCRAGE : Sauvegarde de la sélection ---
        current_item = self.list_widget.currentItem()
        anchor_folder = current_item.data(Qt.UserRole) if current_item else None
        
        df = self.master_df.copy()
        
        # Filtre Texte
        search = self.sidebar.search_bar.text().lower()
        if search:
            df = df[df['Clean_Title'].str.lower().str.contains(search)]
            
        # Filtre Plateforme
        plat = self.sidebar.combo_platform.currentText()
        if plat != "Toutes":
            df = df[df['Platforms'] == plat]

        # Filtres rapides
        if self.sidebar.chk_new.isChecked():
            df = df[df['Status_Flag'] != 'OK']
        else:
            df = df[df['Status_Flag'] == 'OK']
        
        if self.sidebar.chk_a_tester.isChecked():
            # case=False pour ignorer la casse (_temp, _Temp, etc.)
            df = df[df['Path_Root'].str.contains('_temp', case=False, na=False)]

        if self.sidebar.chk_vr.isChecked():
            df = df[df['Path_Root'].str.contains('VR', case=False, na=False)]
            
        # Tri
        sort_col = {"Nom": "Clean_Title", "Date de sortie": "Original_Release_Date", "Développeur": "Developer"}[self.sidebar.combo_sort.currentText()]
        
        if sort_col == "Original_Release_Date":
            # Conversion temporaire en datetime pour un tri chronologique réel
            # 'coerce' transforme les erreurs ou vides en NaT (Not a Time)
            df['temp_sort_date'] = pd.to_datetime(df[sort_col], errors='coerce', dayfirst=True)
            # na_position='last' force les jeux sans date à la fin, peu importe l'ordre de tri
            df = df.sort_values(by='temp_sort_date', ascending=not self.sort_desc, na_position='last')
        elif sort_col == "Clean_Title":
            # Bonus : Tri insensible à la casse pour le nom (Zelda ne sera plus après assassin's creed)
            df['temp_sort_title'] = df[sort_col].str.lower()
            df = df.sort_values(by='temp_sort_title', ascending=not self.sort_desc)
        else:
            df = df.sort_values(by=sort_col, ascending=not self.sort_desc)
        
        # Update UI
        self.current_df = df
        
        # Update Counter
        self.sidebar.lbl_counter.setText(f"{len(df)}/{len(self.master_df)}")
        
        self.list_widget.clear()
        self.loaded_count = 0
        
        # Charge le premier batch
        self.load_more_items()
        
        # --- ANCRAGE : Restauration ---
        if anchor_folder:
            folders_list = self.current_df['Folder_Name'].tolist()
            if anchor_folder in folders_list:
                row_index = folders_list.index(anchor_folder)
                
                # On force le chargement jusqu'à l'élément pour pouvoir l'afficher
                while self.loaded_count <= row_index:
                    self.load_more_items()
                
                item = self.list_widget.item(row_index)
                if item:
                    self.list_widget.setCurrentItem(item)
                    self.list_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        
        # Lance le chargement du reste en arrière-plan
        self.background_loader.start()

    def restore_scroll_position(self):
        if not hasattr(self, 'pending_scroll'): return
        
        sb = self.list_widget.verticalScrollBar()
        
        # Si on peut encore charger et qu'on n'a pas atteint la cible
        if sb.maximum() < self.pending_scroll and self.loaded_count < len(self.current_df):
            self.load_more_items()
            # Force la mise à jour du layout pour recalculer le maximum immédiatement
            self.list_widget.doItemsLayout() 
            # Rappel immédiat pour continuer le chargement si nécessaire
            QTimer.singleShot(0, self.restore_scroll_position)
        else:
            # Cible atteinte ou tout chargé : on applique la position finale
            sb.setValue(self.pending_scroll)
            del self.pending_scroll

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.raise_()
    sys.exit(app.exec())