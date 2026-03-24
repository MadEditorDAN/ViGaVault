# WHY: Single Responsibility Principle - Exclusively handles the visual configuration sliders and regional toggles.
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, 
                               QComboBox, QSlider, QLabel, QGroupBox)
from PySide6.QtCore import Qt, Signal

from ViGaVault_utils import translator, DEFAULT_DISPLAY_SETTINGS

class DisplayTabWidget(QWidget):
    changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.IMG_SIZES = [150, 175, 200, 225, 250, 275, 300]
        self.BTN_SIZES = [35, 40, 45, 50, 55, 60, 65]
        self.TXT_SIZES = [14, 16, 18, 20, 22, 24, 26]
        self.setup_ui()

    def notify_changed(self, *args):
        """WHY: Safely absorbs arbitrary arguments passed by Qt signals before cleanly emitting the zero-argument custom signal."""
        self.changed.emit()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        grp_theme = QGroupBox(translator.tr("settings_display_theme"))
        layout_theme = QVBoxLayout(grp_theme)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems([translator.tr("theme_system"), translator.tr("theme_dark"), translator.tr("theme_light")])
        self.combo_theme.currentIndexChanged.connect(self.notify_changed)
        layout_theme.addWidget(self.combo_theme)
        layout.addWidget(grp_theme)
        
        grp_reg = QGroupBox(translator.tr("settings_display_regional"))
        layout_reg = QHBoxLayout(grp_reg)
        
        col_lang = QVBoxLayout()
        col_lang.addWidget(QLabel(translator.tr("settings_display_language")))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["English", "French", "German", "Spanish", "Italian"])
        self.combo_lang.currentIndexChanged.connect(self.notify_changed)
        col_lang.addWidget(self.combo_lang)
        
        col_date = QVBoxLayout()
        col_date.addWidget(QLabel(translator.tr("settings_display_date_format")))
        self.combo_date = QComboBox()
        self.combo_date.addItems(["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"])
        self.combo_date.currentIndexChanged.connect(self.notify_changed)
        col_date.addWidget(self.combo_date)
        
        layout_reg.addLayout(col_lang)
        layout_reg.addLayout(col_date)
        layout.addWidget(grp_reg)
        
        grp_sizes = QGroupBox(translator.tr("settings_display_sizes_group"))
        layout_sizes = QFormLayout(grp_sizes)
        layout_sizes.setVerticalSpacing(25)
        
        img_layout = QHBoxLayout()
        self.slider_img_size = QSlider(Qt.Horizontal)
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

        self.slider_img_size.valueChanged.connect(self.notify_changed)
        self.slider_btn_size.valueChanged.connect(self.notify_changed)
        self.slider_text_size.valueChanged.connect(self.notify_changed)

    def update_preview_labels(self):
        self.lbl_img_size.setText(f"{self.IMG_SIZES[self.slider_img_size.value()]} px")
        self.lbl_btn_size.setText(f"{self.BTN_SIZES[self.slider_btn_size.value()]} px")
        self.lbl_text_size.setText(f"{self.TXT_SIZES[self.slider_text_size.value()]} px")
        
    def set_state(self, global_settings):
        theme_map = {"System": translator.tr("theme_system"), "Dark": translator.tr("theme_dark"), "Light": translator.tr("theme_light")}
        saved_theme = global_settings.get("theme", "System")
        self.combo_theme.setCurrentText(theme_map.get(saved_theme, translator.tr("theme_system")))
        
        self.combo_lang.setCurrentText(global_settings.get("language", "English"))
        self.combo_date.setCurrentText(global_settings.get("date_format", "DD/MM/YYYY"))

        img_size = global_settings.get("card_image_size", DEFAULT_DISPLAY_SETTINGS['image'])
        self.slider_img_size.setValue(self.IMG_SIZES.index(min(self.IMG_SIZES, key=lambda x:abs(x-img_size))))
        
        btn_size = global_settings.get("card_button_size", DEFAULT_DISPLAY_SETTINGS['button'])
        self.slider_btn_size.setValue(self.BTN_SIZES.index(min(self.BTN_SIZES, key=lambda x:abs(x-btn_size))))
        
        txt_size = global_settings.get("card_text_size", DEFAULT_DISPLAY_SETTINGS['text'])
        self.slider_text_size.setValue(self.TXT_SIZES.index(min(self.TXT_SIZES, key=lambda x:abs(x-txt_size))))
        self.update_preview_labels()
        
    def get_state(self):
        theme_map_rev = {translator.tr("theme_system"): "System", translator.tr("theme_dark"): "Dark", translator.tr("theme_light"): "Light"}
        return {
            "theme": theme_map_rev.get(self.combo_theme.currentText(), "System"),
            "language": self.combo_lang.currentText(),
            "date_format": self.combo_date.currentText(),
            "card_image_size": self.IMG_SIZES[self.slider_img_size.value()],
            "card_button_size": self.BTN_SIZES[self.slider_btn_size.value()],
            "card_text_size": self.TXT_SIZES[self.slider_text_size.value()]
        }