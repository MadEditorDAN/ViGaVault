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

VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.webm')

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
        self.data.setdefault('Has_Video', False)
        
        if not self.data.get('Clean_Title'):
            self._parse_folder_name()
        self._find_video()
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

            old_vid_name = self.data.get('Path_Video', '')
            if old_vid_name:
                vid_dir = self.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
                old_vid_path = os.path.join(vid_dir, os.path.basename(old_vid_name))
                if os.path.exists(old_vid_path):
                    ext = os.path.splitext(old_vid_name)[1]
                    new_vid_name = f"{new_safe_name}{ext}"
                    new_vid_path = os.path.join(vid_dir, new_vid_name)
                    try:
                        if new_vid_path != old_vid_path:
                            os.rename(old_vid_path, new_vid_path)
                            self.data['Path_Video'] = new_vid_name
                    except Exception as e: logging.error(f"Failed to rename video: {e}")

    def merge_with(self, other):
        ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
        ids.update(x.strip() for x in other.data.get('game_ID', '').split(',') if x.strip())
        self.data['game_ID'] = ", ".join(sorted(ids))

        plats = set(x.strip() for x in self.data.get('Platforms', '').split(',') if x.strip())
        plats.update(x.strip() for x in other.data.get('Platforms', '').split(',') if x.strip())
        # WHY: Treat "Local Copy" as a non-real platform that should be overridden if merged with a digital platform.
        real_plats = [p for p in plats if p.lower() != 'local copy']
        if real_plats:
            if 'Local Copy' in plats: plats.remove('Local Copy')
            if 'local copy' in plats: plats.remove('local copy')
        self.data['Platforms'] = ", ".join(sorted(plats))

        for i in range(1, 51):
            col = f"platform_ID_{i:02d}"
            if not self.data.get(col) and other.data.get(col):
                self.data[col] = other.data.get(col)

        conflicts = {}
        fields_to_check = ['Clean_Title', 'Summary', 'Original_Release_Date', 'Developer', 'Publisher', 'Genre', 'Collection', 'Path_Root', 'Path_Video', 'Image_Link', 'Trailer_Link', 'Year_Folder']
        
        for field in fields_to_check:
            val_a = str(self.data.get(field, '')).strip()
            val_b = str(other.data.get(field, '')).strip()
            if not val_a and val_b: self.data[field] = val_b
            elif val_a and val_b and val_a.casefold() != val_b.casefold():
                conflicts[field] = {'A': val_a, 'B': val_b}
        return conflicts

    def _find_video(self):
        video_dir = self.config.get('video_path', os.path.join(BASE_DIR, 'videos'))
        current_name = self.data.get('Path_Video', '')
        if current_name:
            full_check = os.path.join(video_dir, os.path.basename(current_name))
            if os.path.exists(full_check):
                self.data['Path_Video'] = os.path.basename(current_name)
                return

        safe_name = get_safe_filename(self.data.get('Clean_Title') or self.data.get('Folder_Name', ''))
        for ext in VIDEO_EXTS:
            potential_path = os.path.join(video_dir, f"{safe_name}{ext}")
            if os.path.exists(potential_path):
                self.data['Path_Video'] = f"{safe_name}{ext}"
                return

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
            safe_filename = get_safe_filename(self.data.get('Folder_Name', ''))

            try:
                path = urlparse(cover_url).path
                ext = os.path.splitext(path)[1]
                if not ext: ext = '.jpg'
            except: ext = '.jpg'

            save_path = os.path.join(images_dir, f"{safe_filename}{ext}")
            
            try:
                response = requests.get(cover_url, stream=True)
                if response.status_code == 200:
                    with open(save_path, 'wb') as f: shutil.copyfileobj(response.raw, f)
                    return f"{safe_filename}{ext}"
            except Exception as e: pass
        return ""

    def fetch_metadata(self, token):
        search_term = self.data.get('Search_Title') or self.data.get('Clean_Title') or self.data.get('Folder_Name')
        local_year = self.data.get('Year_Folder', '')
        results = query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
            best_match, best_score = None, -1
            for g in results:
                score = 0
                if search_term.lower() in g.get('name', '').lower(): score += 10
                api_year = None
                dates = g.get('release_dates', [])
                if dates:
                    try:
                        ts = min([d['date'] for d in dates if 'date' in d])
                        api_year = datetime.utcfromtimestamp(ts).strftime('%Y')
                    except: pass
                if local_year and api_year:
                    if local_year == api_year: score += 20
                    elif abs(int(local_year) - int(api_year)) <= 1: score += 10
                if score > best_score:
                    best_score, best_match = score, g
            
            if best_match:
                g = best_match
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = normalize_genre(", ".join([ge['name'] for ge in g.get('genres', [])]))
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
                self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                dates = g.get('release_dates', [])
                api_year_str = ""
                if dates:
                    valid_dates = [d['date'] for d in dates if 'date' in d]
                    if valid_dates:
                        orig_ts = min(valid_dates)
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
                        api_year_str = datetime.utcfromtimestamp(orig_ts).strftime('%Y')
                
                if self.data.get('Platforms') == 'Local Copy' and 'id' in g:
                    current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
                    current_ids.add(f"igdb_{g.get('id')}")
                    self.data['game_ID'] = ", ".join(sorted(list(current_ids)))

                self.data['Image_Link'] = self._ensure_cover(g, silent=True)
                self.data['Status_Flag'] = 'OK'
                
                log_msg = f"    [IGDB] Found: {self.data['Clean_Title']}"
                if api_year_str: log_msg += f" ({api_year_str})"
                logging.info(log_msg)
                return True

        if results is not None:
            logging.warning(f"    [IGDB] No results for '{search_term}'")
            self.data['Status_Flag'] = 'NEEDS_ATTENTION'
        return False

    def fetch_smart_metadata(self, token, search_override=None):
        search_term = search_override or self.data.get('Search_Title') or self.data.get('Folder_Name')
        local_dev = self.data.get('Developer', '').lower()
        local_year = self.data.get('Year_Folder', '')
        results = query_igdb_api(token, search_term=search_term, limit=5)
        
        if results:
            best_match, best_score = None, -1
            for g in results:
                score = 0
                if search_term.lower() in g.get('name', '').lower(): score += 10
                devs = [c['company']['name'].lower() for c in g.get('involved_companies', []) if c.get('developer')]
                if local_dev and any(local_dev in d for d in devs): score += 5
                dates = g.get('release_dates', [])
                if local_year and dates:
                    try:
                        api_year = datetime.utcfromtimestamp(min([d['date'] for d in dates if 'date' in d])).strftime('%Y')
                        if local_year == api_year: score += 5
                    except: pass
                if score > best_score:
                    best_score, best_match = score, g

            if best_match:
                g = best_match
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = normalize_genre(", ".join([ge['name'] for ge in g.get('genres', [])]))
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
                self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                dates = g.get('release_dates', [])
                if dates:
                    orig_ts = min([d['date'] for d in dates if 'date' in d])
                    self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
                
                self.data['Image_Link'] = self._ensure_cover(g)
                self.data['Status_Flag'] = 'OK'
                logging.info(f"    [SMART SCAN] Match found: {self.data['Clean_Title']} (Score: {best_score})")
                return True
        return False

    def apply_candidate_data(self, g):
        self.data['Clean_Title'] = g.get('name', self.data.get('Clean_Title'))
        self.data['Summary'] = g.get('summary', '')
        self.data['Genre'] = normalize_genre(", ".join([ge['name'] for ge in g.get('genres', [])]))
        
        companies = g.get('involved_companies', [])
        self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
        self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
        
        videos = g.get('videos', [])
        self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
        
        dates = g.get('release_dates', [])
        if dates:
            orig_ts = min([d['date'] for d in dates if 'date' in d])
            self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
        
        if self.data.get('Platforms') == 'Local Copy' and 'id' in g:
            current_ids = set(x.strip() for x in self.data.get('game_ID', '').split(',') if x.strip())
            current_ids.add(f"igdb_{g.get('id')}")
            self.data['game_ID'] = ", ".join(sorted(list(current_ids)))

        self.data['Image_Link'] = self._ensure_cover(g, force_download=True)
        self.data['Status_Flag'] = 'LOCKED'
        return True

    def to_dict(self):
        return self.data