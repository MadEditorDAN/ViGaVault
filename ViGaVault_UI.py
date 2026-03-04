import sys
import pandas as pd
import os
import re
import requests
import json
from ViGaVault_Scan import LibraryManager
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, 
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox, QFrame, QAbstractItemView, QCheckBox)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray
from PySide6.QtGui import QPixmap, QIcon

DB_FILE = "VGVDB.csv"

# --- Fenêtres de dialogue pour Editer et Scanner ---
class ActionDialog(QDialog):
    def __init__(self, title, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.layout = QFormLayout(self)
        self.inputs = {}
        
        # Liste des champs à cacher (non éditables)
        fields_to_hide = [
            'Path_Root', 'Path_Video', 'Status_Flag', 'Image_Link', 
            'Year_Folder', 'Platforms', 'Empty'
        ]
        
        for field, value in data.items():
            # Si le champ est dans la liste, on l'ignore
            if field in fields_to_hide:
                continue
            
            # Création des champs éditables
            if field == "Summary":
                inp = QTextEdit(str(value))
            else:
                inp = QLineEdit(str(value))
            
            self.layout.addRow(field, inp)
            self.inputs[field] = inp
            
        btn_save = QPushButton("Valider")
        btn_save.clicked.connect(self.accept)
        self.layout.addRow(btn_save)

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
        
        # 1. Recherche
        lbl_search = QLabel("Recherche")
        lbl_search.setStyleSheet(label_style)
        self.filter_layout.addWidget(lbl_search)
        self.search_bar = QLineEdit() # Défini avec self.
        self.search_bar.setPlaceholderText("Nom du jeu...")
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
        lbl_quick_filters = QLabel("Filtres rapides")
        lbl_quick_filters.setStyleSheet(label_style)
        self.filter_layout.addWidget(lbl_quick_filters)

        self.chk_status_ok = QCheckBox("Statut OK uniquement")
        self.filter_layout.addWidget(self.chk_status_ok)

        self.chk_a_tester = QCheckBox("Jeux 'à tester' (_temp)")
        self.filter_layout.addWidget(self.chk_a_tester)

        self.chk_vr = QCheckBox("Jeux VR")
        self.filter_layout.addWidget(self.chk_vr)

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

        # Connexions Filtres Rapides
        self.chk_status_ok.stateChanged.connect(self.parent.apply_filters)
        self.chk_a_tester.stateChanged.connect(self.parent.apply_filters)
        self.chk_vr.stateChanged.connect(self.parent.apply_filters)
        
        # Connexions Scan
        self.scan_btn.clicked.connect(self.parent.run_inline_search)
        self.scan_input.returnPressed.connect(self.parent.run_inline_search)
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
    def __init__(self, game_data, parent_window): # <--- On ajoute parent_window ici
        super().__init__()
        self.data = game_data
        self.parent_window = parent_window # <--- On le stocke
        
        main_layout = QHBoxLayout(self)
        
        # Image
        img_label = QLabel()
        img_label.setFixedSize(200, 266)
        img_label.setAlignment(Qt.AlignCenter)
        img_path = game_data.get('Image_Link', '')
        if img_path and os.path.exists(img_path):
            # Optimisation : FastTransformation est beaucoup plus rapide que SmoothTransformation
            pixmap = QPixmap(img_path).scaled(200, 266, Qt.KeepAspectRatio, Qt.FastTransformation)
            img_label.setPixmap(pixmap)
        else:
            img_label.setText("Pas d'image")
            img_label.setStyleSheet("border: 1px solid #555;")
        main_layout.addWidget(img_label)
        
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
        title_layout.addWidget(title)
        
        path_lbl = QLabel(f"({game_data.get('Path_Root', '')})")
        path_lbl.setStyleSheet("font-size: 11px; color: gray;")
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title_layout.addWidget(path_lbl)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        # Boutons
        btn_folder = QPushButton("📁")
        btn_edit = QPushButton("✏️")
        btn_scan = QPushButton("🔍")
        for btn in [btn_folder, btn_edit, btn_scan]:
            btn.setFixedSize(45, 45)
            btn.setStyleSheet("font-size: 28px; padding: 0px;")
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
            details_layout.addWidget(label)
        
        summary = QLabel(f"Résumé: {game_data.get('Summary', '')}")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_layout.addWidget(summary)
        main_layout.addLayout(details_layout)

    def open_folder(self):
        if os.path.exists(self.data.get('Path_Root', '')):
            os.startfile(self.data.get('Path_Root', ''))

    def edit_game(self):
        dlg = ActionDialog("Éditer le jeu", self.data)
        if dlg.exec():
            print("Sauvegarde demandée...")

    def scan_game(self):
        # Utilise parent_window pour appeler la méthode de la MainWindow
        if hasattr(self.parent_window, 'start_inline_scan'):
            self.parent_window.start_inline_scan(self.data)
            # Lancement automatique de la recherche pour gagner du temps
            if hasattr(self.parent_window, 'run_inline_search'):
                # On diffère légèrement le lancement pour laisser l'interface s'afficher (message d'attente)
                QTimer.singleShot(50, self.parent_window.run_inline_search)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ViGaVault Library")
        self.resize(1200, 800)
        self.sort_desc = True
        
        # Timer pour éviter de recharger la liste à chaque lettre tapée (Debounce)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300) # Attend 300ms après la dernière frappe
        self.search_timer.timeout.connect(self.apply_filters)
        
        # 1. Mise en place du layout principal (Horizontal)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 2. Liste des jeux (à gauche, occupe 3/4 de l'espace)
        self.list_widget = QListWidget()
        # Assure un défilement fluide pixel par pixel au lieu de sauter d'item en item
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.verticalScrollBar().setSingleStep(25)
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
                self.list_widget.verticalScrollBar().setValue(saved_scroll)

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
        
        self.sidebar.scan_input.setFocus() # Donne le focus direct au champ

    def run_inline_search(self):
        term = self.sidebar.scan_input.text()
        if not term: return # Sécurité
        
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        token = manager.get_access_token()
        
        game_obj = manager.games.get(self.current_scan_game.get('Folder_Name'))
        candidates = game_obj.fetch_candidates(token, term)
        
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

    def cancel_inline_scan(self):
        self.sidebar.scan_panel.hide()
        self.sidebar.scan_results.clear()
        self.sidebar.scan_input.clear()

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
            for i in range(self.list_widget.count()):
                list_item = self.list_widget.item(i)
                if list_item.data(Qt.UserRole) == target_folder:
                    self.list_widget.scrollToItem(list_item)
                    self.list_widget.setCurrentItem(list_item)
                    break
            
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
            "chk_status_ok": self.sidebar.chk_status_ok.isChecked(),
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
            self.sidebar.chk_status_ok.blockSignals(True)
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
            
            self.sidebar.chk_status_ok.setChecked(settings.get("chk_status_ok", False))
            self.sidebar.chk_a_tester.setChecked(settings.get("chk_a_tester", False))
            self.sidebar.chk_vr.setChecked(settings.get("chk_vr", False))
            
            self.sidebar.combo_sort.blockSignals(False)
            self.sidebar.combo_platform.blockSignals(False)
            self.sidebar.search_bar.blockSignals(False)
            self.sidebar.chk_status_ok.blockSignals(False)
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

    def apply_filters(self):
        if not hasattr(self, 'master_df'): return
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
        if self.sidebar.chk_status_ok.isChecked():
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
        self.list_widget.clear()
        for _, row in df.iterrows():
            item = QListWidgetItem(self.list_widget)
            # C'est ici qu'il faut ajouter le ', self'
            card = GameCard(row.to_dict(), self) 
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, row['Folder_Name']) # Stocke l'ID pour le scroll
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.raise_()
    sys.exit(app.exec())