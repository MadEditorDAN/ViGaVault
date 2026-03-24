import pandas as pd
from PySide6.QtCore import Qt, QTimer, QObject, QAbstractListModel, QModelIndex, QSize
from PySide6.QtWidgets import QStyledItemDelegate, QAbstractItemView
from widgets import GameCard
from ViGaVault_utils import DEFAULT_DISPLAY_SETTINGS

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
        # WHY: Because every card's height is now strictly locked to the image size, 
        # the Delegate can instantly calculate row heights without querying the database or doing complex text math.
        settings = getattr(self.lc.mw, 'display_settings', DEFAULT_DISPLAY_SETTINGS)
        img_h = int(settings.get('image', DEFAULT_DISPLAY_SETTINGS['image']) * 1.33)
        # WHY: 10px internal card padding + 10px external QListView padding = 20px total bounding compensation.
        return QSize(option.rect.width(), img_h + 20)

class ListController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.model = GameListModel()
        self.mw.list_widget.setModel(self.model)
        self.delegate = GameDelegate(self)
        self.mw.list_widget.setItemDelegate(self.delegate)
        
        self.active_widgets = {}
        
        self.mw.list_widget.verticalScrollBar().valueChanged.connect(self.update_visible_widgets)

    def check_scroll_load(self, value):
        pass # WHY: Obsolete in virtualized architecture, but kept as an empty stub to prevent legacy connection crashes.

    def load_more_items(self):
        """WHY: Virtualized Model-View Architecture. 
        Calculates mathematics in memory instantly and defers widget creation purely to the scrolling viewport."""
        vp_width = self.mw.list_widget.viewport().width()
        current_width = vp_width if vp_width > 100 else 600
        widget_w = current_width - 10 # WHY: Account for standard padding instead of the legacy massive borders.
        
        # WHY: Clear tracking BEFORE resetting model. Qt inherently deletes old index widgets during a model reset.
        self.active_widgets.clear()
        
        self.model.beginResetModel()
        self.model.df = self.mw.current_df
        
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
        widget_w = current_width - 10
        
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
                card.setFixedWidth(widget_w)
                
                self.active_widgets[row] = card
                self.mw.list_widget.setIndexWidget(self.model.index(row, 0), card)

    def update_item_sizes(self):
        vp_width = self.mw.list_widget.viewport().width()
        current_width = vp_width if vp_width > 100 else 600
        widget_w = current_width - 10
        
        if abs(current_width - self.mw.last_viewport_width) < 2: return
            
        top_index = self.mw.list_widget.indexAt(self.mw.list_widget.viewport().rect().topLeft())
        
            
        self.model.layoutChanged.emit()
        self.mw.last_viewport_width = current_width

        for row, card in list(self.active_widgets.items()):
            try:
                card.setFixedWidth(widget_w)
                card.adjustSize()
            except RuntimeError:
                pass
        
        if top_index.isValid():
            self.mw.list_widget.scrollTo(top_index, QAbstractItemView.PositionAtTop)

    def update_single_card(self, folder_name, force_media_reload=False):
        # WHY: Use enumerate to find the true positional index (0-based) rather than the DataFrame's index label. 
        # The label causes IndexError with iloc[] when the DataFrame is sorted or filtered.
        positions = [i for i, f in enumerate(self.mw.current_df['Folder_Name']) if f == folder_name]
        if not positions: return
        row = positions[0]
        
        game_dict = self.mw.current_df.iloc[row].to_dict()
        
        current_width = self.mw.last_viewport_width
        widget_w = current_width - 10
        
        if row in self.active_widgets:
            card = self.active_widgets[row]
            card.data = game_dict
            card.refresh_ui_from_data(force_media_reload=force_media_reload)
            card.setFixedWidth(widget_w)
            
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
        
        # WHY: Force the QListView to re-evaluate its CSS palette variables (like horizontal borders and selection highlight) during theme switches.
        sheet = self.mw.list_widget.styleSheet()
        self.mw.list_widget.setStyleSheet("")
        self.mw.list_widget.setStyleSheet(sheet)
        
        current_width = self.mw.last_viewport_width
        widget_w = current_width - 10
            
        self.model.layoutChanged.emit()
        
        for card in list(self.active_widgets.values()):
            try:
                card.update_style(settings)
                card.setFixedWidth(widget_w)
                card.adjustSize()
            except RuntimeError:
                pass
            
        if top_index.isValid():
            self.mw.list_widget.scrollTo(top_index, QAbstractItemView.PositionAtTop)