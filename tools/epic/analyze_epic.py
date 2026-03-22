# WHY: Single Responsibility - A standalone utility strictly for auditing the actual 
# data structures Epic returns for an authenticated user's library.
import sys
import os
import json
import requests
import shutil

# WHY: Ensure imports work flawlessly from the tools subdirectory.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.epic.login_epic import get_epic_session

def run_epic_analysis():
    session = get_epic_session()
    access_token = session.get("access_token")
    
    if not access_token:
        print("[-] No Epic Games session found. Please click 'Connect' via Platform Manager in ViGaVault first.")
        return

    epic_dir = os.path.dirname(os.path.abspath(__file__))
    images_dir = os.path.join(epic_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    print("[+] Fetching Epic Games Library...")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # WHY: Epic's internal Library API uses cursor-based pagination and caps at 100 items per request.
    # We must loop through the pages using the 'nextCursor' token to retrieve the entire library (400+ games).
    records = []
    cursor = ""
    
    while True:
        library_url = "https://library-service.live.use1a.on.epicgames.com/library/api/public/items"
        if cursor:
            library_url += f"?cursor={cursor}"
            
        resp = requests.get(library_url, headers=headers)
        if resp.status_code != 200:
            print(f"[-] Failed to fetch library page: {resp.status_code} - {resp.text}")
            break
            
        data = resp.json()
        records.extend(data.get("records", []))
        
        cursor = data.get("responseMetaData", {}).get("nextCursor")
        if not cursor:
            break
    
    print(f"[+] Found {len(records)} total items in raw library.")
    
    with open(os.path.join(epic_dir, "epic_library_dump.json"), "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, indent=4)
        
    # WHY: Instead of guessing with GraphQL, we use Epic's internal Bulk Catalog API.
    # By passing the namespace and catalogItemId, it returns guaranteed 1:1 metadata for the exact item owned.
    catalog_results = []
    
    # WHY: Limit to 20 to avoid spamming the API and getting rate limited during testing.
    games_to_analyze = records[:20]
    
    print(f"[+] Fetching rich Catalog Metadata and downloading images for {len(games_to_analyze)} items...")
    
    for idx, item in enumerate(games_to_analyze):
        namespace = item.get("namespace")
        catalog_item_id = item.get("catalogItemId")
        
        if not namespace or not catalog_item_id:
            continue
            
        print(f"    ({idx+1}/{len(games_to_analyze)}) Querying Catalog API for Item ID: {catalog_item_id}")
        
        cat_url = f"https://catalog-public-service-prod06.ol.epicgames.com/catalog/api/shared/namespace/{namespace}/bulk/items?id={catalog_item_id}&includeDLCDetails=true&includeMainGameDetails=true&country=US&locale=en-US"
        
        # WHY: The Catalog API silently returns an empty object {} if requested without the authenticated Bearer token.
        # We inject the headers to prove we have the rights to view these library elements.
        c_resp = requests.get(cat_url, headers=headers, timeout=10)
        
        if c_resp.status_code == 200:
            c_data = c_resp.json()
            
            # WHY: Epic sometimes dynamically redirects the requested catalogItemId to a master ID in the JSON response keys.
            # Instead of strictly checking for the old ID, we safely grab the first available dictionary payload.
            game_metadata = {}
            if c_data and isinstance(c_data, dict):
                game_metadata = list(c_data.values())[0]
            
            if game_metadata:
                title = game_metadata.get("title", "Unknown")
                catalog_results.append({"library_record": item, "catalog_metadata": game_metadata})
                
                # WHY: Explicitly download the images to test resolution quality and aspect ratios.
                for img in game_metadata.get("keyImages", []):
                    img_type = img.get("type", "Unknown")
                    img_url = img.get("url")
                    # WHY: As requested, removed the strict type filter to aggressively download ALL images for analysis.
                    if img_url:
                        safe_title = "".join([c for c in title if c.isalnum() or c==' ']).strip().replace(' ', '_')
                        safe_type = "".join([c for c in img_type if c.isalnum() or c=='_']).strip()
                        filepath = os.path.join(images_dir, f"{safe_title}_{safe_type}.jpg")
                        if not os.path.exists(filepath):
                            try:
                                img_r = requests.get(img_url, stream=True, timeout=5)
                                if img_r.status_code == 200:
                                    with open(filepath, 'wb') as img_f: shutil.copyfileobj(img_r.raw, img_f)
                            except Exception: pass
        
    with open(os.path.join(epic_dir, "epic_catalog_dump.json"), "w", encoding="utf-8") as f:
        json.dump(catalog_results, f, indent=4)
        
    print(f"[+] Done! Data and images saved to {epic_dir}")

if __name__ == "__main__":
    run_epic_analysis()