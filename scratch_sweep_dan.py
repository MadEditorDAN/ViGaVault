import sys
import os

# Append root to path
sys.path.append(os.getcwd())

from ViGaVault_utils import build_scanner_config
from backend.library import LibraryManager

def sweep_dan_db():
    print("Starting sweep on dan.dat...")
    config = build_scanner_config()
    
    # Override the DB file
    config['db_file'] = os.path.join(os.getcwd(), 'dan.dat')
    
    if not os.path.exists(config['db_file']):
        print(f"Error: Database {config['db_file']} not found!")
        return

    manager = LibraryManager(config)
    manager.load_db()
    print(f"Loaded {len(manager.games)} games from dan.dat.")

    # Run the IGDB scrapper (this will fetch missing IGDB IDs and apply the VR genre where needed)
    print("Running IGDB scraper engine to catch missing metadata...")
    manager.run_igdb_scrapper()
    
    # Save the updated DB
    manager.save_db()
    print("Sweep on dan.dat complete!")

if __name__ == "__main__":
    sweep_dan_db()
