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
                             QMessageBox, QGroupBox, QApplication, QAbstractItemView)
from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QIcon, QPixmap, QFont, QPalette

from ViGaVault_utils import translator, get_image_path, get_video_path, get_root_path
from dialogs import ActionDialog
from ViGaVault_workers import ImageLoader

# --- CUSTOM WIDGETS ---
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
        self.layout.addWidget(self.toggle_btn)

        # Content Area
        self.content_area = QWidget()
        self.content_area.setVisible(False)
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # All/None Buttons Container
        self.btns_layout = QHBoxLayout()
        self.btns_layout.setContentsMargins(5, 5, 5, 5)
        self.content_layout.addLayout(self.btns_layout)

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
            h_header = self.toggle_btn.sizeHint().height()
            h_content = 0
            if self.btns_layout.count() > 0:
                h_content += self.btns_layout.sizeHint().height() + self.content_layout.spacing()
            
            self.checkbox_container.adjustSize()
            h_list = self.checkbox_container.sizeHint().height()
            h_chrome = 2 * self.scroll.frameWidth() + self.layout.contentsMargins().top() + self.layout.contentsMargins().bottom() + self.layout.spacing()
            
            total_h = h_header + h_content + h_list + h_chrome + 10
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
        self.setFixedWidth(350)
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
        self.search_bar.setPlaceholderText(translator.tr("sidebar_search_placeholder"))
        self.search_bar.setClearButtonEnabled(True)
        search_layout.addWidget(self.search_bar, 1) # Stretch 1 pour prendre l'espace disponible
        
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
        self.combo_sort.addItems([translator.tr("sidebar_sort_name"), translator.tr("sidebar_sort_release_date"), translator.tr("sidebar_sort_developer")])
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

        # --- SHOW NEW CHECKBOX (Moved here) ---
        self.chk_show_new = QCheckBox(translator.tr("sidebar_chk_show_new"))
        self.chk_show_new.setLayoutDirection(Qt.RightToLeft)
        filters_header_layout.addWidget(self.chk_show_new, 0, Qt.AlignRight)

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

        # --- BOTTOM CONTAINER (Scan Buttons) ---
        self.bottom_layout = QHBoxLayout()
        
        # --- FULL SCAN BUTTON ---
        self.btn_full_scan = QPushButton(translator.tr("sidebar_btn_full_scan"))
        self.btn_full_scan.setMinimumHeight(80) # WHY: Taller button to accommodate the 3 checkboxes visually
        font_scan = QFont()
        font_scan.setBold(True)
        font_scan.setPointSize(16)
        self.btn_full_scan.setFont(font_scan)
        
        # --- SCAN OPTIONS ---
        # WHY: Changed to QGridLayout to support a multi-column layout (easily scalable for Steam/Epic later).
        scan_opts_layout = QGridLayout()
        scan_opts_layout.setSpacing(2)
        
        self.chk_scan_gog = QCheckBox("GOG Galaxy")
        self.chk_scan_gog.setChecked(True)
        
        self.chk_scan_local = QCheckBox("Local Copy")
        self.chk_scan_local.setChecked(True)
        
        # WHY: Removed the retry failures checkbox to enforce use of the new Media Manager for edge cases.
        scan_opts_layout.addWidget(self.chk_scan_gog, 0, 0)
        scan_opts_layout.addWidget(self.chk_scan_local, 0, 1)

        self.bottom_layout.addWidget(self.btn_full_scan, 1) # 1 part stretch (1/3 of total width)
        self.bottom_layout.addLayout(scan_opts_layout, 2)   # 2 parts stretch (2/3 of total width)

        self.layout.addWidget(self.scan_panel)
        self.scan_panel.hide()
        self.layout.addLayout(self.bottom_layout)
        
        # --- CONNECTIONS ---
        self.search_bar.textChanged.connect(self.parent.request_filter_update)
        self.combo_sort.currentIndexChanged.connect(self.parent.request_filter_update)
        self.btn_toggle_sort.clicked.connect(self.parent.toggle_sort_order)
        self.btn_full_scan.clicked.connect(self.parent.start_full_scan)
        self.chk_show_new.toggled.connect(self.parent.request_filter_update)

        # Scan Connections
        self.scan_btn.clicked.connect(self.parent.on_manual_search_trigger)
        self.scan_input.returnPressed.connect(self.parent.on_manual_search_trigger)
        self.btn_confirm.clicked.connect(self.parent.apply_inline_selection)
        self.btn_cancel.clicked.connect(self.parent.cancel_inline_scan)
        self.scan_results.itemDoubleClicked.connect(self.parent.apply_inline_selection)

    def update_sort_button(self, is_desc):
        # Updates label between UP (Ascending) and DOWN (Descending)
        key = "sidebar_sort_descending" if is_desc else "sidebar_sort_ascending"
        self.btn_toggle_sort.setText(translator.tr(key))

    def refresh_styles(self):
        # Only refresh elements that use stylesheets and might cache colors
        for frame in [self.frame_counters, self.frame_search, self.frame_sort, self.frame_filters]:
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
        self.search_bar.setPlaceholderText(translator.tr("sidebar_search_placeholder"))
        self.findChild(QLabel, "sidebar_sort_label").setText(translator.tr("sidebar_sort_label"))
        self.combo_sort.setItemText(0, translator.tr("sidebar_sort_name"))
        self.combo_sort.setItemText(1, translator.tr("sidebar_sort_release_date"))
        self.combo_sort.setItemText(2, translator.tr("sidebar_sort_developer"))
        self.update_sort_button(self.parent.sort_desc)
        self.findChild(QLabel, "sidebar_filters_label").setText(translator.tr("sidebar_filters_label"))
        self.chk_show_new.setText(translator.tr("sidebar_chk_show_new"))
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
        settings = getattr(self.parent_window, 'display_settings', {'image': 200, 'button': 45, 'text': 22})
        img_w = settings.get('image', 200)
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
        self.image_frame.setObjectName("grid_col")
        image_col = QVBoxLayout(self.image_frame)
        image_col.setContentsMargins(0, 0, 0, 0)
        image_col.addWidget(self.img_label)
        image_col.addStretch()
        main_layout.addWidget(self.image_frame)
        
        # --- COLUMN 2 (METADATA) ---
        self.metadata_frame = QFrame()
        self.metadata_frame.setObjectName("grid_col")
        metadata_col = QVBoxLayout(self.metadata_frame)
        metadata_col.setContentsMargins(10, 0, 10, 0) 
        metadata_col.setSpacing(2)
        metadata_col.setAlignment(Qt.AlignTop)
        
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        
        self.title_lbl = QLabel(game_data.get('Clean_Title', 'Unknown'))
        self.title_lbl.setStyleSheet(f"font-weight: bold; font-size: {settings.get('text', 22)}px;")
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
        
        info_font_size = max(10, settings.get('text', 22) - 6)
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
        main_layout.addWidget(self.metadata_frame, stretch=2)

        # --- COLUMN 3 (SCROLLABLE SUMMARY) ---
        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("grid_col")
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
        
        summary_font_size = max(10, settings.get('text', 22) - 8)
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
        main_layout.addWidget(self.summary_frame, stretch=3)

        # --- COLUMN 4 (ACTIONS) ---
        vid_name = str(game_data.get('Path_Video', '')).strip()
        self.video_path = os.path.join(get_video_path(), os.path.basename(vid_name)) if vid_name else ''
        self.trailer_link = game_data.get('Trailer_Link', '')

        has_local_folder = str(game_data.get('Is_Local')).lower() in ['true', '1']
        has_local_video = str(game_data.get('Has_Video')).lower() in ['true', '1']
        has_trailer = bool(self.trailer_link and self.trailer_link.startswith('http'))

        self.actions_frame = QFrame()
        self.actions_frame.setObjectName("actions_col")
        self.actions_col = QVBoxLayout(self.actions_frame)
        self.actions_col.setContentsMargins(5, 5, 5, 5)
        self.actions_col.setSpacing(0)

        self.buttons = {}
        self.actions_col.addStretch()
        for name in ['scan', 'edit', 'folder', 'youtube', 'local_video']:
            btn = QPushButton()
            self.buttons[name] = btn
            btn.installEventFilter(self)
            self.actions_col.addWidget(btn)
            self.actions_col.addStretch()

        self.buttons['local_video'].clicked.connect(self.start_video)
        self.buttons['youtube'].clicked.connect(self.start_trailer)
        self.buttons['folder'].clicked.connect(self.open_folder)
        self.buttons['edit'].clicked.connect(self.edit_game)
        self.buttons['scan'].clicked.connect(self.scan_game)
        
        main_layout.addWidget(self.actions_frame)

    def _update_button_icons(self, has_local_video, has_trailer, has_local_folder):
        """WHY: Single Responsibility Principle - Consolidates all button state and icon rendering logic into one dynamic method."""
        settings = getattr(self.parent_window, 'display_settings', {'image': 200, 'button': 45, 'text': 22})
        btn_size = settings.get('button', 45)

        button_definitions = {
            'local_video': {'enabled': has_local_video, 'fallback': "🎞️", 'font_size': "32px"},
            'youtube':     {'enabled': has_trailer,     'fallback': "▶", 'font_size': "30px"},
            'folder':      {'enabled': has_local_folder,'fallback': "📁", 'font_size': "32px"},
            'edit':        {'enabled': True,            'fallback': "✏️", 'font_size': "28px"},
            'scan':        {'enabled': True,            'fallback': "🔍", 'font_size': "28px"}
        }

        for name, props in button_definitions.items():
            btn = self.buttons.get(name)
            if not btn: continue
            
            btn.setFixedSize(btn_size, btn_size)
            
            icon_to_load = name
            if not props['enabled'] and name in ['local_video', 'youtube', 'folder']:
                icon_to_load = f"{name}_disabled"

            icon_path = f"assets/{icon_to_load}.png"
            if not os.path.exists(icon_path):
                icon_path = f"icons/{icon_to_load}.png"

            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
                btn.setIconSize(QSize(int(btn_size*0.7), int(btn_size*0.7)))
                btn.setStyleSheet("")
                btn.setText("")
            else:
                fallback_emoji = props['fallback']
                style = f"font-size: {props['font_size']};"
                if fallback_emoji == "▶": style += " color: #FF0000;"
                btn.setStyleSheet(style)
                btn.setText(fallback_emoji)
                btn.setIcon(QIcon())
            
            btn.setEnabled(props['enabled'])
            if name == 'local_video' and not props['enabled'] and self.video_path: btn.setToolTip(f"File not found: {self.video_path}")
            else: btn.setToolTip("")

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
        vid_name = str(self.data.get('Path_Video', '')).strip()
        self.video_path = os.path.join(get_video_path(), os.path.basename(vid_name)) if vid_name else ''
        self.trailer_link = self.data.get('Trailer_Link', '')
        
        has_local_folder = str(self.data.get('Is_Local')).lower() in ['true', '1']
        has_local_video = str(self.data.get('Has_Video')).lower() in ['true', '1']
        has_trailer = bool(self.trailer_link and self.trailer_link.startswith('http'))
        
        self._update_button_icons(has_local_video, has_trailer, has_local_folder)
        
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
        settings = getattr(self.parent_window, 'display_settings', {'image': 200})
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33)
        
        if self.cached_pixmap:
            self.img_label.setPixmap(self.cached_pixmap.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.img_label.setText("") # Clear text

    def update_style(self, settings):
        """Updates the card style dynamically."""
        img_w = settings.get('image', 200)
        img_h = int(img_w * 1.33)
        btn_size = settings.get('button', 45)
        text_size = settings.get('text', 22)
        
        self.setFixedHeight(img_h + 10)
        
        # WHY: Force Qt to re-evaluate the palette() keywords by clearing the stylesheet first.
        # This fixes the bug where visible cards fail to switch colors when toggling Dark/Light mode.
        self.setStyleSheet("")
        self.setStyleSheet("""
            QFrame#grid_col { border-right: 1px solid palette(dark); }
            QFrame#actions_col { background-color: palette(alternate-base); border-radius: 5px; }
        """)
        # Update Image
        self.img_label.setFixedSize(img_w, img_h)
        if self.cached_pixmap:
            self.img_label.setPixmap(self.cached_pixmap.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
        # Update Buttons
        has_local_folder = str(self.data.get('Is_Local')).lower() in ['true', '1']
        has_local_video = str(self.data.get('Has_Video')).lower() in ['true', '1']
        has_trailer = bool(self.trailer_link and self.trailer_link.startswith('http'))
        self._update_button_icons(has_local_video, has_trailer, has_local_folder)

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

    def start_video(self):
        # WHY: Just-In-Time check to ensure no crashes happen.
        if self.video_path:
            try:
                if os.path.exists(self.video_path):
                    logging.info(f"Opening local video with default player: {self.video_path}")
                    os.startfile(self.video_path)
                else:
                    # Graceful UI rejection and self-correction
                    QMessageBox.warning(self.parent_window, "Not Found", translator.tr("msg_jit_video_missing"))
                    self.parent_window.update_game_flags(self.data.get('Folder_Name'), {'Has_Video': False})
                    self.buttons['local_video'].setEnabled(False)
            except Exception as e:
                logging.error(f"Could not open local video: {e}")
                QMessageBox.critical(self.parent_window, "Error", f"Could not open video file:\n{e}")

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
        dlg = ActionDialog("dialog_edit_title", self.data, self.parent_window)
        if dlg.exec():
            new_data = dlg.get_data()
            if new_data:
                self.parent_window.update_game_data(self.data['Folder_Name'], new_data)

    def scan_game(self):
        if hasattr(self.parent_window, 'start_inline_scan'):
            self.parent_window.start_inline_scan(self.data)