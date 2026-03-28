@echo off
REM Dedicated build script to generate the portable folder using PyInstaller.

echo [1/5] Flushing Python native bytecode caches...
REM WHY: Recursively hunts down and destroys all __pycache__ folders in the project 
REM so PyInstaller's modulegraph is forced to read pure, uncorrupted .py source code.
FOR /d /r . %%d in (__pycache__) DO @IF EXIST "%%d" rd /s /q "%%d"

echo [2/5] Cleaning previous build artifacts...
REM WHY: Wipes the physical build folder,spec file and preparing destination folder 
REM to guarantee a completely fresh compilation.
IF EXIST "build" rd /s /q "build"
mkdir "build"
IF EXIST "dist" rd /s /q "dist"
IF EXIST "ViGaVault.spec" del /q "ViGaVault.spec"
IF EXIST "d:\ViGaVault\_internal\" rd /s /q "d:\ViGaVault\_internal\"
IF EXIST "d:\ViGaVault\assets\" rd /s /q "d:\ViGaVault\assets\"
IF EXIST "d:\ViGaVault\lang\" rd /s /q "d:\ViGaVault\lang\"
IF EXIST "d:\ViGaVault\ViGaVault.exe" del /q "d:\ViGaVault\ViGaVault.exe"

echo [3/5] Building ViGaVault Portable Engine...
REM --noconfirm: Overwrites previous builds silently.
REM --onedir: Creates a folder with the .exe and all exposed libraries for instant boot times.
REM --windowed: Hides the black CMD console window when running the GUI.
REM --clean: Flushes PyInstaller's cache to prevent corrupted bytecode Analysis errors.
REM -n "ViGaVault" forces the executable and the output folder to be named ViGaVault.
REM --icon: Injects the custom ViGaVault logo into the compiled .exe file metadata.
pyinstaller --noconfirm --onedir --windowed --clean -n "ViGaVault" --icon="assets\images\ViGaVault.ico" ViGaVault_UI.py

echo [4/5] Assembling External User Assets...
REM WHY: Natively copies the editable folders directly next to the executable in the final dist folder.
xcopy /E /I /Y "assets" "dist\ViGaVault\assets" >nul
xcopy /E /I /Y "lang" "dist\ViGaVault\lang" >nul

echo [5/5] Ready to Zip the distribution package...
REM WHY: Uses WinRAR for significantly faster and more powerful maximum-level ZIP compression.
pause 
"c:\Program Files\WinRAR\winrar.exe" a -afzip -m5 -y "d:\ViGaVault\ViGaVault_Beta_0.9.2.zip" "d:\ViGaVault\ViGaVault"

REM Cleanup after use
FOR /d /r . %%d in (__pycache__) DO @IF EXIST "%%d" rd /s /q "%%d"
IF EXIST "build" rd /s /q "build"
IF EXIST "ViGaVault.spec" del /q "ViGaVault.spec"
echo Build complete! Your portable application is inside the "dist\ViGaVault" folder.