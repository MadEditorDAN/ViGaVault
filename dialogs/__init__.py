# WHY: Acts as a facade for the modularized package. 
# Exposes all dialogs so other files can import them cleanly without knowing the exact file structure.

from .edit_game_dialog import ActionDialog
from .merge_tool_dialogs import MergeSelectionDialog, ConflictDialog
from .settings_dialog import SettingsDialog
from .statistics_dialog import StatisticsDialog, ProgressBarDelegate
from .utility_dialogs import PlatformManagerDialog, SelectionDialog, DocumentationDialog
from .media_manager_dialog import MediaManagerDialog