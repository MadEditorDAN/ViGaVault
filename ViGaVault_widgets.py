# WHY: Extracted complex custom UI components to modularize the interface.
# This keeps the main application window clean and delegates visual layout
# concerns to dedicated classes.
import os
import re
import webbrowser
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
                             QPushButton, QScrollArea, QFrame, QSizePolicy, QCheckBox, 
                             QLineEdit, QComboBox, QListWidget, QListWidgetItem, 
                             QMessageBox, QGroupBox, QApplication, QAbstractItemView, QMenu, QToolButton)
from PySide6.QtCore import Qt, QSize, QEvent, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap, QFont, QFontMetrics, QStandardItemModel, QStandardItem

from ViGaVault_utils import translator, get_image_path, get_root_path, DEFAULT_DISPLAY_SETTINGS
from ViGaVault_workers import ImageLoader

# --- CUSTOM WIDGETS ---
class CheckableComboBox(QComboBox):
    """WHY: Single Responsibility - Provides an Excel-style multi-select dropdown for column filtering."""
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))

        # WHY: Make the combo box editable to naturally act as a search box with a dropdown arrow.
        self.setEditable(True)
        self.lineEdit().textEdited.connect(self.filter_items)
        # WHY: Prevent the combo box from automatically selecting the first item and overriding our search text.
        self.setInsertPolicy(QComboBox.NoInsert)

        # WHY: Native model dataChanged accurately captures direct checkbox interactions.
        self.model().dataChanged.connect(self.on_data_changed)
        # WHY: Intercept clicks purely on the dropdown list to toggle checkboxes without forcibly closing the popup.
        self.view().viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.view().viewport():
            if event.type() == QEvent.MouseButtonRelease:
                index = self.view().indexAt(event.pos())
                if index.isValid():
                    item = self.model().itemFromIndex(index)
                    new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                    item.setCheckState(new_state)
                # WHY: Always consume the release event to stop the QComboBox from natively closing.
                return True
            elif event.type() == QEvent.MouseButtonPress:
                return True # Consume press to prevent native item selection from closing the popup
        return super().eventFilter(obj, event)

    def on_data_changed(self, topLeft, bottomRight, roles):
        if Qt.CheckStateRole in roles or not roles:
            self.selection_changed.emit()
            self.reset_text()

    def filter_items(self, text):
        # WHY: Smart Refresh - Dynamically hide/show items in the dropdown list based on the search text.
        search = text.lower()
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            self.view().setRowHidden(i, search not in item.text().lower())

    def hidePopup(self):
        super().hidePopup()
        self.reset_text()
        # WHY: Clear the filter when the popup closes so the next time it opens, all options are visible.
        self.filter_items("")

    def reset_text(self):
        # WHY: Display a clean translated summary of active filters when the box is closed.
        checked = len(self.get_checked_items())
        if checked > 0:
            self.lineEdit().setText(translator.tr("filter_selected_count", count=checked))
        else:
            self.lineEdit().clear()

    def get_checked_items(self):
        checked = []
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            if item.checkState() == Qt.Checked:
                checked.append(item.text())
        return checked

    def add_item(self, text, checked=False):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.model().appendRow(item)
        
    def clear_items(self):
        self.model().clear()
        self.lineEdit().clear()

# A custom group box that can collapse its content to save space in the sidebar.
class CollapsibleFilterGroup(QGroupBox):
    def __init__(self, title, parent_layout, parent=None):
        super().__init__("", parent)
        self.parent_layout = parent_layout
        self.title = title
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # WHY: Wrap the header in a dedicated layout so we can inject the All/None buttons perfectly in line with the Title.
        self.header_widget = QWidget()
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header Button (acts as the toggle trigger)
        self.toggle_btn = QPushButton(f"▶ {title}")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False) # Default collapsed
        self.toggle_btn.setStyleSheet("""
            QPushButton { text-align: left; font-weight: bold; padding: 5px; border: none; background-color: palette(button); color: palette(button-text); }
            QPushButton:hover { background-color: palette(midlight); }
            QPushButton:checked { background-color: palette(button); }
        """)
        self.toggle_btn.toggled.connect(self.toggle_content)
        self.header_layout.addWidget(self.toggle_btn, 1)
        
        self.btn_all = QPushButton(translator.tr("sidebar_btn_all"))
        self.btn_none = QPushButton(translator.tr("sidebar_btn_none"))
        btn_style = "QPushButton { padding: 2px 5px; font-size: 11px; margin: 2px; border: 1px solid palette(dark); border-radius: 3px; background-color: palette(button); }"
        self.btn_all.setStyleSheet(btn_style)
        self.btn_none.setStyleSheet(btn_style)
        self.btn_all.hide()
        self.btn_none.hide()
        
        self.header_layout.addWidget(self.btn_all)
        self.header_layout.addWidget(self.btn_none)
        self.layout.addWidget(self.header_widget)

        # Content Area
        self.content_area = QWidget()
        self.content_area.setVisible(False)
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll Area for Checkboxes (Limits size)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Grid layout for checkboxes (2 columns)
        self.checkbox_container = QWidget()
        self.checkbox_layout = QGridLayout(self.checkbox_container)
        self.checkbox_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.checkbox_container)
        
        self.content_layout.addWidget(self.scroll)
        self.layout.addWidget(self.content_area)

    def toggle_content(self, checked):
        self.content_area.setVisible(checked)
        arrow = "▼" if checked else "▶"
        self.toggle_btn.setText(f"{arrow} {self.title}")
        
        if checked:
            # Switch policy to Expanding so it can take available space...
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            
            # ...BUT we manually calculate the exact required height.
            # WHY: By default, Qt splits space equally (50/50) between 'Expanding' widgets.
            # This looks bad if one group is small and another is huge. 
            # By setting MaximumHeight to the content size, we force the layout to give this 
            # group ONLY what it needs, leaving the remaining space for other large groups.
            h_header = self.header_widget.sizeHint().height()
            
            self.checkbox_container.adjustSize()
            h_list = self.checkbox_container.sizeHint().height()
            h_chrome = 2 * self.scroll.frameWidth() + self.layout.contentsMargins().top() + self.layout.contentsMargins().bottom() + self.layout.spacing()
            
            total_h = h_header + h_list + h_chrome + 10
            self.setMaximumHeight(total_h)

            if self.parent_layout:
                self.parent_layout.setStretchFactor(self, 1)
        else:
            # Revert to Maximum (Compact) when collapsed
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self.setMaximumHeight(16777215) # Remove limit
            if self.parent_layout:
                self.parent_layout.setStretchFactor(self, 0)
        
        self.updateGeometry()

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
        
        self.layout_scan_platforms.addWidget(self.chk_scan_galaxy, 0, 0)
        self.layout_scan_platforms.addWidget(self.chk_scan_gog_web, 0, 1)
        self.layout_scan_platforms.addWidget(self.chk_scan_epic, 1, 0)

        # WHY: Inject placeholders for all upcoming platforms in a clean 2-column grid.
        dummies = ["Steam", "Amazon", "Uplay", "Battle.net", "Origin", "Itch", "Xbox", "PSN"]
        r, c = 1, 1
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
        # WHY: Added self.chk_scan_epic.isChecked() so the button activates when Epic is selected.
        has_source = self.chk_scan_galaxy.isChecked() or self.chk_scan_gog_web.isChecked() or self.chk_scan_epic.isChecked() or self.chk_scan_local.isChecked()
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

# The core display widget for a single game in the list.
# Handles image display, text wrapping, and buttons.
class GameCard(QWidget):
    def __init__(self, game_data, parent_window, list_view=None):
        # WHY: Assign the list_view as the parent immediately to prevent the OS from flashing it as a standalone desktop window.
        super().__init__(list_view)
        self.data = game_data
        self.parent_window = parent_window
        self.list_view = list_view
        self.current_row = -1
        self.info_labels = [] # Store references for dynamic style updates
        self.cached_pixmap = None
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Get display settings from parent
        settings = getattr(self.parent_window, 'display_settings', DEFAULT_DISPLAY_SETTINGS)
        img_w = settings.get('image', DEFAULT_DISPLAY_SETTINGS['image'])
        img_h = int(img_w * 1.33) # Aspect ratio 3:4
        
        # WHY: Force Fixed Height based purely on the image. 
        # This decouples the geometry entirely from the text length, stopping all visual bugs perfectly.
        self.setFixedHeight(img_h + 10)

        # Image
        self.img_label = QLabel()
        self.img_label.setFixedSize(img_w, img_h)
        self.img_label.setAlignment(Qt.AlignCenter)
        img_name = game_data.get('Image_Link', '')
        has_image = str(game_data.get('Has_Image')).lower() in ['true', '1']
        self.image_path = os.path.join(get_image_path(), os.path.basename(img_name)) if img_name else ''
        if self.image_path and has_image:
            self.img_label.setText("Loading...")
            self.start_image_load(self.image_path)
        else:
            self.img_label.setText("No Image")
            self.img_label.setStyleSheet("border: 1px solid #555;")
        self.img_label.installEventFilter(self)
        
        # WHY: Zone 1 (Image). Encapsulate in a VBox with a stretch to push it to the top natively without forced heights.
        self.image_frame = QFrame()
        self.image_frame.setStyleSheet("border-right: 1px solid palette(dark);")
        image_col = QVBoxLayout(self.image_frame)
        image_col.setContentsMargins(0, 0, 0, 0)
        image_col.addWidget(self.img_label)
        image_col.addStretch()
        main_layout.addWidget(self.image_frame)
        
        # --- COLUMN 2 (METADATA) ---
        self.metadata_frame = QFrame()
        self.metadata_frame.setStyleSheet("border-right: 1px solid palette(dark);")
        # WHY: Strictly lock the metadata column to 500px so it never squishes or wraps text awkwardly.
        self.metadata_frame.setFixedWidth(500)
        metadata_col = QVBoxLayout(self.metadata_frame)
        metadata_col.setContentsMargins(10, 0, 10, 0) 
        metadata_col.setSpacing(2)
        metadata_col.setAlignment(Qt.AlignTop)
        
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        
        self.title_lbl = QLabel(game_data.get('Clean_Title', 'Unknown'))
        self.title_lbl.setStyleSheet(f"font-weight: bold; font-size: {settings.get('text', DEFAULT_DISPLAY_SETTINGS['text'])}px;")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # SizePolicy ignored to allow text to shrink/wrap correctly in tight spaces
        self.title_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.title_lbl.setMinimumWidth(0)
        # WHY: Intercept click to trigger card selection before text-highlighting consumes it.
        self.title_lbl.installEventFilter(self)
        title_layout.addWidget(self.title_lbl)

        path_root = game_data.get('Path_Root', '')
        main_path = get_root_path()
        if path_root and path_root.startswith(main_path):
            # WHY: Strip the global root path for a cleaner, relative display
            path_root = path_root[len(main_path):].lstrip('\\/')
        path_text = f"<b>{translator.tr('gamecard_info_local_path')}</b>{path_root}" if path_root else ""
        self.path_lbl = QLabel(path_text)
        self.path_lbl.setStyleSheet("font-size: 11px; color: gray;")
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_lbl.setWordWrap(True)
        self.path_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.path_lbl.setMinimumWidth(0)
        self.path_lbl.installEventFilter(self)
        title_layout.addWidget(self.path_lbl)
        
        metadata_col.addLayout(title_layout)
        metadata_col.addSpacing(10)
        
        info_font_size = max(10, settings.get('text', DEFAULT_DISPLAY_SETTINGS['text']) - 6)
        for field in ['Original_Release_Date', 'Platforms', 'Genre', 'Developer', 'Publisher', 'Collection']:
            display_name = field
            if field == 'Original_Release_Date': display_name = translator.tr("gamecard_info_release_date")
            elif field == 'Platforms': display_name = translator.tr("gamecard_info_platforms")
            elif field == 'Genre': display_name = translator.tr("gamecard_info_genre")            
            elif field == 'Developer': display_name = translator.tr("gamecard_info_developer")
            elif field == 'Publisher': display_name = translator.tr("gamecard_info_publisher")
            elif field == 'Collection': display_name = translator.tr("gamecard_info_collection")
            
            label = QLabel(f"<b>{display_name}:</b> {game_data.get(field, '')}")
            label.setStyleSheet(f"font-size: {info_font_size}px;")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            label.installEventFilter(self)
            metadata_col.addWidget(label)
            self.info_labels.append(label)
            
        metadata_col.addStretch()
        # WHY: Removed stretch factor completely. The summary column will now exclusively absorb all UI resizing.
        main_layout.addWidget(self.metadata_frame)

        # --- COLUMN 3 (SCROLLABLE SUMMARY) ---
        self.summary_frame = QFrame()
        # WHY: Removed the right border so there is no vertical line between the summary and the action buttons.
        summary_col = QVBoxLayout(self.summary_frame)
        summary_col.setContentsMargins(0, 0, 10, 0)
        summary_col.setSpacing(5)

        self.summary_title = QLabel(translator.tr("gamecard_summary_title"))
        self.summary_title.setStyleSheet(f"font-weight: bold; font-size: {info_font_size}px;")
        self.summary_title.installEventFilter(self)
        summary_col.addWidget(self.summary_title)
        
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setFrameShape(QFrame.NoFrame)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.summary_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.summary_scroll.installEventFilter(self)
        
        # WHY: Explicitly bind the scroll container to 'self' to protect it from Python's aggressive garbage collector.
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.scroll_content.installEventFilter(self)
        scroll_layout = QVBoxLayout(self.scroll_content)
        scroll_layout.setContentsMargins(0, 0, 5, 0)
        
        summary_font_size = max(10, settings.get('text', DEFAULT_DISPLAY_SETTINGS['text']) - 8)
        self.summary_content = QLabel(game_data.get('Summary', ''))
        self.summary_content.setWordWrap(True)
        self.summary_content.setStyleSheet(f"font-size: {summary_font_size}px;")
        self.summary_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary_content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary_content.installEventFilter(self)
        
        scroll_layout.addWidget(self.summary_content)
        scroll_layout.addStretch() # Push text to top inside the scroll box
        
        self.summary_scroll.setWidget(self.scroll_content)
        summary_col.addWidget(self.summary_scroll)
        main_layout.addWidget(self.summary_frame, stretch=5)

        # --- COLUMN 4 (ACTIONS) ---
        self.trailer_link = game_data.get('Trailer_Link', '')

        has_local_folder = str(game_data.get('Is_Local')).lower() in ['true', '1']
        has_trailer = bool(self.trailer_link and self.trailer_link.startswith('http'))

        self.actions_frame = QFrame()
        self.actions_frame.setStyleSheet("background-color: palette(alternate-base); border-radius: 5px;")
        self.actions_col = QVBoxLayout(self.actions_frame)
        self.actions_col.setContentsMargins(5, 5, 5, 5)
        self.actions_col.setSpacing(0)

        self.buttons = {}
        self.actions_col.addStretch()
        for name in ['scan', 'edit', 'folder', 'youtube']:
            btn = QPushButton()
            self.buttons[name] = btn
            btn.installEventFilter(self)
            self.actions_col.addWidget(btn)
            self.actions_col.addStretch()

        self.buttons['youtube'].clicked.connect(self.start_trailer)
        self.buttons['folder'].clicked.connect(self.open_folder)
        self.buttons['edit'].clicked.connect(self.edit_game)
        self.buttons['scan'].clicked.connect(self.scan_game)
        
        main_layout.addWidget(self.actions_frame)

    def _update_button_icons(self, has_trailer, has_local_folder):
        """WHY: Single Responsibility Principle - Consolidates all button state and icon rendering logic into one dynamic method."""
        settings = getattr(self.parent_window, 'display_settings', DEFAULT_DISPLAY_SETTINGS)
        btn_size = settings.get('button', DEFAULT_DISPLAY_SETTINGS['button'])

        # WHY: Injected tooltip translation keys directly into the dictionary to map them cleanly within the DRY loop.
        button_definitions = {
            'youtube':     {'enabled': has_trailer,     'fallback': "▶", 'font_size': "32px", 'tt_key': 'gamecard_tooltip_youtube'},
            'folder':      {'enabled': has_local_folder,'fallback': "📁", 'font_size': "32px", 'tt_key': 'gamecard_tooltip_folder'},
            'edit':        {'enabled': True,            'fallback': "✏️", 'font_size': "28px", 'tt_key': 'gamecard_tooltip_edit'},
            'scan':        {'enabled': True,            'fallback': "🔍", 'font_size': "28px", 'tt_key': 'gamecard_tooltip_scan'}
        }

        for name, props in button_definitions.items():
            btn = self.buttons.get(name)
            if not btn: continue
            
            # WHY: Force child buttons to break their OS-level style cache and instantly fetch the new global theme colors.
            btn.setStyleSheet(" ")
            
            btn.setFixedSize(btn_size, btn_size)
            
            icon_to_load = name
            if not props['enabled'] and name in ['youtube', 'folder']:
                icon_to_load = f"{name}_disabled"

            icon_path = f"assets/{icon_to_load}.png"
            if not os.path.exists(icon_path):
                icon_path = f"icons/{icon_to_load}.png"

            # WHY: Define an explicit CSS style for the buttons. Because their parent frame uses a stylesheet,
            # Qt drops the native OS 3D button rendering. We must rebuild the square button look manually.
            base_style = (
                "QPushButton { background-color: palette(button); border: 1px solid palette(dark); border-radius: 4px; }\n"
                "QPushButton:pressed { background-color: palette(mid); }"
            )

            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
                btn.setIconSize(QSize(int(btn_size*0.7), int(btn_size*0.7)))
                btn.setStyleSheet(base_style)
                btn.setText("")
            else:
                fallback_emoji = props['fallback']
                color_css = "color: #FF0000; " if fallback_emoji == "▶" else ""
                custom_style = (
                    f"QPushButton {{ font-size: {props['font_size']}; {color_css} background-color: palette(button); border: 1px solid palette(dark); border-radius: 4px; }}\n"
                    "QPushButton:pressed { background-color: palette(mid); }"
                )
                btn.setStyleSheet(custom_style)
                btn.setText(fallback_emoji)
                btn.setIcon(QIcon())
            
            btn.setEnabled(props['enabled'])
            btn.setToolTip(translator.tr(props['tt_key']))

    def refresh_ui_from_data(self, force_media_reload=False):
        """WHY: Allows surgical updates of the UI instantly without reloading the widget or the list."""
        # Update Texts
        self.title_lbl.setText(self.data.get('Clean_Title', 'Unknown'))
        path_root = self.data.get('Path_Root', '')
        main_path = get_root_path()
        if path_root and path_root.startswith(main_path):
            # WHY: Strip the global root path for a cleaner, relative display
            path_root = path_root[len(main_path):].lstrip('\\/')
        self.path_lbl.setText(f"<b>{translator.tr('gamecard_info_local_path')}</b>{path_root}" if path_root else "")
        
        # Update Buttons
        self.trailer_link = self.data.get('Trailer_Link', '')
        
        has_local_folder = str(self.data.get('Is_Local')).lower() in ['true', '1']
        has_trailer = bool(self.trailer_link and self.trailer_link.startswith('http'))
        
        self._update_button_icons(has_trailer, has_local_folder)
        
        has_image = str(self.data.get('Has_Image')).lower() in ['true', '1']
        # Update Image (Only reload if path actually changed to save IO)
        img_name = self.data.get('Image_Link', '')
        new_image_path = os.path.join(get_image_path(), os.path.basename(img_name)) if img_name else ''
        # WHY: force_media_reload bypasses the path string check to physically reload the image from disk if it was overwritten.
        if (new_image_path != self.image_path or force_media_reload) and has_image:
            self.image_path = new_image_path
            if self.image_path:
                self.start_image_load(self.image_path)
        elif not has_image:
            self.image_path = ''
            self.img_label.setText("No Image")
            self.img_label.setStyleSheet("border: 1px solid #555;")
            self.cached_pixmap = None
                
        # Update Metadata info labels dynamically
        fields = ['Original_Release_Date', 'Platforms', 'Genre', 'Developer', 'Publisher', 'Collection']
        for i, field in enumerate(fields):
            display_name = 'Developer'
            if field == 'Original_Release_Date': display_name = translator.tr("gamecard_info_release_date")
            elif field == 'Platforms': display_name = translator.tr("gamecard_info_platforms")
            elif field == 'Genre': display_name = translator.tr("gamecard_info_genre")            
            elif field == 'Developer': display_name = translator.tr("gamecard_info_developer")
            elif field == 'Publisher': display_name = translator.tr("gamecard_info_publisher")
            elif field == 'Collection': display_name = translator.tr("gamecard_info_collection")
            self.info_labels[i].setText(f"<b>{display_name}:</b> {self.data.get(field, '')}")
            
        self.summary_content.setText(self.data.get('Summary', ''))

    def start_image_load(self, path):
        loader = ImageLoader(path)
        loader.signals.loaded.connect(self.on_image_loaded)
        self.parent_window.thread_pool.start(loader)

    def on_image_loaded(self, image):
        self.cached_pixmap = QPixmap.fromImage(image)
        self.update_image_display()

    def update_image_display(self):
        settings = getattr(self.parent_window, 'display_settings', DEFAULT_DISPLAY_SETTINGS)
        img_w = settings.get('image', DEFAULT_DISPLAY_SETTINGS['image'])
        img_h = int(img_w * 1.33)
        
        if self.cached_pixmap:
            self.img_label.setPixmap(self.cached_pixmap.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.img_label.setText("") # Clear text

    def update_style(self, settings):
        """Updates the card style dynamically."""
        img_w = settings.get('image', DEFAULT_DISPLAY_SETTINGS['image'])
        img_h = int(img_w * 1.33)
        btn_size = settings.get('button', DEFAULT_DISPLAY_SETTINGS['button'])
        text_size = settings.get('text', DEFAULT_DISPLAY_SETTINGS['text'])
        
        self.setFixedHeight(img_h + 10)
        
        # WHY: Force child frames to break their OS-level style cache individually.
        # Setting styles on the parent widget fails to cascade cleanly during dynamic theme swaps.
        for frame in [self.image_frame, self.metadata_frame]:
            frame.setStyleSheet("")
            frame.setStyleSheet("border-right: 1px solid palette(dark);")
        self.summary_frame.setStyleSheet("")
        self.actions_frame.setStyleSheet("")
        self.actions_frame.setStyleSheet("background-color: palette(alternate-base); border-radius: 5px;")
        # Update Image
        self.img_label.setFixedSize(img_w, img_h)
        if self.cached_pixmap:
            self.img_label.setPixmap(self.cached_pixmap.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
        # Update Buttons
        has_local_folder = str(self.data.get('Is_Local')).lower() in ['true', '1']
        has_trailer = bool(self.trailer_link and self.trailer_link.startswith('http'))
        self._update_button_icons(has_trailer, has_local_folder)

        # Update Text
        self.title_lbl.setStyleSheet(f"font-weight: bold; font-size: {text_size}px;")
        
        info_size = max(10, text_size - 6)
        for lbl in self.info_labels:
            lbl.setStyleSheet(f"font-weight: bold; font-size: {info_size}px;")
        self.summary_title.setStyleSheet(f"font-weight: bold; font-size: {info_size}px;")
        self.summary_content.setStyleSheet(f"font-size: {max(10, text_size - 8)}px;")

    def mousePressEvent(self, event):
        if self.list_view and self.current_row >= 0:
            model = self.list_view.model()
            index = model.index(self.current_row, 0)
            self.list_view.setCurrentIndex(index)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.MouseButtonPress:
                if self.list_view and self.current_row >= 0:
                    model = self.list_view.model()
                    index = model.index(self.current_row, 0)
                    self.list_view.setCurrentIndex(index)
            return super().eventFilter(obj, event)
        except (KeyboardInterrupt, RuntimeError, AttributeError):
            return False

    def start_trailer(self):
        if self.trailer_link:
            logging.info(f"Opening trailer in browser: {self.trailer_link}")
            webbrowser.open(self.trailer_link, new=1)

    def open_folder(self):
        path = self.data.get('Path_Root', '')
        if path:
            if os.path.exists(path):
                os.startfile(path)
            else:
                # Graceful UI rejection and self-correction
                QMessageBox.warning(self.parent_window, "Not Found", translator.tr("msg_jit_folder_missing"))
                self.parent_window.update_game_flags(self.data.get('Folder_Name'), {'Is_Local': False})
                self.buttons['folder'].setEnabled(False)

    def edit_game(self):
        # WHY: Lazy import to completely break the circular dependency chain between the widget library and the dialogs package.
        from dialogs import ActionDialog
        dlg = ActionDialog("dialog_edit_title", self.data, self.parent_window)
        if dlg.exec():
            new_data = dlg.get_data()
            if new_data:
                self.parent_window.update_game_data(self.data['Folder_Name'], new_data)

    def scan_game(self):
        if hasattr(self.parent_window, 'start_inline_scan'):
            self.parent_window.start_inline_scan(self.data)