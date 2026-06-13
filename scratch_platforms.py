import sys, os
sys.path.append(os.getcwd())
from backend.api_igdb import get_igdb_access_token
import requests
from backend.igdb.login_igdb import get_igdb_keys

token = get_igdb_access_token()
client_id, _ = get_igdb_keys()
headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
query = 'fields id,name; where name ~ *"VR"* | name ~ *"Virtual Reality"* | name ~ *"Quest"* | name ~ *"Oculus"* | name ~ *"Vive"*; limit 50;'
res = requests.post('https://api.igdb.com/v4/platforms', headers=headers, data=query)
for p in res.json():
    print(f"ID: {p.get('id')} - {p.get('name')}")
