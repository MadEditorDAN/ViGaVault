import os
import json
from PySide6.QtCore import QObject, Qt, Slot, QTimer
from PySide6.QtWidgets import QPushButton, QCheckBox, QApplication, QSizePolicy, QAbstractItemView
from ViGaVault_widgets import CollapsibleFilterGroup
from ViGaVault_workers import FilterWorker
from ViGaVault_utils import get_library_settings_file

class FilterController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.dynamic_filters = {}
        self.filter_buttons = {}

    def populate_dynamic_filters(self, saved_state=None, saved_expansion=None):
        layout = self.mw.sidebar.filters_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        self.dynamic_filters = {}
        self.filter_buttons = {}

        local_config = {}
        rules = {}
        
        lib_settings_file = get_library_settings_file()
        if os.path.exists(lib_settings_file):
            try:
                with open(lib_settings_file, "r", encoding='utf-8') as f:
                    local_config = json.load(f).get("local_scan_config", {})
            except: pass
        elif os.path.exists("settings.json"):
            try:
                with open("settings.json", "r", encoding='utf-8') as f:
                    local_config = json.load(f).get("local_scan_config", {})
            except: pass
            
        scan_mode = local_config.get("scan_mode", "advanced")
        rules = local_config.get("folder_rules", {})

        is_expanded = saved_expansion.get("Platforms", False) if saved_expansion else False
        self.add_filter_group("Platforms", "Platforms", self.mw.sidebar.filters_layout, is_expanded)

        active_types = set()
        if scan_mode == "advanced":
            for folder, rule in rules.items():
                if rule.get("filter", False): active_types.add(rule.get("type"))
        else:
            if local_config.get("global_filter", False):
                g_type = local_config.get("global_type", "Genre")
                if "Direct" not in g_type and "None" not in g_type: active_types.add(g_type)
        
        type_map = {"Genre": "Genre", "Collection": "Collection", "Publisher": "Publisher", "Developer": "Developer", "Year": "Year_Folder"}
        for type_name, col_name in type_map.items():
            if type_name in active_types:
                is_expanded = saved_expansion.get(type_name, False) if saved_expansion else False
                self.add_filter_group(type_name, col_name, self.mw.sidebar.filters_layout, is_expanded)
        
        self.mw.sidebar.filters_layout.addStretch(0)

        if saved_state is not None:
            for col, checkboxes in self.dynamic_filters.items():
                if col in saved_state:
                    for chk in checkboxes: chk.setChecked(chk.text() in saved_state.get(col, []))

    def add_filter_group(self, title, col_name, parent_layout, is_expanded=False):
        group = CollapsibleFilterGroup(title, parent_layout)
        group.checkbox_layout.setColumnStretch(0, 1)
        group.checkbox_layout.setColumnStretch(1, 1)
        
        if title in ["Platforms", "Genre", "Collection"]:
            btn_all = QPushButton("All")
            btn_none = QPushButton("None")
            btn_all.clicked.connect(lambda: self.set_filter_group_state(col_name, True))
            btn_none.clicked.connect(lambda: self.set_filter_group_state(col_name, False))
            group.btns_layout.addWidget(btn_all)
            group.btns_layout.addWidget(btn_none)
            self.filter_buttons[col_name] = (btn_all, btn_none)
        
        values = set()
        if hasattr(self.mw, 'master_df') and not self.mw.master_df.empty and col_name in self.mw.master_df.columns:
            for val_list in self.mw.master_df[col_name].dropna().unique():
                for val in str(val_list).split(','):
                    v = val.strip()
                    if v: values.add(v)
        
        checkboxes = []
        row, col = 0, 0
        for val in sorted(list(values)):
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

    def set_filter_group_state(self, col_name, state):
        if col_name in self.dynamic_filters:
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

        self.mw.sidebar.setEnabled(False)
        self.mw.list_widget.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # WHY: Removed Developer. Mapped the 3rd dropdown option to the internal CSV index tracker.
        sort_col_map = ["temp_sort_title", "temp_sort_date", "temp_sort_index"]
        
        active_filters = {}
        for col, checkboxes in self.dynamic_filters.items():
            if checkboxes and not all(chk.isChecked() for chk in checkboxes):
                active_filters[col] = [chk.text() for chk in checkboxes if chk.isChecked()]

        params = {
            'search_target': getattr(self.mw.sidebar, 'search_target', 'Name'),
            'search_text': self.mw.sidebar.search_bar.text(),
            'active_filters': active_filters,
            'sort_col': sort_col_map[self.mw.sidebar.combo_sort.currentIndex()],
            'sort_desc': self.mw.sort_desc,
            'scan_new': self.mw.sidebar.chk_show_new.isChecked(),
        }

        self.filter_worker = FilterWorker(self.mw.master_df, params)
        self.filter_worker.finished.connect(self.on_filtering_finished)
        self.filter_worker.start()

    @Slot(object)
    def on_filtering_finished(self, filtered_df):
            
        self.mw.current_df = filtered_df
        self.mw.sidebar.lbl_counter.setText(f"{len(filtered_df)}/{len(self.mw.master_df)}")

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
        self.mw.sidebar.search_bar.setFocus()