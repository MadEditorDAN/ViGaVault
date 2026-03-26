@echo off
REM WHY: Single Responsibility - A dedicated build script to generate the portable folder using PyInstaller.
REM --noconfirm: Overwrites previous builds silently.
REM --onedir: Creates a folder with the .exe and all exposed libraries for instant boot times.
REM --windowed: Hides the black CMD console window when running the GUI.
REM --clean: Flushes PyInstaller's cache to prevent corrupted bytecode Analysis errors.

echo [1/5] Flushing Python native bytecode caches...
REM WHY: Recursively hunts down and destroys all __pycache__ folders in the project 
REM so PyInstaller's modulegraph is forced to read pure, uncorrupted .py source code.
FOR /d /r . %%d in (__pycache__) DO @IF EXIST "%%d" rd /s /q "%%d"

echo [2/5] Cleaning previous build artifacts...
REM WHY: Wipes the physical build folder and spec file to guarantee a completely fresh compilation.
IF EXIST "build" rd /s /q "build"
IF EXIST "ViGaVault.spec" del /q "ViGaVault.spec"

echo [3/5] Building ViGaVault Portable Engine...
REM WHY: The --add-data flags are strictly removed so PyInstaller doesn't trap the files in the _internal folder.
REM -n "ViGaVault" forces the executable and the output folder to be named ViGaVault instead of ViGaVault_UI.
pyinstaller --noconfirm --onedir --windowed --clean -n "ViGaVault" ViGaVault_UI.py

echo [4/5] Assembling External User Assets...
REM WHY: Natively copies the editable folders directly next to the executable in the final dist folder.
xcopy /E /I /Y "assets" "dist\ViGaVault\assets" >nul
xcopy /E /I /Y "lang" "dist\ViGaVault\lang" >nul

echo [5/5] Zipping the distribution package...
REM WHY: Uses native PowerShell to compress the final distribution folder into a clean release archive.
IF NOT EXIST "build" mkdir "build"
powershell Compress-Archive -Path "dist\ViGaVault" -DestinationPath "dist\ViGaVault_Beta_0.9.zip" -Force

REM Cleanup after use
FOR /d /r . %%d in (__pycache__) DO @IF EXIST "%%d" rd /s /q "%%d"
IF EXIST "build" rd /s /q "build"
IF EXIST "ViGaVault.spec" del /q "ViGaVault.spec"
echo Build complete! Your portable application is inside the "dist\ViGaVault" folder.