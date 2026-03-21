# WHY: Single Responsibility Principle - A diagnostic tool exclusively designed to rip 
# raw, unfiltered JSON data directly from the GOG API to analyze undocumented data structures.
import os
import sys
import json
import re
import requests

# WHY: DRY Principle - Dynamically import the GOG login module to reuse the existing OAuth token.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.gog.login_gog import get_gog_cookies, refresh_gog_token

def dump_gog_data():
    print("--- GOG API DATA DUMP ---")
    
    session_data = get_gog_cookies()
    access_token = session_data.get('access_token')
    
    if not access_token:
        print("ERROR: No OAuth token found. Please connect your GOG account in ViGaVault first.")
        return

    fresh_token = refresh_gog_token()
    if fresh_token:
        access_token = fresh_token

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    # The user's requested IDs, grouped by game to analyze the ID schism
    target_ids = [
        1207659101, 1098597871,                         # Legacy of Kain Blood Omen 2
        1302753134, 1196310490,                         # Chasm The Rift
        1578751750, 1449710114, 1549667319, 1993581340, # Mafia II Definitive Edition
        1732383191, 1718917128,                         # ELDERBORN
        1158717618                                      # Star Wars Bounty Hunter
    ]

    dump_results = {}
    
    video_output_file = os.path.join(os.path.dirname(__file__), "gog_video_urls.txt")
    v_file = open(video_output_file, 'w', encoding='utf-8')

    for gid in target_ids:
        print(f"Fetching data for ID: {gid} ...")
        dump_results[str(gid)] = {}
        
        # WHY: Endpoint 1 - The Public Store Catalog API (Rich metadata, descriptions, basic images)
        url_catalog = f"https://api.gog.com/products/{gid}?expand=description,downloads,expanded_dlcs,related_products"
        try:
            resp1 = requests.get(url_catalog, headers=headers, timeout=10)
            dump_results[str(gid)]["catalog_api"] = resp1.json() if resp1.status_code == 200 else f"HTTP {resp1.status_code}"
        except Exception as e: dump_results[str(gid)]["catalog_api"] = f"Error: {e}"

        # WHY: Endpoint 2 - The Private Account Details API (Used for downloading installers/goodies/backgrounds)
        url_details = f"https://embed.gog.com/account/gameDetails/{gid}.json"
        try:
            resp2 = requests.get(url_details, headers=headers, timeout=10)
            dump_results[str(gid)]["account_details_api"] = resp2.json() if resp2.status_code == 200 else f"HTTP {resp2.status_code}"
        except Exception as e: dump_results[str(gid)]["account_details_api"] = f"Error: {e}"

        # --- VIDEO URL HARVESTER ---
        # WHY: GOG sometimes embeds raw .mp4 files inside the HTML descriptions instead of providing them 
        # cleanly in an array. We use Regex to rip out all potential video strings for visual inspection.
        cat_data = dump_results[str(gid)].get("catalog_api", {})
        if isinstance(cat_data, dict):
            title_name = cat_data.get("title", str(gid))
            desc_dict = cat_data.get("description", {})
            full_desc = desc_dict.get("full", "") + " " + desc_dict.get("lead", "")
            
            found_vids = set()
            
            # Look for HTML embedded videos (<video src="...">)
            src_matches = re.findall(r'src=["\'](http[^"\']+\.(?:mp4|webm))["\']', full_desc, re.IGNORECASE)
            found_vids.update(src_matches)
            
            # Look for standard YouTube links embedded in text
            yt_matches = re.findall(r'(https?://(?:www\.)?youtube\.com/watch\?v=[a-zA-Z0-9_-]+)', full_desc)
            yt_short = re.findall(r'(https?://youtu\.be/[a-zA-Z0-9_-]+)', full_desc)
            found_vids.update(yt_matches)
            found_vids.update(yt_short)
            
            v_file.write(f"--- {title_name} ({gid}) ---\n")
            if found_vids:
                for v in found_vids: v_file.write(f"{v}\n")
            else:
                v_file.write("No videos found in API data.\n")
            v_file.write("\n")

    v_file.close()
    output_file = os.path.join(os.path.dirname(__file__), "gog_api_dump.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(dump_results, f, indent=4, ensure_ascii=False)
        
    print(f"\nDump complete!")
    print(f"Video URLs saved to: {video_output_file}")

if __name__ == "__main__":
    dump_gog_data()