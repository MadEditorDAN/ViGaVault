# WHY: Single Responsibility Principle - Strictly handles matching, merging,
# and ghost deletion logic for Amazon Luna/Prime Gaming library synchronization.
import logging
import re
import difflib
from datetime import datetime

from backend.game import Game
from ViGaVault_utils import (
    get_safe_filename,
    format_header_row, format_middle_header, format_box_bottom,
    format_separator_row, format_report_row, format_operation_row
)

def get_clean_amazon_id(raw_id):
    """
    WHY: Amazon GraphQL API returns prefixed IDs (e.g. 'amzn1.adg.product.UUID').
    We extract the plain UUID portion to prevent re-scraping and maintain perfect compatibility 
    with GOG Galaxy imports.
    """
    if not raw_id:
        return ""
    return raw_id.split('.')[-1].strip()

def get_claim_year(claim):
    # WHY: Amazon returns orderCreationDate as either ISO 8601 strings (e.g. '2026-05-04T13:02:22Z')
    # or millisecond-based Unix timestamps (e.g. '1716912345678').
    # This robust parser handles both formats to accurately categorize games into active year buckets (2020-2026).
    date_val = claim.get('orderCreationDate')
    if not date_val:
        return datetime.now().year

    # Try numeric conversion (seconds or milliseconds)
    try:
        val_str = str(date_val).strip()
        if val_str.replace('.', '', 1).isdigit():
            val = float(val_str)
            # If the value is extremely large, it is in milliseconds (Unix timestamp in ms)
            if val > 1e11:  # e.g., year 1973 in ms is 1e11
                val = val / 1000.0
            dt = datetime.fromtimestamp(val)
            return dt.year
    except Exception:
        pass

    # If it is a string and looks like ISO format (e.g., starting with 4 digits for year)
    if isinstance(date_val, str):
        val_str = date_val.strip()
        if len(val_str) >= 4 and val_str[:4].isdigit():
            year_val = int(val_str[:4])
            # Basic sanity check to avoid year 1716 if a numeric string somehow slipped through
            if 1970 <= year_val <= 2100:
                return year_val

    # Fallback to current year
    return datetime.now().year

def get_game_year(game):
    y = game.data.get('Year_Folder') or ''
    if isinstance(y, str) and len(y) >= 4 and y[:4].isdigit():
        return int(y[:4])
    d = game.data.get('Original_Release_Date') or ''
    if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return datetime.now().year

def sync_amazon_database(config, games_dict, claims_list, worker_thread=None, print_header=True, target_year=None, print_report=True):
    # WHY: Conditional header suppression prevents duplicate headers when running sequentially year-by-year.
    if print_header:
        logging.info(format_header_row("AMAZON SCAN", is_secondary=False, col_spec=[17, 36, 23]))
    
    # 1. Accept all returned claims directly since the GraphQL search is already restricted to offerType='games'.
    # This automatically includes GOG/Epic/other codes claimed via Prime Gaming, enabling them to merge cleanly
    # and inherit the Amazon platform tag as expected.
    pc_games = claims_list

    # 2. Pre-calculate existing Amazon IDs to skip known entries rapidly
    existing_amazon_set = set()
    for game in games_dict.values():
        gids = game.data.get('game_ID', '').split(',')
        for gid in gids:
            gid = gid.strip()
            if gid.startswith('amazon_'):
                clean_id = get_clean_amazon_id(gid.replace('amazon_', ''))
                if clean_id:
                    existing_amazon_set.add(clean_id)

    changes_made = False
    
    stats = {
        'total_cloud': len(pc_games),
        'already_in_db': 0,
        'new_added': 0,
        'matched_smart': 0,
        'deleted_ghosts': 0,
        'new_titles': [],
        'merged_titles': [],
        'deleted_ghost_titles': []
    }

    # Identify which games in games_dict are ghosts that need unlinking or deletion and group them by year
    pending_deletes = {} # year -> list of (folder_name, action_type)
    if not (worker_thread and worker_thread.isInterruptionRequested()):
        cloud_amazon_ids = set(get_clean_amazon_id(c['item']['id']) for c in pc_games if c.get('item', {}).get('id'))
        if cloud_amazon_ids:
            for folder_name, game in list(games_dict.items()):
                # WHY: Strictly isolate deletion checking to the target year when executing sequentially.
                # This guarantees that claims missing from a single year's batch do not trigger spurious deletes for other years.
                g_year = get_game_year(game)
                if target_year is not None and g_year != target_year:
                    continue
                if not game.data.get('Path_Root'):
                    if game.data.get('Status_Flag') == 'LOCKED':
                        continue
                    game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
                    amazon_ids = [gid.replace('amazon_', '') for gid in game_ids if gid.startswith('amazon_')]
                    if not amazon_ids:
                        continue
                    native_amazon_ids = [aid for aid in amazon_ids if '-' in aid]
                    if not native_amazon_ids:
                        continue
                    missing_all = all(aid not in cloud_amazon_ids for aid in native_amazon_ids)
                    if missing_all:
                        other_ids = [gid for gid in game_ids if not gid.startswith('amazon_')]
                        action = "Deleted" if not other_ids else "Unlinked"
                        
                        if g_year not in pending_deletes:
                            pending_deletes[g_year] = []
                        pending_deletes[g_year].append((folder_name, action))

    # WHY: Dynamically adjust the years loop to support either a single-year sequential pass or full scan scope.
    if target_year is not None:
        years = [target_year]
    else:
        current_year = datetime.now().year
        years = list(range(current_year, 2019, -1))

    for year in years:
        if worker_thread and worker_thread.isInterruptionRequested(): break

        # Find claims and deletions for this year
        year_claims = [c for c in pc_games if get_claim_year(c) == year]
        games_found_count = len(year_claims)

        # Print Year line
        col1 = f" {'Year':<15} "
        col2 = f" {year:<34} "
        col3 = f" {f'{games_found_count:<5} Games Found':<21} "
        logging.info(f"║{col1}│{col2}│{col3}║")

        ops_logged = 0

        # Process cloud claims for this year
        for claim in year_claims:
            if worker_thread and worker_thread.isInterruptionRequested(): break
            
            item = claim.get('item') or {}
            assets_list = item.get('assets') or []
            if isinstance(assets_list, dict):
                assets_list = [assets_list]
                
            item_assets = {}
            for asset in assets_list:
                if 'AMAZON_GAMES_APP' in (asset.get('redemptionPlatforms') or []):
                    item_assets = asset
                    break
            if not item_assets and assets_list:
                item_assets = assets_list[0]
                
            game_node = item.get('game') or {}
            game_assets = game_node.get('assets') or {}
            if isinstance(game_assets, list):
                game_assets = game_assets[0] if game_assets else {}
            
            amazon_id = item.get('id')
            if not amazon_id: continue
            
            clean_amazon_id = get_clean_amazon_id(amazon_id)
            
            # Fast path skip
            if clean_amazon_id in existing_amazon_set:
                stats['already_in_db'] += 1
                continue
                
            title_raw = game_assets.get('title') or item_assets.get('title') or claim.get('itemTitle') or "Unknown Amazon Game"
            # WHY: Amazon Luna sometimes injects raw UUIDs directly into the title string. Strip them to avoid breaking IGDB matching.
            title_raw = re.sub(r'\s*\[[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\]', '', title_raw)
            title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title_raw).strip()
            publisher = game_assets.get('publisher') or ""
            
            card_media = item_assets.get('cardMedia') or {}
            default_media = card_media.get('defaultMedia') or {}
            cover_url = default_media.get('src1x') or ""
            
            # --- ZERO-COST SMART MATCH ---
            norm_title = re.sub(r'[^a-z0-9]', '', title_clean.lower())
            best_score = 0
            best_game = None
            
            for game in games_dict.values():
                # 1. Permanent Blacklist Check
                unmerged = game.data.get('Unmerged_IDs', '')
                if f"amazon_{clean_amazon_id}" in unmerged:
                    continue
                    
                local_title = game.data.get('Clean_Title', '')
                local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
                
                score = 0
                if local_norm_title == norm_title: 
                    score += 60
                else:
                    ratio = difflib.SequenceMatcher(None, title_clean.lower(), local_title.lower()).ratio()
                    if ratio > 0.6: 
                        score += int(ratio * 60)
                        # Number mismatch penalty
                        nums1 = set(re.findall(r'\d+', title_clean))
                        nums2 = set(re.findall(r'\d+', local_title))
                        if nums1 != nums2:
                            score -= 30
                    else: 
                        continue
                    
                local_platforms = game.data.get('Platforms', '').lower()
                if 'amazon' in local_platforms: score += 20
                if local_norm_title == norm_title: score += 20
                
                if score > best_score:
                    best_score, best_game = score, game
                    
            threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
            
            if best_game and best_score >= threshold:
                current_ids = set(x.strip() for x in best_game.data.get('game_ID', '').split(',') if x.strip())
                current_ids.add(f"amazon_{clean_amazon_id}")
                best_game.data['game_ID'] = ", ".join(sorted(list(current_ids)))
                
                mh = best_game.data.get('Merge_History', '')
                mh_parts = [x for x in mh.split('|') if x]
                mh_parts.append(f"amazon_{clean_amazon_id}:{title_clean}")
                best_game.data['Merge_History'] = "|".join(mh_parts)
                
                p_set = set(x.strip() for x in best_game.data.get('Platforms', '').split(',') if x.strip())
                if 'Local Copy' in p_set: p_set.remove('Local Copy')
                p_set.add("Amazon")
                best_game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                
                # Apply year if not already populated
                if not best_game.data.get('Year_Folder'):
                    best_game.data['Year_Folder'] = str(year)
                
                has_img = str(best_game.data.get('Has_Image')).lower() in ['true', '1']
                has_trl = bool(best_game.data.get('Trailer_Link') and str(best_game.data.get('Trailer_Link')).startswith('http'))
                
                if ops_logged == 0:
                    logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
                logging.info(format_operation_row("Merged", title_clean, has_img, has_trl))
                ops_logged += 1
                
                stats['matched_smart'] += 1
                stats['merged_titles'].append(title_clean)
                existing_amazon_set.add(clean_amazon_id)
                changes_made = True
                continue
                
            # No Match - Ingest as NEW
            folder_name = get_safe_filename(title_clean) or f"Unknown Game [{clean_amazon_id}]"
            if folder_name in games_dict: folder_name = f"{title_clean} [{clean_amazon_id}]"
            
            game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='NEW', Path_Root='')
            game_obj.data['Clean_Title'] = title_clean
            game_obj.data['game_ID'] = f"amazon_{clean_amazon_id}"
            game_obj.data['Platforms'] = "Amazon"
            game_obj.data['Publisher'] = publisher
            game_obj.data['Summary'] = item_assets.get('description', '')
            game_obj.data['Year_Folder'] = str(year)
            
            if cover_url:
                if cover_url.startswith('//'): cover_url = "https:" + cover_url
                game_obj.data['Cover_URL'] = cover_url
                
            games_dict[folder_name] = game_obj
            existing_amazon_set.add(clean_amazon_id)
            
            has_img = bool(game_obj.data.get('Cover_URL') or game_obj.data.get('Image_Link'))
            has_trl = bool(game_obj.data.get('Trailer_Link') and str(game_obj.data.get('Trailer_Link')).startswith('http'))
            
            if ops_logged == 0:
                logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
            logging.info(format_operation_row("Added", title_clean, has_img, has_trl))
            ops_logged += 1
            
            stats['new_added'] += 1
            stats['new_titles'].append(title_clean)
            changes_made = True

        # Process pending unlinks/deletes for this year
        year_deletes = pending_deletes.get(year, [])
        for folder, action in year_deletes:
            if worker_thread and worker_thread.isInterruptionRequested(): break
            
            game = games_dict.get(folder)
            if not game: continue

            if action == "Unlinked":
                game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
                other_ids = [gid for gid in game_ids if not gid.startswith('amazon_')]
                game.data['game_ID'] = ", ".join(sorted(other_ids))
                p_set = set(x.strip() for x in game.data.get('Platforms', '').split(',') if x.strip())
                if 'Amazon' in p_set: p_set.remove('Amazon')
                game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                stats['matched_smart'] += 1
                changes_made = True
            else:
                del games_dict[folder]
                stats['deleted_ghosts'] += 1
                stats['deleted_ghost_titles'].append(folder)
                changes_made = True

            if ops_logged == 0:
                logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┬", "┬", "┬"]))
            
            has_img = str(game.data.get('Has_Image')).lower() in ['true', '1'] if action == "Unlinked" else False
            has_trl = bool(game.data.get('Trailer_Link') and str(game.data.get('Trailer_Link')).startswith('http')) if action == "Unlinked" else False
            
            logging.info(format_operation_row(action, folder, has_img, has_trl))
            ops_logged += 1

        # Print bottom divider if operations occurred
        if ops_logged > 0:
            logging.info(format_separator_row([17, 36, 5, 5, 5, 5], ["┼", "┼", "┴", "┴", "┴"]))
            
        # Print divider between years (except after the last year 2020)
        if year > 2020:
            logging.info(format_separator_row([17, 36, 23], ["┼", "┼"]))

    # Output the standard 6-row metrics report
    if print_report:
        if worker_thread and worker_thread.isInterruptionRequested():
            logging.warning("Scan interrupted by user.")
        else:
            logging.info(format_middle_header("REPORT", col_spec=[17, 36, 5, 5, 5, 5]))
            logging.info(format_report_row("Total Games", stats['total_cloud']))
            logging.info(format_report_row("Already in DB", stats['already_in_db']))
            logging.info(format_report_row("New Added", stats['new_added']))
            logging.info(format_report_row("Smart Merged", stats['matched_smart']))
            logging.info(format_report_row("Deleted", stats['deleted_ghosts']))
            logging.info(format_report_row("Errors/Ignored", 0))
            logging.info(format_box_bottom([17, 60]))

    return changes_made, stats
