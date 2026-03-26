# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
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
- Fixed the "Start-Up Overwrite Loop" that wiped user filters and sorting preferences on application boot.
- Fixed the IGDB scrapper "Empty Shell" bug to aggressively prioritize candidates with complete metadata.

### Changed
- Migrated VGVDB from plaintext CSV to an AES-encrypted `.dat` format for absolute security while preserving Pandas memory performance.
- Refined `README.md` to detail technical architecture and feature sets for a broader audience.
- Updated project license to MIT.
- Overhauled real-time UI logging to use single-line dynamic updates instead of spamming multiple rows.

## [0.9.0] - 2026-03-26
### Added
- Initial Beta release of ViGaVault.
- Basic database structure for VGVDB.json.
- Session management for Steam, Epic, and GOG backends.
- Multi-language support (FR, EN, DE, ES, IT).