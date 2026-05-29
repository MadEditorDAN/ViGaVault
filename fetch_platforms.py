import sys
import os
sys.path.insert(0, r"c:\Users\mad_e\PROJECTS\ViGaVault")
from backend.api_igdb import get_igdb_access_token
import requests
import json

def main():
    token = get_igdb_access_token()
    if not token: return
    from backend.igdb.login_igdb import get_igdb_keys
    client_id, _ = get_igdb_keys()
    
    api_url = "https://api.igdb.com/v4/platforms"
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
    
    query = "fields id, name, category; limit 500;"
    
    response = requests.post(api_url, headers=headers, data=query)
    if response.status_code == 200:
        results = response.json()
        with open("platforms_dump.txt", "w", encoding="utf-8") as f:
            for r in results:
                f.write(f"ID {r['id']:<4} | {r['name']}\n")
    else:
        print(f"Error: {response.status_code} {response.text}")

if __name__ == "__main__":
    main()
