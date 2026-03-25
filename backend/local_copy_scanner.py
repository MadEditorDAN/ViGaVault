# WHY: Single Responsibility Principle - Handles scanning the local file system (os.walk) to match installed folders.
import os
import logging
import re

from ViGaVault_utils import BASE_DIR, is_hidden, normalize_genre
from .game import Game

def scan_local_system(config, games_dict, worker_thread=None):
    scan_config = config.get('local_scan_config', {})
    ignore_hidden_global = scan_config.get("ignore_hidden", True)
    scan_mode = scan_config.get("scan_mode", "advanced")
    folder_rules = scan_config.get("folder_rules", {})
    global_type = scan_config.get("global_type", "Genre")
    target_folders = scan_config.get("target_folders", None)
    root_path = config.get('root_path', '')

    logging.info(f"\n{' LOCAL COPY SCAN ':=^80}")
    
    stats = {
        'scanned': 0, 'new': 0, 'updated': 0, 'deleted': 0,
        'merged_titles': [], 'deleted_titles': []
    }
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
        
        # WHY: Targeted scanning explicitly ignores folders that the user unchecked in the Scan Settings panel.
        if depth == 1:
            if target_folders is not None and lvl1_folder not in target_folders:
                dirs[:] = []
                continue
            logging.info(f"{' Scanning: ' + lvl1_folder + ' ':-^80}")

            
        if depth == 2:
            for folder in dirs:
                stats['scanned'] += 1
                found_folders.add(folder)
                full_path = os.path.join(root, folder)
                
                act_str = ""
                
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
                        game_obj = games_dict.pop(ghost_match_key)
                        game_obj.data['Folder_Name'] = folder
                        game_obj.data['Path_Root'] = full_path
                        p_set = set(x.strip() for x in game_obj.data.get('Platforms', '').split(',') if x.strip())
                        p_set.update(x.strip() for x in temp_game.data.get('Platforms', '').split(',') if x.strip())
                        # WHY: Ensure "Local Copy" tag is removed if real platforms exist.
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
                    
                    if len(path_parts) >= 2:
                        content_type = rule.get("type", "None")
                        content_value = path_parts[1]
                        if content_type == "Genre": game.data['Genre'] = normalize_genre(f"{content_value}, {game.data.get('Genre', '')}")
                        elif content_type in ["Collection", "Publisher", "Developer"]: game.data[content_type] = content_value
                        elif content_type == "Year": game.data['Year_Folder'] = content_value
                    
                    # WHY: Apply user-defined batch tags (Custom Injection)
                    if rule.get("inject_enabled", False):
                        inj_field = rule.get("inject_field")
                        inj_val = rule.get("inject_value", "").strip()
                        if inj_field and inj_val:
                            # WHY: Target Update - Support multiple comma-separated values for advanced batch tagging.
                            inj_vals = [v.strip() for v in inj_val.split(',') if v.strip()]
                            
                            if inj_field == "Genre":
                                game.data['Genre'] = normalize_genre(f"{inj_val}, {game.data.get('Genre', '')}")
                            elif inj_field in ["Collection", "Publisher", "Developer"]:
                                # WHY: Safely append multiple injected texts without overwriting existing metadata
                                existing = game.data.get(inj_field, "")
                                existing_list = [x.strip().lower() for x in existing.split(',')] if existing else []
                                for v in inj_vals:
                                    if v.lower() not in existing_list:
                                        existing = f"{existing}, {v}" if existing else v
                                        existing_list.append(v.lower())
                                game.data[inj_field] = existing
                            elif inj_field == "Year" and inj_vals:
                                # WHY: Years don't support multi-values, so we strictly inject the first one available.
                                if not game.data.get('Year_Folder'): game.data['Year_Folder'] = inj_vals[0]

                    p_set = set(x.strip() for x in game.data.get('Platforms', '').split(',') if x.strip())
                    # WHY: Ensure "Local Copy" tag is removed if real platforms exist.
                    if 'Local Copy' in p_set and len(p_set) > 1: p_set.remove('Local Copy')
                    game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                    act_str = "Updated"
                    stats['updated'] += 1
                    # WHY: Any metadata or path refresh strictly acts as a Merge event for the tracking logs.
                    stats['merged_titles'].append(folder)

                game = games_dict[folder]
                if worker_thread and worker_thread.isInterruptionRequested(): break 

                if act_str in ["Added", "Merged"]:
                    log_act = act_str
                    
                    action_title = f"{log_act:<14} : {folder}"
                    # WHY: Simplified local scanner logging to a single wide column as requested.
                    logging.info(f"|{action_title[:78]:<78}|")

    existing_folders = list(games_dict.keys())
    for folder in existing_folders:
        if worker_thread and worker_thread.isInterruptionRequested():
            logging.warning("Scan interrupted during orphan file cleanup.")
            break
        game_to_check = games_dict.get(folder)
        if not game_to_check: continue

        is_on_disk = folder in found_folders
        had_a_path = bool(game_to_check.data.get('Path_Root'))

        # WHY: Jurisdiction Check - Prevent the cleanup engine from deleting games that live 
        # inside Lvl 1 folders the user intentionally excluded from this specific scan.
        if target_folders is not None and had_a_path and not is_on_disk:
            try:
                rel_path = os.path.relpath(game_to_check.data.get('Path_Root'), root_path)
                lvl1_folder = rel_path.split(os.sep)[0]
                if lvl1_folder not in target_folders:
                    continue
            except Exception: pass

        if not is_on_disk and had_a_path:
            platforms_str = game_to_check.data.get('Platforms', '')
            platform_list = [p.strip() for p in platforms_str.split(',') if p.strip()]
            # WHY: Ignore 'Local Copy' and both forms of unknown tags when evaluating if a ghost has a real digital platform.
            real_platforms = [p for p in platform_list if p.lower() not in ['local copy', 'unknown', '_unknown']]
            
            game_ids = game_to_check.data.get('game_ID', '')
            has_external_id = any(x in game_ids for x in ['gog_', 'steam_', 'epic_', 'uplay_', 'origin_'])

            if real_platforms or has_external_id:
                game_to_check.data['Path_Root'] = ''
                # WHY: Clean up legacy tags properly when reverting.
                if 'Local Copy' in platform_list: platform_list.remove('Local Copy')
                game_to_check.data['Platforms'] = ", ".join(sorted(platform_list))
                action_title = f"{'Unlinked':<14} : {folder}"
                # WHY: Simplified local scanner logging to a single wide column.
                logging.info(f"|{action_title[:78]:<78}|")
                stats['updated'] += 1
            else:
                action_title = f"{'Deleted':<14} : {folder}"
                logging.info(f"|{action_title[:78]:<78}|")
                del games_dict[folder]
                stats['deleted'] += 1
                stats['deleted_titles'].append(folder)

    if worker_thread and worker_thread.isInterruptionRequested():
        report = f"\n{' Full Scan interrupted by user ':-^80}\n{' SCAN INTERRUPTED BY USER ':=^80}\n"
    else:
        report = f"{' REPORT ':=^80}\n"
        report += f"Folders Scanned: {stats['scanned']}\n"
        report += f"{'New Added':<28}: {stats['new']}\n"
        # WHY: Removed the mathematical subtraction because 'stats['updated']' natively only increments on updates/merges.
        report += f"{'Smart Merged':<28}: {stats['updated']}\n"
        for t in stats['merged_titles']: report += f"                             {t}\n"
        report += f"{'Missing Purged':<28}: {stats['deleted']}\n"
        for t in stats['deleted_titles']: report += f"                             {t}\n"
        report += f"{'='*80}"
        
    logging.info(report)