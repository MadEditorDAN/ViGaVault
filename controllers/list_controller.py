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
        
        # WHY: Anchor to the top visible item to prevent the view from jumping when resizing.
        top_item = self.mw.list_widget.itemAt(0, 0)

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
        
        if top_item:
            self.mw.list_widget.scrollToItem(top_item, QAbstractItemView.PositionAtTop)

    def update_single_card(self, folder_name):
        """WHY: Finds a specific GameCard and forces it to redraw using updated memory data."""
        row_data = self.mw.master_df[self.mw.master_df['Folder_Name'] == folder_name]
        if row_data.empty: return
        game_dict = row_data.iloc[0].to_dict()
        
        for i in range(self.mw.list_widget.count()):
            item = self.mw.list_widget.item(i)
            if item.data(Qt.UserRole) == folder_name:
                card = self.mw.list_widget.itemWidget(item)
                if card:
                    card.data = game_dict
                    card.refresh_ui_from_data()
                    item.setSizeHint(card.calculate_size_hint(card.width()))
                break

    def remove_single_card(self, folder_name):
        """WHY: Visually destroys a GameCard instantly without a full database reload (Used in Merges)."""
        for i in range(self.mw.list_widget.count()):
            item = self.mw.list_widget.item(i)
            if item.data(Qt.UserRole) == folder_name:
                self.mw.list_widget.takeItem(i)
                if self.mw.loaded_count > 0:
                    self.mw.loaded_count -= 1
                self.mw.sidebar.lbl_counter.setText(f"{len(self.mw.current_df)}/{len(self.mw.master_df)}")
                break

    def apply_display_settings(self, settings):
        """WHY: Extremely fast loop to dynamically scale all visual cards during setting changes."""
        # WHY: Anchor to the top visible item to prevent the view from jumping when settings change.
        top_item = self.mw.list_widget.itemAt(0, 0)
        
        for i in range(self.mw.list_widget.count()):
            item = self.mw.list_widget.item(i)
            card = self.mw.list_widget.itemWidget(item)
            if card:
                card.update_style(settings)
                item.setSizeHint(card.calculate_size_hint(card.width()))
                
        if top_item:
            self.mw.list_widget.scrollToItem(top_item, QAbstractItemView.PositionAtTop)

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