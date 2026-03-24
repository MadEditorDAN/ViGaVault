# WHY: Single Responsibility Principle - Exclusively handles the visual rendering, 
# media loading, and button interactions of a single game.
import os
import webbrowser
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QScrollArea, QFrame, QSizePolicy, QMessageBox)
from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtGui import QIcon, QPixmap

from ViGaVault_utils import translator, get_image_path, get_root_path, DEFAULT_DISPLAY_SETTINGS
from ViGaVault_workers import ImageLoader

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

            icon_path = f"assets/images/{icon_to_load}.png"
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