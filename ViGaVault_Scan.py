import os
import re
import pandas as pd
import logging
import shutil
import ctypes
import requests
from datetime import datetime


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

    def _parse_folder_name(self):
        name = self.data['Folder_Name']
        clean_name = re.sub(r'\(.*?\)', '', name).strip()
        year_match = re.match(r'^(\d{4})\s*-\s*', clean_name)
        if year_match:
            self.data['Year_Folder'] = year_match.group(1)
            clean_name = clean_name[len(year_match.group(0)):]
        self.data['Clean_Title'] = clean_name
        self.data['Search_Title'] = clean_name

    def _find_video(self):
        folder = self.data['Path_Root']
        name = self.data['Folder_Name']
        for ext in VIDEO_EXTS:
            v_path = os.path.join(folder, f"{name}{ext}")
            if os.path.exists(v_path):
                self.data['Path_Video'] = v_path
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
        query = (f'search "{search_term}"; fields name, summary, genres.name, '
                 'involved_companies.company.name, involved_companies.developer, '
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6); limit 1;')
        
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
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6); limit 5;')
        
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
        # Log du début de la recherche
        logging.info(f"    [MANUAL SCAN] Recherche API pour : {search_term}")
        
        api_url = "https://api.igdb.com/v4/games"
        headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
        query = (f'search "{search_term}"; fields name, summary, genres.name, '
                 'involved_companies.company.name, involved_companies.developer, '
                 'involved_companies.publisher, videos.video_id, release_dates.date, cover.url; where platforms = (6); limit 20;')
        
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

    def scan(self):
        token = self.get_access_token()
        logging.info("--- DÉBUT DU SCAN ---")
        for root, dirs, files in os.walk(self.root_path):
            dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
            rel_path = os.path.relpath(root, self.root_path)
            if rel_path == ".": continue
            
            # Ici, on rétablit la vérification de profondeur
            depth = rel_path.count(os.sep) + 1
            
            if depth == 1:
                logging.info(f"Analyse catégorie : {os.path.basename(root)}")
            elif depth == 2:
                for folder in dirs:
                    if folder not in self.games:
                        logging.info(f"    [NEW] Découverte : {folder}")
                        self.games[folder] = Game(Folder_Name=folder, Path_Root=os.path.join(root, folder))
        
        logging.info("--- VÉRIFICATION DES METADATA ---")
        for name, game in self.games.items():
            if game.data.get('Status_Flag') in ['NEW', 'NEEDS_ATTENTION']:
                logging.info(f"    [FETCHING] Tentative pour : {name}")
                if token and game.fetch_metadata(token):
                    pass
                else:
                    logging.warning(f"    [FAILURE] Échec pour : {name}")
        
        logging.info("--- SCAN TERMINÉ ---")
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
            'Publisher', 'Original_Release_Date', 'Summary', 'Genre', 'Trailer_Link'
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
    manager.scan()