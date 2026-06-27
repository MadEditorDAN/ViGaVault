import json
from backend.api_igdb import get_igdb_access_token, query_igdb_api

token = get_igdb_access_token()
print(f"Token: {token}")

results = query_igdb_api(token, "The Elder Scrolls Arena", limit=2)
for g in results:
    print(f"Game: {g.get('name')} (ID: {g.get('id')})")
    dates = g.get('release_dates', [])
    for d in dates:
        import datetime
        dt = datetime.datetime.utcfromtimestamp(d.get('date', 0)).strftime('%Y-%m-%d')
        print(f"  - {dt} (Platform: {d.get('platform')})")
