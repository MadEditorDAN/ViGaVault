import sys
import os

sys.path.append(os.getcwd())
from ViGaVault_utils import build_scanner_config
from backend.library import LibraryManager

def debug_new_local_games():
    config = build_scanner_config()
    manager = LibraryManager(config)
    manager.load_db()

    new_local = []
    locked_games = []
    for f, g in manager.games.items():
        if g.data.get('Status_Flag') == 'NEW' and g.data.get('Platforms') == 'Local Copy':
            new_local.append(g)
        if g.data.get('Status_Flag') == 'LOCKED':
            locked_games.append(g)
            
    print(f"Total NEW Local Copies: {len(new_local)}")
    for g in new_local[:10]:
        print(f" - {g.data.get('Clean_Title')} (Folder: {g.data.get('Folder_Name')}) [ID: {g.data.get('game_ID')}]")
        
    print(f"\nTotal LOCKED games: {len(locked_games)}")
    for g in locked_games[:10]:
        print(f" - {g.data.get('Clean_Title')} (Folder: {g.data.get('Folder_Name')})")

if __name__ == "__main__":
    debug_new_local_games()
