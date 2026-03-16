import subprocess
import logging
import requests
import re
from datetime import datetime
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QMessageBox, QListWidgetItem
from PySide6.QtGui import QPixmap, QIcon

from ViGaVault_Scan import LibraryManager
from ViGaVault_utils import build_scanner_config, get_db_path, translator, QtLogSignal, QtLogHandler
from ViGaVault_workers import FullScanWorker

class ScanController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.log_signal = None
        self.qt_log_handler = None

    def update_sync_log(self, message):
        self.mw.sidebar.scan_results.addItem(message)
        self.mw.sidebar.scan_results.scrollToBottom()

    def start_full_scan(self):
        if self.mw.full_scan_in_progress:
            QMessageBox.information(self.mw, "Info", translator.tr("msg_task_in_progress"))
            return

        try:
            output = subprocess.check_output('tasklist', shell=True).decode(errors='ignore')
            if "GalaxyClient.exe" in output:
                reply = QMessageBox.question(self.mw, "GOG Galaxy Detected",
                                            "GOG Galaxy is running. It must be closed to access the database.\n\nPlease close it and click Yes.",
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No: return
        except: pass

        self.mw.full_scan_in_progress = True
        self.mw.sidebar.btn_full_scan.setEnabled(False)
        self.mw.sidebar.btn_full_scan.setText(translator.tr("sidebar_btn_scanning"))
        self.mw.sidebar.chk_show_new.setEnabled(False)
        self.mw.sidebar.chk_retry_failures.setEnabled(False)
        self.mw.filter_controller.set_filters_ui_state(False)

        self.mw.sidebar.scan_panel.show()
        self.mw.sidebar.scan_title_label.setText(translator.tr("sidebar_scan_title_full"))
        self.mw.sidebar.scan_input.hide()
        self.mw.sidebar.scan_btn.hide()
        self.mw.sidebar.scan_limit_combo.hide()
        self.mw.sidebar.btn_confirm.hide()
        self.mw.sidebar.btn_cancel.setText(translator.tr("sidebar_btn_stop"))
        self.mw.sidebar.scan_results.clear()
        self.mw.sidebar.scan_results.addItem(translator.tr("sidebar_log_scan_start"))

        try: self.mw.sidebar.btn_cancel.clicked.disconnect()
        except: pass
        self.mw.sidebar.btn_cancel.clicked.connect(self.stop_full_scan)

        self.log_signal = QtLogSignal()
        self.log_signal.message_written.connect(self.update_sync_log)
        self.qt_log_handler = QtLogHandler(self.log_signal)
        logging.getLogger().addHandler(self.qt_log_handler)

        do_retry = self.mw.sidebar.chk_retry_failures.isChecked()
        self.full_scan_worker = FullScanWorker(retry_failures=do_retry)
        self.full_scan_worker.finished.connect(self.finish_full_scan)
        self.full_scan_worker.start()

    def stop_full_scan(self):
        if self.mw.full_scan_in_progress and hasattr(self, 'full_scan_worker'):
            logging.info("--- Full Scan interrupted by user. ---")
            self.full_scan_worker.requestInterruption()
            self.mw.sidebar.scan_panel.hide()
            self.mw.filter_controller.set_filters_ui_state(True)
            self.restore_scan_panel()

    def finish_full_scan(self):
        logging.getLogger().removeHandler(self.qt_log_handler)
        
        self.mw.full_scan_in_progress = False
        self.mw.sidebar.btn_full_scan.setEnabled(True)
        self.mw.sidebar.btn_full_scan.setText(translator.tr("sidebar_btn_full_scan"))
        self.mw.sidebar.chk_show_new.setEnabled(True)
        self.mw.sidebar.chk_retry_failures.setEnabled(True)

        if self.mw.sidebar.scan_panel.isVisible():
            self.mw.sidebar.scan_results.addItem(translator.tr("sidebar_log_scan_finish"))
            self.mw.sidebar.scan_results.scrollToBottom()
            self.mw.sidebar.btn_cancel.setText(translator.tr("btn_close"))
            try: self.mw.sidebar.btn_cancel.clicked.disconnect()
            except: pass
            self.mw.sidebar.btn_cancel.clicked.connect(self.cancel_inline_scan)

        self.mw.library_controller.refresh_data()

    def start_inline_scan(self, game_data):
        self.mw.current_scan_game = game_data
        self.mw.sidebar.scan_panel.show()
        self.mw.filter_controller.set_filters_ui_state(False)
        self.restore_scan_panel()
        
        raw_name = game_data.get('Folder_Name', '')
        clean_name = re.sub(r'^\d{4}\s*-\s*', '', raw_name)
        clean_name = re.sub(r'\s*\([^)]*\)$', '', clean_name).strip()
        self.mw.sidebar.scan_input.setText(clean_name)
        
        self.mw.sidebar.scan_results.clear()
        item = QListWidgetItem(translator.tr("sidebar_log_searching"))
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        self.mw.sidebar.scan_results.addItem(item)
        self.mw.sidebar.scan_input.setFocus()

        QTimer.singleShot(50, self.run_inline_search)

    def on_manual_search_trigger(self):
        self.mw.sidebar.scan_results.clear()
        item = QListWidgetItem(translator.tr("sidebar_log_searching"))
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
        self.mw.sidebar.scan_results.addItem(item)
        QTimer.singleShot(50, self.run_inline_search)

    def run_inline_search(self):
        term = self.mw.sidebar.scan_input.text()
        if not term: return
        
        if not self.mw.current_scan_game:
            QMessageBox.warning(self.mw, "Error", "No game selected for scanning. Please click the scan icon on a game.")
            return
        
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        token = manager.get_access_token()

        limit = int(self.mw.sidebar.scan_limit_combo.currentText())
        candidates = manager.fetch_candidates(token, term, limit=limit)
        
        self.mw.sidebar.scan_results.clear()
        for g in candidates:
            year = ''
            if 'release_dates' in g and g['release_dates']:
                dates = [d['date'] for d in g['release_dates'] if 'date' in d]
                if dates:
                    try: year = datetime.utcfromtimestamp(min(dates)).strftime('%Y')
                    except Exception: pass

            display_text = g.get('name', 'Unknown')
            if year: display_text = f"{year} - {display_text}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, g)
            
            if 'cover' in g and 'url' in g['cover']:
                try:
                    img_url = "https:" + g['cover']['url'].replace("t_thumb", "t_cover_small")
                    data = requests.get(img_url, timeout=2).content
                    pix = QPixmap()
                    pix.loadFromData(data)
                    item.setIcon(QIcon(pix))
                except Exception: pass
            self.mw.sidebar.scan_results.addItem(item)

        if not candidates:
            item = QListWidgetItem(translator.tr("sidebar_log_no_results"))
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.mw.sidebar.scan_results.addItem(item)

    def restore_scan_panel(self):
        self.mw.sidebar.scan_title_label.setText(translator.tr("sidebar_manual_scan_title"))
        self.mw.sidebar.scan_input.show()
        self.mw.sidebar.scan_btn.show()
        self.mw.sidebar.scan_limit_combo.show()
        self.mw.sidebar.btn_confirm.show()
        self.mw.sidebar.btn_cancel.setText(translator.tr("sidebar_manual_scan_cancel_btn"))

    def cancel_inline_scan(self):
        self.mw.sidebar.scan_panel.hide()
        self.mw.filter_controller.set_filters_ui_state(True)
        self.mw.sidebar.scan_results.clear()
        self.mw.sidebar.scan_input.clear()
        self.restore_scan_panel()

    def apply_inline_selection(self):
        item = self.mw.sidebar.scan_results.currentItem()
        if not item: return
        
        chosen_game = item.data(Qt.UserRole)
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game_obj = manager.games.get(self.mw.current_scan_game.get('Folder_Name'))
        
        if game_obj.apply_candidate_data(chosen_game):
            while True:
                try:
                    manager.save_db()
                    break 
                except PermissionError:
                    reply = QMessageBox.warning(self.mw, "File Locked",
                                        translator.tr("msg_file_locked", db_path=get_db_path()),
                                        QMessageBox.Ok | QMessageBox.Cancel)
                    if reply == QMessageBox.Cancel:
                        return

            self.mw.pending_anchor_folder = self.mw.current_scan_game.get('Folder_Name')
            self.mw.library_controller.refresh_data()
            
            self.mw.sidebar.scan_results.clear()
            item = QListWidgetItem(translator.tr("sidebar_log_update_complete"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.mw.sidebar.scan_results.addItem(item)
            
            QTimer.singleShot(2000, self.cancel_inline_scan)