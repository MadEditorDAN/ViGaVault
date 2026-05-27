# WHY: Single Responsibility Principle - Strictly handles matching, merging,
# and ghost deletion logic for Amazon Luna/Prime Gaming library synchronization.
import logging
import re
import difflib

from backend.game import Game
from ViGaVault_utils import get_safe_filename

def get_clean_amazon_id(raw_id):
    """
    WHY: Amazon GraphQL API returns prefixed IDs (e.g. 'amzn1.adg.product.UUID').
    We extract the plain UUID portion to prevent re-scraping and maintain perfect compatibility 
    with GOG Galaxy imports.
    """
    if not raw_id:
        return ""
    return raw_id.split('.')[-1].strip()

def sync_amazon_database(config, games_dict, claims_list, worker_thread=None):
    logging.info(f"\n{' AMAZON SYNC ':=^80}")
    
    # 1. Filter claims strictly for AMAZON_GAMES_APP (native PC games, matching the mobile scanner)
    pc_games = []
    for claim in claims_list:
        item = claim.get('item') or {}
        assets_list = item.get('assets') or []
        if isinstance(assets_list, dict):
            assets_list = [assets_list]
        
        # Isolate full PC games
        is_pc_game = False
        for asset in assets_list:
            redemption_platforms = asset.get('redemptionPlatforms') or []
            if 'AMAZON_GAMES_APP' in redemption_platforms:
                is_pc_game = True
                break
        if is_pc_game:
            pc_games.append(claim)
            
    logging.info(f"Found {len(pc_games)} native Amazon PC games in cloud library.")

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

    # 3. Process cloud PC games
    for claim in pc_games:
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
        title_clean = re.sub(r'[^\w\s\-\.\:\,\;\!\?\(\)\[\]\&\'\"]', '', title_raw).strip()
        publisher = game_assets.get('publisher') or ""
        
        # Extract cover url
        card_media = item_assets.get('cardMedia') or {}
        default_media = card_media.get('defaultMedia') or {}
        cover_url = default_media.get('src1x') or ""
        
        # --- ZERO-COST SMART MATCH ---
        norm_title = re.sub(r'[^a-z0-9]', '', title_clean.lower())
        best_score = 0
        best_game = None
        
        for game in games_dict.values():
            local_title = game.data.get('Clean_Title', '')
            local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
            
            score = 0
            if local_norm_title == norm_title: score += 60
            else:
                ratio = difflib.SequenceMatcher(None, title_clean.lower(), local_title.lower()).ratio()
                if ratio > 0.6: score += int(ratio * 60)
                else: continue
                
            local_platforms = game.data.get('Platforms', '').lower()
            if 'amazon' in local_platforms: score += 20
            if local_norm_title == norm_title: score += 20
            
            if score > best_score:
                best_score, best_game = score, game
                
        threshold = 60 if best_game and re.sub(r'[^a-z0-9]', '', best_game.data.get('Clean_Title', '').lower()) == norm_title else 70
        
        # Match found - Merge platforms and IDs
        if best_game and best_score >= threshold:
            current_ids = set(x.strip() for x in best_game.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(f"amazon_{clean_amazon_id}")
            best_game.data['game_ID'] = ", ".join(sorted(list(current_ids)))
            
            p_set = set(x.strip() for x in best_game.data.get('Platforms', '').split(',') if x.strip())
            if 'Local Copy' in p_set: p_set.remove('Local Copy')
            p_set.add("Amazon") # Using strictly "Amazon" as approved!
            best_game.data['Platforms'] = ", ".join(sorted(list(p_set)))
            
            img_str = "Yes" if best_game.data.get('Image_Link') else "No "
            trl_str = "Yes" if best_game.data.get('Trailer_Link') else "No "
            action_title = f"Merged : {title_clean}"
            logging.info(f"|{action_title[:56]:<56}| Img: {img_str[:3]:<3} | Trl: {trl_str[:3]:<3} |")
            
            stats['matched_smart'] += 1
            stats['merged_titles'].append(title_clean)
            existing_amazon_set.add(clean_amazon_id)  # Skip processing this game ID again if it is duplicated in pagination pages
            changes_made = True
            continue
            
        # No Match - Ingest as NEW Game
        folder_name = get_safe_filename(title_clean) or f"Unknown Game [{clean_amazon_id}]"
        if folder_name in games_dict: folder_name = f"{title_clean} [{clean_amazon_id}]"
        
        game_obj = Game(config=config, Folder_Name=folder_name, Status_Flag='NEW', Path_Root='')
        game_obj.data['Clean_Title'] = title_clean
        game_obj.data['game_ID'] = f"amazon_{clean_amazon_id}"
        game_obj.data['Platforms'] = "Amazon"
        game_obj.data['Publisher'] = publisher
        game_obj.data['Summary'] = item_assets.get('description', '')
        
        if cover_url:
            if cover_url.startswith('//'): cover_url = "https:" + cover_url
            game_obj.data['Cover_URL'] = cover_url
            
        games_dict[folder_name] = game_obj
        existing_amazon_set.add(clean_amazon_id)  # Skip processing this game ID again if it is duplicated in pagination pages
        
        img_str = "Yes" if game_obj.data.get('Cover_URL') or game_obj.data.get('Image_Link') else "No "
        trl_str = "Yes" if game_obj.data.get('Trailer_Link') else "No "
        action_title = f"Added : {title_clean}"
        logging.info(f"|{action_title[:56]:<56}| Img: {img_str[:3]:<3} | Trl: {trl_str[:3]:<3} |")
        
        stats['new_added'] += 1
        stats['new_titles'].append(title_clean)
        changes_made = True

    # 4. GHOST DELETION LOGIC
    if not (worker_thread and worker_thread.isInterruptionRequested()):
        ghosts_to_delete = []
        cloud_amazon_ids = set(get_clean_amazon_id(c['item']['id']) for c in pc_games if c.get('item', {}).get('id'))
        
        for folder_name, game in list(games_dict.items()):
            if not game.data.get('Path_Root'):
                # Absolute immunity for explicitly locked games
                if game.data.get('Status_Flag') == 'LOCKED':
                    continue
                    
                game_ids = [x.strip() for x in game.data.get('game_ID', '').split(',') if x.strip()]
                amazon_ids = [gid.replace('amazon_', '') for gid in game_ids if gid.startswith('amazon_')]
                
                if not amazon_ids:
                    continue
                    
                # Filter to native Amazon IDs (UUID format containing hyphens).
                # GOG Galaxy imports Amazon games with numeric IDs (e.g. amazon_123456789) which should be ignored here
                # so they are never deleted or unlinked by the native Amazon sync.
                native_amazon_ids = [aid for aid in amazon_ids if '-' in aid]
                 
                if not native_amazon_ids:
                    continue
                     
                # If all native Amazon IDs are no longer in the cloud list
                missing_all = all(aid not in cloud_amazon_ids for aid in native_amazon_ids)
                if missing_all:
                    other_ids = [gid for gid in game_ids if not gid.startswith('amazon_')]
                    if not other_ids:
                        ghosts_to_delete.append(folder_name)
                    else:
                        # Unlink Amazon platform ID & tag, preserving the rest of the game record
                        game.data['game_ID'] = ", ".join(sorted(other_ids))
                        p_set = set(x.strip() for x in game.data.get('Platforms', '').split(',') if x.strip())
                        if 'Amazon' in p_set: p_set.remove('Amazon')
                        game.data['Platforms'] = ", ".join(sorted(list(p_set)))
                        action_title = f"Unlinked Amazon : {game.data.get('Clean_Title', folder_name)}"
                        logging.info(f"|{action_title[:78]:<78}|")
                        changes_made = True

        for folder in ghosts_to_delete:
            action_title = f"Ghost Delete : {folder}"
            logging.info(f"|{action_title[:78]:<78}|")
            del games_dict[folder]
            stats['deleted_ghosts'] += 1
            stats['deleted_ghost_titles'].append(folder)
            changes_made = True

    report = f"{' REPORT ':=^80}\n"
    report += f"Total Cloud    : {stats['total_cloud']}\n"
    report += f"Already in DB  : {stats['already_in_db']}\n"
    report += f"New Added      : {stats['new_added']}\n"
    report += f"Smart Merged   : {stats['matched_smart']}\n"
    report += f"Ghosts Removed : {stats['deleted_ghosts']}\n"
    report += f"{'='*80}"
    logging.info(report)

    return changes_made, stats
