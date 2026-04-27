"""Data clients for Fantasy Football Isle of Man.

Combines:
1. FullTime API - fixtures, results, league tables (team level)
2. Manx Fantasy Football website - individual player stats (apps, goals)
"""
import os
import re
import json
import random
import requests
import urllib3
from datetime import datetime
from typing import Optional, List, Dict


class FullTimeAPIClient:
    """Client for the FullTime API (unofficial FA FullTime scraper)."""

    BASE_URL = os.getenv("FULLTIME_API_BASE_URL", "https://faapi.jwhsolutions.co.uk/api")
    IOM_LEAGUE_ID = os.getenv("IOM_LEAGUE_ID", "9057188")

    DIVISIONS = {
        "premier": os.getenv("DIV_PREMIER", "175685803"),
        "division_2": os.getenv("DIV_2", "715559946"),
        "combination_1": os.getenv("DIV_COMBINATION_1", "472778251"),
        "combination_2": os.getenv("DIV_COMBINATION_2", "504262635"),
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get(self, endpoint: str) -> list:
        url = f"{self.BASE_URL}/{endpoint}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_league_divisions(self) -> list:
        """Get all divisions for the IOM league."""
        results = self._get(f"Search/leagues/Isle%20of%20Man%20Senior%20Men's")
        for league in results:
            if league["id"] == self.IOM_LEAGUE_ID:
                return league.get("divisions", [])
        return []

    def get_league_table(self, division_id: str) -> list:
        """Get the league table for a division."""
        return self._get(f"League/{division_id}")

    def get_results(self, division_id: str, team_name: str = "") -> list:
        """Get results for a division."""
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
        """Parse '3 - 2 (HT 0-1)' -> (3, 2, 0, 1)."""
        if not score_str:
            return (None, None, None, None)
        match = re.match(r"(\d+)\s*-\s*(\d+)", score_str)
        if not match:
            return (None, None, None, None)
        home, away = int(match.group(1)), int(match.group(2))
        ht_match = re.search(r"\(HT\s*(\d+)\s*-\s*(\d+)\)", score_str)
        ht_home, ht_away = (int(ht_match.group(1)), int(ht_match.group(2))) if ht_match else (None, None)
        return (home, away, ht_home, ht_away)

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse '25/04/26 14:00' -> datetime."""
        if not date_str:
            return None
        return datetime.strptime(date_str, "%d/%m/%y %H:%M")

    def fetch_all_division_data(self) -> dict:
        """Fetch fixtures and results for all divisions."""
        divisions = self.get_league_divisions()
        all_data = {}
        for div in divisions:
            div_id = div["id"]
            try:
                all_data[div_id] = {
                    "name": div["name"],
                    "table": self.get_league_table(div_id),
                    "results": self.get_results(div_id),
                    "fixtures": self.get_fixtures(div_id),
                }
            except Exception as e:
                print(f"Error fetching division {div_id}: {e}")
        return all_data


class ManxFantasyFootballScraper:
    """Scrape individual player stats from manxfantasyfootball.com.

    This site tracks individual player data for IOM leagues:
    - Player name, team, league
    - Appearances (apps), goals scored
    - Fantasy points (their scoring system)
    """

    BASE_URL = "https://www.manxfantasyfootball.com"

    LEAGUE_PARAMS = {
        "prem": "Prem",
        "div2": "Div 2",
        "combi1": "Combi 1",
        "combi2": "Combi 2",
        "overall": "Overall",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })

    def scrape_league_players(self, league: str = "overall") -> list:
        """Scrape player stats from manxfantasyfootball.com.

        Returns list of dicts:
        {name, team, league, apps, goals, points, rank}
        """
        url = f"{self.BASE_URL}/?league={league}"
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            return self._parse_player_table(response.text)
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return []

    def _parse_player_table(self, html: str) -> list:
        """Parse the player table from HTML.

        Table format:
        Rank | Pts | League | Player | Team | Apps | Goals
        """
        players = []
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)

        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cells) < 6:
                continue

            # Clean HTML tags from cells
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

            try:
                rank = int(re.sub(r"[^\d]", "", clean[0]))
            except (ValueError, IndexError):
                continue

            try:
                points = int(clean[1])
            except (ValueError, IndexError):
                continue

            league = clean[2] if len(clean) > 2 else ""
            name = clean[3] if len(clean) > 3 else ""
            team = clean[4] if len(clean) > 4 else ""

            try:
                apps = int(clean[5]) if len(clean) > 5 else 0
            except ValueError:
                apps = 0

            try:
                goals = int(clean[6]) if len(clean) > 6 else 0
            except ValueError:
                goals = 0

            if not name or not team:
                continue

            players.append({
                "rank": rank,
                "points": points,
                "league": league,
                "name": name,
                "team": team,
                "apps": apps,
                "goals": goals,
            })

        return players

    def scrape_all_leagues(self) -> list:
        """Scrape all leagues and return combined player list."""
        all_players = []
        for league_key in ["prem", "div2", "combi1", "combi2"]:
            players = self.scrape_league_players(league_key)
            all_players.extend(players)
        return all_players


def estimate_player_position(name: str, goals: int, apps: int,
                              team_name: str) -> str:
    """Estimate player position based on goals/apps ratio.

    Since the source data only gives us goals and apps, we estimate position:
    - High goals/apps ratio -> FWD
    - Medium goals/apps -> MID
    - Low goals with high apps -> DEF
    - GK estimated by name patterns or very low goals

    This is an estimation - positions can be manually corrected.
    """
    if apps == 0:
        return "MID"

    goals_per_game = goals / apps

    # Goalkeepers: typically 0 goals, high apps
    # We'll estimate GK by checking if a player has very few goals
    # and appears in every game (goalkeepers rarely miss games)
    if goals == 0 and apps >= 10:
        # Could be GK or defender - need more data
        # For now, assume GK if name suggests it or apps are very high
        return "GK"

    # Forward: high goals per game ratio
    if goals_per_game >= 0.5:
        return "FWD"

    # Midfielder: moderate goals
    if goals_per_game >= 0.2:
        return "MID"

    # Defender: low goals
    return "DEF"


def estimate_player_price(goals: int, apps: int, league: str,
                           rank: int) -> float:
    """Estimate FPL-style player price (4.0 - 10.0m).

    Based on performance: goals, apps, league, rank.
    """
    base_price = 5.0

    # Goals contribute to price
    base_price += goals * 0.3

    # Apps contribute
    base_price += (apps / 20.0) * 1.0

    # League bonus
    league_bonus = {
        "Prem": 0.5,
        "Div 2": 0.0,
        "Combi 1": -0.3,
        "Combi 2": -0.5,
    }
    base_price += league_bonus.get(league, 0)

    # Rank bonus
    if rank <= 10:
        base_price += 1.0
    elif rank <= 50:
        base_price += 0.5

    # Clamp to FPL range
    return max(4.0, min(10.0, round(base_price, 1)))


def estimate_assists(goals: int, position: str) -> int:
    """Estimate assists based on goals and position.

    Midfielders typically have more assists. This is a rough estimate.
    """
    if position == "MID":
        return max(0, int(goals * 0.6))
    elif position == "FWD":
        return max(0, int(goals * 0.3))
    elif position == "DEF":
        return max(0, int(goals * 0.2))
    return 0


def assign_positions_to_team_players(players: list,
                                      team_name: str) -> list:
    """Assign positions within a team to ensure proper squad structure.

    Each team needs roughly:
    - 1-2 GK
    - 5-6 DEF
    - 5-6 MID
    - 2-3 FWD
    """
    team_players = [p for p in players if p.get("team") == team_name]

    # Sort by goals descending
    team_players.sort(key=lambda p: p.get("goals", 0), reverse=True)

    # Assign GK: players with 0 goals and high apps
    gk_candidates = [p for p in team_players if p.get("goals", 0) == 0
                     and p.get("apps", 0) >= 10]
    for p in gk_candidates[:2]:
        p["estimated_position"] = "GK"

    remaining = [p for p in team_players if "estimated_position" not in p]

    # Assign FWD: highest scorers
    for p in remaining[:3]:
        p["estimated_position"] = "FWD"

    remaining = [p for p in remaining if "estimated_position" not in p]

    # Assign MID: next highest scorers
    for p in remaining[:5]:
        p["estimated_position"] = "MID"

    # Rest are DEF
    for p in remaining:
        p["estimated_position"] = "DEF"

    return team_players


client = FullTimeAPIClient()
scraper = ManxFantasyFootballScraper()
