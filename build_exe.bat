@echo off
REM WHY: Single Responsibility - A dedicated build script to generate the portable folder using PyInstaller.
REM --noconfirm: Overwrites previous builds silently.
REM --onedir: Creates a folder with the .exe and all exposed libraries for instant boot times.
REM --windowed: Hides the black CMD console window when running the GUI.
REM --clean: Flushes PyInstaller's cache to prevent corrupted bytecode Analysis errors.

echo [1/4] Flushing Python native bytecode caches...
REM WHY: Recursively hunts down and destroys all __pycache__ folders in the project 
REM so PyInstaller's modulegraph is forced to read pure, uncorrupted .py source code.
FOR /d /r . %%d in (__pycache__) DO @IF EXIST "%%d" rd /s /q "%%d"

echo [2/4] Cleaning previous build artifacts...
REM WHY: Wipes the physical build folder and spec file to guarantee a completely fresh compilation.
IF EXIST "build" rd /s /q "build"
IF EXIST "ViGaVault_UI.spec" del /q "ViGaVault_UI.spec"

echo [3/4] Building ViGaVault Portable Engine...
REM WHY: The --add-data flags are strictly removed so PyInstaller doesn't trap the files in the _internal folder.
pyinstaller --noconfirm --onedir --windowed --clean ViGaVault_UI.py

echo [4/4] Assembling External User Assets...
REM WHY: Natively copies the editable folders directly next to the executable in the final dist folder.
xcopy /E /I /Y "assets" "dist\ViGaVault_UI\assets" >nul
xcopy /E /I /Y "lang" "dist\ViGaVault_UI\lang" >nul

REM Cleanup after use
REM FOR /d /r . %%d in (__pycache__) DO @IF EXIST "%%d" rd /s /q "%%d"
REM IF EXIST "ViGaVault_UI.spec" del /q "ViGaVault_UI.spec"
echo Build complete! Your portable application is inside the "dist\ViGaVault_UI" folder.