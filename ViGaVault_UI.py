import sys
import pandas as pd
import os
from ViGaVault_Scan import LibraryManager
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem, 
                             QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, 
                             QLineEdit, QComboBox, QDialog, QTextEdit, QFormLayout, QMessageBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

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
        self.filter_layout.addStretch()
        self.layout.addWidget(self.filter_panel)

        # --- PANNEAU SCAN ---
        self.scan_panel = QWidget()
        self.scan_layout = QVBoxLayout(self.scan_panel)
        
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Nom du jeu à chercher...")
        self.scan_btn = QPushButton("Rechercher")
        self.scan_results = QListWidget()
        self.btn_confirm = QPushButton("Valider le choix")
        
        self.scan_layout.addWidget(QLabel("Scan Manuel"))
        self.scan_layout.addWidget(self.scan_input)
        self.scan_layout.addWidget(self.scan_btn)
        self.scan_layout.addWidget(self.scan_results)
        self.scan_layout.addWidget(self.btn_confirm)
        
        self.layout.addWidget(self.scan_panel)
        self.scan_panel.hide() 
        
        # --- CONNEXIONS ---
        self.search_bar.textChanged.connect(self.parent.apply_filters)
        self.combo_platform.currentIndexChanged.connect(self.parent.apply_filters)
        self.combo_sort.currentIndexChanged.connect(self.parent.apply_filters)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        
        # Connexions Scan
        self.scan_btn.clicked.connect(self.parent.run_inline_search)
        self.scan_input.returnPressed.connect(self.parent.run_inline_search)
        self.btn_confirm.clicked.connect(self.parent.apply_inline_selection)
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
            item.setData(1, g) 
            self.list_widget.addItem(item)
            
        layout.addWidget(self.list_widget)
        
        btn_valider = QPushButton("Valider")
        btn_valider.clicked.connect(self.accept)
        layout.addWidget(btn_valider)
        
    def get_selected_candidate(self):
        item = self.list_widget.currentItem()
        if item:
            return item.data(1) # Récupère l'objet stocké
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
            pixmap = QPixmap(img_path).scaled(200, 266, Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
        title = QLabel(game_data.get('Clean_Title', 'Unknown'))
        title.setStyleSheet("font-weight: bold; font-size: 22px;")
        header_layout.addWidget(title)
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
            details_layout.addWidget(label)
        
        summary = QLabel(f"Résumé: {game_data.get('Summary', '')}")
        summary.setWordWrap(True)
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
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ViGaVault Library")
        self.resize(1200, 800)
        self.sort_desc = False
        
        # 1. Mise en place du layout principal (Horizontal)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 2. Liste des jeux (à gauche, occupe 3/4 de l'espace)
        self.list_widget = QListWidget()
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
            
            # Affichage initial
            self.apply_filters()

    def start_inline_scan(self, game_data):
        self.current_scan_game = game_data
        # On ne touche plus à filter_panel.hide() !
        self.sidebar.scan_panel.show() 
        self.sidebar.scan_input.setText(game_data.get('Clean_Title'))
        self.sidebar.scan_results.clear()
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
            item.setData(1, g)
            self.sidebar.scan_results.addItem(item)
            
        if not candidates:
            QMessageBox.information(self, "Info", "Aucun résultat trouvé.")

    def apply_inline_selection(self):
        item = self.sidebar.scan_results.currentItem()
        if not item: return
        
        chosen_game = item.data(1)
        manager = LibraryManager(r"\\madhdd02\Software\GAMES", "VGVDB.csv")
        manager.load_db()
        game_obj = manager.games.get(self.current_scan_game.get('Folder_Name'))
        
        if game_obj.apply_candidate_data(chosen_game):
            manager.save_db()
            self.refresh_data()
            self.sidebar.scan_panel.hide() # On cache juste le scan après validation
            QMessageBox.information(self, "Succès", "Mise à jour terminée !")

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
            
        # Tri
        sort_col = {"Nom": "Clean_Title", "Date de sortie": "Original_Release_Date", "Développeur": "Developer"}[self.sidebar.combo_sort.currentText()]
        df = df.sort_values(by=sort_col, ascending=not self.sort_desc)
        
        # Update UI
        self.list_widget.clear()
        for _, row in df.iterrows():
            item = QListWidgetItem(self.list_widget)
            # C'est ici qu'il faut ajouter le ', self'
            card = GameCard(row.to_dict(), self) 
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.raise_()
    sys.exit(app.exec())