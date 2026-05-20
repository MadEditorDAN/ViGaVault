import os
import pytest
from unittest.mock import patch
from backend.steam.scan_steam import scan_steam_account

def test_steam_cookie_scraping_regex():
    """
    Tests that the scan_steam_account function properly injects the captured cookies
    and correctly parses the embedded rgGames JSON payload using regex, exactly like the Mobile app.
    """
    mock_session = {
        "steamLoginSecure": "76561198000000000%7C%7C...mocked_cookie...",
        "sessionid": "mocked_sessionid",
        "steam_id": "76561198000000000"
    }
    
    mock_html_response = """
    <html>
        <body>
            <script>
                var rgGames = [{"appid": 440, "name": "Team Fortress 2"}, {"appid": 730, "name": "Counter-Strike: Global Offensive"}];
            </script>
        </body>
    </html>
    """
    
    # We mock requests.get to return a mock response containing the rgGames script
    class MockResponse:
        status_code = 200
        text = mock_html_response
    
    with patch("backend.steam.scan_steam.get_steam_session", return_value=mock_session):
        with patch("backend.steam.scan_steam.requests.get", return_value=MockResponse()) as mock_get:
            
            # Create a mock games dictionary and config
            games_dict = {}
            config = {}
            
            # Execute the scanner
            result = scan_steam_account(config, games_dict)
            
            # Assertions
            mock_get.assert_called_once()
            called_kwargs = mock_get.call_args[1]
            assert "cookies" in called_kwargs, "Must pass the captured browser cookies to requests.get"
            assert called_kwargs["cookies"]["steamLoginSecure"] == mock_session["steamLoginSecure"]
            
            # Ensure the regex extracted the 2 games and instantiated Game objects
            assert result is True, "Changes should be made to the games dictionary"
            assert len(games_dict) == 2
            
            # Check the parsed Game objects
            tf2 = next((g for g in games_dict.values() if "Team Fortress 2" in g.data['Clean_Title']), None)
            assert tf2 is not None
            assert tf2.data['game_ID'] == "steam_440"
