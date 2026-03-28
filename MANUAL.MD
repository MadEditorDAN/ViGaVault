-------------------------------------------------------------------------------
                  _ 
      __      __ (_)   _____         __      __                 _   _   
      \ \    / /  _   / ____|        \ \    / /                | | | |  
       \ \  / /  | | | |  __    __ _  \ \  / /   __ _   _   _  | | | |_ 
        \ \/ /   | | | | |_ |  / _` |  \ \/ /   / _` | | | | | | | | __|
         \  /    | | | |__| | | (_| |   \  /   | (_| | | |_| | | | | |_ 
          \/     |_|  \_____|  \__,_|    \/     \__,_|  \__,_| |_|  \__|

-------------------------------------------------------------------------------
User Manual
-------------------------------------------------------------------------------
Welcome to ViGaVault (Video Game Vault), your high-performance, offline-first
unified video game library manager. This guide will walk you through setting 
up your vault, connecting your accounts, and managing your library with 
forensic precision.

-------------------------------------------------------------------------------
1. Step-by-Step New User Setup & Platforms
-------------------------------------------------------------------------------
When you launch ViGaVault for the very first time, the application will 
automatically prompt you to set up your core configuration. The first and 
most important step is connecting your gaming platforms so ViGaVault knows 
where to look for your games.

Connecting Your Platforms:
--------------------------
Navigate to the Platform Manager in the settings. Currently, ViGaVault 
supports four active integrations (with others marked as "coming soon").

IGDB (Required for Metadata): Before anything else, input your IGDB/Twitch 
Developer Client ID and Secret. This "Bring Your Own Key" (BYOK) system is 
what ViGaVault uses to download all your high-quality game covers, 
descriptions, and release dates.

Epic Games Store: Click connect to log in via the secure pop-up. ViGaVault 
uses a secure OAuth2 flow, meaning you only need to log in once, and the app 
will automatically refresh its access in the background in the future.

GOG.com: Similar to Epic, log in once via the secure portal to grant ViGaVault 
read-only access to your digital GOG library.

Steam: Steam uses a BYOK architecture. You will need to provide your Steam ID 
and a free Steam Web API key to securely sync your digital library without 
risking your account credentials.

GOG Galaxy (Local): If you use GOG Galaxy on your PC, ViGaVault can 
automatically parse its local database to instantly import your existing 
library organization.

-------------------------------------------------------------------------------
2. Library Settings & The Local Copy System
-------------------------------------------------------------------------------
Once your digital accounts are linked, navigate to the Library Settings. This
is where you tell ViGaVault how to handle games physically present on your 
drives (local copies).

The Local Copy System:
----------------------
Not all games come from a digital storefront. If you have DRM-free backups, 
retro games, or standalone installations, you can point ViGaVault to your root
folders (e.g., D:\My Games\).

Folder Rules & Auto-Tagging:
----------------------------
ViGaVault features an Intelligent Local File Scanner that reads your physical 
folder structure to automatically organize your games.

Folder Names: ViGaVault cleans up folder names automatically 
(turning The_Witcher_3_v1.0 into The Witcher 3).

Auto-Tagging Rules: You can configure ViGaVault to read specific tags in your 
folder names or structures. For example, if you organize your hard drive like 
D:\Games\RPGs\, you can set a rule so that any game scanned inside that folder
automatically receives the "RPG" Genre tag.

Global Filters: You can tell the scanner to ignore hidden folders or specific 
keywords so it doesn't accidentally scan internal application data or backup 
folders.

-------------------------------------------------------------------------------
3. Launching Your Game Scans
-------------------------------------------------------------------------------
With your platforms connected and folders defined, you are ready to build 
your vault. Look for the SCAN section on the main interface.

Understanding Scan Settings:
----------------------------
Before clicking "Start Scan," you can toggle exactly what you want ViGaVault 
to look for.

- Galaxy Sync / GOG / Epic / Steam: Toggle these ON to fetch your latest 
digital purchases from the cloud.

- Local Folders: Toggle ON to scan your physical hard drives for new local 
copies. You can scan all folders or target specific ones.

- Images Download: Toggle ON to allow ViGaVault to automatically download 
high-quality vertical cover art for any new games it finds.

What Happens During a Scan:
---------------------------
Intake & Deduplication: ViGaVault rapidly pulls in all your games. If it sees 
you own Cyberpunk 2077 on GOG, Steam, and as a Local Copy, its fuzzy-logic 
engine safely merges them into a single definitive entry with multiple 
platform tags.

The IGDB Scraper: Once the games are imported, they are flagged as NEW. 
ViGaVault then silently contacts IGDB in the background, using a strict 
algorithm to accurately download the developer, publisher, summary, and cover.

Completion: If successful, the game is marked as OK and appears beautifully 
in your library.

-------------------------------------------------------------------------------
4. Editing Games (Hidden & Locked States)
-------------------------------------------------------------------------------
Sometimes you need to manually adjust a game's details. By clicking the pen 
icon on a game card, you can edit its metadata (Genres, Collections, 
Developer, etc.).

The "Lock" Feature (LOCKED):
----------------------------
If you manually change a game's title, cover art, or description, you don't 
want ViGaVault overwriting your hard work during the next scan. By setting a 
game's status to LOCKED, you tell the background IGDB scraper to completely 
ignore this game in the future. Your manual edits are permanently protected.

The "Hidden" Feature (Exclusions & DLCs):
-----------------------------------------
Over time, digital storefronts will flood your library with Soundtracks, 
Artbooks, or DLCs.

-------------------------------------------------------------------------------
5. Manual Scans:
-------------------------------------------------------------------------------
Occasionally, the automatic IGDB scraper might fail to find a game (marking it 
as NEEDS_ATTENTION), usually because the store's title is too obscure or 
strangely formatted.

Manual Scan on a single game:
-----------------------------
Click on the sreach icon in the gamecard. It will start searching for the name 
it has, but if it fails, you can yype in a simplified or alternate name for 
the game (e.g., changing "The Witcher 3: Wild Hunt - Game of the Year Edition" 
to simply "Witcher 3"). ViGaVault will query IGDB with your custom term, 
allowing you to select the correct match and instantly backfill the missing 
data and images.

-------------------------------------------------------------------------------
6. Batch Edit or Delete Games
-------------------------------------------------------------------------------
If you need to organize a massive library, doing it one by one is tedious. 
Use the Game Manager (accessible via the main menu) for powerful bulk 
operations.

Using the Game Manager:
-----------------------
The Game Manager is a spreadsheet-like view of your entire database. 
It features Excel-style multi-select dropdowns at the top of every column, 
allowing you to instantly filter down to exactly what you want (e.g., "Show 
me all Action games developed by Ubisoft").

Batch Delete: Select multiple rows using the checkboxes and delete them from 
your vault simultaneously.

Batch Edit: Select multiple games and click "Batch Edit." A dialog will appear 
where you can type in a new Publisher, Genre, or Collection.

Safe Blank Logic: If you leave a field blank in the batch editor, ViGaVault 
will ignore it. It only append the specific fields you type into.

Exclusions word list: you can add specific keywords (like "Soundtrack" or 
"Bonus") to your Exclusion List. Any game flagged as Excluded is instantly 
hidden from your main library view, keeping your vault clean. You can view 
them at any time by toggling the specific "Show Hidden" filters in the sidebar.

-------------------------------------------------------------------------------
7. Media Manager
-------------------------------------------------------------------------------
ViGaVault acts as a completely offline visual vault. All images are saved 
locally to your hard drive so they load instantly without needing internet.

Managing Visual Assets:
-----------------------
While the background scanner downloads images automatically, the Media Manager 
gives you manual control over your aesthetics:

Missing Media Check: The app continually tracks the physical status of your 
images. If you accidentally delete a cover from your hard drive, ViGaVault 
detects it.

Manual Overrides: Don't like the official poster? You can manually point 
ViGaVault to a custom .jpg or .png file on your computer to use as the cover.

Trailers: ViGaVault stores links to YouTube trailers or online mp4 files, 
allowing you to play rich media directly from the game's detail page. If the 
automatic scraper misses a trailer, you can paste a YouTube link directly into
the Media Manager to link it.

-------------------------------------------------------------------------------
            __  __             _  ______     _  _  _                 
           |  \/  |           | ||  ____|   | |(_)| |                
           | \  / |  __ _   __| || |__    __| | _ | |_   ___   _ __  
           | |\/| | / _` | / _` ||  __|  / _` || || __| / _ \ | '__| 
           | |  | || (_| || (_| || |____| (_| || || |_ | (_) || |    
           |_|  |_| \__,_| \__,_||______|\__,_||_| \__| \___/ |_|

-------------------------------------------------------------------------------
