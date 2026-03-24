# 🌌 ViGaVault (Video Game Vault)

**ViGaVault** is a powerful, offline-first, unified video game library manager. It seamlessly aggregates your digital game collections across multiple storefronts (Steam, GOG, Epic Games) alongside your local DRM-free copies, consolidating them into one beautiful, highly customizable, and searchable interface.

Designed with a focus on speed, data ownership, and clean aesthetics, ViGaVault fetches rich metadata and media for your games while keeping your database entirely local.

---

## ✨ What It Can Do (Current Features)

*   **Unified Library Syncing**: Automatically scans and merges libraries from **Steam**, **Epic Games Store**, **GOG**, and the **GOG Galaxy local database**.
*   **Local DRM-Free Support**: Advanced local folder scanning with customizable rules. Automatically injects metadata (Genres, Collections, Years) based on your physical folder structure.
*   **Smart Deduplication & Merging**: Intelligently matches games across different platforms to prevent duplicates, merging them into a single definitive entry with combined platform tags.
*   **Automated Metadata Scraping**: Integrates with the **IGDB API** in the background to automatically backfill missing developers, publishers, release dates, summaries, and high-quality vertical cover art.
*   **Media & Trailer Management**: Automatically downloads and caches cover images locally for offline viewing. Extracts and plays YouTube or MP4 trailers directly from the application.
*   **Advanced Dynamic Filtering**: Filter your massive library instantly using Excel-style multi-select dropdowns (by Genre, Platform, Publisher, etc.) that dynamically populate based on your actual library content.
*   **Batch Operations**: A dedicated Game Manager for batch editing metadata, batch deleting games, and managing custom exclusion lists (e.g., hiding DLCs or Soundtracks).
*   **Deep Statistics & Reporting**: Generates interactive dashboards visualizing your library's KPIs—top platforms, most common genres, oldest/newest games, media completion ratios, and more.
*   **Highly Customizable UI**: Built with PySide6. Features fully customizable element scaling (images, buttons, text), native Dark/Light themes, and localized translations (English, French, German, Spanish, Italian).

---

## ⚙️ How It Works (Under the Hood)

ViGaVault is built on **Python** using the **PySide6 (Qt)** framework for a responsive, multi-threaded GUI, and **Pandas** for lightning-fast database operations in memory.

1.  **Authentication**: Instead of requiring complex API keys, ViGaVault uses an isolated embedded Chromium browser (`PySide6-WebEngine`) to securely authenticate you with platforms like Steam, Epic, and GOG. It intercepts the session tokens locally and uses them to query your libraries directly.
2.  **Scanning & Parsing**: Background threads orchestrate data fetching. It uses a mix of official APIs (Epic, GOG) and high-speed HTML/React-state scraping (Steam) to pull your ownership lists in seconds.
3.  **Data Enrichment**: Games are initially flagged as `NEW`. A background Scrapper engine then queries IGDB, utilizing fuzzy string matching and weighted scoring algorithms to find the perfect metadata match before promoting the game status to `OK`.
4.  **Local Storage**: Your entire library is saved to a flat, highly visible `VGVDB.csv` file, making it completely portable and easy to view or edit outside the application. Associated configurations are saved in local JSON files.

---

## 🚀 Future Roadmap (What's Next)

ViGaVault is actively evolving. Planned features include:

*   **Migration to SQLite**: Transitioning the core database backend from CSV to SQLite. This will improve data integrity, handle even larger libraries more efficiently, and allow users to utilize tools like *DB Browser for SQLite* for manual administration.
*   **Expanded Storefront Integrations**: Implementing native scanners for additional platforms currently stubbed in the UI, such as Amazon Games, Ubisoft Connect (Uplay), Battle.net, EA/Origin, Xbox, and PSN.
*   **Pre-Scan Discovery Environment**: A robust data discovery tool that allows users to preview a platform's raw data dump *before* importing, giving granular control over exactly which metadata or media files are accepted into the vault.
*   **Enhanced GameCard Customization**: Support for downloading and applying high-resolution background images (e.g., from GOG's repository) to serve as immersive backdrops for individual GameCards.

---

## 🛠️ Installation & Setup

### Requirements
*   Python 3.8+
*   Required packages:
    ```bash
    pip install PySide6 PySide6-WebEngine pandas requests
    ```

### Running the Application
1. Clone the repository.
2. Run the main UI entry point:
    ```bash
    python ViGaVault_UI.py
    ```
3. Open **File > Settings** or the **Platform Manager** in the Tools menu to connect your accounts and set your local game directory paths.
4. Click **SCAN** on the right sidebar to start building your vault!

---

## 📄 License

*(Specify your license here, e.g., MIT License, GPL-3.0, etc.)*