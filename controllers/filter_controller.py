import os
from PySide6.QtCore import QObject, Qt, Slot, QTimer
from PySide6.QtWidgets import (QPushButton, QCheckBox, QApplication, QSizePolicy, 
                               QAbstractItemView, QVBoxLayout, QHBoxLayout, 
                               QGroupBox, QWidget, QLineEdit, QLabel)
from PySide6.QtGui import QValidator
from widgets import CollapsibleFilterGroup
from ViGaVault_workers import FilterWorker
from ViGaVault_utils import get_library_settings_file, load_encrypted_json, BASE_DIR, translator

class YearRangeValidator(QValidator):
    def __init__(self, min_y, max_y, parent=None):
        super().__init__(parent)
        self.min_y = min_y
        self.max_y = max_y

    def validate(self, text, pos):
        if not text:
            return QValidator.Acceptable, text, pos
            
        import re
        if not re.match(r"^\d{0,4}(?:-\d{0,4})?$", text):
            return QValidator.Invalid, text, pos
            
        parts = text.split("-")
        for p in parts:
            p = p.strip()
            if len(p) == 4:
                val = int(p)
                if val < self.min_y or val > self.max_y:
                    return QValidator.Invalid, text, pos
                    
        return QValidator.Acceptable, text, pos

class FilterController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.dynamic_filters = {}
        self.filter_buttons = {}
        self.filter_groups = {}
        self.filter_groups = {}

    def populate_dynamic_filters(self, saved_state=None, saved_expansion=None):
        self.current_cols = 0
        layout = self.mw.sidebar.filters_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        self.dynamic_filters = {}
        self.filter_buttons = {}

        local_config = {}
        rules = {}
        
        lib_settings_file = get_library_settings_file()
        local_config = load_encrypted_json(lib_settings_file).get("local_scan_config", {})
        if not local_config:
            local_config = load_encrypted_json(os.path.join(BASE_DIR, "settings.bin")).get("local_scan_config", {})
            
        scan_mode = local_config.get("scan_mode", "advanced")
        rules = local_config.get("folder_rules", {})

        active_types = set()
        if scan_mode == "advanced":
            for folder, rule in rules.items():
                if rule.get("filter", False): active_types.add(rule.get("type"))
        else:
            if local_config.get("global_filter", False):
                g_type = local_config.get("global_type", "Genre")
                if "Direct" not in g_type and "None" not in g_type: active_types.add(g_type)
        
        type_map = {"Genre": "Genre", "Collection": "Collection", "Publisher": "Publisher", "Developer": "Developer", "Year": "Year_Folder"}
        
        # WHY: Dynamic Filter Auto-Discovery - Always display metadata filters if the loaded database has any non-empty values for that column.
        # This prevents GOG/Steam/Epic/Amazon genres and collections from being hidden if the local scanner rules are not set.
        db_has_data = {}
        if hasattr(self.mw, 'master_df') and not self.mw.master_df.empty:
            for type_name, col_name in type_map.items():
                if col_name in self.mw.master_df.columns:
                    has_val = self.mw.master_df[col_name].dropna().astype(str).str.strip().ne("").any()
                    if has_val:
                        db_has_data[type_name] = True

        # First, add the Year filter at the absolute top of the filters layout if it's active or discovered in DB
        show_year = ("Year" in active_types) or db_has_data.get("Year", False)
        if show_year:
            from datetime import datetime
            years = []
            col_name = "Year_Folder"
            if hasattr(self.mw, 'master_df') and not self.mw.master_df.empty and col_name in self.mw.master_df.columns:
                for y in self.mw.master_df[col_name].dropna().unique():
                    y_str = str(y).strip()
                    if y_str.isdigit() and len(y_str) == 4:
                        years.append(int(y_str))
            min_y = min(years) if years else 1970
            max_y = max(years) if years else datetime.now().year
            
            
            group = QGroupBox()
            group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(0)
            
            header_widget = QWidget()
            header_widget.setObjectName("header_container")
            header_widget.setStyleSheet("""
                #header_container { background-color: palette(button); border-radius: 4px; }
            """)
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(0, 0, 4, 0)
            header_layout.setSpacing(6)
            
            lbl_year = QLabel("Year :")
            lbl_year.setStyleSheet("""
                font-weight: bold; 
                font-size: 12px; 
                color: palette(button-text); 
                background: transparent; 
                padding: 5px; 
                border: none;
            """)
            
            txt_year = QLineEdit()
            txt_year.setPlaceholderText(f"e.g. {min_y} or {min_y}-{max_y}")
            txt_year.setValidator(YearRangeValidator(min_y, max_y, txt_year))
            txt_year.returnPressed.connect(self.request_filter_update)
            txt_year.setFixedWidth(140)
            txt_year.setStyleSheet("""
                QLineEdit {
                    background-color: palette(base);
                    color: palette(text);
                    border: 1px solid palette(dark);
                    border-radius: 3px;
                    padding: 2px 5px;
                }
            """)
            
            btn_all = QPushButton(translator.tr("sidebar_btn_all"))
            btn_none = QPushButton(translator.tr("sidebar_btn_none"))
            btn_style = "QPushButton { padding: 2px 5px; font-size: 11px; margin: 2px; border: 1px solid palette(dark); border-radius: 3px; background-color: palette(button); }"
            btn_all.setStyleSheet(btn_style)
            btn_none.setStyleSheet(btn_style)
            btn_all.setCursor(Qt.PointingHandCursor)
            btn_none.setCursor(Qt.PointingHandCursor)
            
            btn_all.setEnabled(False)
            btn_none.setEnabled(True)
            txt_year.textChanged.connect(lambda text: btn_all.setEnabled(bool(text.strip())))
            
            btn_all.clicked.connect(lambda: self.set_filter_group_state(col_name, True))
            btn_none.clicked.connect(lambda: self.set_filter_group_state(col_name, False))
            
            header_layout.addWidget(lbl_year)
            header_layout.addWidget(txt_year)
            header_layout.addStretch(1)
            header_layout.addWidget(btn_all)
            header_layout.addWidget(btn_none)
            
            group_layout.addWidget(header_widget)
            self.mw.sidebar.filters_layout.addWidget(group)
            
            self.dynamic_filters[col_name] = txt_year
            self.filter_buttons[col_name] = (btn_all, btn_none)

        is_expanded = saved_expansion.get("Platforms", False) if saved_expansion else False
        self.add_filter_group("Platforms", "Platforms", self.mw.sidebar.filters_layout, is_expanded)

        for type_name, col_name in type_map.items():
            if type_name == "Year":
                continue
            if type_name in active_types or db_has_data.get(type_name, False):
                is_expanded = saved_expansion.get(type_name, False) if saved_expansion else False
                self.add_filter_group(type_name, col_name, self.mw.sidebar.filters_layout, is_expanded)
        
        self.mw.sidebar.filters_layout.addStretch(0)

        if saved_state is not None:
            for col, item in self.dynamic_filters.items():
                if col in saved_state:
                    if col == "Year_Folder":
                        if isinstance(item, QLineEdit):
                            vals = saved_state.get(col, [])
                            if vals:
                                item.setText(vals[0])
                    else:
                        for chk in item:
                            chk.setChecked(chk.text() in saved_state.get(col, []))
                            
        self.reflow_filters()

    def add_filter_group(self, title, col_name, parent_layout, is_expanded=False):
        group = CollapsibleFilterGroup(title, parent_layout)
        group.checkbox_layout.setColumnStretch(0, 1)
        group.checkbox_layout.setColumnStretch(1, 1)
        self.filter_groups[col_name] = group
        
        if title in ["Platforms", "Genre", "Collection", "Publisher", "Developer"]:
            group.btn_all.show()
            group.btn_none.show()
            group.btn_all.clicked.connect(lambda: self.set_filter_group_state(col_name, True))
            group.btn_none.clicked.connect(lambda: self.set_filter_group_state(col_name, False))
            self.filter_buttons[col_name] = (group.btn_all, group.btn_none)
        
        values = set()
        if hasattr(self.mw, 'master_df') and not self.mw.master_df.empty and col_name in self.mw.master_df.columns:
            for val_list in self.mw.master_df[col_name].dropna().unique():
                for val in str(val_list).split(','):
                    v = val.strip()
                    if v: values.add(v)
        
        checkboxes = []
        row, col = 0, 0
        for val in sorted(list(values), key=lambda x: x.lower()):
            chk = QCheckBox(val)
            chk.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            chk.setChecked(True)
            chk.stateChanged.connect(lambda state, c=col_name: self.update_filter_buttons(c))
            chk.stateChanged.connect(self.request_filter_update)
            group.checkbox_layout.addWidget(chk, row, col)
            checkboxes.append(chk)
            col += 1
            if col > 1:
                col = 0
                row += 1
        
        self.dynamic_filters[col_name] = checkboxes
        self.update_filter_buttons(col_name)
            
        parent_layout.addWidget(group)
        if is_expanded: group.toggle_btn.setChecked(True)

    def reflow_filters(self):
        """WHY: Single Responsibility Principle - Repacks checkboxes into dynamically calculated columns based on available UI space."""
        if not hasattr(self.mw, 'sidebar') or not hasattr(self.mw.sidebar, 'filters_container'): return
        width = self.mw.sidebar.filters_container.width()
        
        # WHY: Calculate optimal columns based on 140px minimum comfortable width per checkbox. Min 2, Max 4.
        cols = max(2, min(4, width // 140))
        if getattr(self, 'current_cols', 0) == cols: return
        self.current_cols = cols
        
        for col_name, group in self.filter_groups.items():
            if col_name == "Year_Folder": continue
            checkboxes = self.dynamic_filters.get(col_name, [])
            if not checkboxes: continue
            
            # WHY: Cleanly hide the widgets when taking them out of the layout to prevent 
            # floating or overlapping artifacts from remaining visible.
            while group.checkbox_layout.count():
                item = group.checkbox_layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                
            # WHY: Dynamically adjust the column stretches so each active column takes up exactly 
            # equal width (e.g. 50% each for 2 columns, 33.3% each for 3 columns, etc.).
            # This prevents columns beyond index 1 from being squeezed to 0 width.
            for c in range(4):
                if c < cols:
                    group.checkbox_layout.setColumnStretch(c, 1)
                else:
                    group.checkbox_layout.setColumnStretch(c, 0)
                
            row, col = 0, 0
            for chk in checkboxes:
                group.checkbox_layout.addWidget(chk, row, col)
                chk.show()
                col = 0 if col + 1 >= cols else col + 1
                if col == 0: row += 1
                
            # WHY: Recalculate and update the maximum height of the group box so the scroll 
            # area adapts perfectly to the new height.
            if group.toggle_btn.isChecked():
                group.toggle_content(True)

    def set_filter_group_state(self, col_name, state):
        if col_name in self.dynamic_filters:
            if col_name == "Year_Folder":
                item = self.dynamic_filters[col_name]
                if isinstance(item, QLineEdit):
                    item.clear()
            else:
                for chk in self.dynamic_filters[col_name]:
                    chk.blockSignals(True)
                    chk.setChecked(state)
                    chk.blockSignals(False)
                    self.update_filter_buttons(col_name)
            self.request_filter_update()

    def update_filter_buttons(self, col_name):
        if col_name in self.filter_buttons:
            btn_all, btn_none = self.filter_buttons[col_name]
            checkboxes = self.dynamic_filters.get(col_name, [])
            if not checkboxes: return
            btn_all.setEnabled(not all(chk.isChecked() for chk in checkboxes))
            btn_none.setEnabled(not (not any(chk.isChecked() for chk in checkboxes)))

    def set_filters_ui_state(self, enabled):
        layout = self.mw.sidebar.filters_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), CollapsibleFilterGroup):
                item.widget().setEnabled(enabled)
                if not enabled: item.widget().toggle_btn.setChecked(False)

        if not enabled:
            self.mw.sidebar.layout.setStretchFactor(self.mw.sidebar.top_layout, 0)
            self.mw.sidebar.layout.setStretchFactor(self.mw.sidebar.scan_panel, 1)
        else:
            self.mw.sidebar.layout.setStretchFactor(self.mw.sidebar.top_layout, 1)
            self.mw.sidebar.layout.setStretchFactor(self.mw.sidebar.scan_panel, 0)

    def toggle_sort_order(self):
        self.mw.sort_desc = not self.mw.sort_desc
        self.mw.sidebar.update_sort_button(self.mw.sort_desc)
        self.request_filter_update()

    def request_filter_update(self):
        self.mw.filter_timer.start()

    def start_filter_worker(self):
        if not hasattr(self.mw, 'master_df'): return

        self._prev_focus_widget = QApplication.focusWidget()

        self.mw.sidebar.setEnabled(False)
        self.mw.list_widget.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Update combo box counts
        if hasattr(self.mw.sidebar, 'combo_view_mode'):
            self.mw.sidebar.combo_view_mode.blockSignals(True)
            self.mw.sidebar.update_view_mode_counts()
            self.mw.sidebar.combo_view_mode.blockSignals(False)

        # WHY: Removed Developer. Mapped the 3rd dropdown option to the internal CSV index tracker.
        sort_col_map = ["temp_sort_title", "temp_sort_date", "temp_sort_index"]
        
        active_filters = {}
        for col, item in self.dynamic_filters.items():
            if col == "Year_Folder":
                if isinstance(item, QLineEdit):
                    txt = item.text().strip()
                    if txt:
                        active_filters[col] = [txt]
            else:
                if item and not all(chk.isChecked() for chk in item):
                    active_filters[col] = [chk.text() for chk in item if chk.isChecked()]

        # WHY: Safety Guard - Truncate excessively long search strings to prevent the regex engine from crashing on malformed text.
        search_text = self.mw.sidebar.search_bar.text()
        if len(search_text) > 80:
            search_text = search_text[:80]

        combo = getattr(self.mw.sidebar, 'combo_view_mode', None)
        idx = combo.currentIndex() if combo else 0

        params = {
            'search_target': getattr(self.mw.sidebar, 'search_target', 'Name'),
            'search_text': search_text,
            'active_filters': active_filters,
            'sort_col': sort_col_map[self.mw.sidebar.combo_sort.currentIndex()],
            'sort_desc': self.mw.sort_desc,
            'scan_new': idx == 3,
            'scan_dlc': idx == 4,
            'scan_no_img': idx == 1,
            'scan_no_trl': idx == 2,
        }

        self.filter_worker = FilterWorker(self.mw.master_df, params)
        self.filter_worker.finished.connect(self.on_filtering_finished)
        self.filter_worker.start()

    @Slot(object)
    def on_filtering_finished(self, filtered_df):
            
        self.mw.current_df = filtered_df
        
        # WHY: Smart Refresh - Calculates total valid games purely by mathematically ignoring DLCs and Exclusions, perfectly hiding them from the counter.
        valid_games_mask = ~self.mw.master_df['Is_DLC'] & ~self.mw.master_df['Is_Excluded']
        valid_total = valid_games_mask.sum()
        self.mw.sidebar.lbl_counter.setText(f"{len(filtered_df)}/{valid_total}")

        if hasattr(self.mw, 'pending_anchor_folder') and self.mw.pending_anchor_folder:
            anchor_folder = self.mw.pending_anchor_folder
            self.mw.pending_anchor_folder = None
        else:
            # WHY: DRY Principle - Defer to the central library controller to securely fetch the layout anchor.
            anchor_folder = self.mw.library_controller.get_second_visible_folder()
            if not anchor_folder and self.mw.list_widget.currentIndex().isValid():
                anchor_folder = self.mw.list_widget.model().data(self.mw.list_widget.currentIndex(), Qt.UserRole + 1)
                
        self.mw.loaded_count = 0

        self.mw.list_controller.load_more_items()
        
        if anchor_folder:
            folders_list = self.mw.current_df['Folder_Name'].tolist()
            if anchor_folder in folders_list:
                row_index = folders_list.index(anchor_folder)
                # WHY: Delegate the slow, blocking load to an asynchronous, non-blocking timer in the ListController.
                # This allows the UI to render instantly and then catch up to the anchor smoothly.
                self.mw.list_controller.catch_up_to_anchor(row_index)

        self.mw.background_loader.start()
        QApplication.restoreOverrideCursor()

        if self.mw.is_startup: self.mw.is_startup = False
            
        self.mw.sidebar.setEnabled(True)
        self.mw.list_widget.setEnabled(True)

        if hasattr(self, '_prev_focus_widget') and self._prev_focus_widget:
            try:
                self._prev_focus_widget.setFocus()
            except: pass
            self._prev_focus_widget = None