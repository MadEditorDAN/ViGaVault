# WHY: Single Responsibility Principle - Strictly handles the layout and logic of the right-hand control panel.
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
                             QPushButton, QFrame, QSizePolicy, QCheckBox, 
                             QLineEdit, QComboBox, QListWidget, QToolButton, QMenu, QGroupBox)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QFontMetrics

from ViGaVault_utils import translator
from .custom_inputs import CollapsibleFilterGroup

# The right-hand sidebar containing Counters, Search, Sort, Filters, and the Scan Panel.
class Sidebar(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        # WHY: Removed FixedWidth to allow resizing. Set minimum to ~1/5 of an 800px window.
        self.setMinimumWidth(280)
        # WHY: Decouple the Sidebar's internal vertical math from the Main Window. 
        # This acts as a circuit breaker, preventing Qt from aggressively locking the window's minimum height based on hidden panel elements.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # --- TOP CONTAINER (Search, Sort, Filters) ---
        self.top_layout = QVBoxLayout()
        self.top_layout.setSpacing(10) # Aération entre les cadres

        font_lbl = QFont()
        font_lbl.setBold(True)
        font_lbl.setPixelSize(16)
        
        # Style commun pour les cadres (bordure visible + fond légèrement différent)
        self.frame_style = """
            QFrame#sidebar_frame {
                border: 1px solid palette(mid);
                border-radius: 6px;
                background-color: palette(alternate-base);
            }
        """

        # 1. Cadre 1: Compteurs et Nom de la librairie
        self.frame_counters = QFrame()
        self.frame_counters.setObjectName("sidebar_frame")
        self.frame_counters.setStyleSheet(self.frame_style)
        counters_layout = QHBoxLayout(self.frame_counters)
        counters_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_counter = QLabel("0/0")
        self.lbl_counter.setFont(QFont(font_lbl.family(), 20, QFont.Bold))
        counters_layout.addWidget(self.lbl_counter)
        
        counters_layout.addStretch()

        self.lbl_lib_name = QLabel("")
        self.lbl_lib_name.setFont(QFont(font_lbl.family(), 20, QFont.Bold))
        self.lbl_lib_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        counters_layout.addWidget(self.lbl_lib_name)
        
        self.top_layout.addWidget(self.frame_counters)
        
        # 2. Cadre 2: Recherche
        self.frame_search = QFrame()
        self.frame_search.setObjectName("sidebar_frame")
        self.frame_search.setStyleSheet(self.frame_style)
        search_layout = QHBoxLayout(self.frame_search)
        search_layout.setContentsMargins(8, 8, 8, 8)

        lbl_search = QLabel(translator.tr("sidebar_search_label"))
        lbl_search.setObjectName("sidebar_search_label")
        lbl_search.setFont(font_lbl)
        search_layout.addWidget(lbl_search)

        self.search_bar = QLineEdit()
        
        # WHY: "Name" is hardcoded as the default target so there is no state persistence across app restarts.
        self.search_target = "Name"
        self.search_ph_key = "search_ph_name"
        self.search_bar.setPlaceholderText(translator.tr(self.search_ph_key))
        self.search_bar.setClearButtonEnabled(True)
        search_layout.addWidget(self.search_bar, 1) # Stretch 1 pour prendre l'espace disponible
        
        self.search_btn = QToolButton()
        self.search_btn.setText("▼")
        self.search_btn.setPopupMode(QToolButton.InstantPopup)
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setStyleSheet("QToolButton { border: none; padding: 2px 5px; } QToolButton::menu-indicator { image: none; }")
        
        self.search_menu = QMenu(self.search_btn)
        self.act_search_name = self.search_menu.addAction(translator.tr("search_target_name"))
        self.act_search_dev = self.search_menu.addAction(translator.tr("search_target_developer"))
        self.act_search_pub = self.search_menu.addAction(translator.tr("search_target_publisher"))
        self.act_search_sum = self.search_menu.addAction(translator.tr("search_target_summary"))
        self.search_btn.setMenu(self.search_menu)
        
        # WHY: Appending the invisible tool button natively inside the search frame creates the illusion of a composite widget.
        search_layout.addWidget(self.search_btn)
        
        self.top_layout.addWidget(self.frame_search)
        
        # 3. Cadre 3: Tri
        self.frame_sort = QFrame()
        self.frame_sort.setObjectName("sidebar_frame")
        self.frame_sort.setStyleSheet(self.frame_style)
        sort_layout = QHBoxLayout(self.frame_sort)
        sort_layout.setContentsMargins(8, 8, 8, 8)

        lbl_sort = QLabel(translator.tr("sidebar_sort_label"))
        lbl_sort.setObjectName("sidebar_sort_label")
        lbl_sort.setFont(font_lbl)
        sort_layout.addWidget(lbl_sort)

        self.combo_sort = QComboBox()
        self.combo_sort.addItems([
            translator.tr("sidebar_sort_name"), 
            translator.tr("sidebar_sort_release_date"), 
            translator.tr("sidebar_sort_date_added")
        ])
        sort_layout.addWidget(self.combo_sort, 1) # Stretch 1 pour prendre l'espace disponible
        
        self.btn_toggle_sort = QPushButton()
        self.btn_toggle_sort.setFixedWidth(50)
        self.update_sort_button(self.parent.sort_desc)
        sort_layout.addWidget(self.btn_toggle_sort)
        
        self.top_layout.addWidget(self.frame_sort)

        # 4. Cadre 4: Filtres
        self.frame_filters = QFrame()
        self.frame_filters.setObjectName("sidebar_frame")
        self.frame_filters.setStyleSheet(self.frame_style)
        filters_frame_layout = QVBoxLayout(self.frame_filters)
        filters_frame_layout.setContentsMargins(8, 8, 8, 8)

        # WHY: Grouping Filters label and Show NEW checkbox in the same horizontal line.
        filters_header_layout = QHBoxLayout()
        lbl_filters = QLabel(translator.tr("sidebar_filters_label"))
        lbl_filters.setObjectName("sidebar_filters_label")
        lbl_filters.setFont(font_lbl)
        filters_header_layout.addWidget(lbl_filters)

        # WHY: Add a stretch spacer to push the "Show NEW" checkbox to the far right edge of the layout.
        filters_header_layout.addStretch()

        # WHY: Add a 'Show :' label to clearly define the purpose of the adjacent filter toggles.
        self.lbl_show = QLabel(translator.tr("sidebar_lbl_show"))
        self.lbl_show.setObjectName("sidebar_lbl_show")
        filters_header_layout.addWidget(self.lbl_show)

        # --- MUTUAL EXCLUSIVE VIEW TOGGLES ---
        self.btn_toggle_new = QPushButton(translator.tr("sidebar_btn_toggle_new"))
        self.btn_toggle_dlc = QPushButton(translator.tr("sidebar_btn_toggle_dlc"))
        self.btn_toggle_review = QPushButton(translator.tr("sidebar_btn_toggle_review"))
        
        toggle_style = """
            QPushButton { padding: 4px 8px; border: 1px solid palette(dark); border-radius: 4px; background-color: palette(button); }
            QPushButton:checked { background-color: palette(highlight); color: palette(highlighted-text); font-weight: bold; }
        """
        
        for btn in [self.btn_toggle_new, self.btn_toggle_dlc, self.btn_toggle_review]:
            btn.setCheckable(True)
            btn.setStyleSheet(toggle_style)
            btn.setCursor(Qt.PointingHandCursor)
            filters_header_layout.addWidget(btn)
            
        # WHY: Handled manually instead of QButtonGroup so the user can easily un-toggle everything to revert to the default safe view.
        self.btn_toggle_new.toggled.connect(lambda checked: self.handle_view_toggle(self.btn_toggle_new, checked))
        self.btn_toggle_dlc.toggled.connect(lambda checked: self.handle_view_toggle(self.btn_toggle_dlc, checked))
        self.btn_toggle_review.toggled.connect(lambda checked: self.handle_view_toggle(self.btn_toggle_review, checked))

        self.btn_approve_review = QPushButton(translator.tr("sidebar_btn_approve_review"))
        self.btn_approve_review.setStyleSheet("padding: 4px 8px; font-weight: bold; border: 1px solid palette(dark); border-radius: 4px; background-color: palette(button);")
        self.btn_approve_review.setCursor(Qt.PointingHandCursor)
        filters_header_layout.addWidget(self.btn_approve_review)

        filters_frame_layout.addLayout(filters_header_layout)

        # We remove the outer scroll area to let individual groups handle their scrolling/sizing
        self.filters_container = QWidget()
        self.filters_layout = QVBoxLayout(self.filters_container)
        self.filters_layout.setContentsMargins(0, 0, 0, 0)
        
        filters_frame_layout.addWidget(self.filters_container, 1)
        
        self.top_layout.addWidget(self.frame_filters, 1) # Give it stretch to take available space
        self.layout.addLayout(self.top_layout, 1) # Give top part stretch priority

        # --- SCAN PANEL (Manual Scan / Full Scan Logs) ---
        # Hidden by default, shown when scanning starts
        self.scan_panel = QWidget()
        self.scan_layout = QVBoxLayout(self.scan_panel)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken) # Uses QPalette.Shadow, customized for dark mode
        self.scan_layout.addWidget(line)
        
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText(translator.tr("sidebar_manual_scan_placeholder"))

        scan_action_layout = QHBoxLayout()
        self.scan_btn = QPushButton(translator.tr("sidebar_manual_scan_search_btn"))
        scan_action_layout.addWidget(self.scan_btn, 3)

        self.scan_limit_combo = QComboBox()
        self.scan_limit_combo.addItems(['10', '20', '30', '40', '50'])
        self.scan_limit_combo.setCurrentText('10')
        scan_action_layout.addWidget(self.scan_limit_combo, 1)

        self.scan_results = QListWidget()
        self.scan_results.setIconSize(QSize(50, 70))
        # WHY: Force a monospace font and smaller text size to guarantee perfect vertical ASCII alignment for the new tabular logs.
        self.scan_results.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 11px;")

        self.btns_layout = QHBoxLayout()
        self.btn_confirm = QPushButton(translator.tr("sidebar_manual_scan_confirm_btn"))
        self.btn_cancel = QPushButton(translator.tr("sidebar_manual_scan_cancel_btn"))
        self.btns_layout.addWidget(self.btn_confirm)
        self.btns_layout.addWidget(self.btn_cancel)
        
        self.scan_title_label = QLabel(translator.tr("sidebar_manual_scan_title"))
        self.scan_layout.addWidget(self.scan_title_label)
        self.scan_layout.addWidget(self.scan_input)
        self.scan_layout.addLayout(scan_action_layout)
        self.scan_layout.addWidget(self.scan_results)
        self.scan_layout.addLayout(self.btns_layout)

        # --- SCAN SETTINGS PANEL ---
        self.scan_settings_panel = QWidget()
        self.scan_settings_layout = QVBoxLayout(self.scan_settings_panel)
        
        line_ss = QFrame()
        line_ss.setFrameShape(QFrame.HLine)
        line_ss.setFrameShadow(QFrame.Sunken)
        self.scan_settings_layout.addWidget(line_ss)

        self.lbl_scan_settings_title = QLabel(translator.tr("scan_settings_title"))
        self.lbl_scan_settings_title.setObjectName("scan_settings_title_lbl")
        self.lbl_scan_settings_title.setFont(font_lbl)
        self.scan_settings_layout.addWidget(self.lbl_scan_settings_title)

        self.grp_scan_platforms = QGroupBox(translator.tr("scan_settings_platforms"))
        self.layout_scan_platforms = QGridLayout(self.grp_scan_platforms)
        
        self.chk_scan_galaxy = QCheckBox("Galaxy")
        self.chk_scan_gog_web = QCheckBox("GOG.com")
        # WHY: Renamed strictly to "Epic" to align with the visual consistency of the other short-named platforms.
        self.chk_scan_epic = QCheckBox("Epic")
        self.chk_scan_steam = QCheckBox("Steam")
        
        self.layout_scan_platforms.addWidget(self.chk_scan_galaxy, 0, 0)
        self.layout_scan_platforms.addWidget(self.chk_scan_gog_web, 0, 1)
        self.layout_scan_platforms.addWidget(self.chk_scan_epic, 1, 0)
        self.layout_scan_platforms.addWidget(self.chk_scan_steam, 1, 1)

        # WHY: Inject placeholders for all upcoming platforms in a clean 2-column grid.
        dummies = ["Amazon", "Uplay", "Battle.net", "Origin", "Itch", "Xbox", "PSN"]
        r, c = 2, 0
        for d in dummies:
            chk = QCheckBox(d)
            chk.setEnabled(False)
            self.layout_scan_platforms.addWidget(chk, r, c)
            c += 1
            if c > 1:
                c = 0
                r += 1

        self.scan_settings_layout.addWidget(self.grp_scan_platforms)

        self.grp_scan_local = QGroupBox(translator.tr("scan_settings_local"))
        self.layout_scan_local = QGridLayout(self.grp_scan_local)
        # WHY: Force the grid layout to pack tightly against the top instead of centering its rows in available space.
        self.layout_scan_local.setAlignment(Qt.AlignTop)
        self.chk_scan_local = QCheckBox("Local Copy")
        # WHY: Make the master checkbox span across both columns so it acts as a header.
        self.layout_scan_local.addWidget(self.chk_scan_local, 0, 0, 1, 2)

        self.chk_scan_folders = {} # Stores references to dynamic checkboxes
        
        # WHY: Flat hierarchy. Toggle child checkboxes directly instead of hiding a middle-man container.
        self.chk_scan_local.toggled.connect(lambda state: [chk.setEnabled(state) for chk in self.chk_scan_folders.values()])

        # WHY: Add the group box without stretch, and append a stretch below it to push the groups to the top.
        self.scan_settings_layout.addWidget(self.grp_scan_local)
        
        # --- SCAN OPTIONS SECTION ---
        self.grp_scan_options = QGroupBox(translator.tr("scan_settings_options"))
        self.layout_scan_options = QGridLayout(self.grp_scan_options)
        self.layout_scan_options.setAlignment(Qt.AlignTop)
        
        self.chk_scan_dl_images = QCheckBox(translator.tr("settings_data_media_download_images"))
        self.layout_scan_options.addWidget(self.chk_scan_dl_images, 0, 0)
        
        self.scan_settings_layout.addWidget(self.grp_scan_options)
        self.scan_settings_layout.addStretch()
        
        self.btn_close_scan_settings = QPushButton(translator.tr("btn_close"))
        self.scan_settings_layout.addWidget(self.btn_close_scan_settings)

        # --- BOTTOM CONTAINER (Scan Buttons) ---
        self.frame_bottom = QFrame()
        self.frame_bottom.setObjectName("sidebar_frame")
        self.frame_bottom.setStyleSheet(self.frame_style)
        self.bottom_layout = QHBoxLayout(self.frame_bottom)
        self.bottom_layout.setContentsMargins(8, 8, 8, 8)

        self.btn_scan_settings = QPushButton(translator.tr("sidebar_btn_scan_settings"))
        self.btn_scan_settings.setMinimumHeight(80)
        font_scan_set = QFont()
        font_scan_set.setBold(True)
        font_scan_set.setPointSize(12)
        self.btn_scan_settings.setFont(font_scan_set)

        # --- FULL SCAN BUTTON ---
        self.btn_full_scan = QPushButton(translator.tr("sidebar_btn_full_scan"))
        self.btn_full_scan.setMinimumHeight(80) # WHY: Taller button to accommodate the 3 checkboxes visually
        font_scan = QFont()
        font_scan.setBold(True)
        font_scan.setPointSize(16)
        self.btn_full_scan.setFont(font_scan)
        
        # WHY: Requested horizontal ratio: Scan on the left (2/3), Settings on the right (1/3).
        self.bottom_layout.addWidget(self.btn_full_scan, 2)
        self.bottom_layout.addWidget(self.btn_scan_settings, 1)

        self.layout.addWidget(self.scan_panel)
        self.scan_panel.hide()
        self.layout.addWidget(self.scan_settings_panel)
        self.scan_settings_panel.hide()
        self.layout.addWidget(self.frame_bottom)
        
        # --- CONNECTIONS ---
        self.search_bar.textChanged.connect(self.parent.request_filter_update)
        self.combo_sort.currentIndexChanged.connect(self.parent.request_filter_update)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        self.btn_full_scan.clicked.connect(self.parent.start_full_scan)
        self.btn_approve_review.clicked.connect(self.parent.approve_reviews)
        self.btn_scan_settings.clicked.connect(self.parent.open_scan_settings)
        self.btn_close_scan_settings.clicked.connect(self.parent.close_scan_settings)
        
        # WHY: Reverted to explicit signal connections. Removing instantaneous saving 
        # so settings are batched and saved on application close just like the GOG checkbox.
        self.chk_scan_galaxy.toggled.connect(self.update_scan_button_state)
        self.chk_scan_gog_web.toggled.connect(self.update_scan_button_state)
        self.chk_scan_epic.toggled.connect(self.update_scan_button_state)
        self.chk_scan_local.toggled.connect(self.update_scan_button_state)

        # Scan Connections
        self.scan_btn.clicked.connect(self.parent.on_manual_search_trigger)
        self.scan_input.returnPressed.connect(self.parent.on_manual_search_trigger)
        self.btn_confirm.clicked.connect(self.parent.apply_inline_selection)
        self.btn_cancel.clicked.connect(self.parent.cancel_inline_scan)
        self.scan_results.itemDoubleClicked.connect(self.parent.apply_inline_selection)

        self.act_search_name.triggered.connect(lambda: self.set_search_target("Name", "search_ph_name"))
        self.act_search_dev.triggered.connect(lambda: self.set_search_target("Developer", "search_ph_developer"))
        self.act_search_pub.triggered.connect(lambda: self.set_search_target("Publisher", "search_ph_publisher"))
        self.act_search_sum.triggered.connect(lambda: self.set_search_target("Summary", "search_ph_summary"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # WHY: Ping the controller to potentially repack the grid columns based on new width.
        if hasattr(self, 'parent') and hasattr(self.parent, 'filter_controller'):
            self.parent.filter_controller.reflow_filters()
        self.adjust_scan_log_font()

    def handle_view_toggle(self, toggled_btn, checked):
        if checked:
            for btn in [self.btn_toggle_new, self.btn_toggle_dlc, self.btn_toggle_review]:
                if btn != toggled_btn:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
        self.parent.request_filter_update()

    def adjust_scan_log_font(self):
        """WHY: Dynamically calculates the perfect pixel size required to fit exactly 80 monospace characters in the list width."""
        viewport_width = self.scan_results.viewport().width()
        if viewport_width < 50: return
        
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        best_size = 6
        for size in range(24, 5, -1):
            font.setPixelSize(size)
            fm = QFontMetrics(font)
            if fm.horizontalAdvance("X" * 80) <= viewport_width - 15: # 15px buffer for padding
                best_size = size
                break
        self.scan_results.setStyleSheet(f"font-family: Consolas, 'Courier New', monospace; font-size: {best_size}px;")

    def update_scan_button_state(self):
        """WHY: Single Responsibility - Enables or disables the Scan button based on selected sources."""
        if getattr(self.parent, 'full_scan_in_progress', False): return
        has_source = self.chk_scan_galaxy.isChecked() or self.chk_scan_gog_web.isChecked() or self.chk_scan_epic.isChecked() or self.chk_scan_steam.isChecked() or self.chk_scan_local.isChecked()
        self.btn_full_scan.setEnabled(has_source)

    def set_search_target(self, target, ph_key):
        """Dynamically swaps the placeholder text and triggers an instant refilter."""
        self.search_target = target
        self.search_ph_key = ph_key
        self.search_bar.setPlaceholderText(translator.tr(ph_key))
        if self.search_bar.text(): self.parent.request_filter_update()

    def update_sort_button(self, is_desc):
        # Updates label between UP (Ascending) and DOWN (Descending)
        key = "sidebar_sort_descending" if is_desc else "sidebar_sort_ascending"
        self.btn_toggle_sort.setText(translator.tr(key))

    def refresh_styles(self):
        # Only refresh elements that use stylesheets and might cache colors
        for frame in [self.frame_counters, self.frame_search, self.frame_sort, self.frame_filters, self.frame_bottom]:
            frame.setStyleSheet(self.frame_style)

        # Refresh Filter Groups to pick up new palette
        for i in range(self.filters_layout.count()):
            item = self.filters_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), CollapsibleFilterGroup):
                w = item.widget()
                # Force re-eval of palette() keywords
                sheet = w.toggle_btn.styleSheet()
                w.toggle_btn.setStyleSheet("")
                w.toggle_btn.setStyleSheet(sheet)

    def retranslate_ui(self):
        self.findChild(QLabel, "sidebar_search_label").setText(translator.tr("sidebar_search_label"))
        self.search_bar.setPlaceholderText(translator.tr(self.search_ph_key))
        self.act_search_name.setText(translator.tr("search_target_name"))
        self.act_search_dev.setText(translator.tr("search_target_developer"))
        self.act_search_pub.setText(translator.tr("search_target_publisher"))
        self.act_search_sum.setText(translator.tr("search_target_summary"))
        self.findChild(QLabel, "sidebar_sort_label").setText(translator.tr("sidebar_sort_label"))
        self.combo_sort.setItemText(0, translator.tr("sidebar_sort_name"))
        self.combo_sort.setItemText(1, translator.tr("sidebar_sort_release_date"))
        self.combo_sort.setItemText(2, translator.tr("sidebar_sort_date_added"))
        self.update_sort_button(self.parent.sort_desc)
        self.findChild(QLabel, "sidebar_filters_label").setText(translator.tr("sidebar_filters_label"))
        # WHY: Retranslate the newly added 'Show :' label dynamically.
        self.lbl_show.setText(translator.tr("sidebar_lbl_show"))
        self.btn_toggle_new.setText(translator.tr("sidebar_btn_toggle_new"))
        self.btn_toggle_dlc.setText(translator.tr("sidebar_btn_toggle_dlc"))
        self.btn_toggle_review.setText(translator.tr("sidebar_btn_toggle_review"))
        self.btn_approve_review.setText(translator.tr("sidebar_btn_approve_review"))
        self.btn_scan_settings.setText(translator.tr("sidebar_btn_scan_settings"))
        self.findChild(QLabel, "scan_settings_title_lbl").setText(translator.tr("scan_settings_title"))
        self.grp_scan_platforms.setTitle(translator.tr("scan_settings_platforms"))
        self.grp_scan_local.setTitle(translator.tr("scan_settings_local"))
        self.grp_scan_options.setTitle(translator.tr("scan_settings_options"))
        self.chk_scan_dl_images.setText(translator.tr("settings_data_media_download_images"))
        self.btn_close_scan_settings.setText(translator.tr("btn_close"))
        self.btn_full_scan.setText(translator.tr("sidebar_btn_full_scan"))
        # Scan panel
        self.scan_title_label.setText(translator.tr("sidebar_manual_scan_title"))
        self.scan_input.setPlaceholderText(translator.tr("sidebar_manual_scan_placeholder"))
        self.scan_btn.setText(translator.tr("sidebar_manual_scan_search_btn"))
        self.btn_confirm.setText(translator.tr("sidebar_manual_scan_confirm_btn"))
        self.btn_cancel.setText(translator.tr("sidebar_manual_scan_cancel_btn"))