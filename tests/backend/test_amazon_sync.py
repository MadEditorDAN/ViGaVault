import sys
import os

# Insert workspace path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.game import Game
from backend.amazon.sync_amazon import sync_amazon_database

class FakeConfig(dict):
    pass

def test_gog_galaxy_amazon_game_is_immune_to_deletion():
    # Setup games database dictionary
    games_dict = {}
    
    # 1. Add an Amazon game originally imported via GOG Galaxy (has numeric ID amazon_123456789)
    gog_galaxy_game = Game(config={}, Folder_Name="Dread Templar", Status_Flag="NEW", Path_Root="")
    gog_galaxy_game.data["Clean_Title"] = "Dread Templar"
    gog_galaxy_game.data["game_ID"] = "amazon_123456789"
    gog_galaxy_game.data["Platforms"] = "Amazon"
    games_dict["Dread Templar"] = gog_galaxy_game
    
    # 2. Add an Amazon game with both GOG Galaxy ID and native Amazon UUID
    merged_game = Game(config={}, Folder_Name="Hue", Status_Flag="NEW", Path_Root="")
    merged_game.data["Clean_Title"] = "Hue"
    merged_game.data["game_ID"] = "amazon_123456789, amazon_2ebae692-5e13-4ee1-a4bd-1f901bac77c6"
    merged_game.data["Platforms"] = "Amazon, GOG Galaxy"
    games_dict["Hue"] = merged_game

    # 3. Add a truly deleted native Amazon game (has only UUID and is missing from cloud)
    ghost_game = Game(config={}, Folder_Name="Ghost Game", Status_Flag="NEW", Path_Root="")
    ghost_game.data["Clean_Title"] = "Ghost Game"
    ghost_game.data["game_ID"] = "amazon_77777777-7777-7777-7777-777777777777"
    ghost_game.data["Platforms"] = "Amazon"
    games_dict["Ghost Game"] = ghost_game

    # Setup cloud claims list (only contains the UUID of Hue, missing Dread Templar's Galaxy ID and Ghost Game's UUID)
    claims_list = [
        {
            "item": {
                "id": "2ebae692-5e13-4ee1-a4bd-1f901bac77c6",
                "assets": [{"redemptionPlatforms": ["AMAZON_GAMES_APP"]}]
            },
            "itemTitle": "Hue"
        }
    ]

    # Execute sync
    changes_made, stats = sync_amazon_database(FakeConfig(), games_dict, claims_list)

    # Assertions:
    # - "Dread Templar" must be completely untouched and NOT deleted (immune due to GOG Galaxy numeric ID)
    assert "Dread Templar" in games_dict
    assert games_dict["Dread Templar"].data["game_ID"] == "amazon_123456789"
    assert "Amazon" in games_dict["Dread Templar"].data["Platforms"]

    # - "Hue" must be preserved because its native UUID is in the cloud claims, despite its GOG Galaxy ID being missing
    assert "Hue" in games_dict
    assert "Amazon" in games_dict["Hue"].data["Platforms"]

    # - "Ghost Game" must be deleted because its native UUID is missing from the cloud claims list
    assert "Ghost Game" not in games_dict


def test_get_claim_year():
    # WHY: Test that get_claim_year correctly parses millisecond-based Unix timestamps, ISO 8601 strings, and fallback scenarios.
    from backend.amazon.sync_amazon import get_claim_year
    from datetime import datetime

    # 1. Test ISO 8601 string
    claim_iso = {"orderCreationDate": "2026-05-04T13:02:22Z"}
    assert get_claim_year(claim_iso) == 2026

    # 2. Test Unix millisecond timestamp string
    claim_ms_str = {"orderCreationDate": "1716912345678"} # 2024-05-28
    assert get_claim_year(claim_ms_str) == 2024

    # 3. Test Unix millisecond timestamp integer
    claim_ms_int = {"orderCreationDate": 1716912345678}
    assert get_claim_year(claim_ms_int) == 2024

    # 4. Test Unix second timestamp string
    claim_sec_str = {"orderCreationDate": "1716912345"}
    assert get_claim_year(claim_sec_str) == 2024

    # 5. Test missing date fallback
    claim_empty = {}
    assert get_claim_year(claim_empty) == datetime.now().year

    # 6. Test invalid string fallback
    claim_invalid = {"orderCreationDate": "invalid_date"}
    assert get_claim_year(claim_invalid) == datetime.now().year
