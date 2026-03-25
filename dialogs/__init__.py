# WHY: Acts as a facade for the modularized package. 
# Exposes all dialogs so other files can import them cleanly without knowing the exact file structure.

from .edit_game_dialog import ActionDialog
from .merge_tool_dialogs import MergeSelectionDialog, ConflictDialog
from .settings_dialog import SettingsDialog
from .statistics_dialog import StatisticsDialog, ProgressBarDelegate
from .utility_dialogs import SelectionDialog, DocumentationDialog
from .media_manager_dialog import MediaManagerDialog
from .metadata_manager_dialog import MetadataManagerDialog
from .game_manager_dialog import GameManagerDialog
from .igdb_auth_dialog import IGDBAuthDialog
from .steam_auth_dialog import SteamAuthDialog

# Conditionally import WebEngine to prevent fatal crashes if the module isn't installed yet.
try: from .login_browser_dialog import LoginBrowserDialog
except ImportError: pass