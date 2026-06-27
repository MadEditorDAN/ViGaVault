import json
from backend.library import load_library
config = {}
with open('c:\\Users\\mad_e\\PROJECTS\\ViGaVault\\config.json', 'r') as f:
    config = json.load(f)
games_dict = load_library(config)
for name, game in games_dict.items():
    if "Arena" in name:
        print(f"[{name}] Original_Release_Date: {game.data.get('Original_Release_Date')} - Folder: {game.data.get('Folder_Name')} - Status: {game.data.get('Status_Flag')}")
