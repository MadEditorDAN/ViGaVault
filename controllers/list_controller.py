import pandas as pd
from PySide6.QtCore import Qt, QTimer, QObject, QAbstractListModel, QModelIndex, QSize
from PySide6.QtWidgets import QStyledItemDelegate, QAbstractItemView
from ViGaVault_widgets import GameCard

class GameListModel(QAbstractListModel):
    def __init__(self, df=pd.DataFrame()):
        super().__init__()
        self.df = df

    def rowCount(self, parent=QModelIndex()):
        return len(self.df)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        if role == Qt.UserRole: return self.df.iloc[index.row()].to_dict()
        elif role == Qt.UserRole + 1: return self.df.iloc[index.row()]['Folder_Name']
        return None

class GameDelegate(QStyledItemDelegate):
    def __init__(self, list_controller):
        super().__init__()
        self.lc = list_controller
    def sizeHint(self, option, index):
        row = index.row()
        if row < len(self.lc.row_heights): return self.lc.row_heights[row]
        return QSize(option.rect.width(), 200)

class ListController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.model = GameListModel()
        self.mw.list_widget.setModel(self.model)
        self.delegate = GameDelegate(self)
        self.mw.list_widget.setItemDelegate(self.delegate)
        
        self.active_widgets = {}
        self.row_heights = []
        self.dummy_card = GameCard({}, self.mw, self.mw.list_widget)
        self.dummy_card.hide()
        
        self.mw.list_widget.verticalScrollBar().valueChanged.connect(self.update_visible_widgets)

    def check_scroll_load(self, value):
        pass # WHY: Obsolete in virtualized architecture, but kept as an empty stub to prevent legacy connection crashes.

    def load_more_items(self):
        """WHY: Virtualized Model-View Architecture. 
        Calculates mathematics in memory instantly and defers widget creation purely to the scrolling viewport."""
        vp_width = self.mw.list_widget.viewport().width()
        current_width = vp_width if vp_width > 100 else 600
        
        # WHY: Clear tracking BEFORE resetting model. Qt inherently deletes old index widgets during a model reset.
        self.active_widgets.clear()
        
        self.model.beginResetModel()
        self.model.df = self.mw.current_df
        
        self.row_heights = []
        for i in range(len(self.mw.current_df)):
            game_dict = self.mw.current_df.iloc[i].to_dict()
            self.dummy_card.set_data_for_height_calc(game_dict)
            size = self.dummy_card.calculate_size_hint(current_width)
            self.row_heights.append(size)
            
        self.model.endResetModel()
        
        self.mw.last_viewport_width = current_width
        
        
        self.mw.loaded_count = len(self.mw.current_df) 
        self.mw.background_loader.stop()
        
        self.update_visible_widgets()

    def update_visible_widgets(self):
        if self.model.rowCount() == 0: return
        
        viewport = self.mw.list_widget.viewport()
        top_index = self.mw.list_widget.indexAt(viewport.rect().topLeft())
        bottom_index = self.mw.list_widget.indexAt(viewport.rect().bottomRight())
        
        if not top_index.isValid(): start_row = self.mw.list_widget.verticalScrollBar().value() // 200
        else: start_row = top_index.row()
            
        if not bottom_index.isValid(): end_row = min(self.model.rowCount() - 1, start_row + 10)
        else: end_row = bottom_index.row()
            
        start_row = max(0, start_row - 2)
        end_row = min(self.model.rowCount() - 1, end_row + 2)
        
        visible_rows = set(range(start_row, end_row + 1))
        current_width = viewport.width() if viewport.width() > 100 else 600
        
        for row in list(self.active_widgets.keys()):
            if row not in visible_rows:
                card = self.active_widgets.pop(row)
                # WHY: Setting index widget to None delegates C++ object deletion entirely to the Qt View.
                self.mw.list_widget.setIndexWidget(self.model.index(row, 0), None)
                
        for row in visible_rows:
            if row not in self.active_widgets:
                # WHY: Instantiate fresh widgets since Qt inherently destroys removed index widgets. Fast since disk I/O is gone.
                card = GameCard({}, self.mw, self.mw.list_widget)
                game_dict = self.model.df.iloc[row].to_dict()
                card.data = game_dict
                card.current_row = row 
                card.refresh_ui_from_data(force_media_reload=False)
                card.setFixedWidth(current_width)
                
                self.active_widgets[row] = card
                self.mw.list_widget.setIndexWidget(self.model.index(row, 0), card)

    def update_item_sizes(self):
        vp_width = self.mw.list_widget.viewport().width()
        current_width = vp_width if vp_width > 100 else 600
        
        if abs(current_width - self.mw.last_viewport_width) < 2: return
            
        top_index = self.mw.list_widget.indexAt(self.mw.list_widget.viewport().rect().topLeft())
        
        self.row_heights = []
        for i in range(len(self.mw.current_df)):
            game_dict = self.mw.current_df.iloc[i].to_dict()
            self.dummy_card.set_data_for_height_calc(game_dict)
            size = self.dummy_card.calculate_size_hint(current_width)
            self.row_heights.append(size)
            
        self.model.layoutChanged.emit()
        self.mw.last_viewport_width = current_width

        for row, card in list(self.active_widgets.items()):
            try:
                card.setFixedWidth(current_width)
                card.adjustSize()
            except RuntimeError:
                pass
        
        if top_index.isValid():
            self.mw.list_widget.scrollTo(top_index, QAbstractItemView.PositionAtTop)

    def update_single_card(self, folder_name, force_media_reload=False):
        c_idx = self.mw.current_df.index[self.mw.current_df['Folder_Name'] == folder_name].tolist()
        if not c_idx: return
        row = c_idx[0]
        
        game_dict = self.mw.current_df.iloc[row].to_dict()
        
        current_width = self.mw.last_viewport_width
        self.dummy_card.set_data_for_height_calc(game_dict)
        self.row_heights[row] = self.dummy_card.calculate_size_hint(current_width)
        
        if row in self.active_widgets:
            card = self.active_widgets[row]
            card.data = game_dict
            card.refresh_ui_from_data(force_media_reload=force_media_reload)
            card.setFixedWidth(current_width)
            
        self.model.dataChanged.emit(self.model.index(row, 0), self.model.index(row, 0))

    def remove_single_card(self, folder_name):
        self.load_more_items()

    def catch_up_to_anchor(self, target_row):
        """WHY: Virtualized list calculates geometry instantly in memory, so we can jump to the anchor mathematically."""
        if 0 <= target_row < self.model.rowCount():
            index = self.model.index(target_row, 0)
            if target_row > 0:
                prev_index = self.model.index(target_row - 1, 0)
                self.mw.list_widget.scrollTo(prev_index, QAbstractItemView.PositionAtTop)
            else:
                self.mw.list_widget.scrollTo(index, QAbstractItemView.PositionAtTop)
            self.update_visible_widgets()

    def apply_display_settings(self, settings):
        top_index = self.mw.list_widget.indexAt(self.mw.list_widget.viewport().rect().topLeft())
        self.dummy_card.update_style(settings)
        
        current_width = self.mw.last_viewport_width
        self.row_heights = []
        for i in range(len(self.mw.current_df)):
            game_dict = self.mw.current_df.iloc[i].to_dict()
            self.dummy_card.set_data_for_height_calc(game_dict)
            size = self.dummy_card.calculate_size_hint(current_width)
            self.row_heights.append(size)
            
        self.model.layoutChanged.emit()
        
        for card in list(self.active_widgets.values()):
            try:
                card.update_style(settings)
                card.setFixedWidth(current_width)
                card.adjustSize()
            except RuntimeError:
                pass
            
        if top_index.isValid():
            self.mw.list_widget.scrollTo(top_index, QAbstractItemView.PositionAtTop)