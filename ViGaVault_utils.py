# WHY: Extracted utility, configuration, and theming logic into a separate module 
# to keep the main UI file cleaner and more maintainable.
import os
import json
import logging
from datetime import datetime
from PySide6.QtWidgets import QApplication, QStyleFactory
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt, QObject, Signal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")

def get_db_path():
    """Reads the db_path from settings.json, falling back to the default."""
    settings_file = os.path.join(BASE_DIR, "settings.json")
    default_db = os.path.join(BASE_DIR, "VGVDB.csv")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("db_path", default_db)
        except Exception:
            pass
    return default_db

def get_library_settings_file():
    """Returns the path to the JSON settings file for the current library."""
    db_path = get_db_path()
    return os.path.splitext(db_path)[0] + ".json"

def get_video_path():
    """Returns the configured video path or default 'videos' folder."""
    settings_path = get_library_settings_file()
    default_path = os.path.join(BASE_DIR, "videos")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("video_path", default_path)
        except: pass
    return default_path

def get_root_path():
    """Returns the configured root path from the library's settings."""
    settings_path = get_library_settings_file()
    default_path = r"\\madhdd02\Software\GAMES"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("root_path", default_path)
        except: pass
    global_settings_path = os.path.join(BASE_DIR, "settings.json")
    if os.path.exists(global_settings_path):
         try:
            with open(global_settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("root_path", default_path)
         except: pass
    return default_path

def get_platform_config():
    """Loads platform mapping and ignore list from settings.json or returns defaults."""
    default_map = {
        'gog': 'GOG', 'steam': 'Steam', 'epic': 'Epic Games Store', 'epic games store': 'Epic Games Store',
        'uplay': 'Uplay', 'ubisoft': 'Uplay', 'ubisoft connect': 'Uplay', 'origin': 'Origin', 
        'ea': 'EA', 'ea app': 'EA', 'amazon': 'Amazon', 'amazon prime': 'Amazon',
        'battlenet': 'Battle.net', 'battle.net': 'Battle.net', 'rockstar': 'Rockstar', 
        'bethesda': 'Bethesda', 'itch': 'itch.io', 'itch.io': 'itch.io', 'discord': 'Discord',
        'ffxiv': 'Final Fantasy XIV', 'kartridge': 'Kartridge', 'minecraft': 'Minecraft',
        'oculus': 'Oculus', 'paradox': 'Paradox', 'riot': 'Riot Games', 'stadia': 'Stadia',
        'totalwar': 'Total War', 'twitch': 'Twitch', 'wargaming': 'Wargaming.net',
        'winstore': 'Windows Store', 'windows store': 'Windows Store', 'beamdog': 'Beamdog',
    }
    default_ignore = [
        'humble', 'gmg', 'fanatical', 'nuuvem', 'indiegala', 
        'd2d', 'direct2drive', 'dotemu', 'fxstore', 'gamehouse', 
        'gamesessions', 'gameuk', 'playfire', 'weplay'
    ]
    settings_path = get_library_settings_file()
    global_settings_path = os.path.join(BASE_DIR, "settings.json")
    if not os.path.exists(settings_path):
        settings_path = global_settings_path
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("platform_map", default_map), settings.get("ignored_prefixes", default_ignore)
        except Exception as e:
            logging.error(f"Error loading settings.json: {e}")
    return default_map, default_ignore

def get_local_scan_config():
    """Loads local scan configuration from settings.json."""
    default_config = {
        "ignore_hidden": True,
        "scan_mode": "advanced",
        "global_type": "Genre",
        "folder_rules": {}
    }
    settings_path = get_library_settings_file()
    global_settings_path = os.path.join(BASE_DIR, "settings.json")
    if not os.path.exists(settings_path):
        settings_path = global_settings_path
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get("local_scan_config", default_config)
        except:
            pass
    return default_config

def build_scanner_config():
    """Builds the comprehensive configuration dict required by LibraryManager."""
    p_map, p_ignore = get_platform_config()
    return {
        'db_file': get_db_path(),
        'root_path': get_root_path(),
        'video_path': get_video_path(),
        'platform_map': p_map,
        'ignored_prefixes': p_ignore,
        'local_scan_config': get_local_scan_config()
    }

def setup_logging():
    """Sets up file logging for the application."""
    os.makedirs(LOG_DIR, exist_ok=True)
    logs = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.startswith("scan_")]
    logs.sort(key=os.path.getctime)
    while len(logs) >= 10:
        os.remove(logs.pop(0))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"scan_{timestamp}.log")
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s [%(levelname)s] %(message)s', 
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'), 
            logging.StreamHandler()
        ]
    )

# --- TRANSLATION ---
# Handles loading JSON translation files based on user preference.
# It falls back to the key name if a translation is missing.
class Translator:
    def __init__(self):
        self.translations = {}
        self.language = "English"
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def load_language(self, language):
        self.language = language
        lang_code = "en"
        if language == "French":
            lang_code = "fr"
        elif language == "German":
            lang_code = "de"
        elif language == "Spanish":
            lang_code = "es"
        elif language == "Italian":
            lang_code = "it"
        
        # Check lang/ subdirectory first (cleaner), then root
        lang_file = os.path.join(self.base_path, "lang", f"{lang_code}.json")
        if not os.path.exists(lang_file):
            lang_file = os.path.join(self.base_path, f"{lang_code}.json")
            
        if os.path.exists(lang_file):
            try:
                with open(lang_file, "r", encoding='utf-8') as f:
                    self.translations = json.load(f)
                logging.info(f"Loaded language file: {lang_file}")
            except Exception as e:
                logging.error(f"Failed to load language file {lang_file}: {e}")
                self.translations = {}
        else:
            logging.warning(f"Language file not found: {lang_file}")
            self.translations = {}

    def tr(self, key, **kwargs):
        return self.translations.get(key, key).format(**kwargs)

translator = Translator()

def apply_theme(app, theme_name):
    effective_theme = theme_name
    if theme_name == "System":
        try:
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            if value == 0:
                effective_theme = "Dark"
            else:
                effective_theme = "Light"
        except:
            pass

    # Always use Fusion to ensure consistency and palette respect
    app.setStyle(QStyleFactory.create("Fusion"))

    if effective_theme == "Dark":
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.WindowText, Qt.white)
        dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
        dark_palette.setColor(QPalette.ToolTipText, Qt.white)
        dark_palette.setColor(QPalette.Text, Qt.white)
        dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ButtonText, Qt.white)
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.Highlight, QColor(50, 50, 50))
        dark_palette.setColor(QPalette.HighlightedText, Qt.white)
        
        # WHY: Explicitly set disabled colors so disabled widgets (like All/None buttons) actually look greyed out.
        dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.gray)
        dark_palette.setColor(QPalette.Disabled, QPalette.Text, Qt.gray)
        dark_palette.setColor(QPalette.Disabled, QPalette.WindowText, Qt.gray)
        
        app.setPalette(dark_palette)
    else: # Light or System
        # Force a Light Palette to ensure it doesn't inherit Dark Mode from OS
        light_palette = QPalette()
        light_palette.setColor(QPalette.Window, QColor(240, 240, 240))
        light_palette.setColor(QPalette.WindowText, Qt.black)
        light_palette.setColor(QPalette.Base, Qt.white)
        light_palette.setColor(QPalette.AlternateBase, QColor(233, 233, 233))
        light_palette.setColor(QPalette.ToolTipBase, Qt.white)
        light_palette.setColor(QPalette.ToolTipText, Qt.black)
        light_palette.setColor(QPalette.Text, Qt.black)
        light_palette.setColor(QPalette.Button, QColor(240, 240, 240))
        light_palette.setColor(QPalette.ButtonText, Qt.black)
        light_palette.setColor(QPalette.BrightText, Qt.red)
        light_palette.setColor(QPalette.Link, QColor(0, 0, 255))
        
        # Custom Highlight (Grey instead of Blue)
        light_palette.setColor(QPalette.Highlight, QColor(200, 200, 200))
        light_palette.setColor(QPalette.HighlightedText, Qt.black)
        
        # WHY: Explicitly set disabled colors so disabled widgets (like All/None buttons) actually look greyed out.
        light_palette.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.gray)
        light_palette.setColor(QPalette.Disabled, QPalette.Text, Qt.gray)
        light_palette.setColor(QPalette.Disabled, QPalette.WindowText, Qt.gray)
        
        app.setPalette(light_palette)

# --- Custom Logging Handler for UI ---
# WHY: Moved here to centralize all utility and core infrastructure classes.
# Allows redirecting Python's standard logging output to a PyQt Signal.
class QtLogSignal(QObject):
    message_written = Signal(str)

class QtLogHandler(logging.Handler):
    def __init__(self, signal_emitter, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_emitter = signal_emitter
        # Set a simple formatter for the UI log, without timestamp/level
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record):
        msg = self.format(record)
        self.signal_emitter.message_written.emit(msg)