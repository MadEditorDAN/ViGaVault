# WHY: Single Responsibility Principle - Exclusively handles the rendering and state logic 
# for physical disk paths, scan rules, and Galaxy configuration.
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                               QComboBox, QLabel, QCheckBox, QGroupBox, QLineEdit, QPushButton, 
                               QFileDialog, QScrollArea, QFrame)
from PySide6.QtCore import Qt, Signal

from ViGaVault_utils import BASE_DIR, translator, is_hidden

class LocalSourcesTabWidget(QWidget):
    changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_folder_rules = {}
        self.current_scan_mode = "simple"
        self.setup_ui()
        
    def notify_changed(self, *args):
        """WHY: Safely absorbs arbitrary arguments passed by Qt signals before cleanly emitting the zero-argument custom signal."""
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
        self.struct_layout = QGridLayout(grp_root)
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
        
        self.struct_layout.addWidget(self.chk_scan_local, 0, 0)
        self.struct_layout.addWidget(lbl_root_path, 0, 1)
        self.struct_layout.addWidget(self.root_path_input, 0, 2)
        self.struct_layout.addWidget(self.btn_browse_root, 0, 3)
        
        self.chk_ignore_hidden = QCheckBox(translator.tr("settings_folders_ignore_hidden"))
        self.chk_ignore_hidden.toggled.connect(self.update_hidden_folders_visibility)
        self.chk_ignore_hidden.toggled.connect(self.notify_changed)
        self.struct_layout.addWidget(self.chk_ignore_hidden, 1, 0, 1, 4)

        self.mode_simple_widget = QWidget()
        simple_layout = QGridLayout(self.mode_simple_widget)
        simple_layout.setContentsMargins(0, 10, 0, 0)
        lbl_simple = QLabel(translator.tr("settings_folders_simple_mode_label"))
        lbl_simple.setStyleSheet("font-weight: bold; color: #4CAF50;")
        lbl_simple.setFixedWidth(COL_0_W)
        lbl_simple_content = QLabel(translator.tr("settings_folders_simple_mode_content"))
        lbl_simple_content.setFixedWidth(COL_1_W)
        self.combo_global_type = QComboBox()
        self.combo_global_type.addItems(["Direct (Root -> Games)", "Genre", "Collection", "Publisher", "Developer", "Year", "Other", "None"])
        self.combo_global_type.currentIndexChanged.connect(self.notify_changed)
        self.chk_global_filter = QCheckBox(translator.tr("settings_folders_simple_mode_add_filter"))
        self.chk_global_filter.toggled.connect(self.notify_changed)
        simple_layout.addWidget(lbl_simple, 0, 0)
        simple_layout.addWidget(lbl_simple_content, 0, 1)
        simple_layout.addWidget(self.combo_global_type, 0, 2)
        simple_layout.addWidget(self.chk_global_filter, 0, 3)
        simple_layout.setColumnStretch(2, 1)
        
        self.btn_switch_advanced = QPushButton(translator.tr("settings_folders_simple_mode_switch_btn"))
        self.btn_switch_advanced.clicked.connect(self.switch_to_advanced)
        simple_layout.addWidget(self.btn_switch_advanced, 1, 0, 1, 4)
        self.struct_layout.addWidget(self.mode_simple_widget, 2, 0, 1, 4)
 
        self.mode_advanced_widget = QWidget()
        adv_layout = QVBoxLayout(self.mode_advanced_widget)
        adv_layout.setContentsMargins(0, 10, 0, 0)
        lbl_adv = QLabel(translator.tr("settings_folders_adv_mode_label"))
        lbl_adv.setStyleSheet("font-weight: bold; color: #2196F3;")
        adv_layout.addWidget(lbl_adv)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.levels_container = QWidget()
        self.folders_grid = QGridLayout(self.levels_container)
        self.folders_grid.setAlignment(Qt.AlignTop)
        self.folders_grid.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.levels_container)
        adv_layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        self.btn_switch_simple = QPushButton(translator.tr("settings_folders_adv_mode_switch_btn"))
        self.btn_switch_simple.clicked.connect(self.switch_to_simple)
        self.btn_clear_all = QPushButton("Clear All")
        self.btn_clear_all.clicked.connect(self.clear_all_folders)
        btn_layout.addWidget(self.btn_switch_simple)
        btn_layout.addWidget(self.btn_clear_all)
        btn_layout.addStretch()
        adv_layout.addLayout(btn_layout)
        self.struct_layout.addWidget(self.mode_advanced_widget, 3, 0, 1, 4)
        self.struct_layout.setColumnStretch(2, 1)
        layout.addWidget(grp_root, 1)

    def toggle_local_scan_options(self, checked):
        self.root_path_input.setEnabled(checked)
        self.btn_browse_root.setEnabled(checked)
        self.chk_ignore_hidden.setEnabled(checked)
        self.mode_simple_widget.setEnabled(checked)
        self.mode_advanced_widget.setEnabled(checked)

    def switch_to_simple(self):
        self.mode_advanced_widget.hide()
        self.mode_simple_widget.show()
        self.current_scan_mode = "simple"

    def switch_to_advanced(self):
        self.mode_simple_widget.hide()
        self.mode_advanced_widget.show()
        self.current_scan_mode = "advanced"
        self.save_current_folder_rules_state()
        self.populate_folders_list()
        
    def on_path_edited(self):
        if self.current_scan_mode == "advanced":
            self.save_current_folder_rules_state()
            self.populate_folders_list()
            
    def save_current_folder_rules_state(self):
        if not hasattr(self, 'folder_widgets'): return
        for folder, widgets in self.folder_widgets.items():
            self.current_folder_rules[folder] = {
                "type": widgets["combo"].currentText(),
                "filter": widgets["filter"].isChecked(),
                "scan": widgets["scan"].isChecked(),
                "inject_enabled": widgets["inject_enabled"].isChecked(),
                "inject_field": widgets["inject_field"].currentText(),
                "inject_value": widgets["inject_value"].text().strip()
            }
            
    def clear_all_folders(self):
        if not hasattr(self, 'folder_widgets'): return
        for widgets in self.folder_widgets.values():
            widgets["scan"].setChecked(False)
        self.notify_changed()

    def browse_path(self, target_input, title):
        dir_path = QFileDialog.getExistingDirectory(self, title, target_input.text())
        if dir_path: target_input.setText(os.path.normpath(dir_path))
            
    def browse_galaxy_db(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Galaxy Database", self.galaxy_db_input.text(), "SQLite DB (*.db);;All Files (*.*)")
        if file_path: self.galaxy_db_input.setText(file_path)

    def populate_folders_list(self):
        while self.folders_grid.count():
            item = self.folders_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_folder")), 0, 0)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_scan")), 0, 1)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_content_type")), 0, 2)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_filter")), 0, 3)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_inject")), 0, 5)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_inject_field")), 0, 6)
        self.folders_grid.addWidget(QLabel(translator.tr("settings_folders_adv_mode_inject_value")), 0, 7)

        root = self.root_path_input.text().strip()
        disk_folders = set()
        if os.path.exists(root):
            try: disk_folders = {f for f in os.listdir(root) if os.path.isdir(os.path.join(root, f))}
            except: pass
        
        all_folders = sorted(list(disk_folders))
        
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        self.folders_grid.addWidget(vline, 0, 4, len(all_folders) + 1, 1)      
        self.folders_grid.setColumnMinimumWidth(1, 40)
        self.folders_grid.setColumnMinimumWidth(2, 200)
        self.folders_grid.setColumnMinimumWidth(3, 40)
        self.folders_grid.setColumnMinimumWidth(4, 10)
        self.folders_grid.setColumnMinimumWidth(5, 40)
        self.folders_grid.setColumnMinimumWidth(6, 200)
        self.folders_grid.setColumnMinimumWidth(7, 200)        
        
        self.folder_widgets = {}
        row = 1
        for folder in all_folders:
            full_path = os.path.join(root, folder)
            hidden = is_hidden(full_path) if os.path.exists(full_path) else False
            lbl = QLabel(folder)
            if folder not in disk_folders: lbl.setStyleSheet("color: red;")
            
            combo = QComboBox()
            combo.addItems(["None", "Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            chk_filter = QCheckBox()
            chk_scan = QCheckBox()
            
            chk_inject = QCheckBox()
            combo_inject = QComboBox()
            combo_inject.addItems(["Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            txt_inject = QLineEdit()
            
            if folder in self.current_folder_rules:
                rule = self.current_folder_rules[folder]
                combo.setCurrentText(rule.get("type", "None"))
                chk_filter.setChecked(rule.get("filter", False))
                chk_scan.setChecked(rule.get("scan", True))
                chk_inject.setChecked(rule.get("inject_enabled", False))
                combo_inject.setCurrentText(rule.get("inject_field", "Genre"))
                txt_inject.setText(rule.get("inject_value", ""))
            else:
                chk_scan.setChecked(False)
            
            combo.setEnabled(chk_scan.isChecked())
            chk_filter.setEnabled(chk_scan.isChecked())
            chk_inject.setEnabled(chk_scan.isChecked())
            combo_inject.setEnabled(chk_scan.isChecked() and chk_inject.isChecked())
            txt_inject.setEnabled(chk_scan.isChecked() and chk_inject.isChecked())
            
            chk_scan.stateChanged.connect(lambda state, c=combo, f=chk_filter, i=chk_inject, ci=combo_inject, ti=txt_inject, scan=chk_scan: 
                                          (c.setEnabled(state and scan.isEnabled()), f.setEnabled(state and scan.isEnabled()), i.setEnabled(state and scan.isEnabled()), ci.setEnabled(state and i.isChecked() and scan.isEnabled()), ti.setEnabled(state and i.isChecked() and scan.isEnabled())))
            chk_inject.stateChanged.connect(lambda state, ci=combo_inject, ti=txt_inject: (ci.setEnabled(state), ti.setEnabled(state)))
            
            combo.currentIndexChanged.connect(self.notify_changed)
            chk_filter.toggled.connect(self.notify_changed)
            chk_scan.toggled.connect(self.notify_changed)
            chk_inject.toggled.connect(self.notify_changed)
            combo_inject.currentIndexChanged.connect(self.notify_changed)
            txt_inject.textChanged.connect(self.notify_changed)
            
            self.folders_grid.addWidget(lbl, row, 0)
            self.folders_grid.addWidget(chk_scan, row, 1)
            self.folders_grid.addWidget(combo, row, 2)
            self.folders_grid.addWidget(chk_filter, row, 3)
            self.folders_grid.addWidget(chk_inject, row, 5)
            self.folders_grid.addWidget(combo_inject, row, 6)
            self.folders_grid.addWidget(txt_inject, row, 7)

            self.folder_widgets[folder] = {
                "lbl": lbl, "combo": combo, "filter": chk_filter, "scan": chk_scan, 
                "inject_enabled": chk_inject, "inject_field": combo_inject, "inject_value": txt_inject,
                "is_hidden": hidden
            }
            row += 1
        self.update_hidden_folders_visibility()

    def update_hidden_folders_visibility(self):
        if not hasattr(self, 'folder_widgets'): return
        ignore = self.chk_ignore_hidden.isChecked()
        for folder, widgets in self.folder_widgets.items():
            if widgets.get("is_hidden", False):
                is_enabled = not ignore
                widgets["lbl"].setEnabled(is_enabled)
                widgets["scan"].setEnabled(is_enabled)
                
                scan_checked = widgets["scan"].isChecked() and is_enabled
                widgets["combo"].setEnabled(scan_checked)
                widgets["filter"].setEnabled(scan_checked)
                widgets["inject_enabled"].setEnabled(scan_checked)
                
                inj_checked = widgets["inject_enabled"].isChecked() and scan_checked
                widgets["inject_field"].setEnabled(inj_checked)
                widgets["inject_value"].setEnabled(inj_checked)
                
    def set_state(self, lib_settings, live_dl_images=None):
        self.root_path_input.setText(lib_settings.get("root_path", ""))
        local_config = lib_settings.get("local_scan_config", {})
        
        self.chk_scan_local.setChecked(local_config.get("enable_local_scan", False))
        self.toggle_local_scan_options(self.chk_scan_local.isChecked())
        self.chk_ignore_hidden.setChecked(local_config.get("ignore_hidden", True))
        
        self.current_scan_mode = local_config.get("scan_mode", "simple")
        self.combo_global_type.setCurrentText(local_config.get("global_type", "Genre"))
        self.chk_global_filter.setChecked(local_config.get("global_filter", True))

        if self.current_scan_mode == "simple": self.switch_to_simple()
        else: self.switch_to_advanced()
        
        self.current_folder_rules = local_config.get("folder_rules", {})
        self.populate_folders_list()
        
        self.chk_enable_galaxy.setChecked(lib_settings.get("enable_galaxy_db", False))
        self.galaxy_db_input.setText(lib_settings.get("galaxy_db_path", os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')))
        self.galaxy_db_input.setEnabled(self.chk_enable_galaxy.isChecked())
        self.btn_browse_galaxy.setEnabled(self.chk_enable_galaxy.isChecked())
        
        if live_dl_images is not None: self.chk_download_images.setChecked(live_dl_images)
        else: self.chk_download_images.setChecked(lib_settings.get("download_images", True))
            
        self.image_path_input.setText(lib_settings.get("image_path", os.path.join(BASE_DIR, "images")))
        
    def get_state(self):
        self.save_current_folder_rules_state()
        return {
            "root_path": self.root_path_input.text(),
            "local_scan_config": {
                "enable_local_scan": self.chk_scan_local.isChecked(),
                "ignore_hidden": self.chk_ignore_hidden.isChecked(),
                "scan_mode": self.current_scan_mode,
                "global_type": self.combo_global_type.currentText(),
                "global_filter": self.chk_global_filter.isChecked(),
                "folder_rules": self.current_folder_rules
            },
            "enable_galaxy_db": self.chk_enable_galaxy.isChecked(),
            "galaxy_db_path": self.galaxy_db_input.text(),
            "download_images": self.chk_download_images.isChecked(),
            "image_path": self.image_path_input.text()
        }