# WHY: Single Responsibility Principle - Strictly isolates the routing logic for Epic's multi-platform entitlements.
import logging

def map_epic_platforms(raw_platforms, app_name="Unknown"):
    """
    Analyzes the raw platform array provided by the Epic Games API and maps them 
    to ViGaVault's internal virtual platform identifiers.
    
    Args:
        raw_platforms (list): Array of strings directly from the API (e.g., ['Windows', 'iOS']).
        app_name (str): Used strictly for logging trace context.
    """
    if not raw_platforms:
        return "Epic Games Store"
        
    mapped = set()
    for p in raw_platforms:
        p_lower = str(p).lower()
        # WHY: Route PC/Mac architectures to the standard desktop platform.
        if p_lower in ['windows', 'mac', 'win32']:
            mapped.add('Epic Games Store')
        # WHY: Route mobile architectures to the new virtual mobile platform.
        elif p_lower in ['ios', 'android']:
            mapped.add('Epic Games Mobile')
            logging.debug(f"[EpicScanner] Mobile platform '{p}' detected for {app_name}. Tagging as Epic Games Mobile.")
    
    # WHY: Fail-safe fallback. If Epic returns an unrecognized architecture string, default to the desktop store.
    if not mapped: mapped.add('Epic Games Store')
        
    return ", ".join(sorted(list(mapped)))