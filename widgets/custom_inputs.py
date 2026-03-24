# WHY: Single Responsibility Principle - Isolates generic reusable UI building blocks 
# so they can be securely imported across the application without dragging in massive components like the Sidebar.
from PySide6.QtWidgets import (QComboBox, QGroupBox, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QScrollArea, QFrame, 
                             QGridLayout, QSizePolicy)
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem

from ViGaVault_utils import translator

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