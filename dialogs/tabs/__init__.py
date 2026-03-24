# WHY: Acts as a facade for the settings tabs package. 
# Exposes UI tab components cleanly so the main orchestrator can import them effortlessly.
from .display_tab import DisplayTabWidget
from .local_sources_tab import LocalSourcesTabWidget
from .platforms_tab import PlatformsTabWidget