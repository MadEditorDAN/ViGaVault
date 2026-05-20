# WHY: Single Responsibility Principle - Isolates complex backup and restore UI logic, 
# ensuring the main controller isn't bloated with archive analysis flows and modular checkboxes.
import os
import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                               QCheckBox, QFileDialog, QMessageBox, QGroupBox)
from PySide6.QtCore import Qt

from ViGaVault_utils import translator, center_window
from backend.backup_manager import create_vgv_backup, analyze_vgv_backup, restore_vgv_backup

class BackupDialog(QDialog):
    def __init__(self, db_path, image_path, global_settings, lib_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("menu_file_export") + " (.vgv)")
        self.setMinimumWidth(400)
        center_window(self, parent)
        
        self.db_path = db_path
        self.image_path = image_path
        self.global_settings = global_settings
        self.lib_settings = lib_settings
        
        layout = QVBoxLayout(self)
        
        group = QGroupBox("Select Data to Backup")
        g_layout = QVBoxLayout(group)
        
        self.chk_db = QCheckBox("Database (.dat)")
        self.chk_db.setChecked(True)
        g_layout.addWidget(self.chk_db)
        
        self.chk_images = QCheckBox("Cached Covers (Images)")
        self.chk_images.setChecked(True)
        g_layout.addWidget(self.chk_images)
        
        self.chk_settings = QCheckBox("Application Settings")
        self.chk_settings.setChecked(True)
        g_layout.addWidget(self.chk_settings)
        
        layout.addWidget(group)
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        btn_cancel.clicked.connect(self.reject)
        
        self.btn_backup = QPushButton(translator.tr("settings_btn_save"))
        self.btn_backup.clicked.connect(self.execute_backup)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_backup)
        layout.addLayout(btn_layout)

    def execute_backup(self):
        # WHY: Always provide a safe file dialog so the user dictates exactly where the backup lives.
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Backup", "ViGaVault_Backup.vgv", "ViGaVault Backup (*.vgv)")
        if not file_path:
            return
            
        if not file_path.lower().endswith('.vgv'):
            file_path += '.vgv'
            
        try:
            self.btn_backup.setEnabled(False)
            self.btn_backup.setText("Processing...")
            self.repaint() # Force UI update before heavy blocking IO
            
            # WHY: Only pass paths if the user checked them, else pass a dummy empty path
            db_p = self.db_path if self.chk_db.isChecked() else ""
            img_p = self.image_path if self.chk_images.isChecked() else ""
            glob_set = self.global_settings if self.chk_settings.isChecked() else {}
            lib_set = self.lib_settings if self.chk_settings.isChecked() else {}
            
            create_vgv_backup(db_p, img_p, glob_set, lib_set, file_path)
            
            QMessageBox.information(self, "Success", "Backup generated successfully!")
            self.accept()
        except Exception as e:
            logging.error(f"Backup failed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to generate backup:\n{e}")
        finally:
            self.btn_backup.setEnabled(True)
            self.btn_backup.setText(translator.tr("settings_btn_save"))


class RestoreDialog(QDialog):
    def __init__(self, target_db_dir, target_img_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translator.tr("menu_file_import") + " (.vgv)")
        self.setMinimumWidth(400)
        center_window(self, parent)
        
        self.target_db_dir = target_db_dir
        self.target_img_dir = target_img_dir
        self.backup_path = None
        self.restored_global = None
        self.restored_lib = None
        self.restored_db_path = None
        
        self.layout = QVBoxLayout(self)
        
        # Step 1: File selection
        self.btn_select = QPushButton("Select .vgv Backup File")
        self.btn_select.clicked.connect(self.select_file)
        self.layout.addWidget(self.btn_select)
        
        # Step 2: Modules (hidden initially)
        self.group = QGroupBox("Available Modules")
        self.g_layout = QVBoxLayout(self.group)
        
        self.chk_db = QCheckBox("Database")
        self.chk_images = QCheckBox("Cached Covers")
        self.chk_settings = QCheckBox("Settings")
        
        self.g_layout.addWidget(self.chk_db)
        self.g_layout.addWidget(self.chk_images)
        self.g_layout.addWidget(self.chk_settings)
        
        self.group.setVisible(False)
        self.layout.addWidget(self.group)
        
        # Step 3: Actions
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton(translator.tr("settings_btn_cancel"))
        btn_cancel.clicked.connect(self.reject)
        
        self.btn_restore = QPushButton("Restore Selected")
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self.execute_restore)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_restore)
        self.layout.addLayout(btn_layout)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Backup", "", "ViGaVault Backup (*.vgv)")
        if file_path:
            self.backup_path = file_path
            self.btn_select.setText(os.path.basename(file_path))
            self.analyze_file()

    def analyze_file(self):
        try:
            analysis = analyze_vgv_backup(self.backup_path)
            if not analysis:
                QMessageBox.warning(self, "Invalid Backup", "The selected file could not be analyzed.")
                return
                
            self.group.setVisible(True)
            self.btn_restore.setEnabled(True)
            
            # WHY: Dynamically enable checkboxes strictly based on archive contents.
            self.chk_db.setEnabled(analysis['hasDb'])
            self.chk_db.setChecked(analysis['hasDb'])
            
            self.chk_images.setEnabled(analysis['hasImages'])
            self.chk_images.setChecked(analysis['hasImages'])
            
            self.chk_settings.setEnabled(analysis['hasSettings'])
            self.chk_settings.setChecked(analysis['hasSettings'])
            
        except Exception as e:
            logging.error(f"Failed to analyze backup: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open backup:\n{e}")

    def execute_restore(self):
        try:
            self.btn_restore.setEnabled(False)
            self.btn_restore.setText("Processing...")
            self.repaint() # Force UI update
            
            result = restore_vgv_backup(
                self.backup_path, 
                restore_db=self.chk_db.isChecked(),
                restore_images=self.chk_images.isChecked(),
                restore_settings=self.chk_settings.isChecked(),
                target_db_dir=self.target_db_dir,
                target_img_dir=self.target_img_dir
            )
            
            self.restored_global = result['global_settings']
            self.restored_lib = result['lib_settings']
            self.restored_db_path = result['db_path']
            
            QMessageBox.information(self, "Success", "Backup restored successfully! The application UI will now refresh.")
            self.accept()
        except Exception as e:
            logging.error(f"Restore failed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to restore backup:\n{e}")
        finally:
            self.btn_restore.setEnabled(True)
            self.btn_restore.setText("Restore Selected")
