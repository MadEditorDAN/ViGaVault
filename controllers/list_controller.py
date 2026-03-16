import pandas as pd
from PySide6.QtCore import Qt, QTimer, QObject
from PySide6.QtWidgets import QListWidgetItem, QAbstractItemView
from ViGaVault_widgets import GameCard

class ListController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window

    def check_scroll_load(self, value):
        maximum = self.mw.list_widget.verticalScrollBar().maximum()
        if maximum > 0 and value >= maximum * 0.85:
            self.load_more_items()

    def load_more_items(self):
        if self.mw.loaded_count >= len(self.mw.current_df):
            self.mw.background_loader.stop()
            return
            
        end_index = min(self.mw.loaded_count + self.mw.batch_size, len(self.mw.current_df))
        batch_df = self.mw.current_df.iloc[self.mw.loaded_count:end_index]
        
        vp_width = self.mw.list_widget.viewport().width()
        current_width = vp_width if vp_width > 100 else 600
        
        if self.mw.loaded_count > 0 and abs(current_width - self.mw.last_viewport_width) > 2:
            self.update_item_sizes()
            current_width = self.mw.list_widget.viewport().width()
        
        self.mw.last_viewport_width = current_width
        
        for _, row in batch_df.iterrows():
            item = QListWidgetItem(self.mw.list_widget)
            card = GameCard(row.to_dict(), self.mw, item)
            
            card.setFixedWidth(current_width)
            card.adjustSize()
            item.setSizeHint(card.sizeHint())
            card.setMinimumWidth(0)
            card.setMaximumWidth(16777215)
            
            item.setData(Qt.UserRole, row['Folder_Name'])
            self.mw.list_widget.addItem(item)
            self.mw.list_widget.setItemWidget(item, card)
            
        self.mw.loaded_count = end_index

    def update_item_sizes(self):
        vp_width = self.mw.list_widget.viewport().width()
        viewport_width = vp_width if vp_width > 100 else 600
        
        for i in range(self.mw.list_widget.count()):
            item = self.mw.list_widget.item(i)
            widget = self.mw.list_widget.itemWidget(item)
            if widget:
                widget.setFixedWidth(viewport_width)
                widget.adjustSize()
                item.setSizeHint(widget.sizeHint())
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(16777215)
        self.mw.last_viewport_width = viewport_width

    def restore_scroll_position(self, retries=10):
        if not hasattr(self.mw, 'pending_scroll'):
            self.mw.sidebar.setEnabled(True)
            self.mw.list_widget.setEnabled(True)
            return
        
        sb = self.mw.list_widget.verticalScrollBar()
        
        if sb.maximum() < self.mw.pending_scroll and self.mw.loaded_count < len(self.mw.current_df):
            self.load_more_items()
            self.mw.list_widget.doItemsLayout() 
            QTimer.singleShot(10, lambda: self.restore_scroll_position(10))
        elif sb.maximum() < self.mw.pending_scroll and self.mw.loaded_count >= len(self.mw.current_df) and retries > 0:
            QTimer.singleShot(50, lambda: self.restore_scroll_position(retries - 1))
        else:
            sb.setValue(self.mw.pending_scroll)
            del self.mw.pending_scroll
            self.mw.sidebar.setEnabled(True)
            self.mw.list_widget.setEnabled(True)
            self.mw.sidebar.search_bar.setFocus()