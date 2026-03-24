@echo off
REM WHY: Single Responsibility - A dedicated build script to generate the portable folder using PyInstaller.
REM --noconfirm: Overwrites previous builds silently.
REM --onedir: Creates a folder with the .exe and all exposed libraries for instant boot times.
REM --windowed: Hides the black CMD console window when running the GUI.

echo Building ViGaVault Portable Architecture...
pyinstaller --noconfirm --onedir --windowed ^
--add-data "assets;assets" ^
--add-data "lang;lang" ^
--add-data "backend/genre_taxonomy.json;backend" ^
ViGaVault_UI.py

echo Build complete! Your portable application is inside the "dist\ViGaVault_UI" folder.
pause