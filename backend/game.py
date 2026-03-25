# WHY: Single Responsibility Principle - Holds the data structure for a single game and resolves logic for merging entities.
import os
import re
import logging
import shutil
import difflib
from datetime import datetime
from urllib.parse import urlparse
import requests

from ViGaVault_utils import BASE_DIR, get_safe_filename, normalize_genre
from .api_igdb import query_igdb_api

class Game:
    def __init__(self, config=None, **kwargs):
        self.config = config or {}
        self.data = kwargs
        self.data.setdefault('Folder_Name', 'Unknown')
        self.data.setdefault('Path_Root', '')
        self.data.setdefault('Status_Flag', 'NEW')
        self.data.setdefault('Platforms', '')
        self.data.setdefault('Collection', '')
        
        self.data.setdefault('Is_Local', False)
        self.data.setdefault('Has_Image', False)
        
        if not self.data.get('Clean_Title'):
            self._parse_folder_name()
        self._find_image()

    def _parse_folder_name(self):
        name = self.data['Folder_Name']
        tag_match = re.search(r'\(([^)]+)\)$', name)
        if tag_match:
            tag_content = tag_match.group(1)
            platform_map = self.config.get('platform_map', {})
            if platform_map:
                platform_pattern = r'|'.join(re.escape(k) for k in platform_map.keys())
                found_platforms_raw = re.findall(platform_pattern, tag_content, re.IGNORECASE)
                if found_platforms_raw:
                    canonical_platforms = {platform_map[p.lower()] for p in found_platforms_raw}
                    self.data['Platforms'] = ", ".join(sorted(list(canonical_platforms)))

        if not self.data.get('Platforms') and self.data.get('Path_Root'):
            self.data['Platforms'] = 'Local Copy'

        clean_name = re.sub(r'\s*\([^)]*\)$', '', name).strip()
        year_match = re.match(r'^(\d{4})\s*-\s*', clean_name)
        if year_match:
            self.data['Year_Folder'] = year_match.group(1)
            clean_name = clean_name[len(year_match.group(0)):]
            
        self.data['Clean_Title'] = clean_name
        self.data['Search_Title'] = clean_name

    def update_media_filenames(self, old_title, old_date):
        new_title = self.data.get('Clean_Title', '')
        new_date = self.data.get('Original_Release_Date', '')

        if new_title != old_title or new_date != old_date:
            base_filename = new_title
            if new_date and len(new_date) >= 4:
                base_filename += f" ({new_date[-4:]})"
            new_safe_name = get_safe_filename(base_filename)
            
            old_img_name = self.data.get('Image_Link', '')
            if old_img_name:
                img_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
                old_img_path = os.path.join(img_dir, os.path.basename(old_img_name))
                if os.path.exists(old_img_path):
                    ext = os.path.splitext(old_img_name)[1]
                    new_img_name = f"{new_safe_name}{ext}"
                    new_img_path = os.path.join(img_dir, new_img_name)
                    try:
                        if new_img_path != old_img_path:
                            os.rename(old_img_path, new_img_path)
                            self.data['Image_Link'] = new_img_name
                    except Exception as e: logging.error(f"Failed to rename image: {e}")

    def merge_with(self, other):
        ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
        ids.update(x.strip() for x in other.data.get('game_ID', '').split(',') if x.strip())
        self.data['game_ID'] = ", ".join(sorted(ids))

        plats = set(x.strip() for x in self.data.get('Platforms', '').split(',') if x.strip())
        plats.update(x.strip() for x in other.data.get('Platforms', '').split(',') if x.strip())
        # WHY: Treat "Local Copy" and "_UNKNOWN" as non-real platforms that should be overridden if merged with a valid digital platform.
        real_plats = [p for p in plats if p.lower() not in ['local copy', '_unknown']]
        if real_plats:
            if 'Local Copy' in plats: plats.remove('Local Copy')
            if 'local copy' in plats: plats.remove('local copy')
            if '_UNKNOWN' in plats: plats.remove('_UNKNOWN')
            if '_unknown' in plats: plats.remove('_unknown')
        self.data['Platforms'] = ", ".join(sorted(plats))

        for i in range(1, 51):
            col = f"platform_ID_{i:02d}"
            if not self.data.get(col) and other.data.get(col):
                self.data[col] = other.data.get(col)

        conflicts = {}
        fields_to_check = ['Clean_Title', 'Summary', 'Original_Release_Date', 'Developer', 'Publisher', 'Genre', 'Collection', 'Path_Root', 'Image_Link', 'Trailer_Link', 'Year_Folder']
        
        for field in fields_to_check:
            val_a = str(self.data.get(field, '')).strip()
            val_b = str(other.data.get(field, '')).strip()
            if not val_a and val_b: self.data[field] = val_b
            elif val_a and val_b and val_a.casefold() != val_b.casefold():
                conflicts[field] = {'A': val_a, 'B': val_b}
        return conflicts

    def _find_image(self):
        images_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        current_name = self.data.get('Image_Link', '')
        if current_name:
            full_check = os.path.join(images_dir, os.path.basename(current_name))
            if os.path.exists(full_check):
                self.data['Image_Link'] = os.path.basename(current_name)
                return
                
        safe_name = get_safe_filename(self.data.get('Folder_Name', ''))
        for ext in ['.jpg', '.png', '.jpeg', '.webp']:
            potential_path = os.path.join(images_dir, f"{safe_name}{ext}")
            if os.path.exists(potential_path):
                self.data['Image_Link'] = f"{safe_name}{ext}"
                return

    def _ensure_cover(self, game_info, force_download=False, silent=False):
        existing_name = self.data.get('Image_Link', '')
        images_dir = self.config.get('image_path', os.path.join(BASE_DIR, 'images'))
        existing_path = os.path.join(images_dir, os.path.basename(existing_name)) if existing_name else ''
        
        if not force_download and existing_path and os.path.exists(existing_path):
            return os.path.basename(existing_name)

        if 'cover' in game_info:
            os.makedirs(images_dir, exist_ok=True)
            cover_url = "https:" + game_info['cover']['url'].replace('t_thumb', 't_cover_big')

            # WHY: Always save the URL to the DB for asynchronous backfilling.
            self.data['Cover_URL'] = cover_url

            safe_filename = get_safe_filename(self.data.get('Folder_Name', ''))

            try:
                path = urlparse(cover_url).path
                ext = os.path.splitext(path)[1]
                if not ext: ext = '.jpg'
            except: ext = '.jpg'

            expected_filename = f"{safe_filename}{ext}"
            save_path = os.path.join(images_dir, expected_filename)
            
            # WHY: Only process the physical HTTP download request if manually overridden (like Inline Scans).
            # Automated scans strictly defer downloading to the IGDB Scrapper/Backfill phase.
            if force_download:
                try:
                    response = requests.get(cover_url, stream=True)
                    if response.status_code == 200:
                        with open(save_path, 'wb') as f: shutil.copyfileobj(response.raw, f)
                except Exception as e: pass
            return expected_filename
        return existing_name

    def _score_igdb_candidate(self, g, search_term):
        """WHY: DRY Principle & Tiered Weighting - A single intelligent scoring engine.
        Strictly weights Name and Year highest, uses Dev/Pub as a secondary check, 
        and relegates Media purely to a tie-breaker role to prevent false positives."""
        score = 0
        
        # 1. Exact Match Supremacy (Max 100)
        ratio = difflib.SequenceMatcher(None, search_term.lower(), g.get('name', '').lower()).ratio()
        score += int(ratio * 100)
        
        # 2. Category Multipliers (Max 15)
        folder_lower = self.data.get('Folder_Name', '').lower()
        edition_keywords = ['goty', 'remaster', 'definitive', 'complete', 'edition', 'director', 'redux', 'anniversary']
        has_edition_keyword = any(kw in folder_lower for kw in edition_keywords)
        
        cat = g.get('category', 0)
        if cat == 0: score += 15
        elif cat in [1, 2]: score -= 30
        elif cat in [3, 8, 9] and not has_edition_keyword: score -= 20
        
        # 3. Temporal Priority (Max 40)
        local_year = self.data.get('Year_Folder', '')
        if local_year:
            dates = g.get('release_dates', [])
            if dates:
                try:
                    api_year = datetime.utcfromtimestamp(min([d['date'] for d in dates if 'date' in d])).strftime('%Y')
                    if str(local_year) == str(api_year): score += 40
                    elif abs(int(local_year) - int(api_year)) <= 1: score += 20
                except: pass
        
        # 4. Creator Validation via Fuzzy Matching (Max 20)
        local_dev = self.data.get('Developer', '').lower()
        local_pub = self.data.get('Publisher', '').lower()
        
        def fuzzy_match(local_val, api_list):
            if not local_val: return False
            local_clean = re.sub(r'[^a-z0-9]', '', local_val)
            for api_str in api_list:
                api_clean = re.sub(r'[^a-z0-9]', '', api_str.lower())
                if difflib.SequenceMatcher(None, local_clean, api_clean).ratio() > 0.8:
                    return True
            return False
            
        companies = g.get('involved_companies', [])
        api_devs = [c.get('company', {}).get('name', '') for c in companies if c.get('developer') and c.get('company', {}).get('name')]
        api_pubs = [c.get('company', {}).get('name', '') for c in companies if c.get('publisher') and c.get('company', {}).get('name')]
        
        if fuzzy_match(local_dev, api_devs) or fuzzy_match(local_pub, api_pubs):
            score += 20
            
        # 5. Media Tie-Breakers (Max 7)
        if 'cover' in g and 'url' in g['cover']: score += 5
        if 'videos' in g and g['videos']: score += 2
        
        return score

    def fetch_metadata(self, token):
        search_term = self.data.get('Search_Title') or self.data.get('Clean_Title') or self.data.get('Folder_Name')
        results = query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
            best_match, best_score = None, -1
            for g in results:
                score = self._score_igdb_candidate(g, search_term)
                if score > best_score:
                    best_score, best_match = score, g
            
            # WHY: Minimum Confidence Threshold. Reject the match if it scores less than 80 points,
            # preventing garbage data from being applied when IGDB returns a single, poorly-matched result.
            if best_match and best_score >= 80:
                g = best_match
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = normalize_genre(", ".join([ge.get('name', '') for ge in g.get('genres', [])]))
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('developer') and c.get('company', {}).get('name')])
                self.data['Publisher'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('publisher') and c.get('company', {}).get('name')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                dates = g.get('release_dates', [])
                api_year_str = ""
                if dates:
                    valid_dates = [d['date'] for d in dates if 'date' in d]
                    if valid_dates:
                        orig_ts = min(valid_dates)
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime(self.config.get('date_format', '%d/%m/%Y'))
                        api_year_str = datetime.utcfromtimestamp(orig_ts).strftime('%Y')
                
                if self.data.get('Platforms') == 'Local Copy' and 'id' in g:
                    current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
                    current_ids.add(f"igdb_{g.get('id')}")
                    self.data['game_ID'] = ", ".join(sorted(list(current_ids)))

                self.data['Image_Link'] = self._ensure_cover(g, silent=True)
                self.data['Status_Flag'] = 'OK'
                
                return True

        if results is not None:
            self.data['Status_Flag'] = 'NEEDS_ATTENTION'
        return False

    def fill_missing_metadata(self, token, images_only=False):
        """
        WHY: Single Responsibility - Queries IGDB to strictly fill in any empty fields 
        for newly discovered games without overwriting their existing valid metadata.
        """
        search_term = self.data.get('Search_Title') or self.data.get('Clean_Title') or self.data.get('Folder_Name')
        
        results = query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
            best_match, best_score = None, -1
            for g in results:
                score = self._score_igdb_candidate(g, search_term)
                
                if score > best_score:
                    best_score, best_match = score, g
            
            if best_match and best_score >= 80:
                g = best_match
                
                if images_only:
                    # WHY: Do not check Image_Link string here. A physically deleted image still retains its filename in the DB.
                    if not self.data.get('Cover_URL'):
                        self.data['Image_Link'] = self._ensure_cover(g, silent=True)
                    return True
                
                # WHY: For Local Copies that lack platform metadata, we allow IGDB to perfect the title capitalization and store the ID.
                if self.data.get('Platforms') == 'Local Copy':
                    if 'name' in g: self.data['Clean_Title'] = g.get('name')
                    if 'id' in g:
                        current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
                        current_ids.add(f"igdb_{g.get('id')}")
                        self.data['game_ID'] = ", ".join(sorted(list(current_ids)))
                        
                if not self.data.get('Summary'): self.data['Summary'] = g.get('summary', '')
                if not self.data.get('Genre'): self.data['Genre'] = normalize_genre(", ".join([ge.get('name', '') for ge in g.get('genres', [])]))
                
                companies = g.get('involved_companies', [])
                if not self.data.get('Developer'): self.data['Developer'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('developer') and c.get('company', {}).get('name')])
                if not self.data.get('Publisher'): self.data['Publisher'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('publisher') and c.get('company', {}).get('name')])
                
                if not self.data.get('Trailer_Link'):
                    videos = g.get('videos', [])
                    if videos: self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}"
                
                if not self.data.get('Original_Release_Date'):
                    dates = g.get('release_dates', [])
                    if dates:
                        valid_dates = [d['date'] for d in dates if 'date' in d]
                        if valid_dates:
                            orig_ts = min(valid_dates)
                            self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime(self.config.get('date_format', '%d/%m/%Y'))
                
                # WHY: Let _ensure_cover handle the physical disk check natively.
                if not self.data.get('Cover_URL'):
                    self.data['Image_Link'] = self._ensure_cover(g, silent=True)
                return True
        return False

    def fetch_smart_metadata(self, token, search_override=None):
        search_term = search_override or self.data.get('Search_Title') or self.data.get('Folder_Name')
        
        results = query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
            best_match, best_score = None, -1
            for g in results:
                score = self._score_igdb_candidate(g, search_term)
                if score > best_score:
                    best_score, best_match = score, g

            if best_match and best_score >= 80:
                g = best_match
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = normalize_genre(", ".join([ge.get('name', '') for ge in g.get('genres', [])]))
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('developer') and c.get('company', {}).get('name')])
                self.data['Publisher'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('publisher') and c.get('company', {}).get('name')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                dates = g.get('release_dates', [])
                if dates:
                    valid_dates = [d['date'] for d in dates if 'date' in d]
                    if valid_dates:
                        orig_ts = min(valid_dates)
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime(self.config.get('date_format', '%d/%m/%Y'))
                
                self.data['Image_Link'] = self._ensure_cover(g)
                self.data['Status_Flag'] = 'OK'
                return True
        return False

    def apply_candidate_data(self, g):
        self.data['Clean_Title'] = g.get('name', self.data.get('Clean_Title'))
        self.data['Summary'] = g.get('summary', '')
        self.data['Genre'] = normalize_genre(", ".join([ge.get('name', '') for ge in g.get('genres', [])]))
        
        companies = g.get('involved_companies', [])
        self.data['Developer'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('developer') and c.get('company', {}).get('name')])
        self.data['Publisher'] = ", ".join([c.get('company', {}).get('name', '') for c in companies if c.get('publisher') and c.get('company', {}).get('name')])
        
        videos = g.get('videos', [])
        self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
        
        dates = g.get('release_dates', [])
        if dates:
            valid_dates = [d['date'] for d in dates if 'date' in d]
            if valid_dates:
                orig_ts = min(valid_dates)
                self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime(self.config.get('date_format', '%d/%m/%Y'))
        
        if self.data.get('Platforms') == 'Local Copy' and 'id' in g:
            current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(f"igdb_{g.get('id')}")
            self.data['game_ID'] = ", ".join(sorted(list(current_ids)))

        self.data['Image_Link'] = self._ensure_cover(g, force_download=True)
        self.data['Status_Flag'] = 'LOCKED'
        return True

    def to_dict(self):
        return self.data