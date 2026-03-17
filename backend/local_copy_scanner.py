# WHY: Single Responsibility Principle - Handles scanning the local file system (os.walk) to match installed folders.
import os
import logging
import re

from ViGaVault_utils import BASE_DIR, is_hidden, normalize_genre
from .game import Game

def scan_local_system(config, games_dict, token, worker_thread=None):
    scan_config = config.get('local_scan_config', {})
    ignore_hidden_global = scan_config.get("ignore_hidden", True)
    scan_mode = scan_config.get("scan_mode", "advanced")
    folder_rules = scan_config.get("folder_rules", {})
    global_type = scan_config.get("global_type", "Genre")
    root_path = config.get('root_path', '')

    logging.info("--- START OF SCAN ---")
    
    stats = {'scanned': 0, 'new': 0, 'updated': 0, 'deleted': 0, 'fetched_success': 0, 'fetched_fail': 0}
    found_folders = set()

    target_game_depth = 1 if scan_mode == "simple" and "Direct" in global_type else 2 if scan_mode == "simple" else 3

    for root, dirs, files in os.walk(root_path):
        if worker_thread and worker_thread.isInterruptionRequested(): break
        
        if ignore_hidden_global:
            dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
        
        rel_path = os.path.relpath(root, root_path)
        if rel_path == ".": continue
        
        depth = rel_path.count(os.sep) + 1
        path_parts = rel_path.split(os.sep)
        lvl1_folder = path_parts[0]

        rule = folder_rules.get(lvl1_folder)
        if not rule or not rule.get("scan", False):
            dirs[:] = []
            continue
        
        if depth == 1:
            logging.info(f"Analyzing: {lvl1_folder} (Type: {rule.get('type', 'None')})")
            
        if depth == 2:
            for folder in dirs:
                stats['scanned'] += 1
                found_folders.add(folder)
                full_path = os.path.join(root, folder)
                
                if folder not in games_dict:
                    ghost_match_key = None
                    temp_game = Game(config=config, Folder_Name=folder)
                    local_norm_title = re.sub(r'[^a-z0-9]', '', temp_game.data.get('Clean_Title', '').lower())
                    local_year = temp_game.data.get('Year_Folder', '')
                    
                    for k, g in games_dict.items():
                        if not g.data.get('Path_Root'):
                            g_norm = re.sub(r'[^a-z0-9]', '', g.data.get('Clean_Title', '').lower())
                            if g_norm == local_norm_title:
                                ghost_match_key = k
                                break
                    
                    if ghost_match_key:
                        logging.info(f"    [MERGE] Linking local folder '{folder}' to GOG entry '{ghost_match_key}'")
                        game_obj = games_dict.pop(ghost_match_key)
                        game_obj.data['Folder_Name'] = folder
                        game_obj.data['Path_Root'] = full_path
                        p_set = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
                        p_set.update(x.strip() for x in temp_game.data.get('Platforms', '').split(',') if x.strip())
                        # WHY: Ensure "Local Copy" tag is removed if real platforms exist.
                        if 'Local Copy' in p_set and len(p_set) > 1: p_set.remove('Local Copy')
                        game_obj.data['Platforms'] = ", ".join(sorted(list(p_set)))
                        games_dict[folder] = game_obj
                        stats['updated'] += 1
                    else:
                        logging.info(f"    [NEW] Discovered: {folder}")
                        games_dict[folder] = Game(config=config, Folder_Name=folder, Path_Root=full_path)
                        stats['new'] += 1
                else:
                    game = games_dict[folder]
                    game.data['Path_Root'] = full_path
                    game._parse_folder_name()
                    
                    if len(path_parts) >= 2:
                        content_type = rule.get("type", "None")
                        content_value = path_parts[1]
                        if content_type == "Genre": game.data['Genre'] = normalize_genre(f"{content_value}, {game.data.get('Genre', '')}")
                        elif content_type in ["Collection", "Publisher", "Developer"]: game.data[content_type] = content_value
                        elif content_type == "Year": game.data['Year_Folder'] = content_value
                    
                    p_set = set(x.strip() for x in game.data.get('Platforms', '').split(',') if x.strip())
                    # WHY: Ensure "Local Copy" tag is removed if real platforms exist.
                    if 'Local Copy' in p_set and len(p_set) > 1: p_set.remove('Local Copy')
                    game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                    stats['updated'] += 1

                game = games_dict[folder]
                if worker_thread and worker_thread.isInterruptionRequested(): break 

                status = game.data.get('Status_Flag')
                if status == 'NEW':
                    if token and game.fetch_metadata(token): stats['fetched_success'] += 1
                    else: 
                        logging.warning(f"    [FAILURE] Failure for: {folder}")
                        stats['fetched_fail'] += 1

    existing_folders = list(games_dict.keys())
    for folder in existing_folders:
        if worker_thread and worker_thread.isInterruptionRequested():
            logging.warning("Scan interrupted during orphan file cleanup.")
            break
        game_to_check = games_dict.get(folder)
        if not game_to_check: continue

        is_on_disk = folder in found_folders
        had_a_path = bool(game_to_check.data.get('Path_Root'))

        if not is_on_disk and had_a_path:
            platforms_str = game_to_check.data.get('Platforms', '')
            platform_list = [p.strip() for p in platforms_str.split(',') if p.strip()]
            # WHY: Ignore 'Local Copy' and both forms of unknown tags when evaluating if a ghost has a real digital platform.
            real_platforms = [p for p in platform_list if p.lower() not in ['local copy', 'unknown', '_unknown']]
            
            game_ids = game_to_check.data.get('game_ID', '')
            has_external_id = any(x in game_ids for x in ['gog_', 'steam_', 'epic_', 'uplay_', 'origin_'])

            if real_platforms or has_external_id:
                logging.info(f"    [UPDATE] Local files removed for '{folder}'. Reverting to Platform Entry.")
                game_to_check.data['Path_Root'] = ''
                # WHY: Clean up legacy tags properly when reverting.
                if 'Local Copy' in platform_list: platform_list.remove('Local Copy')
                game_to_check.data['Platforms'] = ", ".join(sorted(platform_list))
                stats['updated'] += 1
            else:
                logging.info(f"    [DELETE] Game entry not found on disk, deleting: {folder}")
                del games_dict[folder]
                stats['deleted'] += 1

    if worker_thread and worker_thread.isInterruptionRequested():
        report = "\n=== SCAN INTERRUPTED BY USER ===\n"
    else:
        report = (
            "\n=== LOCAL SCAN REPORT ===\n"
            f"Folders scanned: {stats['scanned']}\n"
            f"-----------------------------------\n"
            f"New games detected: {stats['new']}\n"
            f"Existing games checked: {stats['updated']}\n"
            f"Deleted games (not found): {stats['deleted']}\n"
            f"-----------------------------------\n"
            f"Metadata fetched (IGDB): {stats['fetched_success']}\n"
            f"IGDB fetch failures: {stats['fetched_fail']}\n"
            "==================================="
        )
    logging.info(report)