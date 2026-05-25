import os
import pytest
from backend.backup_manager import create_vgv_backup, analyze_vgv_backup, restore_vgv_backup

def test_backup_manager_merge_split(safe_sandbox, mock_settings):
    """
    Tests that create_vgv_backup successfully merges global and lib settings into a single 
    settings.json, and restore_vgv_backup successfully splits them back into two dicts.
    """
    db_path = os.path.join(safe_sandbox, "VGVDB.dat")
    with open(db_path, "w") as f:
        f.write("mock_db_data")
        
    img_path = os.path.join(safe_sandbox, "images")
    os.makedirs(img_path, exist_ok=True)
    
    backup_path = os.path.join(safe_sandbox, "backup.vgv")
    
    global_set = mock_settings["global"]
    lib_set = mock_settings["lib"]
    
    # 1. Test Backup Creation (Merge)
    create_vgv_backup(db_path, img_path, global_set, lib_set, backup_path)
    
    assert os.path.exists(backup_path), "Backup archive should be created"
    
    # 2. Test Analyze
    analysis = analyze_vgv_backup(backup_path)
    assert analysis is not None
    assert analysis["hasDb"] is True
    assert analysis["hasSettings"] is True
    
    # 3. Test Restore (Split)
    target_db_path = os.path.join(safe_sandbox, "restored_db", "VGVDB.dat")
    
    result = restore_vgv_backup(
        backup_path,
        restore_db=True,
        restore_images=False,
        restore_settings=True,
        target_db_path=target_db_path,
        target_img_dir=None
    )
    
    restored_global = result["global_settings"]
    restored_lib = result["lib_settings"]
    
    # Assert the split was successful based on the GLOBAL_KEYS logic
    assert restored_global["dateFormat"] == "DD/MM/YYYY"
    assert restored_global["language"] == "English"
    assert restored_global["theme"] == "Dark"
    assert restored_global["libraryName"] == "VGVDB.dat"
    
    assert restored_lib["scanSteam"] is True
    assert restored_lib["rootPath"] == "C:\\MockGames"
    assert restored_lib["downloadImages"] is True
    
    # Ensure keys didn't cross over
    assert "scanSteam" not in restored_global
    assert "dateFormat" not in restored_lib

def test_backup_manager_sessions(safe_sandbox, monkeypatch):
    import ViGaVault_utils
    # Base sandbox directory is automatically mocked by conftest
    base_dir = ViGaVault_utils.BASE_DIR
    
    # Create a mock platform session file
    igdb_session_dir = os.path.join(base_dir, "backend", "igdb")
    os.makedirs(igdb_session_dir, exist_ok=True)
    session_file_path = os.path.join(igdb_session_dir, "igdb_session.dat")
    with open(session_file_path, "w") as f:
        f.write("mock_session_key")
        
    db_path = os.path.join(safe_sandbox, "VGVDB.dat")
    with open(db_path, "w") as f:
        f.write("mock_db_data")
        
    img_path = os.path.join(safe_sandbox, "images")
    os.makedirs(img_path, exist_ok=True)
    
    backup_path = os.path.join(safe_sandbox, "backup_with_sessions.vgv")
    
    # 1. Test Backup Creation (should include sessions since settings are passed)
    global_set = {"dateFormat": "DD/MM/YYYY"}
    lib_set = {"scanSteam": True}
    create_vgv_backup(db_path, img_path, global_set, lib_set, backup_path)
    
    assert os.path.exists(backup_path), "Backup should be generated"
    
    # Remove local session file to verify restoration
    os.remove(session_file_path)
    assert not os.path.exists(session_file_path)
    
    # 2. Test Restore
    target_db_path = os.path.join(safe_sandbox, "restored_db", "VGVDB.dat")
    
    restore_vgv_backup(
        backup_path,
        restore_db=True,
        restore_images=False,
        restore_settings=True, # must be True to restore sessions
        target_db_path=target_db_path,
        target_img_dir=None
    )
    
    # Verify that the session file was restored back to backend/igdb/igdb_session.dat
    assert os.path.exists(session_file_path), "Session file should be restored"
    with open(session_file_path, "r") as f:
        content = f.read()
    assert content == "mock_session_key"
