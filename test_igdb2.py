import sys
sys.path.append('c:/Users/mad_e/PROJECTS/ViGaVault')
from backend.api_igdb import get_igdb_access_token, query_igdb_api
token = get_igdb_access_token()
print(query_igdb_api(token, custom_query='fields id,name,slug; where name = "Below" | name = "below"; limit 10;'))
