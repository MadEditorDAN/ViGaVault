# WHY: Single Responsibility Principle - Exclusively handles the rendering and state logic 
# for physical disk paths, scan rules, and Galaxy configuration.
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                               QComboBox, QLabel, QCheckBox, QGroupBox, QLineEdit, QPushButton, 
                               QFileDialog, QScrollArea, QFrame, QMessageBox)
from PySide6.QtCore import Qt, Signal

from ViGaVault_utils import BASE_DIR, translator, is_hidden

class ScrolllessComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()

class LocalSourcesTabWidget(QWidget):
    changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_folder_rules = {}
        self.folder_widgets = {}
        self.setup_ui()
        
    def notify_changed(self, *args):
        self.changed.emit()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        COL_0_W = 160
        COL_1_W = 140

        grp_galaxy = QGroupBox(translator.tr("settings_data_galaxy_group"))
        layout_galaxy = QGridLayout(grp_galaxy)
        self.chk_enable_galaxy = QCheckBox(translator.tr("settings_data_galaxy_checkbox"))
        self.chk_enable_galaxy.setFixedWidth(COL_0_W)
        self.chk_enable_galaxy.toggled.connect(lambda chk: (self.galaxy_db_input.setEnabled(chk), self.btn_browse_galaxy.setEnabled(chk), self.notify_changed()))

        self.galaxy_db_input = QLineEdit()
        self.galaxy_db_input.textChanged.connect(self.notify_changed)
        self.btn_browse_galaxy = QPushButton("...")
        self.btn_browse_galaxy.setFixedWidth(40)
        self.btn_browse_galaxy.clicked.connect(self.browse_galaxy_db)
        
        lbl_gal_path = QLabel("")
        lbl_gal_path.setFixedWidth(COL_1_W)
        
        layout_galaxy.addWidget(self.chk_enable_galaxy, 0, 0)
        layout_galaxy.addWidget(lbl_gal_path, 0, 1)
        layout_galaxy.addWidget(self.galaxy_db_input, 0, 2)
        layout_galaxy.addWidget(self.btn_browse_galaxy, 0, 3)
        layout_galaxy.setColumnStretch(2, 1)
        layout.addWidget(grp_galaxy)
        
        grp_media = QGroupBox(translator.tr("settings_data_media_group"))
        layout_media = QGridLayout(grp_media)
        self.chk_download_images = QCheckBox(translator.tr("settings_data_media_download_images"))
        self.chk_download_images.setFixedWidth(COL_0_W)
        self.chk_download_images.toggled.connect(self.notify_changed)
        
        lbl_img_path = QLabel(translator.tr("settings_data_media_images_path"))
        lbl_img_path.setFixedWidth(COL_1_W)
        self.image_path_input = QLineEdit()
        self.image_path_input.textChanged.connect(self.notify_changed)
        self.btn_browse_image = QPushButton("...")
        self.btn_browse_image.setFixedWidth(40)
        self.btn_browse_image.clicked.connect(lambda: self.browse_path(self.image_path_input, "Select Images Folder"))
        
        layout_media.addWidget(self.chk_download_images, 0, 0)
        layout_media.addWidget(lbl_img_path, 0, 1)
        layout_media.addWidget(self.image_path_input, 0, 2)
        layout_media.addWidget(self.btn_browse_image, 0, 3)
        layout_media.setColumnStretch(2, 1)
        layout.addWidget(grp_media)
        
        grp_root = QGroupBox(translator.tr("settings_folders_local_copies_group"))
        self.struct_layout = QVBoxLayout(grp_root)
        
        top_h = QHBoxLayout()
        self.chk_scan_local = QCheckBox(translator.tr("settings_folders_scan_local"))
        self.chk_scan_local.setFixedWidth(COL_0_W)
        self.chk_scan_local.toggled.connect(self.toggle_local_scan_options)
        self.chk_scan_local.toggled.connect(self.notify_changed)
        
        lbl_root_path = QLabel(translator.tr("settings_folders_main_path"))
        lbl_root_path.setFixedWidth(COL_1_W)
        self.root_path_input = QLineEdit("")
        self.root_path_input.textChanged.connect(self.notify_changed)
        self.root_path_input.editingFinished.connect(self.on_path_edited)
        self.btn_browse_root = QPushButton("...")
        self.btn_browse_root.setFixedWidth(40)
        self.btn_browse_root.clicked.connect(lambda: (self.browse_path(self.root_path_input, "Select Root Folder"), self.on_path_edited()))
        
        top_h.addWidget(self.chk_scan_local)
        top_h.addWidget(lbl_root_path)
        top_h.addWidget(self.root_path_input, 1)
        top_h.addWidget(self.btn_browse_root)
        self.struct_layout.addLayout(top_h)
        
        self.chk_ignore_hidden = QCheckBox(translator.tr("settings_folders_ignore_hidden"))
        self.chk_ignore_hidden.toggled.connect(self.notify_changed)
        self.struct_layout.addWidget(self.chk_ignore_hidden)

        self.table_widget = QWidget()
        table_layout = QVBoxLayout(self.table_widget)
        table_layout.setContentsMargins(0, 10, 0, 0)
        
        lbl_adv = QLabel("Directory Scan Rules")
        lbl_adv.setStyleSheet("font-weight: bold; color: #2196F3;")
        table_layout.addWidget(lbl_adv)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.levels_container = QWidget()
        self.folders_grid = QGridLayout(self.levels_container)
        self.folders_grid.setAlignment(Qt.AlignTop)
        self.folders_grid.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.levels_container)
        table_layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        self.btn_add_folder = QPushButton("+ Add Folder")
        self.btn_add_folder.clicked.connect(self.add_selected_folder)
        btn_layout.addWidget(self.btn_add_folder)
        
        self.btn_add_all = QPushButton("+ Add Main Path Subfolders")
        self.btn_add_all.clicked.connect(self.add_all_folders)
        btn_layout.addWidget(self.btn_add_all)
        
        btn_layout.addStretch()
        
        self.btn_clear_all = QPushButton("Clear All (Keep Root)")
        self.btn_clear_all.clicked.connect(self.clear_all_folders)
        btn_layout.addWidget(self.btn_clear_all)
        
        table_layout.addLayout(btn_layout)
        self.struct_layout.addWidget(self.table_widget)
        
        layout.addWidget(grp_root, 1)

    def toggle_local_scan_options(self, checked):
        self.root_path_input.setEnabled(checked)
        self.btn_browse_root.setEnabled(checked)
        self.chk_ignore_hidden.setEnabled(checked)
        self.table_widget.setEnabled(checked)

    def on_path_edited(self):
        self.save_current_folder_rules_state()
        self.populate_folders_list()
            
    def save_current_folder_rules_state(self):
        if not hasattr(self, 'folder_widgets'): return
        for folder, widgets in self.folder_widgets.items():
            self.current_folder_rules[folder] = {
                "scan": widgets["scan"].isChecked() if widgets.get("scan") else True,
                "structure": widgets["structure"].currentText(),
                "type": widgets["combo"].currentText(),
                "filter": widgets["filter"].isChecked(),
                "inject_enabled": widgets["inject_enabled"].isChecked(),
                "inject_field": widgets["inject_field"].currentText(),
                "inject_value": widgets["inject_value"].text().strip()
            }
            
    def clear_all_folders(self):
        self.save_current_folder_rules_state()
        keys_to_remove = [k for k in self.current_folder_rules.keys() if k != "[ROOT PATH]"]
        for k in keys_to_remove:
            del self.current_folder_rules[k]
        self.populate_folders_list()
        self.notify_changed()

    def remove_folder_rule(self, folder):
        self.save_current_folder_rules_state()
        if folder in self.current_folder_rules:
            del self.current_folder_rules[folder]
        self.populate_folders_list()
        self.notify_changed()

    def browse_path(self, target_input, title):
        dir_path = QFileDialog.getExistingDirectory(self, title, target_input.text())
        if dir_path: target_input.setText(os.path.normpath(dir_path))
            
    def browse_galaxy_db(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Galaxy Database", self.galaxy_db_input.text(), "SQLite DB (*.db);;All Files (*.*)")
        if file_path: self.galaxy_db_input.setText(file_path)

    def add_selected_folder(self):
        self.save_current_folder_rules_state()
        root = self.root_path_input.text().strip()
        if not os.path.exists(root):
            QMessageBox.warning(self, "Error", "Please define a valid Main Path first.")
            return
            
        dir_path = QFileDialog.getExistingDirectory(self, "Select Subfolder", root)
        if not dir_path: return
        
        dir_path = os.path.normpath(dir_path)
        root_norm = os.path.normpath(root)
        
        if not dir_path.startswith(root_norm) or dir_path == root_norm:
            QMessageBox.warning(self, "Invalid Folder", "You must select a subfolder located INSIDE your Main Path.")
            return
            
        rel_path = os.path.relpath(dir_path, root_norm)
        
        if rel_path in self.current_folder_rules:
            QMessageBox.information(self, "Already Exists", "This folder is already in the rules list.")
            return
            
        self.current_folder_rules[rel_path] = {"scan": True, "structure": "Contains Games Directly", "type": "Unused", "filter": False, "inject_enabled": False, "inject_field": "Genre", "inject_value": ""}
        self.populate_folders_list()
        self.notify_changed()

    def add_all_folders(self):
        self.save_current_folder_rules_state()
        root = self.root_path_input.text().strip()
        if not os.path.exists(root): return
        try: disk_folders = [f for f in os.listdir(root) if os.path.isdir(os.path.join(root, f))]
        except: disk_folders = []
        
        unadded = [f for f in disk_folders if f not in self.current_folder_rules and f != "[ROOT PATH]"]
        if len(unadded) > 10:
            reply = QMessageBox.question(self, "Warning", f"You are about to add {len(unadded)} folders to the table.\nAre you sure you want to proceed?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No: return
            
        for f in unadded:
            self.current_folder_rules[f] = {"scan": True, "structure": "Contains Games Directly", "type": "Unused", "filter": False, "inject_enabled": False, "inject_field": "Genre", "inject_value": ""}
            
        self.populate_folders_list()
        self.notify_changed()

    def populate_folders_list(self):
        while self.folders_grid.count():
            item = self.folders_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_folder")), 0, 0)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_scan")), 0, 1)
        self.folders_grid.addWidget(QLabel("Structure"), 0, 2)
        self.folders_grid.addWidget(QLabel("SubFolders Type"), 0, 3)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_filter")), 0, 4)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_inject")), 0, 6)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_inject_field")), 0, 7)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_inject_value")), 0, 8)
        self.folders_grid.addWidget(QLabel("Action"), 0, 9)
        
        # Buffer column sizing for the path label
        self.folders_grid.setColumnStretch(0, 0)
        self.folders_grid.setColumnStretch(8, 1)

        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        self.folders_grid.addWidget(vline, 0, 5, len(self.current_folder_rules) + 2, 1)      
        
        self.folder_widgets = {}
        
        # Ensure [ROOT PATH] always exists
        if "[ROOT PATH]" not in self.current_folder_rules:
            self.current_folder_rules["[ROOT PATH]"] = {"scan": True, "structure": "Contains Games Directly", "type": "Unused", "filter": False, "inject_enabled": False, "inject_field": "Genre", "inject_value": ""}

        all_folders = ["[ROOT PATH]"] + sorted([k for k in self.current_folder_rules.keys() if k != "[ROOT PATH]"])
        
        row = 1
        for folder in all_folders:
            rule = self.current_folder_rules[folder]
            
            if folder == "[ROOT PATH]":
                display_text = self.root_path_input.text() or "[ROOT PATH]"
            else:
                display_text = os.path.join(self.root_path_input.text(), folder) if self.root_path_input.text() else folder
                
            lbl = QLabel(display_text)
            if folder == "[ROOT PATH]": lbl.setStyleSheet("font-weight: bold;")
            
            chk_scan = QCheckBox()
            if folder == "[ROOT PATH]":
                chk_scan.setChecked(rule.get("scan", True))
            else:
                chk_scan.setChecked(rule.get("scan", True))

            combo_struct = ScrolllessComboBox()
            combo_struct.addItems(["Contains Games Directly", "Contains Subfolders"])
            combo_struct.setCurrentText(rule.get("structure", "Contains Games Directly"))
            
            combo = ScrolllessComboBox()
            combo.addItems(["Unused", "Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            loaded_type = rule.get("type", "Unused")
            if loaded_type == "None": loaded_type = "Unused"
            combo.setCurrentText(loaded_type)
            
            chk_filter = QCheckBox()
            chk_filter.setChecked(rule.get("filter", False))
            
            chk_inject = QCheckBox()
            chk_inject.setChecked(rule.get("inject_enabled", False))
            combo_inject = ScrolllessComboBox()
            combo_inject.addItems(["Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            combo_inject.setCurrentText(rule.get("inject_field", "Genre"))
            txt_inject = QLineEdit()
            txt_inject.setText(rule.get("inject_value", ""))
            
            # Button Remove
            if folder != "[ROOT PATH]":
                btn_remove = QPushButton("✖")
                btn_remove.setFixedWidth(30)
                btn_remove.clicked.connect(lambda _, f=folder: self.remove_folder_rule(f))
            else:
                btn_remove = QLabel("")
            
            # Initial enabling states
            def update_enablers(state_scan, state_inject, lbl=lbl, cs=combo_struct, c=combo, f=chk_filter, i=chk_inject, ci=combo_inject, ti=txt_inject):
                cs.blockSignals(True)
                if not state_scan:
                    if cs.currentText() != "Not Scanned":
                        cs.setProperty("prev_struct", cs.currentText())
                    if cs.findText("Not Scanned") == -1:
                        cs.addItem("Not Scanned")
                    cs.setCurrentText("Not Scanned")
                else:
                    prev = cs.property("prev_struct")
                    if not prev or prev == "Not Scanned":
                        prev = "Contains Games Directly"
                    if cs.currentText() == "Not Scanned":
                        cs.setCurrentText(prev)
                    idx = cs.findText("Not Scanned")
                    if idx != -1:
                        cs.removeItem(idx)
                cs.blockSignals(False)
                
                state_struct = cs.currentText()
                has_subfolders = (state_struct == "Contains Subfolders")
                
                lbl.setEnabled(state_scan)
                cs.setEnabled(state_scan)
                c.setEnabled(state_scan and has_subfolders)
                f.setEnabled(state_scan)
                i.setEnabled(state_scan)
                ci.setEnabled(state_scan and state_inject)
                ti.setEnabled(state_scan and state_inject)

            update_enablers(chk_scan.isChecked(), chk_inject.isChecked())
            
            chk_scan.stateChanged.connect(lambda state, func=update_enablers, inj=chk_inject: func(bool(state), inj.isChecked()))
            combo_struct.currentTextChanged.connect(lambda text, func=update_enablers, scan=chk_scan, inj=chk_inject: func(scan.isChecked(), inj.isChecked()))
            chk_inject.stateChanged.connect(lambda state, func=update_enablers, scan=chk_scan: func(scan.isChecked(), bool(state)))
            
            combo_struct.currentIndexChanged.connect(self.notify_changed)
            combo.currentIndexChanged.connect(self.notify_changed)
            chk_filter.toggled.connect(self.notify_changed)
            chk_scan.toggled.connect(self.notify_changed)
            chk_inject.toggled.connect(self.notify_changed)
            combo_inject.currentIndexChanged.connect(self.notify_changed)
            txt_inject.textChanged.connect(self.notify_changed)
            
            self.folders_grid.addWidget(lbl, row, 0)
            self.folders_grid.addWidget(chk_scan, row, 1)
            self.folders_grid.addWidget(combo_struct, row, 2)
            self.folders_grid.addWidget(combo, row, 3)
            self.folders_grid.addWidget(chk_filter, row, 4)
            self.folders_grid.addWidget(chk_inject, row, 6)
            self.folders_grid.addWidget(combo_inject, row, 7)
            self.folders_grid.addWidget(txt_inject, row, 8)
            self.folders_grid.addWidget(btn_remove, row, 9)

            self.folder_widgets[folder] = {
                "lbl": lbl, "scan": chk_scan, "structure": combo_struct, "combo": combo, "filter": chk_filter,
                "inject_enabled": chk_inject, "inject_field": combo_inject, "inject_value": txt_inject
            }
            row += 1

    def set_state(self, lib_settings, live_dl_images=None):
        self.root_path_input.setText(lib_settings.get("rootPath", ""))
        local_config = lib_settings.get("localScanConfig", {})
        
        self.chk_scan_local.setChecked(local_config.get("enable_local_scan", False))
        self.toggle_local_scan_options(self.chk_scan_local.isChecked())
        self.chk_ignore_hidden.setChecked(local_config.get("ignore_hidden", True))
        
        self.current_folder_rules = local_config.get("folder_rules", {})
        self.populate_folders_list()
        
        self.chk_enable_galaxy.setChecked(lib_settings.get("enableGalaxyDb", False))
        self.galaxy_db_input.setText(lib_settings.get("galaxyDbPath", os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')))
        self.galaxy_db_input.setEnabled(self.chk_enable_galaxy.isChecked())
        self.btn_browse_galaxy.setEnabled(self.chk_enable_galaxy.isChecked())
        
        if live_dl_images is not None: self.chk_download_images.setChecked(live_dl_images)
        else: self.chk_download_images.setChecked(lib_settings.get("downloadImages", True))
            
        self.image_path_input.setText(lib_settings.get("imagePath", os.path.join(BASE_DIR, "images")))
        
    def get_state(self):
        self.save_current_folder_rules_state()
        return {
            "root_path": self.root_path_input.text(),
            "local_scan_config": {
                "enable_local_scan": self.chk_scan_local.isChecked(),
                "ignore_hidden": self.chk_ignore_hidden.isChecked(),
                "folder_rules": self.current_folder_rules
            },
            "enable_galaxy_db": self.chk_enable_galaxy.isChecked(),
            "galaxy_db_path": self.galaxy_db_input.text(),
            "download_images": self.chk_download_images.isChecked(),
            "image_path": self.image_path_input.text()
        }