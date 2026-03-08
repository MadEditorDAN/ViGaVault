import os
import pandas as pd
import ctypes

def is_hidden(filepath):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
        return attrs != -1 and (attrs & 2)
    except:
        return False

def generate_folder_report(start_path):
    """
    Generates a hierarchical report:
    - Lists Lvl 2 folders inside Lvl 1.
    - Counts Lvl 3 folders inside Lvl 2.
    - Compares 'warez' folders against VGVDB.csv to find missing entries.
    """
    base = start_path
    db_file = "VGVDB.csv"
    
    if not os.path.exists(base):
        print(f"Error: The path '{base}' does not exist.")
        return

    # --- Load VGVDB.csv ---
    db_data = {}
    if os.path.exists(db_file):
        try:
            df = pd.read_csv(db_file, sep=';', encoding='utf-8').fillna('')
            if 'Folder_Name' in df.columns and 'Platforms' in df.columns:
                # Create dictionary: Folder_Name -> Platforms
                db_data = dict(zip(df['Folder_Name'], df['Platforms'].astype(str)))
            print(f"Successfully loaded {len(db_data)} entries from {db_file}.\n")
        except Exception as e:
            print(f"Error loading {db_file}: {e}")
            return
    else:
        print(f"Warning: {db_file} not found. Cannot compare against database.")

    total_lvl3_count = 0
    total_platforms_count = 0
    missing_warez_folders = []
    converted_warez_folders = [] # Folders without tags but identified as Platform in DB
    
    print(f"Analysis started at: {base}\n" + "="*70)
    print(f"{'Structure':<40} | {'Lvl 3':<8} | {'Platforms':<10}")
    print("-"*70)

    # Use os.scandir for performance on network drives
    with os.scandir(base) as lvl1_iterator:
        for lvl1 in lvl1_iterator:
            if is_hidden(lvl1.path): continue
            if lvl1.is_dir():
                print(f"\n[Lvl 1] {lvl1.name}")
                
                try:
                    with os.scandir(lvl1.path) as lvl2_iterator:
                        for lvl2 in lvl2_iterator:
                            if is_hidden(lvl2.path): continue
                            if lvl2.is_dir():
                                # Initialize counters for this specific Lvl 2 folder
                                current_lvl3 = 0
                                current_platforms = 0
                                
                                try:
                                    with os.scandir(lvl2.path) as lvl3_iterator:
                                        for item in lvl3_iterator:
                                            if is_hidden(item.path): continue
                                            if item.is_dir():
                                                current_lvl3 += 1
                                                # Check for 'platforms' (folders with parentheses)
                                                if '(' in item.name and ')' in item.name:
                                                    current_platforms += 1
                                                else:
                                                    # It looks like a Warez folder (no parentheses)
                                                    if item.name not in db_data:
                                                        missing_warez_folders.append(item.path)
                                                    else:
                                                        # Check if it's actually classified as something else in DB
                                                        plat = db_data[item.name]
                                                        # If it has a platform that isn't just 'Warez' or empty
                                                        if 'Warez' not in plat and plat.strip() != '':
                                                            converted_warez_folders.append((item.name, plat))
                                except PermissionError:
                                    continue
                                
                                # Update global counters
                                total_lvl3_count += current_lvl3
                                total_platforms_count += current_platforms
                                
                                # Print line report
                                print(f"   -> [Lvl 2] {lvl2.name:<25} | {current_lvl3:<8} | {current_platforms:<10}")
                                
                except PermissionError:
                    print(f"   -> [Error] Access denied to: {lvl1.name}")

    print("\n" + "="*70)
    print(f"GRAND TOTALS:")
    print(f"Total Lvl 3 folders: {total_lvl3_count}")
    print(f"Total 'Platforms' folders: {total_platforms_count}")
    print(f"Total 'Warez' folders (Script logic): {total_lvl3_count - total_platforms_count}")
    print("="*70)

    # --- Print the list of missing warez folders ---
    if missing_warez_folders:
        print("\n" + "="*70)
        print(f"WAREZ FOLDERS ON DISK BUT NOT IN '{db_file}' ({len(missing_warez_folders)} found):")
        print("="*70)
        for path in sorted(missing_warez_folders):
            print(path)
    
    # --- Print the list of converted warez folders ---
    if converted_warez_folders:
        print("\n" + "="*70)
        print(f"FOLDERS WITHOUT TAGS BUT IDENTIFIED AS PLATFORMS IN DB ({len(converted_warez_folders)} found):")
        print("(These explain discrepancies between script count and GUI Warez count)")
        print("="*70)
        for name, plat in sorted(converted_warez_folders):
            print(f"{name} -> {plat}")


# --- Configuration ---
target_path = r"t:\GAMES" 

# Execute
generate_folder_report(target_path)