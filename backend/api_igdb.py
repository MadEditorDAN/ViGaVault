# WHY: Single Responsibility Principle - Moved to backend package. Isolates Twitch Auth and IGDB API requests.
import logging
import requests
import time

def get_igdb_access_token():
    # WHY: Dynamically load keys from the secure user session instead of relying on hardcoded vulnerabilities.
    from .igdb.login_igdb import get_igdb_keys
    client_id, client_secret = get_igdb_keys()
    if not client_id or not client_secret:
        logging.error(f"{'IGDB API ERROR':<15} : Missing API Keys. Please configure IGDB in Platform Manager.")
        return None
        
    url = "https://id.twitch.tv/oauth2/token"
    params = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    try:
        # WHY: Always enforce a timeout to prevent the thread from freezing permanently if the auth server drops the connection.
        response = requests.post(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            logging.error(f"{'IGDB API ERROR':<15} : Token failure: {response.text}")
            return None
    except Exception as e:
        logging.error(f"{'IGDB API ERROR':<15} : Token request failed: {e}")
        return None

def query_igdb_api(token, search_term="", limit=10, by_id=False, custom_query=None, go_wild=False):
    """WHY: Centralized API abstraction enforcing standard field retrieval and platform filters."""
    from .igdb.login_igdb import get_igdb_keys
    client_id, _ = get_igdb_keys()
    if not client_id: return None
    
    api_url = "https://api.igdb.com/v4/games"
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
    
    if custom_query: query = custom_query
    else:
        fields = ('id, name, summary, genres.name, involved_companies.company.name, '
                  'involved_companies.developer, involved_companies.publisher, '
                  'videos.video_id, release_dates.date, cover.url, category, platforms')
        if by_id: query = f'fields {fields}; where id = {search_term};'
        elif go_wild: query = f'search "{search_term}"; fields {fields}; limit {limit};'
        else: query = f'search "{search_term}"; fields {fields}; where platforms = (3, 6, 13, 14, 34, 39, 48, 49, 130, 161, 162, 163, 164, 165, 167, 169, 384, 385, 386, 388, 390, 409, 471); limit {limit};'
            
    # WHY: Twitch/IGDB strictly limits API requests to 4 per second. 
    # We enforce a mandatory 300ms delay to prevent HTTP 429 (Too Many Requests) connection hangs.
    time.sleep(0.3)
    
    try:
        response = requests.post(api_url, headers=headers, data=query, timeout=10)
        if response.status_code == 200:
            results = response.json()
            if not results and not by_id and not custom_query:
                # WHY: IGDB's full-text search engine aggressively filters out short/common English "stop words" 
                # (like "Below", "Control", "Inside"), returning zero results. We bypass the full-text search 
                # engine entirely by doing a direct exact-match fallback query.
                exact_query = f'fields {fields}; where name ~ "{search_term}"; limit {limit};'
                try:
                    time.sleep(0.3)
                    fallback_res = requests.post(api_url, headers=headers, data=exact_query, timeout=10)
                    if fallback_res.status_code == 200 and fallback_res.json():
                        return fallback_res.json()
                except Exception:
                    pass

                import re
                fallback_regex = re.compile(r'\s*\(?(\d{4}|classic|original|remake)\)?$', flags=re.IGNORECASE)
                if fallback_regex.search(search_term):
                    fallback_term = fallback_regex.sub('', search_term).strip()
                    fallback_term = re.sub(r'[:-]\s*$', '', fallback_term).strip()
                    if fallback_term and fallback_term != search_term:
                        return query_igdb_api(token, search_term=fallback_term, limit=limit, by_id=by_id, custom_query=custom_query)
            return results
        else:
            logging.error(f"{'IGDB API ERROR':<15} : {response.status_code} for query: {query}")
            return None
    except Exception as e:
        logging.error(f"{'IGDB API ERROR':<15} : {e}")
        return None