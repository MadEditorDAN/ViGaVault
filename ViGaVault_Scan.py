import os
import re
import pandas as pd
import logging
import shutil
import ctypes
import requests
import sqlite3
import json
import argparse
from datetime import datetime
import difflib


# --- CONFIGURATION ---
ROOT_PATH = r"\\madhdd02\Software\GAMES"
DB_FILE = "VGVDB.csv"
LOG_DIR = "./logs"
BACKUP_DIR = "./backups"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.webm')
MAX_FILES = 10 

# --- CONFIGURATION API ---
IGDB_CLIENT_ID = "a6q5htw1uxkye5kta223vwjs2qlace"
IGDB_CLIENT_SECRET = "psmi013osf0leudnb0jlyzpr8xz9fq"

# --- LOGGING SETUP ---
def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logs = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.startswith("scan_")]
    logs.sort(key=os.path.getctime)
    while len(logs) >= MAX_FILES:
        os.remove(logs.pop(0))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"scan_{timestamp}.log")
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s [%(levelname)s] %(message)s', 
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'), 
            logging.StreamHandler() # <--- C'est lui qui envoie tout vers la console
        ]
    )
setup_logging()

def is_hidden(filepath):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
        return attrs != -1 and (attrs & 2)
    except:
        return False

class Game:
    def __init__(self, **kwargs):
        self.data = kwargs
        self.data.setdefault('Folder_Name', 'Unknown')
        self.data.setdefault('Path_Root', '')
        self.data.setdefault('Status_Flag', 'NEW')
        self.data.setdefault('Platforms', '')
        if not self.data.get('Clean_Title'):
            self._parse_folder_name()
        self._find_video()
        self._find_image()

    def _parse_folder_name(self):
        name = self.data['Folder_Name']
        
        # Détection de la/des plateforme(s)
        tag_match = re.search(r'\(([^)]+)\)$', name)
        if tag_match:
            tag_content = tag_match.group(1)
            
            # Map pour la canonicalisation des noms de plateforme
            platform_map = {
                'gog': 'GOG',
                'steam': 'Steam',
                'epic games store': 'Epic Games Store',
                'uplay': 'Uplay',
                'origin': 'Origin',
                'amazon': 'Amazon'
            }
            platform_pattern = r'|'.join(platform_map.keys())
            found_platforms_raw = re.findall(platform_pattern, tag_content, re.IGNORECASE)
            
            if found_platforms_raw:
                canonical_platforms = {platform_map[p.lower()] for p in found_platforms_raw}
                self.data['Platforms'] = ", ".join(sorted(list(canonical_platforms)))

        if not self.data.get('Platforms'):
            self.data['Platforms'] = 'Warez'

        # Nettoyage du nom pour le titre
        clean_name = re.sub(r'\s*\([^)]*\)$', '', name).strip() # Retire la dernière parenthèse
        year_match = re.match(r'^(\d{4})\s*-\s*', clean_name)
        if year_match:
            self.data['Year_Folder'] = year_match.group(1)
            clean_name = clean_name[len(year_match.group(0)):]
            
        self.data['Clean_Title'] = clean_name
        self.data['Search_Title'] = clean_name

    def _find_video(self):
        folder = self.data.get('Path_Root', '')
        name = self.data.get('Folder_Name', '')
        if not folder or not os.path.exists(folder):
            return
            
        # Recherche dans le dossier parent (à côté du dossier du jeu)
        parent_dir = os.path.dirname(folder)
            
        for ext in VIDEO_EXTS:
            v_path = os.path.join(parent_dir, f"{name}{ext}")
            if os.path.exists(v_path):
                # On met à jour seulement si c'est nouveau ou différent
                current_video_path = self.data.get('Path_Video', '')
                
                # Normalisation robuste (Absolu + Normalisé + Casse) pour éviter les faux positifs
                try:
                    p1 = os.path.normcase(os.path.abspath(os.path.normpath(current_video_path))) if current_video_path else ""
                    p2 = os.path.normcase(os.path.abspath(os.path.normpath(v_path)))
                except:
                    p1 = os.path.normcase(current_video_path) if current_video_path else ""
                    p2 = os.path.normcase(v_path)

                if p1 != p2:
                    self.data['Path_Video'] = v_path
                    logging.info(f"    [VIDEO] Trouvée : {name}{ext}")
                return

    def _find_image(self):
        # Si le lien existe déjà et est valide, on ne fait rien
        current_path = self.data.get('Image_Link', '')
        if current_path and os.path.exists(current_path):
            return

        # Sinon, on regarde si une image existe déjà dans le dossier images
        name = self.data.get('Folder_Name', '')
        for ext in ['.jpg', '.png', '.jpeg']:
            potential_path = os.path.join("images", f"{name}{ext}")
            if os.path.exists(potential_path):
                self.data['Image_Link'] = potential_path
                logging.info(f"    [IMAGE] Trouvée localement : {name}{ext}")
                return

    def _ensure_cover(self, game_info, force_download=False):
        existing_path = self.data.get('Image_Link', '')
        
        # Si on ne force pas, on vérifie l'existence comme avant
        if not force_download and existing_path and os.path.exists(existing_path):
            return existing_path

        # Si on arrive ici, c'est qu'on doit (re)télécharger
        if 'cover' in game_info:
            os.makedirs("images", exist_ok=True)
            # IGDB fournit une URL relative commençant par //, on rajoute https:
            cover_url = "https:" + game_info['cover']['url'].replace('t_thumb', 't_cover_big')
            save_path = os.path.join("images", f"{self.data['Folder_Name']}.jpg")
            
            try:
                response = requests.get(cover_url, stream=True)
                if response.status_code == 200:
                    with open(save_path, 'wb') as f:
                        for chunk in response.iter_content(1024):
                            f.write(chunk)
                    logging.info(f"    [IMAGE OK] Téléchargée (forcée={force_download}) : {save_path}")
                    return save_path
            except Exception as e:
                logging.error(f"    [IMAGE ERREUR] {e}")
        return ""

    def fetch_metadata(self, token):
        # Utilisation prioritaire du Search_Title pour la requête API
        search_term = self.data.get('Search_Title') or self.data.get('Clean_Title') or self.data.get('Folder_Name')
        
        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        # Note: 'release_dates.date' is essential here to get the Unix timestamp
        query = (f'search "{search_term}"; fields id, name, summary, genres.name, '
                 'involved_companies.company.name, involved_companies.developer, '
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13); limit 1;')
        
        try:
            response = requests.post(api_url, headers=headers, data=query, timeout=10)
            if response.status_code == 200 and response.json():
                g = response.json()[0]
                self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                self.data['Summary'] = g.get('summary', '')
                self.data['Genre'] = ", ".join([ge['name'] for ge in g.get('genres', [])])
                
                companies = g.get('involved_companies', [])
                self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
                self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
                
                videos = g.get('videos', [])
                self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
                
                # Updated Logic for Release Date
                dates = g.get('release_dates', [])
                if dates:
                    # Filter valid dates and extract the earliest timestamp
                    valid_dates = [d['date'] for d in dates if 'date' in d]
                    if valid_dates:
                        orig_ts = min(valid_dates)
                        # Explicitly use utcfromtimestamp to format as DD/MM/YYYY
                        self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
                
                # Si le jeu n'a pas de plateforme définie (c'est un "Warez"), on stocke son ID IGDB.
                if self.data.get('Platforms') == 'Warez':
                    if 'id' in g:
                        self.data['game_ID'] = f"igdb_{g.get('id')}"
                        logging.info(f"    [ID UPDATE] IGDB ID {g.get('id')} assigné au jeu.")

                self.data['Image_Link'] = self._ensure_cover(g)
                self.data['Status_Flag'] = 'OK'
                logging.info(f"    [API SUCCESS] trouvé : {self.data['Clean_Title']}")
                return True
            else:
                logging.warning(f"    [API WARNING] Aucun résultat pour '{search_term}'")
                self.data['Status_Flag'] = 'NEEDS_ATTENTION'
                return False
        except Exception as e:
            logging.error(f"    [API CRITICAL] Erreur réseau : {e}")
            return False

    def fetch_smart_metadata(self, token, search_override=None):
        # 1. Définition du terme de recherche
        search_term = search_override or self.data.get('Search_Title') or self.data.get('Folder_Name')
        logging.info(f"    [SMART SCAN] recherche de : {search_term}")
        
        local_dev = self.data.get('Developer', '').lower()
        local_year = self.data.get('Year_Folder', '')

        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        
        # 2. Requête avec limite à 5 pour le scoring
        query = (f'search "{search_term}"; fields name, summary, genres.name, '
                 'involved_companies.company.name, involved_companies.developer, '
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13, 14, 3); limit 5;')
        
        try:
            response = requests.post(api_url, headers=headers, data=query, timeout=10)
            if response.status_code == 200 and response.json():
                results = response.json()
                best_match = None
                best_score = -1

                # 3. LOGIQUE DE SCORING (Le "cerveau")
                for g in results:
                    score = 0
                    # Score sur le titre
                    if search_term.lower() in g.get('name', '').lower(): score += 10
                    
                    # Score sur le développeur
                    devs = [c['company']['name'].lower() for c in g.get('involved_companies', []) if c.get('developer')]
                    if local_dev and any(local_dev in d for d in devs): score += 5
                    
                    # Score sur l'année
                    dates = g.get('release_dates', [])
                    if local_year and dates:
                        try:
                            api_year = datetime.utcfromtimestamp(min([d['date'] for d in dates if 'date' in d])).strftime('%Y')
                            if local_year == api_year: score += 5
                        except:
                            pass
                    
                    # --- AJOUT DU LOG DE DÉTAIL ---
                    logging.info(f"    [CANDIDAT] '{g.get('name')}' - Score obtenu: {score}")
                    
                    # On garde le meilleur résultat
                    if score > best_score:
                        best_score = score
                        best_match = g
                
                # 4. APPLICATION DU MEILLEUR MATCH
                if best_match:
                    g = best_match
                    self.data['Clean_Title'] = g.get('name', self.data['Clean_Title'])
                    self.data['Summary'] = g.get('summary', '')
                    self.data['Genre'] = ", ".join([ge['name'] for ge in g.get('genres', [])])
                    
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
                    logging.info(f"    [SMART SCAN] Match trouvé : {self.data['Clean_Title']} (Score: {best_score})")
                    return True
            return False
        except Exception as e:
            logging.error(f"    [SMART SCAN CRITICAL] {e}")
            return False

    def fetch_candidates(self, token, search_term):
        search_term = str(search_term).strip()
        # Log du début de la recherche
        logging.info(f"    [MANUAL SCAN] Recherche API pour : {search_term}")
        
        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        
        # Si le terme est un ID numérique, on cherche par ID
        if search_term.isdigit():
            query = (f'fields id, name, summary, genres.name, '
                     'involved_companies.company.name, involved_companies.developer, '
                     f'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where id = {search_term};')
        else:
            query = (f'search "{search_term}"; fields id, name, summary, genres.name, '
                     'involved_companies.company.name, involved_companies.developer, '
                     'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13, 14, 3); limit 50;')
        
        response = requests.post(api_url, headers=headers, data=query, timeout=10)
        
        if response.status_code == 200:
            results = response.json()
            if results:
                logging.info(f"    [MANUAL SCAN] {len(results)} candidats trouvés :")
                for g in results:
                    logging.info(f"        -> {g.get('name')}")
            else:
                logging.warning(f"    [MANUAL SCAN] Aucun résultat pour : {search_term}")
            return results
        else:
            logging.error(f"    [MANUAL SCAN CRITICAL] Erreur API : {response.status_code}")
            return []

    def apply_candidate_data(self, g):
        self.data['Clean_Title'] = g.get('name', self.data.get('Clean_Title'))
        self.data['Summary'] = g.get('summary', '')
        self.data['Genre'] = ", ".join([ge['name'] for ge in g.get('genres', [])])
        
        companies = g.get('involved_companies', [])
        self.data['Developer'] = ", ".join([c['company']['name'] for c in companies if c.get('developer')])
        self.data['Publisher'] = ", ".join([c['company']['name'] for c in companies if c.get('publisher')])
        
        videos = g.get('videos', [])
        self.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={videos[0]['video_id']}" if videos else ""
        
        dates = g.get('release_dates', [])
        if dates:
            orig_ts = min([d['date'] for d in dates if 'date' in d])
            self.data['Original_Release_Date'] = datetime.utcfromtimestamp(orig_ts).strftime('%d/%m/%Y')
        
        # Si le jeu n'a pas de plateforme définie (c'est un "Warez"), on stocke son ID IGDB.
        # Cela rendra les futures mises à jour beaucoup plus fiables.
        if self.data.get('Platforms') == 'Warez':
            if 'id' in g:
                self.data['game_ID'] = f"igdb_{g.get('id')}"
                logging.info(f"    [ID UPDATE] IGDB ID {g.get('id')} assigné au jeu.")

        # Téléchargement forcé de l'image
        self.data['Image_Link'] = self._ensure_cover(g, force_download=True)
        self.data['Status_Flag'] = 'OK'
        return True

    def to_dict(self):
        return self.data

class LibraryManager:
    def __init__(self, root_path, db_file):
        self.root_path = root_path
        self.db_file = db_file
        self.games = {} 

    def sync_gog(self):
        logging.info("--- DÉBUT DE LA SYNCHRONISATION GOG ---")
        token = self.get_access_token()
        gog_db_path = os.path.join(os.environ['ProgramData'], 'GOG.com', 'Galaxy', 'storage', 'galaxy-2.0.db')

        if not os.path.exists(gog_db_path):
            logging.error(f"La base de données GOG Galaxy n'a pas été trouvée à : {gog_db_path}")
            return

        try:
            con = sqlite3.connect(f'file:{gog_db_path}?mode=ro', uri=True)
            query = """
                SELECT DISTINCT
                    urp.releaseKey,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'meta' LIMIT 1) as meta_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'title' LIMIT 1) as title_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'originalTitle' LIMIT 1) as orig_title_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'summary' LIMIT 1) as summary_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'developers' LIMIT 1) as developers_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'publishers' LIMIT 1) as publishers_json,
                    (SELECT value FROM GamePieces gp JOIN GamePieceTypes gpt ON gp.gamePieceTypeId = gpt.id WHERE gp.releaseKey = urp.releaseKey AND gpt.type = 'originalImages' LIMIT 1) as original_images_json,
                    (SELECT name FROM Products p JOIN ReleaseProperties rp ON p.id = rp.gameId WHERE rp.releaseKey = urp.releaseKey LIMIT 1) as product_name,
                    (SELECT title FROM LimitedDetails WHERE productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_title,
                    (SELECT description FROM Details d JOIN LimitedDetails ld ON d.limitedDetailsId = ld.id WHERE ld.productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_summary,
                    (SELECT releaseDate FROM Details d JOIN LimitedDetails ld ON d.limitedDetailsId = ld.id WHERE ld.productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_release_date,
                    (SELECT images FROM LimitedDetails WHERE productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_images,
                    (SELECT videos FROM Details d JOIN LimitedDetails ld ON d.limitedDetailsId = ld.id WHERE ld.productId = (SELECT gameId FROM ReleaseProperties WHERE releaseKey = urp.releaseKey LIMIT 1) LIMIT 1) as ld_videos
                FROM
                    UserReleaseProperties urp
                LEFT JOIN
                    ReleaseProperties rp ON urp.releaseKey = rp.releaseKey
                WHERE
                    (rp.isDlc IS NULL OR rp.isDlc = 0)
            """
            gog_games = con.execute(query).fetchall()
            con.close()
            logging.info(f"{len(gog_games)} jeux trouvés dans votre bibliothèque GOG.")
        except Exception as e:
            logging.error(f"Erreur lors de la lecture de la base de données GOG : {e}")
            return

        os.makedirs("images", exist_ok=True)
        os.makedirs("videos", exist_ok=True)
        
        # Stats pour le rapport
        stats = {
            'total_found': len(gog_games),
            'processed': 0,
            'new': 0,
            'matched_key': 0,
            'matched_smart': 0,
            'errors': 0,
            'fetched_success': 0,
            'fetched_fail': 0
        }

        # Création d'une map pour une recherche ultra-rapide par releaseKey
        key_to_game_map = {game.data.get('game_ID'): game for game in self.games.values() if game.data.get('game_ID')}

        for releaseKey, meta_json, title_json, orig_title_json, summary_json, developers_json, publishers_json, original_images_json, product_name, ld_title, ld_summary, ld_release_date, ld_images, ld_videos in gog_games:
            title = "Unknown"
            metadata = {}
            
            # Helper pour extraire du JSON en toute sécurité
            def safe_json_load(json_str):
                if not json_str: return None
                try: return json.loads(json_str)
                except: return None

            meta_data = safe_json_load(meta_json) or {}

            # 1. Essai via métadonnées complètes (meta)
            title = meta_data.get('title')
            
            # 2. Essai via GamePieces 'title' ou 'originalTitle'
            if not title:
                def extract_title_from_json(json_str):
                    if not json_str: return None
                    try:
                        data = json.loads(json_str)
                        if isinstance(data, dict):
                            return data.get('title') or data.get('value') or data.get('originalTitle')
                        return str(data)
                    except:
                        return json_str # Si ce n'est pas du JSON, c'est peut-être le titre brut
                
                title = extract_title_from_json(title_json)
                if not title: title = extract_title_from_json(orig_title_json)
            
            # 3. Essai via la table Products (fallback ultime)
            if not title: title = product_name
            if not title: title = ld_title

            try:
                if not title:
                    logging.warning(f"    [GOG WARNING] Jeu avec releaseKey {releaseKey} ignoré (pas de titre).")
                    stats['errors'] += 1
                    continue

                platform = 'Unknown'
                if releaseKey.startswith('gog_'): platform = 'GOG'
                elif releaseKey.startswith('steam_'): platform = 'Steam'
                elif releaseKey.startswith('epic_'): platform = 'Epic Games Store'
                elif releaseKey.startswith('xboxone_') or releaseKey.startswith('xbox_'): platform = 'Xbox'
                elif releaseKey.startswith('ps_') or releaseKey.startswith('ps4_') or releaseKey.startswith('ps5_'): platform = 'PlayStation'
                elif releaseKey.startswith('amazon_'): platform = 'Amazon'
                elif releaseKey.startswith('uplay_'): platform = 'Uplay'
                elif releaseKey.startswith('origin_'): platform = 'Origin'
                elif releaseKey.startswith('battle.net_'): platform = 'Battle.net'
                elif releaseKey.startswith('humble_'): platform = 'Humble Bundle'

                # --- EXTRACTION METADATA POUR COMPARAISON ---
                gog_dev = meta_data.get('developer')
                if not gog_dev:
                    d_data = safe_json_load(developers_json)
                    if isinstance(d_data, list): gog_dev = ", ".join(d_data)
                
                gog_pub = meta_data.get('publisher')
                if not gog_pub:
                    p_data = safe_json_load(publishers_json)
                    if isinstance(p_data, list): gog_pub = ", ".join(p_data)

                gog_year = None
                if release_ts := meta_data.get('releaseTimestamp'):
                    gog_year = datetime.utcfromtimestamp(release_ts).strftime('%Y')
                elif ld_release_date:
                    try: gog_year = ld_release_date[:4]
                    except: pass

                game_obj = None
                # 1. Match par identifiant unique (le plus fiable)
                if releaseKey in key_to_game_map:
                    game_obj = key_to_game_map[releaseKey]
                    logging.info(f"    [GOG MATCH KEY] Mise à jour par clé : '{title}'")
                    stats['matched_key'] += 1
                # 2. Match intelligent (Score based)
                else:
                    best_score = 0
                    best_game = None
                    
                    # Normalisation pour comparaison (minuscules, sans caractères spéciaux)
                    norm_title = re.sub(r'[^a-z0-9]', '', title.lower())
                    
                    for game in self.games.values():
                        # On ignore les jeux qui ont déjà un ID GOG (mais on autorise ceux avec un ID IGDB)
                        gid = game.data.get('game_ID', '')
                        if gid and not gid.startswith('igdb_'):
                            continue

                        local_title = game.data.get('Clean_Title', '')
                        local_norm_title = re.sub(r'[^a-z0-9]', '', local_title.lower())
                        
                        score = 0
                        
                        # 1. Titre (0-60 points)
                        if local_norm_title == norm_title:
                            score += 60
                        else:
                            ratio = difflib.SequenceMatcher(None, title.lower(), local_title.lower()).ratio()
                            if ratio > 0.6:
                                score += int(ratio * 60)
                            else:
                                continue # Titre trop différent, on passe

                        # 2. Plateforme (20 points)
                        local_platforms = game.data.get('Platforms', '').lower()
                        if platform.lower() in local_platforms:
                            score += 20
                        
                        # 3. Développeur / Editeur (10 points)
                        local_dev = game.data.get('Developer', '').lower()
                        local_pub = game.data.get('Publisher', '').lower()
                        if gog_dev and gog_dev.lower() in local_dev: score += 10
                        elif gog_pub and gog_pub.lower() in local_pub: score += 10
                        
                        # 4. Année (10 points)
                        local_year = game.data.get('Year_Folder', '')
                        if not local_year and game.data.get('Original_Release_Date'):
                             try: local_year = game.data.get('Original_Release_Date')[-4:]
                             except: pass
                        
                        if gog_year and local_year and gog_year == local_year:
                            score += 10

                        if score > best_score:
                            best_score = score
                            best_game = game
                    
                    # Seuil d'acceptation : 70 points
                    if best_game and best_score >= 70:
                        game_obj = best_game
                        logging.info(f"    [GOG MATCH SMART] Associé (Score: {best_score}) : '{title}' -> '{best_game.data.get('Clean_Title')}'")
                        stats['matched_smart'] += 1
                
                # 3. Si aucun match, c'est un nouveau jeu
                if not game_obj:
                    logging.info(f"    [GOG NEW] Ajout du jeu : '{title}' ({platform})")
                    folder_name = title
                    # Nettoyage des caractères interdits dans les noms de fichiers
                    folder_name = re.sub(r'[<>:"/\\|?*]', '', folder_name)
                    if folder_name in self.games:
                        folder_name = f"{title} [{releaseKey}]" # Evite les doublons de nom
                    game_obj = Game(Folder_Name=folder_name, Status_Flag='OK', Path_Root='')
                    stats['new'] += 1

                # --- MISE A JOUR DES DONNEES ---
                game_obj.data['game_ID'] = releaseKey
                game_obj.data['Clean_Title'] = title
                game_obj.data['Platforms'] = platform

                # Summary
                summary = meta_data.get('summary')
                if not summary:
                    s_data = safe_json_load(summary_json)
                    if isinstance(s_data, dict): summary = s_data.get('summary') or s_data.get('value')
                if not summary: summary = ld_summary
                if summary: game_obj.data['Summary'] = summary

                # Developer
                gog_dev = meta_data.get('developer')
                if not gog_dev:
                    # Parfois 'developers' (pluriel) dans meta
                    devs_list = meta_data.get('developers')
                    if isinstance(devs_list, list):
                        gog_dev = ", ".join([d.get('name', '') if isinstance(d, dict) else str(d) for d in devs_list])
                if not gog_dev:
                    d_data = safe_json_load(developers_json)
                    if isinstance(d_data, list):
                        gog_dev = ", ".join([d.get('name', '') if isinstance(d, dict) else str(d) for d in d_data])
                if gog_dev: game_obj.data['Developer'] = gog_dev

                # Publisher
                gog_pub = meta_data.get('publisher')
                if not gog_pub:
                    pubs_list = meta_data.get('publishers')
                    if isinstance(pubs_list, list):
                        gog_pub = ", ".join([p.get('name', '') if isinstance(p, dict) else str(p) for p in pubs_list])
                if not gog_pub:
                    p_data = safe_json_load(publishers_json)
                    if isinstance(p_data, list):
                        gog_pub = ", ".join([p.get('name', '') if isinstance(p, dict) else str(p) for p in p_data])
                if gog_pub: game_obj.data['Publisher'] = gog_pub

                # Genre
                genres = meta_data.get('genres')
                if genres:
                    if isinstance(genres, list):
                        if len(genres) > 0 and isinstance(genres[0], dict):
                             game_obj.data['Genre'] = ", ".join([g.get('name', '') for g in genres if g.get('name')])
                        else:
                             game_obj.data['Genre'] = ", ".join([str(g) for g in genres])

                # Release Date
                release_date = None
                # GOG utilise 'releaseDate' (vu dans le CSV) ou 'releaseTimestamp'
                release_ts = meta_data.get('releaseDate') or meta_data.get('releaseTimestamp')
                if release_ts:
                    try: release_date = datetime.utcfromtimestamp(release_ts).strftime('%d/%m/%Y')
                    except: pass
                elif ld_release_date:
                    # Nettoyage de la date (parfois "2020-10-05T00:00:00+00:00" ou "2020-10-05")
                    clean_date_str = ld_release_date.split('T')[0] # Garde YYYY-MM-DD
                    try:
                        dt = datetime.strptime(clean_date_str, '%Y-%m-%d')
                        release_date = dt.strftime('%d/%m/%Y')
                    except ValueError:
                        release_date = ld_release_date # On garde tel quel si échec (ex: juste l'année)
                if release_date: game_obj.data['Original_Release_Date'] = release_date

                # Trailer Link (Youtube)
                if not game_obj.data.get('Trailer_Link'):
                    # 1. Depuis meta_data (GOG natif)
                    videos = meta_data.get('videos', [])
                    yt_video = next((v for v in videos if v.get('provider') == 'youtube'), None)
                    
                    # 2. Depuis ld_videos (Jeux externes)
                    if not yt_video and ld_videos:
                        v_data = safe_json_load(ld_videos)
                        if isinstance(v_data, list):
                            yt_video = next((v for v in v_data if v.get('provider') == 'youtube'), None)
                    
                    if yt_video and yt_video.get('video_id'):
                        game_obj.data['Trailer_Link'] = f"https://www.youtube.com/watch?v={yt_video.get('video_id')}"

                folder_name_for_files = game_obj.data['Folder_Name']
                # Téléchargement de la jaquette (toujours)
                cover_url = meta_data.get('image')
                
                # Fallback sur originalImages (souvent présent pour Steam/Epic selon le CSV)
                if not cover_url:
                    orig_imgs = safe_json_load(original_images_json)
                    if orig_imgs:
                        cover_url = orig_imgs.get('verticalCover') or orig_imgs.get('boxart') or orig_imgs.get('poster') or orig_imgs.get('squareIcon') or orig_imgs.get('background')

                if not cover_url and ld_images:
                    imgs = safe_json_load(ld_images)
                    if isinstance(imgs, list) and len(imgs) > 0:
                        # On cherche une image de type "boxart", "vertical_cover", "packshot" ou "poster"
                        preferred_types = ['boxart', 'vertical_cover', 'packshot', 'poster']
                        cover_url = next((img.get('url') for img in imgs if img.get('type') in preferred_types), None)
                        # Si pas de type préférentiel, on cherche n'importe quoi qui n'est PAS un screenshot
                        if not cover_url:
                            cover_url = next((img.get('url') for img in imgs if img.get('type') != 'screenshot'), None)
                
                if cover_url:
                    if cover_url.startswith('//'): cover_url = "https:" + cover_url
                    save_path = os.path.join("images", f"{folder_name_for_files}.jpg")
                    if not os.path.exists(save_path):
                        try:
                            response = requests.get(cover_url, timeout=5)
                            if response.status_code == 200:
                                with open(save_path, 'wb') as f: f.write(response.content)
                                game_obj.data['Image_Link'] = save_path
                        except: pass
                    else:
                        game_obj.data['Image_Link'] = save_path

                # Téléchargement de la vidéo (toujours)
                # On cherche une URL de fichier vidéo direct (.mp4)
                video_url = None
                
                # 1. Via meta_data (GOG)
                videos = meta_data.get('videos', [])
                if videos:
                    video_url = next((v.get('video_url') for v in videos if 'gog' in v.get('provider', '') and v.get('video_url', '').endswith('.mp4')), None)
                
                # 2. Via ld_videos (Externe)
                if not video_url and ld_videos:
                    v_data = safe_json_load(ld_videos)
                    if isinstance(v_data, list):
                        for v in v_data:
                            url = v.get('video_url') or v.get('url')
                            if url and url.endswith('.mp4'):
                                video_url = url
                                break

                if video_url:
                    video_save_path = os.path.join("videos", f"{folder_name_for_files}.mp4")
                    if not os.path.exists(video_save_path):
                        try:
                            response = requests.get(video_url, stream=True, timeout=10)
                            if response.status_code == 200:
                                with open(video_save_path, 'wb') as f: shutil.copyfileobj(response.raw, f)
                                game_obj.data['Path_Video'] = video_save_path
                        except: pass
                    else:
                        game_obj.data['Path_Video'] = video_save_path
                
                self.games[game_obj.data['Folder_Name']] = game_obj
                stats['processed'] += 1
            except Exception as e:
                logging.error(f"    [GOG ERROR] Erreur lors du traitement du jeu '{title}' (releaseKey: {releaseKey}): {e}")
                stats['errors'] += 1

        # Rapport final
        report = (
            "\n=== RAPPORT DE SYNCHRONISATION GOG ===\n"
            f"Jeux trouvés dans GOG : {stats['total_found']}\n"
            f"Jeux traités avec succès : {stats['processed']}\n"
            f"-----------------------------------\n"
            f"Nouveaux jeux ajoutés : {stats['new']}\n"
            f"Mises à jour (Clé unique) : {stats['matched_key']}\n"
            f"Mises à jour (Intelligente) : {stats['matched_smart']}\n"
            f"Erreurs / Ignorés : {stats['errors']}\n"
            "==================================="
        )
        logging.info(report)
        self.save_db()

    def get_access_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": IGDB_CLIENT_ID, "client_secret": IGDB_CLIENT_SECRET, "grant_type": "client_credentials"}
        response = requests.post(url, params=params)
        return response.json().get("access_token") if response.status_code == 200 else None

    def load_db(self):
        if os.path.exists(self.db_file):
            df = pd.read_csv(self.db_file, sep=';', encoding='utf-8').fillna('')
            for _, row in df.iterrows():
                game_data = {k: str(v) for k, v in row.to_dict().items()}
                self.games[game_data['Folder_Name']] = Game(**game_data)
            logging.info(f"{len(self.games)} jeux chargés.")

    def fetch_candidates(self, token, search_term):
        search_term = str(search_term).strip()
        # Log du début de la recherche
        logging.info(f"    [MANUAL SCAN] Recherche API pour : {search_term}")
        
        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        
        # Si le terme est un ID numérique, on cherche par ID
        if search_term.isdigit():
            query = (f'fields name, summary, genres.name, '
                     'involved_companies.company.name, involved_companies.developer, '
                     f'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where id = {search_term};')
        else:
            query = (f'search "{search_term}"; fields name, summary, genres.name, '
                     'involved_companies.company.name, involved_companies.developer, '
                     'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6, 13, 14, 3); limit 50;')
        
        response = requests.post(api_url, headers=headers, data=query, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"    [MANUAL SCAN CRITICAL] Erreur API : {response.status_code}")
            return []

    def scan(self):
        token = self.get_access_token()
        logging.info("--- DÉBUT DU SCAN ---")
        
        stats = {
            'scanned': 0,
            'new': 0,
            'updated': 0,
            'deleted': 0,
            'fetched_success': 0,
            'fetched_fail': 0
        }
        
        found_folders = set() # Pour suivre les jeux réellement présents sur le disque

        for root, dirs, files in os.walk(self.root_path):
            dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
            rel_path = os.path.relpath(root, self.root_path)
            if rel_path == ".": continue
            
            # Ici, on rétablit la vérification de profondeur
            depth = rel_path.count(os.sep) + 1
            
            if depth == 1:
                logging.info(f"Analyse catégorie : {os.path.basename(root)}")
            elif depth == 2:
                stats['scanned'] += 1
                for folder in dirs:
                    found_folders.add(folder) # On marque ce dossier comme trouvé
                    full_path = os.path.join(root, folder)
                    if folder not in self.games:
                        logging.info(f"    [NEW] Découverte : {folder}")
                        self.games[folder] = Game(Folder_Name=folder, Path_Root=full_path)
                        stats['new'] += 1
                    else:
                        # Pour les jeux existants, on met à jour le chemin et on revérifie la vidéo
                        game = self.games[folder]
                        if game.data.get('Path_Root') != full_path:
                            game.data['Path_Root'] = full_path
                        game._parse_folder_name()
                        game._find_video()
                        game._find_image()
                        stats['updated'] += 1
        
        # Nettoyage : Suppression des jeux qui ne sont plus sur le disque
        existing_folders = list(self.games.keys())
        for folder in existing_folders:
            if folder not in found_folders:
                logging.info(f"    [DELETE] Jeu introuvable sur le disque, suppression : {folder}")
                del self.games[folder]
                stats['deleted'] += 1
        
        logging.info("--- VÉRIFICATION DES METADATA ---")
        for name, game in self.games.items():
            # SÉCURITÉ : Vérification physique ultime avant requête
            if not os.path.exists(game.data.get('Path_Root', '')):
                logging.warning(f"    [GHOST] Le dossier '{name}' n'existe plus physiquement. Ignoré.")
                continue
                
            # On fetch les métadonnées si le jeu est nouveau, en erreur, OU s'il n'a pas d'ID et pas de plateforme (jeu local existant)
            is_local_without_id = not game.data.get('game_ID') and game.data.get('Platforms') == 'Warez'
            if game.data.get('Status_Flag') in ['NEW', 'NEEDS_ATTENTION'] or is_local_without_id:
                logging.info(f"    [FETCHING] Tentative pour : {name}")
                if token and game.fetch_metadata(token):
                    stats['fetched_success'] += 1
                else:
                    logging.warning(f"    [FAILURE] Échec pour : {name}")
                    stats['fetched_fail'] += 1
        
        # Rapport final
        report = (
            "\n=== RAPPORT DE SCAN LOCAL ===\n"
            f"Dossiers scannés : {stats['scanned']}\n"
            f"-----------------------------------\n"
            f"Nouveaux jeux détectés : {stats['new']}\n"
            f"Jeux existants vérifiés : {stats['updated']}\n"
            f"Jeux supprimés (introuvables) : {stats['deleted']}\n"
            f"-----------------------------------\n"
            f"Métadonnées récupérées (IGDB) : {stats['fetched_success']}\n"
            f"Échecs récupération IGDB : {stats['fetched_fail']}\n"
            "==================================="
        )
        logging.info(report)
        self.save_db()

    def scan_single_game(self, game_name, manual_search_term=None):
        token = self.get_access_token()
        if not token: return False
        
        game = self.games.get(game_name)
        if game:
            # On passe manual_search_term à fetch_smart_metadata
            success = game.fetch_smart_metadata(token, search_override=manual_search_term)
            self.save_db()
            return success
        return False

    def save_db(self):
        # 1. Création du DataFrame
        df = pd.DataFrame([g.to_dict() for g in self.games.values()])
        
        # 2. Liste de toutes les colonnes attendues (pour garantir la structure)
        expected_columns = [
            'Folder_Name', 'Clean_Title', 'Search_Title', 'Path_Root', 'Path_Video', 
            'Status_Flag', 'Image_Link', 'Year_Folder', 'Platforms', 'Developer', 
            'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Trailer_Link',
            'game_ID'
        ]
        
        # 3. Forcer les colonnes : on ajoute celles qui manquent (remplies de vide)
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ''
        
        # 4. Nettoyage et sauvegarde
        df = df[expected_columns] # Réordonne proprement
        for col in ['Year_Folder', 'Original_Release_Date']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).replace('nan', '')
        
        df.fillna('').to_csv(self.db_file, sep=';', index=False, encoding='utf-8')

if __name__ == "__main__":
    manager = LibraryManager(ROOT_PATH, DB_FILE)
    manager.load_db()
    
    parser = argparse.ArgumentParser(description="ViGaVault Library Manager.")
    parser.add_argument('--sync-gog', action='store_true', help='Synchronise les jeux depuis la base de données GOG Galaxy.')
    args = parser.parse_args()

    if args.sync_gog:
        manager.sync_gog()
    else:
        manager.scan()