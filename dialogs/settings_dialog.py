# WHY: Single Responsibility Principle - Handles ONLY UI interactions relating to global and local settings.
import os
import json
import logging
import shutil
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout, 
                               QComboBox, QSlider, QLabel, QCheckBox, QGroupBox, QLineEdit, QPushButton, 
                               QFileDialog, QGridLayout, QScrollArea, QFrame, QMessageBox, QSizePolicy,
                               QTableWidget, QHeaderView, QAbstractItemView, QInputDialog)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette

from ViGaVault_utils import BASE_DIR, get_library_settings_file, translator, DIALOG_STD_SIZE, center_window, DEFAULT_DISPLAY_SETTINGS, is_hidden

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(translator.tr("settings_title"))
        
        # WHY: Pre-initialize to prevent crashes when signals fire during UI construction.
        self.btn_apply = None

        # WHY: Apply user-requested size limits.
        self.IMG_SIZES = [150, 175, 200, 225, 250, 275, 300]
        self.BTN_SIZES = [35, 40, 45, 50, 55, 60, 65]
        self.TXT_SIZES = [14, 16, 18, 20, 22, 24, 26]

        self.resize(*DIALOG_STD_SIZE)
        center_window(self, parent)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.tab_display = QWidget()
        self.setup_display_tab()
        self.tabs.addTab(self.tab_display, translator.tr("settings_tab_display"))
        
        self.tab_data = QWidget()
        self.setup_data_tab()
        self.tabs.addTab(self.tab_data, translator.tr("settings_tab_data"))
        
        self.tab_platforms = QWidget()
        self.setup_platforms_tab()
        self.tabs.addTab(self.tab_platforms, translator.tr("settings_tab_platforms"))
        
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton(translator.tr("settings_btn_apply"))
        self.btn_apply.setEnabled(False)
        btn_save = QPushButton(translator.tr("settings_btn_save"))
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        self.btn_apply.clicked.connect(self.apply_settings)
        btn_save.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.load_settings()

    def mark_changed(self, *args):
        """WHY: Enables the Apply button the moment any state inside the dialog is modified."""
        if self.btn_apply:
            self.btn_apply.setEnabled(True)

    def setup_display_tab(self):
        layout = QVBoxLayout(self.tab_display)
        
        grp_theme = QGroupBox(translator.tr("settings_display_theme"))
        layout_theme = QVBoxLayout(grp_theme)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems([translator.tr("theme_system"), translator.tr("theme_dark"), translator.tr("theme_light")])
        self.combo_theme.currentIndexChanged.connect(self.mark_changed)
        layout_theme.addWidget(self.combo_theme)
        layout.addWidget(grp_theme)
        
        grp_reg = QGroupBox(translator.tr("settings_display_regional"))
        layout_reg = QHBoxLayout(grp_reg)
        
        col_lang = QVBoxLayout()
        col_lang.addWidget(QLabel(translator.tr("settings_display_language")))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["English", "French", "German", "Spanish", "Italian"])
        self.combo_lang.currentIndexChanged.connect(self.mark_changed)
        col_lang.addWidget(self.combo_lang)
        
        col_date = QVBoxLayout()
        col_date.addWidget(QLabel(translator.tr("settings_display_date_format")))
        self.combo_date = QComboBox()
        self.combo_date.addItems(["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"])
        self.combo_date.currentIndexChanged.connect(self.mark_changed)
        col_date.addWidget(self.combo_date)
        
        layout_reg.addLayout(col_lang)
        layout_reg.addLayout(col_date)
        layout.addWidget(grp_reg)
        
        grp_sizes = QGroupBox(translator.tr("settings_display_sizes_group"))
        layout_sizes = QFormLayout(grp_sizes)
        # WHY: Inserts the equivalent of an empty line vertically between each slider.
        layout_sizes.setVerticalSpacing(25)
        
        img_layout = QHBoxLayout()
        self.slider_img_size = QSlider(Qt.Horizontal)
        # WHY: DRY Principle - Dynamically size the slider based on the length of the array.
        self.slider_img_size.setRange(0, len(self.IMG_SIZES) - 1)
        self.slider_img_size.setPageStep(1)
        self.slider_img_size.setTickInterval(1)
        self.slider_img_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_img_size = QLabel("200 px")
        self.lbl_img_size.setFixedWidth(60)
        img_layout.addWidget(self.slider_img_size)
        img_layout.addWidget(self.lbl_img_size)
        layout_sizes.addRow(translator.tr("settings_display_img_size"), img_layout)

        btn_layout = QHBoxLayout()
        self.slider_btn_size = QSlider(Qt.Horizontal)
        self.slider_btn_size.setRange(0, len(self.BTN_SIZES) - 1)
        self.slider_btn_size.setPageStep(1)
        self.slider_btn_size.setTickInterval(1)
        self.slider_btn_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_btn_size = QLabel("45 px")
        self.lbl_btn_size.setFixedWidth(60)
        btn_layout.addWidget(self.slider_btn_size)
        btn_layout.addWidget(self.lbl_btn_size)
        layout_sizes.addRow(translator.tr("settings_display_btn_size"), btn_layout)

        txt_layout = QHBoxLayout()
        self.slider_text_size = QSlider(Qt.Horizontal)
        self.slider_text_size.setRange(0, len(self.TXT_SIZES) - 1)
        self.slider_text_size.setPageStep(1)
        self.slider_text_size.setTickInterval(1)
        self.slider_text_size.setTickPosition(QSlider.TicksBelow)
        self.lbl_text_size = QLabel("22 px")
        self.lbl_text_size.setFixedWidth(60)
        txt_layout.addWidget(self.slider_text_size)
        txt_layout.addWidget(self.lbl_text_size)
        layout_sizes.addRow(translator.tr("settings_display_txt_size"), txt_layout)

        layout.addWidget(grp_sizes)
        layout.addStretch()

        self.slider_img_size.valueChanged.connect(self.update_preview_labels)
        self.slider_btn_size.valueChanged.connect(self.update_preview_labels)
        self.slider_text_size.valueChanged.connect(self.update_preview_labels)

        self.slider_img_size.valueChanged.connect(self.mark_changed)
        self.slider_btn_size.valueChanged.connect(self.mark_changed)
        self.slider_text_size.valueChanged.connect(self.mark_changed)

    def update_preview_labels(self):
        self.lbl_img_size.setText(f"{self.IMG_SIZES[self.slider_img_size.value()]} px")
        self.lbl_btn_size.setText(f"{self.BTN_SIZES[self.slider_btn_size.value()]} px")
        self.lbl_text_size.setText(f"{self.TXT_SIZES[self.slider_text_size.value()]} px")

    def toggle_local_scan_options(self, checked):
        # WHY: Explicitly target the variables because they are no longer blindly looped inside a QVBoxLayout container.
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
        self.populate_folders_list(self.current_folder_rules)
        
    def on_path_edited(self):
        """WHY: Smart Refresh - Updates the advanced folders list live when the text input loses focus or Enter is pressed."""
        if hasattr(self, 'current_scan_mode') and self.current_scan_mode == "advanced":
            self.save_current_folder_rules_state()
            self.populate_folders_list(self.current_folder_rules)
            
    def save_current_folder_rules_state(self):
        """WHY: Captures the live UI states before wiping the grid so the user doesn't lose their unsaved checkboxes."""
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
        """WHY: Convenience function to instantly uncheck the scan flag for all advanced folders."""
        if not hasattr(self, 'folder_widgets'): return
        for widgets in self.folder_widgets.values():
            widgets["scan"].setChecked(False)
        self.mark_changed()

    def populate_folders_list(self, saved_rules):
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
        
        # WHY: Strict Physical Mirroring. Stop merging historical JSON rules with actual disk contents.
        all_folders = sorted(list(disk_folders))
        
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        self.folders_grid.addWidget(vline, 0, 4, len(all_folders) + 1, 1)      
        # WHY: Coordinate re-mapping to logically position the Scan Master Checkbox directly next to the Folder Name.
        self.folders_grid.setColumnMinimumWidth(1, 40)  # Scan
        self.folders_grid.setColumnMinimumWidth(2, 200) # Content Type
        self.folders_grid.setColumnMinimumWidth(3, 40)  # Filter
        self.folders_grid.setColumnMinimumWidth(4, 10)  # VLine
        self.folders_grid.setColumnMinimumWidth(5, 40)  # Inject
        self.folders_grid.setColumnMinimumWidth(6, 200) # Target
        self.folders_grid.setColumnMinimumWidth(7, 200) # Value        
        
        self.folder_widgets = {}
        
        row = 1
        for folder in all_folders:
            full_path = os.path.join(root, folder)
            hidden = is_hidden(full_path) if os.path.exists(full_path) else False
                      
            lbl = QLabel(folder)
            if folder not in disk_folders:
                lbl.setStyleSheet("color: red;")
            
            combo = QComboBox()
            # WHY: Explicitly force the widget to stretch horizontally to utilize the 1280px window width.
            combo.addItems(["None", "Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            
            chk_filter = QCheckBox()
            chk_scan = QCheckBox()
            
            chk_inject = QCheckBox()
            combo_inject = QComboBox()
            combo_inject.addItems(["Genre", "Collection", "Publisher", "Developer", "Year", "Other"])
            txt_inject = QLineEdit()
            
            if folder in saved_rules:
                rule = saved_rules[folder]
                combo.setCurrentText(rule.get("type", "None"))
                chk_filter.setChecked(rule.get("filter", False))
                chk_scan.setChecked(rule.get("scan", True))
                
                chk_inject.setChecked(rule.get("inject_enabled", False))
                combo_inject.setCurrentText(rule.get("inject_field", "Genre"))
                txt_inject.setText(rule.get("inject_value", ""))
            else:
                chk_scan.setChecked(False)
            
            # WHY: Establish cascading UI logic. Inject controls are greyed out unless both Scan and Inject are ticked.
            combo.setEnabled(chk_scan.isChecked())
            chk_filter.setEnabled(chk_scan.isChecked())
            chk_inject.setEnabled(chk_scan.isChecked())
            combo_inject.setEnabled(chk_scan.isChecked() and chk_inject.isChecked())
            txt_inject.setEnabled(chk_scan.isChecked() and chk_inject.isChecked())
            
            chk_scan.stateChanged.connect(lambda state, c=combo, f=chk_filter, i=chk_inject, ci=combo_inject, ti=txt_inject, scan=chk_scan: 
                                          (c.setEnabled(state and scan.isEnabled()), f.setEnabled(state and scan.isEnabled()), i.setEnabled(state and scan.isEnabled()), ci.setEnabled(state and i.isChecked() and scan.isEnabled()), ti.setEnabled(state and i.isChecked() and scan.isEnabled())))
            chk_inject.stateChanged.connect(lambda state, ci=combo_inject, ti=txt_inject: 
                                            (ci.setEnabled(state), ti.setEnabled(state)))
            
            combo.currentIndexChanged.connect(self.mark_changed)
            chk_filter.toggled.connect(self.mark_changed)
            chk_scan.toggled.connect(self.mark_changed)
            chk_inject.toggled.connect(self.mark_changed)
            combo_inject.currentIndexChanged.connect(self.mark_changed)
            txt_inject.textChanged.connect(self.mark_changed)
            
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
        """WHY: Smart Refresh - Instantly greys out hidden folders and disables their sub-widgets if the ignore setting is checked."""
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
    def setup_platforms_tab(self):
        layout = QVBoxLayout(self.tab_platforms)
        
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
        
        self.platform_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)          # Name + Copyright
        self.platform_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents) # Button
        
        platforms = [
            ("gog", "GOG", "© CD Projekt"), 
            ("epic", "Epic Games Store", "© Epic Games"), 
            ("steam", "Steam", "© Valve Corporation"),
            ("amazon", "Amazon", "© Amazon.com, Inc."), 
            ("uplay", "Uplay", "© Ubisoft"), 
            ("battlenet", "Battle.net", "© Blizzard Entertainment"),
            ("origin", "Origin", "© Electronic Arts"), 
            ("itch", "itch.io", "© Itch Corp"), 
            ("xbox", "Xbox", "© Microsoft"), 
            ("psn", "PSN", "© Sony Interactive Entertainment")
        ]
        
        self.platform_table.setRowCount(len(platforms))
        # WHY: Height 55 perfectly fits the native button size + the 5px spacer margins without looking cramped.
        self.platform_table.verticalHeader().setDefaultSectionSize(55)
        
        for row, (p_id, p_name, p_copy) in enumerate(platforms):
            # WHY: Format as Rich Text HTML to enforce typography rules (Bold title, small grey copyright) in a single widget.
            lbl_name = QLabel(f"<b>{p_name}</b> &nbsp;&nbsp;<span style='color:gray; font-size:10px;'>{p_copy}</span>")
            lbl_name.setTextFormat(Qt.RichText)
            lbl_name.setContentsMargins(15, 0, 0, 0)
            self.platform_table.setCellWidget(row, 0, lbl_name)
            
            is_connected = False
            if p_id == "gog":
                from backend.gog.login_gog import is_gog_connected
                is_connected = is_gog_connected()
            elif p_id == "epic":
                # WHY: Dynamic import checks our backend connection status directly.
                try:
                    from backend.epic.login_epic import is_epic_connected
                    is_connected = is_epic_connected()
                except ImportError:
                    pass
            
            btn_connect = QPushButton()
            self.update_platform_btn_ui(btn_connect, is_connected)
            
            btn_connect.clicked.connect(lambda _, pid=p_id, b=btn_connect: self.handle_platform_action(pid, b))
            btn_connect.setFixedWidth(120)
            
            # WHY: Wrap the button inside a QWidget with a Layout to force physical margins (spacing) 
            # between the buttons in the QTableWidget's tight cell structure.
            btn_container = QWidget()
            btn_layout = QHBoxLayout(btn_container)
            btn_layout.setContentsMargins(0, 5, 15, 5) 
            btn_layout.addWidget(btn_connect)
            
            self.platform_table.setCellWidget(row, 1, btn_container)
            
        g_layout.addWidget(self.platform_table)
        layout.addWidget(group)

    def update_platform_btn_ui(self, btn, is_connected):
        """WHY: Smart Refresh - Instantly toggles the UI state of a single button without redrawing the table."""
        if is_connected:
            btn.setText(translator.tr("tools_platform_btn_disconnect"))
            btn.setStyleSheet("color: #C62828; font-weight: bold;")
        else:
            btn.setText(translator.tr("tools_platform_btn_connect"))
            btn.setStyleSheet("")

    def handle_platform_action(self, platform_id, btn):
        try:
            from dialogs.login_browser_dialog import LoginBrowserDialog 
        except ImportError:
            QMessageBox.critical(self, "Missing Dependency", "Please install PySide6-WebEngine to use platform connections:\n\npip install PySide6-WebEngine")
            return
            
        if platform_id == "gog":
            from backend.gog.login_gog import is_gog_connected, disconnect_gog, save_gog_session, exchange_code_for_token
            
            if is_gog_connected():
                disconnect_gog()
                self.update_platform_btn_ui(btn, False)
            else:
                oauth_url = "https://auth.gog.com/auth?client_id=46899977096215655&redirect_uri=https://embed.gog.com/on_login_success%3Forigin%3Dclient&response_type=code&layout=client2"
                dlg = LoginBrowserDialog(oauth_url, success_url="on_login_success", parent=self)
                
                def on_gog_finished(result):
                    # WHY: Delay the popup by 100ms. If a modal QMessageBox spawns the exact millisecond 
                    # the browser window hides, the OS window manager gets confused and buries the alert 
                    # underneath the Settings Dialog, creating an invisible, blocking trap!
                    def handle_gog_result():
                        if dlg.success_triggered and dlg.auth_code:
                            token_data = exchange_code_for_token(dlg.auth_code)
                            if token_data and 'access_token' in token_data:
                                save_gog_session(token_data)
                                self.update_platform_btn_ui(btn, True)
                            else:
                                QMessageBox.warning(self, "Login Failed", "Failed to negotiate OAuth token with GOG.")
                        else:
                            QMessageBox.warning(self, "Login Failed", translator.tr("msg_login_failed"))
                        dlg.deleteLater()
                    QTimer.singleShot(100, handle_gog_result)
                
                # WHY: Event-Driven Architecture - Bypasses the fragile blocking C++ loop of exec().
                dlg.finished.connect(on_gog_finished)
                dlg.open()
        elif platform_id == "epic":
            # WHY: Wiring Epic to use the manual authorization code flow via the user's default external browser.
            from backend.epic.login_epic import is_epic_connected, disconnect_epic, exchange_code_for_token, save_epic_session
            import webbrowser
            import re
            
            if is_epic_connected():
                disconnect_epic()
                self.update_platform_btn_ui(btn, False)
                
                # WHY: Dynamically disable the scanner if disconnected.
                if hasattr(self.parent_window, 'sidebar'):
                    self.parent_window.sidebar.chk_scan_epic.setChecked(False)
                    self.parent_window.sidebar.chk_scan_epic.setEnabled(False)
                    self.parent_window.epic_connected_cache = False
            else:
                logging.info("[EPIC BROWSER] Starting Epic Games manual login flow...")
                
                instruction_msg = translator.tr("msg_epic_login_instructions")
                reply = QMessageBox.information(self, translator.tr("msg_epic_login_title"), instruction_msg, QMessageBox.Ok | QMessageBox.Cancel)
                
                if reply == QMessageBox.Ok:
                    # WHY: Epic's security returns 'null' if you directly hit the API endpoint with a stale session. 
                    # Wrapping the API endpoint inside Epic's official login router forces the server to perfectly 
                    # refresh the security context before safely generating the authorizationCode.
                    oauth_url = "https://www.epicgames.com/id/login?redirectUrl=https%3A%2F%2Fwww.epicgames.com%2Fid%2Fapi%2Fredirect%3FclientId%3D34a02cf8f4414e29b15921876da36f9a%26responseType%3Dcode"
                    webbrowser.open(oauth_url)
                    
                    # WHY: Provide 200ms breathing room to ensure the instruction QMessageBox is completely destroyed 
                    # by the OS window manager before spawning the modal QInputDialog. This prevents Z-order corruption 
                    # that causes the main application to invisibly freeze after closing settings.
                    def prompt_token():
                        code_input, ok = QInputDialog.getText(
                            self, 
                            translator.tr("msg_epic_input_title"), 
                            translator.tr("msg_epic_input_prompt")
                        )
                        
                        if ok and code_input:
                            match = re.search(r'([a-fA-F0-9]{32})', code_input)
                            if match:
                                auth_code = match.group(1)
                                logging.info(f"[EPIC BROWSER] Extracted manual exchange code: {auth_code[:5]}...")
                                token_data = exchange_code_for_token(auth_code)
                                
                                if token_data and 'access_token' in token_data:
                                    logging.info("[EPIC BROWSER] Token exchanged successfully. Saving session.")
                                    save_epic_session(token_data)
                                    self.update_platform_btn_ui(btn, True)
                                    
                                    if hasattr(self.parent_window, 'sidebar'):
                                        self.parent_window.sidebar.chk_scan_epic.setEnabled(True)
                                        self.parent_window.epic_connected_cache = True
                                else:
                                    logging.error("[EPIC BROWSER] Failed to exchange manual code for token.")
                                    QMessageBox.warning(self, "Login Failed", translator.tr("msg_epic_token_failed"))
                            else:
                                logging.error("[EPIC BROWSER] Found no valid 32-char code in input.")
                                QMessageBox.warning(self, "Login Failed", translator.tr("msg_epic_invalid_code"))
                    QTimer.singleShot(200, prompt_token)
        else:
            QMessageBox.information(self, "Info", translator.tr("tools_platform_not_impl"))

    def setup_data_tab(self):
        layout = QVBoxLayout(self.tab_data)
        
        # WHY: Force strict vertical alignment for the labels and checkboxes across entirely separate group boxes.
        COL_0_W = 160
        COL_1_W = 140

        # --- GALAXY ---
        grp_galaxy = QGroupBox(translator.tr("settings_data_galaxy_group"))
        layout_galaxy = QGridLayout(grp_galaxy)
        
        self.chk_enable_galaxy = QCheckBox(translator.tr("settings_data_galaxy_checkbox"))
        self.chk_enable_galaxy.setFixedWidth(COL_0_W)
        self.chk_enable_galaxy.toggled.connect(self.toggle_galaxy_input)

        lbl_gal_path = QLabel("")
        lbl_gal_path.setFixedWidth(COL_1_W)

        self.galaxy_db_input = QLineEdit()
        self.galaxy_db_input.textChanged.connect(self.mark_changed)
        default_path = os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')
        self.galaxy_db_input.setText(default_path)
        self.chk_enable_galaxy.toggled.connect(self.mark_changed)
        
        self.btn_browse_galaxy = QPushButton("...")
        self.btn_browse_galaxy.setFixedWidth(40)
        self.btn_browse_galaxy.clicked.connect(self.browse_galaxy_db)
        
        layout_galaxy.addWidget(self.chk_enable_galaxy, 0, 0)
        layout_galaxy.addWidget(lbl_gal_path, 0, 1)
        layout_galaxy.addWidget(self.galaxy_db_input, 0, 2)
        layout_galaxy.addWidget(self.btn_browse_galaxy, 0, 3)
        layout_galaxy.setColumnStretch(2, 1)
        
        layout.addWidget(grp_galaxy)
        
        # --- MEDIA DOWNLOAD ---
        grp_media = QGroupBox(translator.tr("settings_data_media_group"))
        layout_media = QGridLayout(grp_media)
        
        self.chk_download_images = QCheckBox(translator.tr("settings_data_media_download_images"))
        self.chk_download_images.setFixedWidth(COL_0_W)
        self.chk_download_images.toggled.connect(self.mark_changed)
        
        lbl_img_path = QLabel(translator.tr("settings_data_media_images_path"))
        lbl_img_path.setFixedWidth(COL_1_W)
        self.image_path_input = QLineEdit()
        self.image_path_input.textChanged.connect(self.mark_changed)
        self.btn_browse_image = QPushButton("...")
        self.btn_browse_image.setFixedWidth(40)
        self.btn_browse_image.clicked.connect(self.browse_image_path)
        
        layout_media.addWidget(self.chk_download_images, 0, 0)
        layout_media.addWidget(lbl_img_path, 0, 1)
        layout_media.addWidget(self.image_path_input, 0, 2)
        layout_media.addWidget(self.btn_browse_image, 0, 3)
        layout_media.setColumnStretch(2, 1)
        
        layout.addWidget(grp_media)
        
        # --- LOCAL COPIES (MERGED) ---
        # WHY: The "Folder Structure" box was removed to adhere to DRY UI principles, grouping 
        # strictly related variables perfectly under a single aligned grid layout header.
        grp_root = QGroupBox(translator.tr("settings_folders_local_copies_group"))
        
        self.struct_layout = QGridLayout(grp_root)
        
        self.chk_scan_local = QCheckBox(translator.tr("settings_folders_scan_local"))
        self.chk_scan_local.setFixedWidth(COL_0_W)
        self.chk_scan_local.setChecked(False)
        self.chk_scan_local.toggled.connect(self.mark_changed)
        self.chk_scan_local.toggled.connect(self.toggle_local_scan_options)
        
        lbl_root_path = QLabel(translator.tr("settings_folders_main_path"))
        lbl_root_path.setFixedWidth(COL_1_W)
        
        self.root_path_input = QLineEdit("")
        self.root_path_input.textChanged.connect(self.mark_changed)
        # WHY: Trigger smart UI refresh instantly when user modifies the text path manually.
        self.root_path_input.editingFinished.connect(self.on_path_edited)
        
        self.btn_browse_root = QPushButton("...")
        self.btn_browse_root.setFixedWidth(40)
        self.btn_browse_root.clicked.connect(self.browse_root_path)
        
        self.struct_layout.addWidget(self.chk_scan_local, 0, 0)
        self.struct_layout.addWidget(lbl_root_path, 0, 1)
        self.struct_layout.addWidget(self.root_path_input, 0, 2)
        self.struct_layout.addWidget(self.btn_browse_root, 0, 3)
        
        self.chk_ignore_hidden = QCheckBox(translator.tr("settings_folders_ignore_hidden"))
        self.chk_ignore_hidden.toggled.connect(self.mark_changed)
        self.chk_ignore_hidden.toggled.connect(self.update_hidden_folders_visibility)
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
        self.combo_global_type.currentIndexChanged.connect(self.mark_changed)
        
        self.chk_global_filter = QCheckBox(translator.tr("settings_folders_simple_mode_add_filter"))
        self.chk_global_filter.toggled.connect(self.mark_changed)
        
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
        
        # WHY: Quality of Life feature - Clear All instantly wipes the active flags.
        self.btn_clear_all = QPushButton("Clear All")
        self.btn_clear_all.clicked.connect(self.clear_all_folders)
        
        btn_layout.addWidget(self.btn_switch_simple)
        btn_layout.addWidget(self.btn_clear_all)
        btn_layout.addStretch()
        adv_layout.addLayout(btn_layout)
        
        self.struct_layout.addWidget(self.mode_advanced_widget, 3, 0, 1, 4)
        self.struct_layout.setColumnStretch(2, 1)
        layout.addWidget(grp_root, 1)
        
        self.current_folder_rules = {}

    def browse_root_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Root Folder", self.root_path_input.text())
        if dir_path: 
            self.root_path_input.setText(os.path.normpath(dir_path))
            self.on_path_edited()

    def browse_galaxy_db(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Galaxy Database", self.galaxy_db_input.text(), "SQLite DB (*.db);;All Files (*.*)")
        if file_path: self.galaxy_db_input.setText(file_path)

    def browse_image_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Images Folder", self.image_path_input.text())
        if dir_path: self.image_path_input.setText(os.path.normpath(dir_path))

    def toggle_galaxy_input(self, checked):
        self.galaxy_db_input.setEnabled(checked)
        self.btn_browse_galaxy.setEnabled(checked)

    def load_settings(self):
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass

        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass
                
        theme_map = {
            "System": translator.tr("theme_system"),
            "Dark": translator.tr("theme_dark"),
            "Light": translator.tr("theme_light")
        }
        saved_theme_key = global_settings.get("theme", "System")
        self.combo_theme.setCurrentText(theme_map.get(saved_theme_key, translator.tr("theme_system")))
        self.combo_lang.setCurrentText(global_settings.get("language", "English"))
        
        self.combo_date.setCurrentText(global_settings.get("date_format", "DD/MM/YYYY"))
        self.initial_date = global_settings.get("date_format", "DD/MM/YYYY")

        saved_img_size = global_settings.get("card_image_size", DEFAULT_DISPLAY_SETTINGS['image'])
        img_index = self.IMG_SIZES.index(min(self.IMG_SIZES, key=lambda x:abs(x-saved_img_size)))
        self.slider_img_size.setValue(img_index)

        saved_btn_size = global_settings.get("card_button_size", DEFAULT_DISPLAY_SETTINGS['button'])
        btn_index = self.BTN_SIZES.index(min(self.BTN_SIZES, key=lambda x:abs(x-saved_btn_size)))
        self.slider_btn_size.setValue(btn_index)

        saved_txt_size = global_settings.get("card_text_size", DEFAULT_DISPLAY_SETTINGS['text'])
        txt_index = self.TXT_SIZES.index(min(self.TXT_SIZES, key=lambda x:abs(x-saved_txt_size)))
        self.slider_text_size.setValue(txt_index)
        self.update_preview_labels()

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
        self.populate_folders_list(self.current_folder_rules)
        
        self.chk_enable_galaxy.setChecked(lib_settings.get("enable_galaxy_db", False))
        self.galaxy_db_input.setText(lib_settings.get("galaxy_db_path", self.galaxy_db_input.text()))
        self.toggle_galaxy_input(self.chk_enable_galaxy.isChecked())
        
        # WHY: Smart Sync - Read the live RAM state directly from the sidebar UI if it exists, bypassing the slower disk state to prevent desyncs.
        if self.parent_window and hasattr(self.parent_window, 'sidebar'):
            self.chk_download_images.setChecked(self.parent_window.sidebar.chk_scan_dl_images.isChecked())
        else:
            self.chk_download_images.setChecked(lib_settings.get("download_images", True))
            
        default_image_path = os.path.join(BASE_DIR, "images")
        self.image_path_input.setText(lib_settings.get("image_path", default_image_path))
        self.original_image_path = self.image_path_input.text()
        
        # WHY: "Dirty Flags" initialization. We save the starting states of purely cosmetic variables.
        self.initial_theme = global_settings.get("theme", "System")
        self.initial_lang = global_settings.get("language", "English")
        self.initial_img_size = global_settings.get("card_image_size", DEFAULT_DISPLAY_SETTINGS['image'])
        self.initial_btn_size = global_settings.get("card_button_size", DEFAULT_DISPLAY_SETTINGS['button'])
        self.initial_txt_size = global_settings.get("card_text_size", DEFAULT_DISPLAY_SETTINGS['text'])
        self.initial_galaxy = lib_settings.get("enable_galaxy_db", False)
        self.initial_gog_web = lib_settings.get("sidebar_chk_gog_web", False)
        self.initial_local = lib_settings.get("local_scan_config", {}).get("enable_local_scan", False)
        
        # WHY: Disable the apply button after loading state programmatically.
        self.btn_apply.setEnabled(False)

    def save_settings(self):
        global_settings = {}
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    global_settings = json.load(f)
            except: pass
            
        theme_map_rev = {
            translator.tr("theme_system"): "System",
            translator.tr("theme_dark"): "Dark",
            translator.tr("theme_light"): "Light"
        }
        global_settings["theme"] = theme_map_rev.get(self.combo_theme.currentText(), "System")
        global_settings["language"] = self.combo_lang.currentText()
        global_settings["date_format"] = self.combo_date.currentText()
        global_settings["card_image_size"] = self.IMG_SIZES[self.slider_img_size.value()]
        global_settings["card_button_size"] = self.BTN_SIZES[self.slider_btn_size.value()]
        global_settings["card_text_size"] = self.TXT_SIZES[self.slider_text_size.value()]
        
        # WHY: Targeted Cleanup - Scrub local library data out of the global settings file.
        local_keys = ["sort_desc", "sort_index", "search_text", "anchor_folder", "scan_new", "filter_states", "filter_expansion", "sidebar_chk_galaxy", "sidebar_chk_gog_web", "sidebar_chk_epic", "sidebar_chk_local", "platform_map", "ignored_prefixes", "root_path", "local_scan_config", "enable_galaxy_db", "galaxy_db_path", "download_images", "download_videos", "image_path", "video_path"]
        for k in local_keys: global_settings.pop(k, None)
        
        try:
            with open("settings.json", "w", encoding='utf-8') as f:
                json.dump(global_settings, f, indent=4)
        except Exception as e: pass

        lib_settings_file = get_library_settings_file()
        lib_settings = {}
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    lib_settings = json.load(f)
            except: pass

        # WHY: Targeted Cleanup - Scrub global OS data out of the local library settings file.
        global_keys = ["geometry", "theme", "language", "card_image_size", "card_button_size", "card_text_size", "db_path"]
        for k in global_keys: lib_settings.pop(k, None)

        lib_settings["root_path"] = self.root_path_input.text()
        
        self.save_current_folder_rules_state()

        lib_settings["local_scan_config"] = {
            "enable_local_scan": self.chk_scan_local.isChecked(),
            "ignore_hidden": self.chk_ignore_hidden.isChecked(),
            "scan_mode": self.current_scan_mode,
            "global_type": self.combo_global_type.currentText(),
            "global_filter": self.chk_global_filter.isChecked(),
            "folder_rules": self.current_folder_rules
        }
        
        lib_settings["enable_galaxy_db"] = self.chk_enable_galaxy.isChecked()
        lib_settings["galaxy_db_path"] = self.galaxy_db_input.text()
        lib_settings["download_images"] = self.chk_download_images.isChecked()
        
        new_image_path = self.image_path_input.text()
        lib_settings["image_path"] = new_image_path
        
        if new_image_path != self.original_image_path and os.path.exists(self.original_image_path):
            reply = QMessageBox.question(self, "Move Image Files?",
                f"The image folder has changed from:\n{self.original_image_path}\nto:\n{new_image_path}\n\n"
                "Do you want to move existing image files to the new location?\n\n"
                "YES: Moves files to the new location.\n"
                "NO: Does NOT move files (Links may break until you move files manually).",
                QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                self.move_media_files(self.original_image_path, new_image_path, "image")
        self.original_image_path = new_image_path
        
        try:
            with open(lib_settings_file, "w", encoding='utf-8') as f:
                json.dump(lib_settings, f, indent=4)
        except Exception as e: pass

        if self.parent_window and hasattr(self.parent_window, 'display_settings'):
            self.parent_window.display_settings['image'] = self.IMG_SIZES[self.slider_img_size.value()]
            self.parent_window.display_settings['button'] = self.BTN_SIZES[self.slider_btn_size.value()]
            self.parent_window.display_settings['text'] = self.TXT_SIZES[self.slider_text_size.value()]

    def move_media_files(self, old_path, new_path, media_type):
        try:
            os.makedirs(new_path, exist_ok=True)
            files = [f for f in os.listdir(old_path) if os.path.isfile(os.path.join(old_path, f))]
            count = 0
            for f in files:
                src = os.path.join(old_path, f)
                dst = os.path.join(new_path, f)
                shutil.move(src, dst)
                count += 1
            QMessageBox.information(self, "Success", f"Moved {count} files to new {media_type} folder.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to move files: {e}")

    def apply_settings(self):
        # WHY: Input Validation - Prevent saving an invalid state where the local scan engine is enabled but has nowhere to look.
        if self.chk_scan_local.isChecked() and not self.root_path_input.text().strip():
            QMessageBox.warning(self, "Warning", translator.tr("msg_local_path_mandatory"))
            return False
            
        self.save_settings()
        
        # WHY: Smart Refresh logic checking Dirty Flags
        theme_map_rev = {translator.tr("theme_system"): "System", translator.tr("theme_dark"): "Dark", translator.tr("theme_light"): "Light"}
        new_theme = theme_map_rev.get(self.combo_theme.currentText(), "System")
        new_lang = self.combo_lang.currentText()
        new_date = self.combo_date.currentText()
        new_img = self.IMG_SIZES[self.slider_img_size.value()]
        new_btn = self.BTN_SIZES[self.slider_btn_size.value()]
        new_txt = self.TXT_SIZES[self.slider_text_size.value()]
        
        if new_theme != self.initial_theme or new_lang != self.initial_lang or new_date != self.initial_date:
            if self.parent_window and hasattr(self.parent_window, 'reload_global_settings'):
                self.parent_window.reload_global_settings()
                self.initial_theme = new_theme
                self.initial_lang = new_lang
                self.initial_date = new_date
                
        if new_img != self.initial_img_size or new_btn != self.initial_btn_size or new_txt != self.initial_txt_size:
            if self.parent_window and hasattr(self.parent_window, 'list_controller'):
                self.parent_window.list_controller.apply_display_settings(self.parent_window.display_settings)
                self.initial_img_size = new_img
                self.initial_btn_size = new_btn
                self.initial_txt_size = new_txt
                
        new_galaxy = self.chk_enable_galaxy.isChecked()
        new_gog_web = self.parent_window.sidebar.chk_scan_gog_web.isChecked() if self.parent_window else self.initial_gog_web
        new_local = self.chk_scan_local.isChecked()
        
        # WHY: Dynamically push disabled states back to the quick-toggles in the sidebar
        if new_galaxy != self.initial_galaxy or new_local != self.initial_local or new_gog_web != self.initial_gog_web:
            if self.parent_window and hasattr(self.parent_window, 'sidebar'):
                self.parent_window.sidebar.chk_scan_galaxy.setEnabled(new_galaxy)
                if not new_galaxy: self.parent_window.sidebar.chk_scan_galaxy.setChecked(False)
                self.parent_window.sidebar.chk_scan_local.setEnabled(new_local)
                if not new_local: self.parent_window.sidebar.chk_scan_local.setChecked(False)
            self.parent_window.sidebar.update_scan_button_state()
            self.initial_galaxy = new_galaxy
            self.initial_gog_web = new_gog_web
            
        # WHY: Push the dialog's visual state back into the Sidebar's live physical checkbox.
        new_dl_images = self.chk_download_images.isChecked()
        if self.parent_window and hasattr(self.parent_window, 'sidebar'):
            self.parent_window.sidebar.chk_scan_dl_images.setChecked(new_dl_images)
            
        if self.parent_window and hasattr(self.parent_window, 'library_controller'):
            self.parent_window.library_controller.refresh_scan_folders_ui()
            
        # WHY: State successfully committed.
        self.btn_apply.setEnabled(False)
        return True

    def accept(self):
        logging.error("[SETTINGS DIALOG] >>> accept() WAS CALLED! <<<")
        if self.apply_settings():
            super().accept()

    def reject(self):
        logging.error("[SETTINGS DIALOG] >>> reject() WAS CALLED! <<<")
        super().reject()