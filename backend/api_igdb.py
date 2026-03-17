# WHY: Single Responsibility Principle - Moved to backend package. Isolates Twitch Auth and IGDB API requests.
import logging
import requests

IGDB_CLIENT_ID = "a6q5htw1uxkye5kta223vwjs2qlace"
IGDB_CLIENT_SECRET = "psmi013osf0leudnb0jlyzpr8xz9fq"

def get_igdb_access_token():
    url = "https://id.twitch.tv/oauth2/token"
    params = {"client_id": IGDB_CLIENT_ID, "client_secret": IGDB_CLIENT_SECRET, "grant_type": "client_credentials"}
    response = requests.post(url, params=params)
    if response.status_code == 200:
        logging.info("    [API AUTH] IGDB token successfully generated.")
        return response.json().get("access_token")
    else:
        logging.error(f"    [API AUTH ERROR] Token failure: {response.text}")
        return None

def query_igdb_api(token, search_term=None, limit=5, by_id=False, custom_query=None):
    api_url = "https://api.igdb.com/v4/games"
    headers = {"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {token}"}
    
    if custom_query: query = custom_query
    else:
        fields = ('id, name, summary, genres.name, involved_companies.company.name, '
                  'involved_companies.developer, involved_companies.publisher, '
                  'videos.video_id, release_dates.date, cover.url, category')
        if by_id: query = f'fields {fields}; where id = {search_term};'
        else: query = f'search "{search_term}"; fields {fields}; where platforms = (3, 6, 13, 14, 161, 162, 163); limit {limit};'
            
    try:
        response = requests.post(api_url, headers=headers, data=query, timeout=10)
        if response.status_code == 200: return response.json()
        else:
            logging.error(f"    [IGDB API ERROR] {response.status_code} for query: {query}")
            return None
    except Exception as e:
        logging.error(f"    [IGDB NETWORK ERROR] {e}")
        return None