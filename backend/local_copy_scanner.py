# WHY: Single Responsibility Principle - Handles scanning the local file system (os.walk) to match installed folders.
import os
import logging
import re

from ViGaVault_utils import (
    BASE_DIR, is_hidden, normalize_genre,
    format_header_row, format_middle_header, format_box_bottom,
    format_separator_row, format_report_row, format_operation_row
)
from .game import Game

def scan_local_system(config, games_dict, worker_thread=None):
    scan_config = config.get('local_scan_config', {})
    ignore_hidden_global = scan_config.get("ignore_hidden", True)
    scan_mode = scan_config.get("scan_mode", "advanced")
    folder_rules = scan_config.get("folder_rules", {})
    global_type = scan_config.get("global_type", "Genre")
    target_folders = scan_config.get("target_folders", None)
    root_path = config.get('root_path', '')

    logging.info(format_header_row("LOCAL COPY SCAN", is_secondary=False, col_spec=[17, 36, 23]))
    
    stats = {
        'scanned': 0, 'new': 0, 'updated': 0, 'deleted': 0,
        'merged_titles': [], 'deleted_titles': []
    }

    # Set of all rules that are actively enabled for scanning
    all_scan_enabled_rules = set(f for f, r in folder_rules.items() if r.get("scan", False))
    if "[ROOT PATH]" not in all_scan_enabled_rules:
        all_scan_enabled_rules.add("[ROOT PATH]")

    # Pre-calculate which games in the DB belong to which lvl1_folder to detect ghosts efficiently
    db_games_by_lvl1 = {}
    for folder, game in games_dict.items():
        path_root = game.data.get('Path_Root')
        if path_root:
            try:
                rel_path = os.path.relpath(path_root, root_path)
                if not rel_path.startswith(".."):
                    target_lvl1 = "[ROOT PATH]"
                    parts = rel_path.replace('\\', '/').split('/')
                    for i in range(len(parts), 0, -1):
                        test_os = os.sep.join(parts[:i])
                        test_fwd = '/'.join(parts[:i])
                        test_back = '\\'.join(parts[:i])
                        if test_os in all_scan_enabled_rules: target_lvl1 = test_os; break
                        if test_fwd in all_scan_enabled_rules: target_lvl1 = test_fwd; break
                        if test_back in all_scan_enabled_rules: target_lvl1 = test_back; break
                    
                    if target_lvl1 not in db_games_by_lvl1:
                        db_games_by_lvl1[target_lvl1] = []
                    db_games_by_lvl1[target_lvl1].append(folder)
            except Exception:
                pass

    active_folders = []
    if target_folders is not None:
        active_folders = sorted(list(target_folders))
    else:
        active_folders = sorted([f for f, r in folder_rules.items() if r.get("scan", False)])

    # Put [ROOT PATH] first in the scan order
    if "[ROOT PATH]" in active_folders:
        active_folders.remove("[ROOT PATH]")
        active_folders.insert(0, "[ROOT PATH]")

    for idx, lvl1_folder in enumerate(active_folders):
        if worker_thread and worker_thread.isInterruptionRequested(): break

        rule = folder_rules.get(lvl1_folder)
        if not rule or not rule.get("scan", False):
            continue

        walk_root = os.path.join(root_path, lvl1_folder) if lvl1_folder != "[ROOT PATH]" else root_path
        if not os.path.exists(walk_root):
            continue

        collected_games = []
        disk_folders = set()
        
        # Determine the structural depth
        structure_str = rule.get("structure", "Contains Games Directly")
        target_depth = 0 if structure_str == "Contains Games Directly" else 1
        
        # 1. Gather games for this lvl1_folder with extreme pruning to prevent deep crawling
        for root, dirs, files in os.walk(walk_root):
            if worker_thread and worker_thread.isInterruptionRequested(): break
            
            if ignore_hidden_global:
                dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
                
            rel_path = os.path.relpath(root, walk_root)
            depth = rel_path.count(os.sep) + 1 if rel_path != "." else 0
            
            # Critical step: Skip any directory that is configured independently!
            if depth < target_depth + 1:
                base_for_join = lvl1_folder if lvl1_folder != "[ROOT PATH]" else ""
                def is_managed(d_name):
                    p = os.path.join(base_for_join, rel_path, d_name) if rel_path != "." else os.path.join(base_for_join, d_name)
                    p_norm = os.path.normpath(p)
                    return p_norm in all_scan_enabled_rules or p_norm.replace('\\', '/') in all_scan_enabled_rules or p_norm.replace('/', '\\') in all_scan_enabled_rules
                
                dirs[:] = [d for d in dirs if not is_managed(d)]
            
            if depth == target_depth:
                subfolder = os.path.basename(root) if depth > 0 else ""
                for folder in dirs:
                    full_path = os.path.join(root, folder)
                    disk_folders.add(folder)
                    collected_games.append({
                        'folder': folder,
                        'root': root,
                        'full_path': full_path,
                        'subfolder': subfolder
                    })
                # Critical Performance Fix: Stop os.walk from crawling into the game's actual content files!
                dirs[:] = []
                
        # Sort alphabetically for consistent logs
        collected_games.sort(key=lambda x: x['folder'])

        # 2. Identify ghosts for this lvl1_folder
        folder_deletes = []
        for db_folder in db_games_by_lvl1.get(lvl1_folder, []):
            if db_folder not in disk_folders:
                game_to_check = games_dict.get(db_folder)
                if not game_to_check: continue
                
                platforms_str = game_to_check.data.get('Platforms', '')
                platform_list = [p.strip() for p in platforms_str.split(',') if p.strip()]
                real_platforms = [p for p in platform_list if p.lower() not in ['local copy', 'unknown', '_unknown']]
                
                game_ids = game_to_check.data.get('game_ID', '')
                has_external_id = any(x in game_ids for x in ['gog_', 'steam_', 'epic_', 'uplay_', 'origin_'])
                
                action = "Unlinked" if (real_platforms or has_external_id) else "Deleted"
                folder_deletes.append((db_folder, action))

        # 3. Print UI Headers for this folder
        games_found_count = len(collected_games)
        col1 = f" {'Folder':<15} "
        lvl1_display = os.path.basename(lvl1_folder)
        if not lvl1_display: lvl1_display = lvl1_folder
        col2 = f" {lvl1_display:<34} "
        col3 = f" {f'{games_found_count:<5} Games Found':<21} "
        logging.info(f"║{col1}│{col2}│{col3}║")

        folder_ops_logged = 0

        # 4. Process found games
        for item in collected_games:
            if worker_thread and worker_thread.isInterruptionRequested(): break
            
            folder = item['folder']
            root = item['root']
            full_path = item['full_path']
            subfolder = item['subfolder']
            
            stats['scanned'] += 1
            act_str = ""
            
            if folder not in games_dict:
                ghost_match_key = None
                temp_game = Game(config=config, Folder_Name=folder)
                local_norm_title = re.sub(r'[^a-z0-9]', '', temp_game.data.get('Clean_Title', '').lower())
                
                for k, g in games_dict.items():
                    if not g.data.get('Path_Root'):
                        g_norm = re.sub(r'[^a-z0-9]', '', g.data.get('Clean_Title', '').lower())
                        if g_norm == local_norm_title:
                            ghost_match_key = k
                            break
                
                if ghost_match_key:
                    game_obj = games_dict.pop(ghost_match_key)
                    game_obj.data['Folder_Name'] = folder
                    game_obj.data['Path_Root'] = full_path
                    p_set = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
                    p_set.update(x.strip() for x in temp_game.data.get('Platforms', '').split(',') if x.strip())
                    if 'Local Copy' in p_set and len(p_set) > 1: p_set.remove('Local Copy')
                    game_obj.data['Platforms'] = ", ".join(sorted(list(p_set)))
                    games_dict[folder] = game_obj
                    act_str = "Merged"
                    stats['updated'] += 1
                    stats['merged_titles'].append(folder)
                else:
                    games_dict[folder] = Game(config=config, Folder_Name=folder, Path_Root=full_path)
                    act_str = "Added"
                    stats['new'] += 1
            else:
                game = games_dict[folder]
                game.data['Path_Root'] = full_path
                game._parse_folder_name()
                
                p_set = set(x.strip() for x in game.data.get('Platforms', '').split(',') if x.strip())
                if 'Local Copy' in p_set and len(p_set) > 1: p_set.remove('Local Copy')
                game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                act_str = "Updated"
                stats['updated'] += 1
                stats['merged_titles'].append(folder)

            # WHY: Apply subfolder and injection rules to ALL games (Added, Merged, or Updated)
            game = games_dict[folder]
            
            def append_dedup(field_name, new_val_str):
                existing = game.data.get(field_name, "")
                existing_items = [x.strip() for x in existing.split(',')] if existing else []
                existing_lower = [x.lower() for x in existing_items]
                new_vals = [v.strip() for v in new_val_str.split(',') if v.strip()]
                for v in new_vals:
                    if v.lower() not in existing_lower:
                        existing_items.append(v)
                        existing_lower.append(v.lower())
                    else:
                        idx = existing_lower.index(v.lower())
                        existing_items[idx] = v
                game.data[field_name] = ", ".join(existing_items)

            if subfolder:
                content_type = rule.get("type", "Unused")
                content_value = subfolder
                if content_type == "Genre": 
                    append_dedup("Genre", content_value)
                elif content_type in ["Collection", "Publisher", "Developer"]: 
                    game.data[content_type] = content_value
                elif content_type == "Year": 
                    game.data['Year_Folder'] = content_value
            
            if rule.get("inject_enabled", False):
                inj_field = rule.get("inject_field")
                inj_val = rule.get("inject_value", "").strip()
                if inj_field and inj_val:
                    if inj_field in ["Genre", "Collection", "Publisher", "Developer"]:
                        append_dedup(inj_field, inj_val)
                    elif inj_field == "Year":
                        inj_vals = [v.strip() for v in inj_val.split(',') if v.strip()]
                        if inj_vals and not game.data.get('Year_Folder'): 
                            game.data['Year_Folder'] = inj_vals[0]

            if act_str in ["Added", "Merged"]:
                if folder_ops_logged == 0:
                    logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
                
                game = games_dict[folder]
                has_img = str(game.data.get('Has_Image')).lower() in ['true', '1']
                has_trl = bool(game.data.get('Trailer_Link') and str(game.data.get('Trailer_Link')).startswith('http'))
                logging.info(format_operation_row(act_str, folder, has_img, has_trl))
                folder_ops_logged += 1

        # 5. Process ghosts for this folder
        for db_folder, action in folder_deletes:
            if worker_thread and worker_thread.isInterruptionRequested(): break
            game_to_check = games_dict.get(db_folder)
            
            if action == "Unlinked":
                platforms_str = game_to_check.data.get('Platforms', '')
                platform_list = [p.strip() for p in platforms_str.split(',') if p.strip()]
                game_to_check.data['Path_Root'] = ''
                if 'Local Copy' in platform_list: platform_list.remove('Local Copy')
                game_to_check.data['Platforms'] = ", ".join(sorted(platform_list))
                stats['updated'] += 1
            else:
                del games_dict[db_folder]
                stats['deleted'] += 1
                stats['deleted_titles'].append(db_folder)

            if folder_ops_logged == 0:
                logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
            
            has_img = str(game_to_check.data.get('Has_Image')).lower() in ['true', '1'] if action == "Unlinked" else False
            has_trl = bool(game_to_check.data.get('Trailer_Link') and str(game_to_check.data.get('Trailer_Link')).startswith('http')) if action == "Unlinked" else False
            logging.info(format_operation_row(action, db_folder, has_img, has_trl))
            folder_ops_logged += 1

        if folder_ops_logged > 0:
            logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┴", "┴", "┴"]))
            
        if idx < len(active_folders) - 1:
            logging.info(format_separator_row([17, 36, 23], ["┼", "┼"]))

    if worker_thread and worker_thread.isInterruptionRequested():
        logging.warning("Scan interrupted by user.")
    else:
        logging.info(format_middle_header("REPORT", col_spec=[17, 36, 5, 5, 5, 5]))
        
        already_in_db = stats['scanned'] - stats['new'] - stats['updated']
        if already_in_db < 0: already_in_db = 0

        logging.info(format_report_row("Total Games", stats['scanned']))
        logging.info(format_report_row("Already in DB", already_in_db))
        logging.info(format_report_row("New Added", stats['new']))
        logging.info(format_report_row("Smart Merged", stats['updated']))
        logging.info(format_report_row("Deleted", stats['deleted']))
        logging.info(format_report_row("Errors/Ignored", 0))
        
        logging.info(format_box_bottom([17, 60]))

    return stats