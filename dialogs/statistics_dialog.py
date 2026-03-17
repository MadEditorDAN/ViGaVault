# WHY: Single Responsibility Principle - Handles ONLY the generation and display of Pandas-driven statistics.
import pandas as pd
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QWidget, QLabel, 
                               QPushButton, QFormLayout, QSizePolicy, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QAbstractItemView, QStyledItemDelegate, QStyleOptionProgressBar, 
                               QApplication, QStyle, QTextBrowser)
from PySide6.QtCore import Qt

from ViGaVault_utils import translator

class ProgressBarDelegate(QStyledItemDelegate):
    """
    WHY: Draws a progress bar natively inside the cell. 
    Using setCellWidget() breaks table sorting (widgets don't move when sorted).
    This delegate guarantees the progress bar follows the data when headers are clicked.
    """
    def paint(self, painter, option, index):
        val = index.data(Qt.EditRole)
        max_val = index.data(Qt.UserRole)
        show_text = index.data(Qt.UserRole + 1)
        
        if val is not None and max_val:
            opts = QStyleOptionProgressBar()
            opts.rect = option.rect
            opts.minimum = 0
            opts.maximum = int(max_val)
            opts.progress = int(val)
            if show_text:
                opts.textVisible = True
                opts.text = str(val)
                opts.textAlignment = Qt.AlignCenter
            else:
                opts.textVisible = False
            QApplication.style().drawControl(QStyle.CE_ProgressBar, opts, painter)
        else:
            super().paint(painter, option, index)

class StatisticsDialog(QDialog):
    def __init__(self, df, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("tools_stats_title"))
        # WHY: Increased vertical starting height to 900 to comfortably fit the new HTML QLabel and bottom graphs.
        self.resize(1300, 900)
        self.df = df
        
        # WHY: Shift the dialog background to the darker 'Base' color (matching the GameCard list)
        # to guarantee the 'Highlight' text selection color is vividly visible against it.
        self.setObjectName("stats_window")
        self.setStyleSheet("QDialog#stats_window, QScrollArea, QWidget#stats_container { background-color: palette(base); }")
        
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        container = QWidget()
        container.setObjectName("stats_container")
        dashboard_layout = QVBoxLayout(container)
        
        lbl_overview = QLabel(translator.tr("tools_stats_overview"))
        lbl_overview.setStyleSheet("font-size: 18px; font-weight: bold;")
        dashboard_layout.addWidget(lbl_overview)
        
        dashboard_layout.addWidget(self.create_overview_section())
        
        graphs_layout = QHBoxLayout()
        graphs_layout.addWidget(self.create_distribution_section("Platforms", translator.tr("tools_stats_platforms")))
        graphs_layout.addWidget(self.create_distribution_section("Genre", translator.tr("tools_stats_genres")))
        graphs_layout.addWidget(self.create_timeline_section())
        
        dashboard_layout.addLayout(graphs_layout)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        btn_close = QPushButton(translator.tr("btn_close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

    def create_overview_section(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 15)
        
        total_games = len(self.df)
        scrapped = len(self.df[self.df['Status_Flag'].isin(['OK', 'LOCKED'])])
        incomplete = total_games - scrapped
        
        boxes_layout = QHBoxLayout()

        def add_stat_card(title, value, color):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet(f"background-color: {color}; border-radius: 10px; color: white;")
            fl = QVBoxLayout(frame)
            lbl_val = QLabel(str(value))
            lbl_val.setStyleSheet("font-size: 36px; font-weight: bold;")
            lbl_val.setAlignment(Qt.AlignCenter)
            lbl_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("font-size: 14px;")
            lbl_title.setAlignment(Qt.AlignCenter)
            lbl_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
            fl.addWidget(lbl_val)
            fl.addWidget(lbl_title)
            boxes_layout.addWidget(frame, 1)

        add_stat_card(translator.tr("tools_stats_total"), total_games, "#2196F3")
        add_stat_card(translator.tr("tools_stats_scrapped"), scrapped, "#4CAF50")
        add_stat_card(translator.tr("tools_stats_incomplete"), incomplete, "#FF9800")
        layout.addLayout(boxes_layout)

        stats_data = []

        def get_top_count(col):
            if col not in self.df.columns: return "N/A"
            all_vals = []
            for x in self.df[col].dropna():
                all_vals.extend([v.strip() for v in str(x).split(',') if v.strip()])
            if not all_vals: return "N/A"
            c = pd.Series(all_vals).value_counts()
            return f"{c.idxmax()} ({c.max()})"
            
        def get_unique_count(col):
            if col not in self.df.columns: return 0
            all_vals = {v.strip() for x in self.df[col].dropna() for v in str(x).split(',') if v.strip()}
            return len(all_vals)

        stats_data.append(("tools_stats_top_plat", get_top_count('Platforms')))
        stats_data.append(("tools_stats_top_genre", get_top_count('Genre')))
        stats_data.append(("tools_stats_top_dev", get_top_count('Developer')))
        stats_data.append(("tools_stats_top_pub", get_top_count('Publisher')))
        stats_data.append(("tools_stats_total_col", get_unique_count('Collection')))
        stats_data.append(("tools_stats_top_col", get_top_count('Collection')))
        stats_data.append(("tools_stats_unique_devs", get_unique_count('Developer')))
        
        years = pd.to_datetime(self.df['Original_Release_Date'], errors='coerce', dayfirst=True).dt.year if 'Original_Release_Date' in self.df.columns else pd.Series(dtype=int)
        if not years.dropna().empty:
            yc = years.value_counts()
            stats_data.append(("tools_stats_best_year", f"{int(yc.idxmax())} ({yc.max()})"))
        else:
            stats_data.append(("tools_stats_best_year", "N/A"))

        has_img = len(self.df[self.df['Image_Link'].astype(str).str.strip() != '']) if 'Image_Link' in self.df.columns else 0
        media_pct = round((has_img / total_games * 100) if total_games else 0, 1)
        stats_data.append(("tools_stats_media_comp", f"{media_pct}% ({has_img})"))

        has_trailer = len(self.df[(self.df['Trailer_Link'].astype(str).str.strip() != '') | (self.df['Path_Video'].astype(str).str.strip() != '')]) if 'Trailer_Link' in self.df.columns else 0
        stats_data.append(("tools_stats_trailer_hoarder", has_trailer))

        indie_count = self.df['Genre'].astype(str).str.contains('Indie', case=False, na=False).sum() if 'Genre' in self.df.columns else 0
        stats_data.append(("tools_stats_indie_games", indie_count))
        
        if 'Original_Release_Date' in self.df.columns:
            valid_dates = self.df[pd.to_datetime(self.df['Original_Release_Date'], errors='coerce', dayfirst=True).notna()].copy()
            if not valid_dates.empty:
                valid_dates['DateObj'] = pd.to_datetime(valid_dates['Original_Release_Date'], errors='coerce', dayfirst=True)
                sorted_dates = valid_dates.sort_values('DateObj')
                oldest = sorted_dates.iloc[0]
                newest = sorted_dates.iloc[-1]
                stats_data.append(("tools_stats_oldest_relic", f"{oldest['Clean_Title']} ({oldest['DateObj'].year})"))
                stats_data.append(("tools_stats_newest_edge", f"{newest['Clean_Title']} ({newest['DateObj'].year})"))
            else:
                stats_data.extend([("tools_stats_oldest_relic", "N/A"), ("tools_stats_newest_edge", "N/A")])

        if 'Clean_Title' in self.df.columns:
            valid_titles = self.df['Clean_Title'].dropna().astype(str)
            if not valid_titles.empty:
                lengths = valid_titles.str.len()
                stats_data.append(("tools_stats_longest_title", valid_titles.loc[lengths.idxmax()]))
                stats_data.append(("tools_stats_shortest_title", valid_titles.loc[lengths.idxmin()]))
                
                import re
                words = []
                stopwords = {'the', 'of', 'and', 'in', 'to', 'a', 'for', 'on', 'with', 'edition', 'game', 'hd', 'remastered', 'collection', 'director', 'cut'}
                for title in valid_titles:
                    w_list = re.findall(r'\b[^\d\W_]{3,}\b', title.lower())
                    words.extend([w for w in w_list if w not in stopwords])
                if words:
                    stats_data.append(("tools_stats_common_word", pd.Series(words).value_counts().idxmax().title()))
                else:
                    stats_data.append(("tools_stats_common_word", "N/A"))
            else:
                stats_data.extend([("tools_stats_longest_title", "N/A"), ("tools_stats_shortest_title", "N/A"), ("tools_stats_common_word", "N/A")])

        if 'Summary' in self.df.columns:
            valid_sums = self.df['Summary'].fillna('').astype(str)
            sum_lengths = valid_sums.str.len()
            if not sum_lengths.empty and sum_lengths.max() > 0:
                stats_data.append(("tools_stats_longest_sum", self.df.loc[sum_lengths.idxmax(), 'Clean_Title']))
            else:
                stats_data.append(("tools_stats_longest_sum", "N/A"))
            stats_data.append(("tools_stats_no_sum", len(valid_sums[valid_sums.str.strip() == ''])))
            
        if 'Platforms' in self.df.columns:
            local_copy_count = len(self.df[self.df['Platforms'].astype(str).str.lower() == 'local copy'])
            local_copy_pct = round((local_copy_count / total_games * 100) if total_games else 0, 1)
            stats_data.append(("tools_stats_local_copy_ratio", f"{local_copy_pct}% ({local_copy_count})"))

        num_items = len(stats_data)
        items_per_col = (num_items + 2) // 3

        # WHY: Replaced isolated QLabels with a single unified QTextBrowser using an HTML table.
        # This allows fluid, native block-text selection across all columns and rows simultaneously.
        html = "<table width='100%' cellspacing='10'><tr>"
        
        for col_idx in range(3):
            start_idx = col_idx * items_per_col
            end_idx = min(start_idx + items_per_col, num_items)
            col_data = stats_data[start_idx:end_idx]
            
            html += "<td valign='top'><table width='100%' cellspacing='8'>"
            for key, val in col_data:
                if key == "tools_stats_common_word" and val != "N/A":
                    val = f"'{val}'"
                title_str = translator.tr(key)
                html += f"<tr><td align='right' width='50%'>{title_str} :</td><td align='left' width='50%'><b>{val}</b></td></tr>"
            html += "</table></td>"
            
        html += "</tr></table>"
        
        # WHY: Switched from QTextBrowser to a single rich-text QLabel. 
        # QLabel intrinsically understands HTML layout math (fixing the massive gap), 
        # and natively uses OS-level selection colors (fixing the invisible highlight).
        lbl_stats = QLabel()
        lbl_stats.setTextFormat(Qt.RichText)
        lbl_stats.setText(html)
        lbl_stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_stats.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lbl_stats.setWordWrap(True)
        
        layout.addWidget(lbl_stats)
        return widget

    def create_distribution_section(self, col_name, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        all_values = []
        for item in self.df[col_name].dropna():
            parts = [x.strip() for x in str(item).split(',') if x.strip()]
            all_values.extend(parts)
            
        counts = pd.Series(all_values).value_counts()
        
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([title, translator.tr("tools_stats_col_count"), translator.tr("tools_stats_col_dist")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setRowCount(len(counts))
        
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        
        delegate = ProgressBarDelegate(table)
        table.setItemDelegateForColumn(2, delegate)

        max_val = counts.max() if not counts.empty else 1
        
        for i, (name, count) in enumerate(counts.items()):
            item_name = QTableWidgetItem()
            item_name.setData(Qt.EditRole, name)
            table.setItem(i, 0, item_name)
            
            item_count = QTableWidgetItem()
            item_count.setData(Qt.EditRole, int(count))
            table.setItem(i, 1, item_count)
            
            item_pbar = QTableWidgetItem()
            item_pbar.setData(Qt.EditRole, int(count))
            item_pbar.setData(Qt.UserRole, int(max_val))
            item_pbar.setData(Qt.UserRole + 1, False)
            table.setItem(i, 2, item_pbar)
            
        table.setSortingEnabled(True)
        table.sortItems(1, Qt.DescendingOrder)
            
        layout.addWidget(table)
        return widget

    def create_timeline_section(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        years = pd.to_datetime(self.df['Original_Release_Date'], errors='coerce', dayfirst=True).dt.year
        year_counts = years.dropna().astype(int).value_counts().sort_index()
        
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels([translator.tr("tools_stats_col_year"), translator.tr("tools_stats_col_released")])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setRowCount(len(year_counts))
        
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        
        delegate = ProgressBarDelegate(table)
        table.setItemDelegateForColumn(1, delegate)
        
        max_val = year_counts.max() if not year_counts.empty else 1
        
        for i, (year, count) in enumerate(year_counts.items()):
            item_year = QTableWidgetItem()
            item_year.setData(Qt.EditRole, int(year))
            table.setItem(i, 0, item_year)
            
            item_pbar = QTableWidgetItem()
            item_pbar.setData(Qt.EditRole, int(count))
            item_pbar.setData(Qt.UserRole, int(max_val))
            item_pbar.setData(Qt.UserRole + 1, True)
            table.setItem(i, 1, item_pbar)
            
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.AscendingOrder)
            
        layout.addWidget(table)
        return widget