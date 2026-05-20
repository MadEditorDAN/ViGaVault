import pytest
from PySide6.QtCore import Qt
from dialogs.backup_restore_dialogs import BackupDialog

def test_backup_dialog_checkboxes(safe_sandbox, mock_settings, qtbot):
    """
    Tests that the BackupDialog successfully renders and correctly maps the 
    split configuration dictionaries into its checkboxes using pytest-qt.
    """
    global_set = mock_settings["global"]
    lib_set = mock_settings["lib"]
    
    dialog = BackupDialog(
        db_path="dummy_db",
        image_path="dummy_img",
        global_settings=global_set,
        lib_settings=lib_set,
        parent=None
    )
    qtbot.addWidget(dialog)
    
    # Assert initial visual states
    assert dialog.chk_db.isChecked() is True
    assert dialog.chk_images.isChecked() is True
    assert dialog.chk_settings.isChecked() is True
    
    # Programmatically interact with the UI elements headless
    dialog.chk_images.setChecked(False)
    assert dialog.chk_images.isChecked() is False
    
    # Re-check and ensure it responds
    dialog.chk_images.setChecked(True)
    assert dialog.chk_images.isChecked() is True
