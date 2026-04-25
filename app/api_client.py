"""Client for the FullTime API (unofficial FA FullTime scraper)."""
import os
import re
import requests
from datetime import datetime
from typing import Optional


class FullTimeAPIClient:
    """Client for the FullTime API."""
    
    BASE_URL = os.getenv(
        "FULLTIME_API_BASE_URL",
        "https://faapi.jwhsolutions.co.uk/api"
    )
    IOM_LEAGUE_ID = os.getenv("IOM_LEAGUE_ID", "9057188")
    
    # Division IDs for IOM Senior Men's Leagues
    DIVISIONS = {
        "premier": os.getenv("DIV_PREMIER", "175685803"),
        "division_2": os.getenv("DIV_2", "715559946"),
        "combination_1": os.getenv("DIV_COMBINATION_1", "472778251"),
        "combination_2": os.getenv("DIV_COMBINATION_2", "504262635"),
    }
    
    def __init__(self):
        # SSL cert is expired on their end, so we disable verification
        self.session = requests.Session()
        self.session.verify = False
        # Disable SSL warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    def _get(self, endpoint: str) -> list:
        """Make a GET request to the API."""
        url = f"{self.BASE_URL}/{endpoint}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def get_league_divisions(self) -> list:
        """Get all divisions for the IOM Senior Men's Leagues."""
        # Search for the league and return divisions
        results = self._get(f"Search/leagues/Isle%20of%20Man%20Senior%20Men's")
        for league in results:
            if league["id"] == self.IOM_LEAGUE_ID:
                return league.get("divisions", [])
        return []
    
    def get_league_table(self, division_id: str) -> list:
        """Get the league table for a division."""
        return self._get(f"League/{division_id}")
    
    def get_results(self, division_id: str, team_name: str = "") -> list:
        """Get results for a division, optionally filtered by team."""
        params = f"?teamName={team_name}" if team_name else ""
        return self._get(f"Results/{division_id}{params}")
    
    def get_fixtures(self, division_id: str, team_name: str = "") -> list:
        """Get upcoming fixtures for a division."""
        params = f"?teamName={team_name}" if team_name else ""
        return self._get(f"Fixtures/{division_id}{params}")
    
    def get_team_form(self, division_id: str, team_name: str) -> list:
        """Get the last 5 match results for a team."""
        return self._get(f"Results/{division_id}/form?teamName={team_name}")
    
    def parse_score(self, score_str: str) -> tuple:
        """Parse a score string like '3 - 2' or '0 - 3 (HT 0-1)' into (home, away, ht_home, ht_away)."""
        if not score_str:
            return (None, None, None, None)
        
        # Extract main score
        match = re.match(r"(\d+)\s*-\s*(\d+)", score_str)
        if not match:
            return (None, None, None, None)
        
        home = int(match.group(1))
        away = int(match.group(2))
        
        # Extract half-time score if present
        ht_home, ht_away = None, None
        ht_match = re.search(r"\(HT\s*(\d+)\s*-\s*(\d+)\)", score_str)
        if ht_match:
            ht_home = int(ht_match.group(1))
            ht_away = int(ht_match.group(2))
        
        return (home, away, ht_home, ht_away)
    
    def parse_date(self, date_str: str) -> datetime:
        """Parse a date string like '25/04/26 14:00'."""
        if not date_str:
            return None
        return datetime.strptime(date_str, "%d/%m/%y %H:%M")
    
    def fetch_and_update_division(self, division_id: str) -> dict:
        """Fetch league table, results, and fixtures for a division."""
        table = self.get_league_table(division_id)
        results = self.get_results(division_id)
        fixtures = self.get_fixtures(division_id)
        
        return {
            "division_id": division_id,
            "table": table,
            "results": results,
            "fixtures": fixtures,
        }


# Singleton instance
client = FullTimeAPIClient()
