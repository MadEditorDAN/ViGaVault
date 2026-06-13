import sys
import os

sys.path.append(os.getcwd())
from ViGaVault_utils import build_scanner_config
from backend.library import LibraryManager
from backend.local_copy_scanner import scan_local_system

def test_scan():
    config = build_scanner_config()
    manager = LibraryManager(config)
    manager.load_db()

    print("Before scan:")
    for f, g in manager.games.items():
        if g.data.get('Status_Flag') == 'LOCKED':
            print(f"LOCKED: {f}")

    scan_local_system(config, manager.games)

    print("\nAfter scan:")
    for f, g in manager.games.items():
        if g.data.get('Status_Flag') == 'NEW' and g.data.get('Platforms') == 'Local Copy':
            print(f"BECAME NEW: {f}")

if __name__ == "__main__":
    test_scan()
