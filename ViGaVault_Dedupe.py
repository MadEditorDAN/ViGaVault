import pandas as pd
import re
import os
import shutil
from datetime import datetime
import logging

DB_FILE = "VGVDB.csv"
BACKUP_DIR = "./backups"
DECISION_LOG = "dedupe_decisions.log"

def normalize_title(title):
    """Removes special characters and converts to lowercase for comparison."""
    return re.sub(r'[^a-z0-9]', '', str(title).lower())

def deduplicate_db():
    if not os.path.exists(DB_FILE):
        print(f"Database file {DB_FILE} not found.")
        return

    print(f"Loading {DB_FILE}...")
    df = pd.read_csv(DB_FILE, sep=';', encoding='utf-8').fillna('')
    
    # Setup logging for decisions
    logging.basicConfig(filename=DECISION_LOG, level=logging.INFO, format='%(asctime)s | %(message)s', filemode='a')

    # Create a backup
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"VGVDB_DEDUPE_{timestamp}.csv.bak")
    shutil.copy2(DB_FILE, backup_file)
    print(f"Backup created: {backup_file}")

    # Group by normalized title
    df['norm_title'] = df['Clean_Title'].apply(normalize_title)
    
    # Identify duplicates
    # We look for groups with more than 1 entry where at least one has a GOG/Steam ID and another has a Path_Root
    groups = df.groupby('norm_title')
    
    to_drop = []
    merged_count = 0

    print("\nScanning for duplicates...")
    
    for title, group in groups:
        if len(group) > 1:
            print(f"\n--- Group: '{title}' ({len(group)} entries) ---")
            for idx, row in group.iterrows():
                print(f"  [{idx}] Title: '{row['Clean_Title']}' | ID: '{row['game_ID']}' | Path: '{row['Path_Root']}'")

            # We have potential duplicates
            # Strategy: Prefer the entry with a GOG/Steam ID (Sync result) but merge data from the Local Scan entry
            
            # 1. Find the "Master" record (Priority: Has GOG/Steam ID > Has Path_Root)
            # Actually, usually we want to KEEP the one with the ID, but fill it with the Path from the other.
            
            sync_entries = group[group['game_ID'].str.contains('steam_|gog_|epic_|uplay_|origin_|xbox_', case=False, na=False)]
            local_entries = group[~group.index.isin(sync_entries.index)]
            
            if not sync_entries.empty and not local_entries.empty:
                # We have a split! One from sync, one (or more) from local.
                master_idx = sync_entries.index[0]
                
                for local_idx in local_entries.index:
                    # Refresh master row to show accumulated changes from previous merges
                    master_row = df.loc[master_idx]
                    local_row = df.loc[local_idx]

                    # --- SAFETY CHECK: YEAR MISMATCH ---
                    # Detect reboots (e.g. Prey 2006 vs Prey 2017)
                    m_year = str(master_row.get('Original_Release_Date', ''))[-4:]
                    l_year = str(local_row.get('Year_Folder', ''))
                    if not l_year:
                         l_year = str(local_row.get('Original_Release_Date', ''))[-4:]
                    
                    year_warning = ""
                    if m_year.isdigit() and l_year.isdigit():
                        diff = abs(int(m_year) - int(l_year))
                        if diff > 3:
                            year_warning = f"\n  !!! WARNING: RELEASE YEARS DIFFER BY {diff} YEARS ({m_year} vs {l_year}) !!!"
                            year_warning += "\n  !!! THIS MIGHT BE A DIFFERENT GAME (REBOOT/REMAKE) !!!"

                    print(f"\n{'='*80}")
                    print(f"POTENTIAL MERGE DETECTED")
                    if year_warning:
                        print(f"{year_warning}")
                    print(f"{'='*80}")
                    
                    columns_to_show = ['Clean_Title', 'Folder_Name', 'game_ID', 'Platforms', 'Developer', 'Publisher', 'Original_Release_Date', 'Year_Folder', 'Path_Root', 'Path_Video', 'Image_Link', 'Status_Flag']
                    
                    print(f"{'FIELD':<25} | {'MASTER (KEEP)':<50} | {'LOCAL (MERGE & DELETE)':<50}")
                    print("-" * 130)
                    for col in columns_to_show:
                        val_m = str(master_row.get(col, ''))[:48]
                        val_l = str(local_row.get(col, ''))[:48]
                        print(f"{col:<25} | {val_m:<50} | {val_l:<50}")
                    print("-" * 130)

                    confirm = input(">> Merge this pair? [y/N]: ").strip().lower()
                    
                    logging.info(f"DECISION: {confirm} | MASTER: {master_row['Clean_Title']} ({master_row['game_ID']}) | LOCAL: {local_row['Clean_Title']} ({local_row['Path_Root']})")

                    if confirm != 'y':
                        print("  Skipped.")
                        continue
                    
                    # MERGE LOGIC
                    # We copy useful local data to the master if the master is missing it
                    
                    # Path_Root: Critical
                    if not master_row['Path_Root'] and local_row['Path_Root']:
                        df.at[master_idx, 'Path_Root'] = local_row['Path_Root']
                        # Also update Folder_Name to match the local folder, usually safer for local file operations
                        df.at[master_idx, 'Folder_Name'] = local_row['Folder_Name']
                        df.at[master_idx, 'Year_Folder'] = local_row['Year_Folder']

                    # IDs: Merge them
                    id_master = set(x.strip() for x in str(master_row['game_ID']).split(',') if x.strip())
                    id_local = set(x.strip() for x in str(local_row['game_ID']).split(',') if x.strip())
                    merged_ids = id_master.union(id_local)
                    df.at[master_idx, 'game_ID'] = ", ".join(sorted(list(merged_ids)))

                    # --- VIDEO HANDLING ---
                    m_vid = master_row['Path_Video']
                    l_vid = local_row['Path_Video']
                    
                    if not m_vid and l_vid:
                        df.at[master_idx, 'Path_Video'] = local_row['Path_Video']
                    elif m_vid and l_vid and m_vid != l_vid:
                        # Both have videos. Check if they are in the 'videos' folder.
                        m_in_videos = os.path.abspath(m_vid).startswith(os.path.abspath("videos"))
                        l_in_videos = os.path.abspath(l_vid).startswith(os.path.abspath("videos"))
                        
                        # Only consider deleting if BOTH are in the 'videos' folder (safe to delete)
                        if m_in_videos and l_in_videos and os.path.exists(m_vid) and os.path.exists(l_vid):
                            m_time = os.path.getmtime(m_vid)
                            l_time = os.path.getmtime(l_vid)
                            
                            if l_time > m_time:
                                # Local is newer, keep local, delete master
                                try: os.remove(m_vid)
                                except: pass
                                df.at[master_idx, 'Path_Video'] = l_vid
                            else:
                                # Master is newer, keep master, delete local
                                try: os.remove(l_vid)
                                except: pass

                    # --- IMAGE HANDLING ---
                    m_img = master_row['Image_Link']
                    l_img = local_row['Image_Link']

                    if not m_img and l_img:
                        df.at[master_idx, 'Image_Link'] = local_row['Image_Link']
                    elif m_img and l_img and m_img != l_img and os.path.exists(m_img) and os.path.exists(l_img):
                        # Both have images. Keep the most recent one.
                        m_time = os.path.getmtime(m_img)
                        l_time = os.path.getmtime(l_img)
                        
                        if l_time > m_time:
                            try: os.remove(m_img)
                            except: pass
                            df.at[master_idx, 'Image_Link'] = l_img
                        else:
                            try: os.remove(l_img)
                            except: pass
                        
                    # Platforms: Merge them
                    p_master = set(x.strip() for x in str(master_row['Platforms']).split(',') if x.strip())
                    p_local = set(x.strip() for x in str(local_row['Platforms']).split(',') if x.strip())
                    # If local had "Warez" or "Unknown", ignore it if master has real platforms
                    if 'Warez' in p_local: p_local.remove('Warez')
                    
                    merged_platforms = p_master.union(p_local)
                    df.at[master_idx, 'Platforms'] = ", ".join(sorted(list(merged_platforms)))

                    # Mark local entry for deletion
                    to_drop.append(local_idx)
                    merged_count += 1

    # Apply deletions
    if to_drop:
        df.drop(to_drop, inplace=True)
        # Save
        df.drop(columns=['norm_title'], inplace=True) # Clean up helper col
        df.to_csv(DB_FILE, sep=';', index=False, encoding='utf-8')
        print(f"\nSuccess! Merged {merged_count} duplicate entries. Database saved.")
    else:
        print("\nNo mergeable duplicates found.")

if __name__ == "__main__":
    deduplicate_db()