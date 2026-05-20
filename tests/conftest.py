import os
import sys
import pytest
from unittest.mock import patch

# Ensure the root project directory is in the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

@pytest.fixture(autouse=True)
def safe_sandbox(tmp_path, monkeypatch):
    """
    WHY: Secure Sandbox Pattern.
    Automatically intercepts file paths across the application to guarantee that 
    automated tests never overwrite or corrupt the user's real settings or database.
    """
    # Redirect BASE_DIR in ViGaVault_utils
    monkeypatch.setattr("ViGaVault_utils.BASE_DIR", str(tmp_path))
    
    # Also patch commonly imported references in controllers
    try:
        monkeypatch.setattr("controllers.settings_controller.BASE_DIR", str(tmp_path))
    except AttributeError:
        pass
        
    try:
        monkeypatch.setattr("controllers.library_controller.BASE_DIR", str(tmp_path))
    except AttributeError:
        pass

    yield tmp_path

@pytest.fixture
def mock_settings(safe_sandbox):
    """Creates isolated, dummy settings files within the temporary sandbox."""
    from ViGaVault_utils import save_encrypted_json
    
    global_settings = {
        "theme": "Dark",
        "language": "English",
        "dateFormat": "DD/MM/YYYY",
        "libraryName": "VGVDB.dat"
    }
    save_encrypted_json(os.path.join(safe_sandbox, "settings.bin"), global_settings)
    
    lib_settings = {
        "rootPath": "C:\\MockGames",
        "scanSteam": True,
        "downloadImages": True
    }
    save_encrypted_json(os.path.join(safe_sandbox, "VGVDB.bin"), lib_settings)
    
    return {"global": global_settings, "lib": lib_settings}
