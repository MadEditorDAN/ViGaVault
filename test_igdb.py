import sys
sys.path.append('c:/Users/mad_e/PROJECTS/ViGaVault')
from backend.api_igdb import get_igdb_access_token, query_igdb_api
token = get_igdb_access_token()
print("Token:", bool(token))
res1 = query_igdb_api(token, custom_query='fields id,name,slug; where slug = "below";')
print("Slug Query:", res1)
res2 = query_igdb_api(token, custom_query='search "Below"; fields id,name,slug; limit 10;')
print("Search Query:", res2)
res3 = query_igdb_api(token, custom_query='fields id,name,slug; where name ~ *"Below"* | name ~ *"below"*; limit 10;')
print("Name Match Query:", res3)
