import sqlite3
import os
import json
import sys
import io

# Force UTF-8 encoding for the Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def debug_gog_metadata():
    gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')
    
    if not os.path.exists(gog_db_path):
        print(f"ERROR: Database not found at: {gog_db_path}")
        return

    print(f"--- GOG PLATFORM DISCOVERY ---\n")
    
    try:
        conn = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        found_platforms = set()

        # 1. Inspect main releaseKeys from UserReleaseProperties
        print("Scanning UserReleaseProperties...")
        cursor.execute("SELECT releaseKey FROM UserReleaseProperties")
        for row in cursor.fetchall():
            key = row['releaseKey']
            if '_' in key:
                platform = key.split('_', 1)[0]
                found_platforms.add(platform)
            elif key.isdigit():
                found_platforms.add('gog') # Legacy GOG keys
            else:
                # Fallback for keys without underscore
                found_platforms.add(key)

        # 2. Inspect allGameReleases from GamePieces
        print("Scanning GamePieces (allGameReleases)...")
        cursor.execute("""
            SELECT value 
            FROM GamePieces gp 
            JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id 
            WHERE gpt.type = 'allGameReleases'
        """)
        
        for row in cursor.fetchall():
            json_data = row['value']
            if not json_data:
                continue
                
            try:
                data = json.loads(json_data)
                if isinstance(data, dict) and 'releases' in data:
                    for release in data['releases']:
                        if isinstance(release, str):
                            if '_' in release:
                                platform = release.split('_', 1)[0]
                                found_platforms.add(platform)
                            elif release.isdigit():
                                found_platforms.add('gog')
                            else:
                                found_platforms.add(release)
            except json.JSONDecodeError:
                pass

        print("\n--- FOUND PLATFORMS ---")
        sorted_platforms = sorted(list(found_platforms))
        for p in sorted_platforms:
            print(p)
            
        # Save to file for easy copy-paste
        output_file = "platforms_list.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            for p in sorted_platforms:
                f.write(f"{p}\n")
        print(f"\nList saved to {output_file}")

    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    debug_gog_metadata()
