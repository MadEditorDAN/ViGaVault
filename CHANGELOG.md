# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Integrated headless Prime Gaming & Luna GraphQL scanner on the main thread, with persistent browser sessions and automated title smart-merging under the Amazon platform tag.
- Main-window-integrated Last Scan Log settings viewer, displaying monospace logs with auto-scaled fonts and direct settings transitions.
- Consolidated global synchronization summary report at the end of the full library scans.
- Enclosed the new Year filter in a styled, non-collapsible QGroupBox container with matching solid-grey button palette backgrounds.
- Added All and None buttons aligned to the right side of the Year filter row.
- SteamGridDB integration with automated API key extraction and an interactive manual cover picker dialog displaying alternative visual propositions.
- Amazon Luna integration supporting multiple region selections and automated login token capture.
- Standardized database date schema to YYYY-MM-DD with dynamic localization conversion for UI rendering.
- Immediate list sorting reflow triggered in-memory upon editing game dates or titles.
- Implemented real-time Amazon session validation check mid-scan (detecting login redirects), providing instant GUI feedback if the active session has expired and needs to be re-applied.

### Changed
- Swapped custom non-native cover import file selector for the native system Windows Explorer dialog in the metadata editor.
- Removed legacy placeholder storefront checkboxes from the scan settings panel to maintain a clean, active-only storefront layout.
- Restructured all storefront synchronization logs to return clean count-based metrics instead of spamming verbose game title list prints.
- Refactored the Year filter in the sidebar to be a single-row layout displaying Year followed by a colon and the text input field, placed as the absolute first filter in the filters list.
- Updated all collapsible filter group headers globally to use solid-grey button background styling, eliminating dark gap spaces.
- Configured the All button of the Year filter to dynamically grey out when no year is typed, keeping the None button active and enabled by default.
- Upgraded platform tagging system to cumulatively append local copy parenthesized platform tags rather than replacing existing storefront platforms.
- Aligned Amazon Luna scanning logs and report layout to perfectly match standard GOG and Epic formats, ensuring it always outputs a scan header and metrics report block even on empty fetches, and successfully integrates into the final consolidation breakdown and grand totals.
- Added data-loss guard to Amazon ghost deletion logic, completely preventing the unlinking or deletion of local databases if a transient network/scraper issue returns an empty cloud catalog.

### Fixed
- Fixed the Amazon storefront ghost checking logic by swapping from any() to all(), ensuring Galaxy-synced prefix patterns are immune to unlinking during scans.
- Resolved disappearing dynamic filter checkboxes during sidebar resizing by dynamically balancing layout column stretches and performing layout reflow on startup.
- Resolved Amazon scan ImportError by implementing a persistent `get_amazon_profile` function within the login browser dialog module, securing headless cookie storage and preventing crash-on-close C++ parent-child cleanup races.
- Fixed `TypeError` in `FullScanWorker` initialization during full scans by adding the missing `do_amazon` and `amazon_claims` parameters to the background thread constructor and dynamically feeding the retrieved cloud entries to the scanner engine.
- Restored multi-year backward loop over GraphQL claims queries in the headless Amazon scanner, successfully retrieving complete multi-year claim catalogs and deduplicating records by item ID.
- Re-architected scan startup logs to render the pre-scan checklist at the absolute beginning of full scans (on the main thread) before spawning any headless browser sessions.
- Resolved "stuck redoing Page 1" UI confusion by modifying the year-loop progress messaging to only print page numbers for actual multi-page pagination lists.
- Resolved infinite IGDB rescanning loops of incomplete games by excluding `NEEDS_ATTENTION` games from the automated scrapper queue, ensuring they are only queried once when added as `NEW` to prevent redundant network traffic.
- Resolved `TypeError: cannot unpack non-iterable bool object` critical thread crash in full scan thread by aligning `scan_gog_account`, `scan_epic_account`, and `scan_steam_account` return signatures to return `(changes_made, stats)` tuples, matching GOG, Epic, and Steam backend sync expectations.
- Resolved redundant rescanning and duplication of existing Amazon games by implementing a clean UUID extractor `get_clean_amazon_id` to unify dot-prefixed cloud IDs with database GOG Galaxy formats.

## [1.2.0] - 2026-05-20
### Added
- **Added:** Advanced `.vgv` Backup & Restore system (AES-256 encrypted archive) with modular UI for selective data restoration.
- **Added:** Global Test Harness infrastructure (`pytest`, `pytest-qt`) with isolated sandboxing to automatically verify future feature stability.
- **Added:** Steam Browser Authentication via Embedded QWebEngineView. Users can now securely log into Steam natively, solving CAPTCHAs and 2FA, while the app automatically extracts `steamLoginSecure` cookies in the background.
- **Native Key Standardization:** All configuration dictionary keys natively refactored to `camelCase` (e.g. `dateFormat`, `scanSteam`) to strictly align the Python data schemas with the Mobile app's expectations, enabling seamless `.vgv` settings imports/exports.
### Changed
- **Changed:** Removed legacy CSV Export/Import system in favor of the new `.vgv` modular backup architecture.
- **Changed:** Completely removed the legacy Steam Web API Key requirement. The application now fetches Steam libraries directly from the Steam Community profile by scraping the `rgGames` JavaScript payload, perfectly mirroring the Mobile app's logic.

## [0.9.2] - 2026-03-28
### Added
- Virtual platform "Epic Games Mobile" to track iOS and Android game entitlements natively.
- Multi-platform mapping utility for the Epic Games backend to elegantly merge PC and Mobile ownership into single, unified library items.
## [0.9.1] - 2026-03-27
### Changed
- Updated `README.md` to reflect the new AES encryption (`.dat`/`.bin`) architecture, strict 80% IGDB confidence thresholds, and CSV Import/Export capabilities.
### Added
- New project logo with metallic shield and neon blue accents.
- "Video Game Vault" subtitle added to the brand identity.
- Assets directory structure for `assets/images/`.
- **Zero-Trust Security:** AES symmetric encryption for all local configuration and session files (migrated to `.dat`).
- **Steam BYOK:** "Bring Your Own Key" architecture for Steam, replacing the embedded web login for permanent stability.
- Background auto-refresh logic for Epic Games OAuth tokens.
- Tiered, weighted scoring algorithm for IGDB scraping with a strict 80% minimum confidence threshold and data-richness priority.
- Import/Export CSV tools in the File menu to retain full user ownership and external spreadsheet editing capabilities.
- Automated `.zip` release packaging in the PyInstaller build script (`build_exe.bat`).

### Fixed
- Improved `.gitignore` logic to specifically target root `.json` files without affecting subfolders.
- Cleaned up the repository by removing cached configuration files.
- **Security:** Fixed a Regex injection vulnerability in the search bar by enforcing literal string matching.
- Fixed an infinite loop bug in Galaxy ghost deletion concerning digital Steam games.
- Fixed the "Start-Up Overwrite Loop" that wiped user filters and sorting preferences on application boot by blocking signals during UI population.
- Fixed the IGDB scrapper "Empty Shell" bug to aggressively prioritize candidates with complete metadata.
- Fixed Epic Games API pagination by correctly identifying the case-sensitive `responseMetadata` key.
- Fixed a file collision between the encrypted database (`.dat`) and its settings file by migrating settings to `.bin`.

### Changed
- Migrated VGVDB from plaintext CSV to an AES-encrypted `.dat` format for absolute security while preserving in-memory Pandas performance.
- Refined `README.md` to detail technical architecture and feature sets for a broader audience.
- Updated project license to MIT.
- Overhauled real-time UI logging to use single-line dynamic updates instead of spamming multiple rows.

## [0.9.0] - 2026-03-26
### Added
- Initial Beta release of ViGaVault.
- Basic database structure for VGVDB.json.
- Session management for Steam, Epic, and GOG backends.
- Multi-language support (FR, EN, DE, ES, IT).