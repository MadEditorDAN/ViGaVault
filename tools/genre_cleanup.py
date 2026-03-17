# WHY: Single Responsibility Principle - Standalone script to audit and safely apply 
# genre normalizations to the database without risking the main application's integrity.
import os
import sys
import pandas as pd

# WHY: DRY Principle - Dynamically import the core logic so the script behaves 
# exactly identically to the main application.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ViGaVault_utils import normalize_genre, get_db_path, load_genre_taxonomy

def run_genre_cleanup():
    db_path = get_db_path()
    
    # WHY: Force reload the JSON file at runtime just in case the user edited it while the script was open
    load_genre_taxonomy()
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    print(f"Loading database from: {db_path} ...")
    df = pd.read_csv(db_path, sep=';', encoding='utf-8').fillna('')
    
    if 'Genre' not in df.columns:
        print("Error: 'Genre' column not found in database.")
        return

    print("\nAnalyzing existing genres...")
    all_genres = set()
    for text in df['Genre']:
        if text:
            parts = [p.strip() for p in str(text).split(',')]
            all_genres.update([p for p in parts if p])

    # WHY: Save all unique genres to a text file so the user can easily copy and share 
    # the list for further taxonomy map analysis without cluttering the console.
    output_file = os.path.join(os.path.dirname(__file__), "all_genres_list.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        for g in sorted(all_genres):
            f.write(f"{g}\n")
    print(f"\nExtracted {len(all_genres)} unique genres.")
    print(f"A complete list has been saved to: {output_file}")

    proposals = {}
    for raw_genre in all_genres:
        normalized = normalize_genre(raw_genre)
        # WHY: Strictly compare exact strings. This guarantees we fix capitalization 
        # (e.g. "moba" -> "MOBA") as well as spelling (e.g. "Aventure" -> "Adventure").
        if raw_genre != normalized:
            proposals[raw_genre] = normalized

    if not proposals:
        print("\nNo genres need normalization based on the current taxonomy map. Your database is clean!")
        return

    print(f"\nFound {len(proposals)} genre categories that will be unified:\n")
    print(f"{'CURRENT RAW GENRE':<35} -> {'PROPOSED NORMALIZATION'}")
    print("-" * 65)
    for raw, norm in sorted(proposals.items()):
        print(f"{raw:<35} -> {norm}")
        
    print("-" * 65)
    
    games_affected = 0
    for text in df['Genre']:
        if text and normalize_genre(text) != str(text):
            games_affected += 1
    
    print(f"\nThis will update the Genre field for {games_affected} games in your library.")
    
    choice = input("\nDo you want to apply these changes to the CSV? (y/n): ")
    if choice.lower() == 'y':
        print("\nApplying changes...")
        df['Genre'] = df['Genre'].apply(lambda x: normalize_genre(x) if x else "")
        df.to_csv(db_path, sep=';', index=False, encoding='utf-8')
        print("Database successfully updated! You can now restart ViGaVault.")
    else:
        print("\nOperation cancelled. No changes were made.")

if __name__ == "__main__":
    run_genre_cleanup()