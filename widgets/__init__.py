# WHY: Acts as a facade for the modularized widgets package. 
# Exposes UI components cleanly so other files can import them without knowing the exact file structure.
from .custom_inputs import CheckableComboBox, CollapsibleFilterGroup
from .sidebar import Sidebar
from .game_card import GameCard