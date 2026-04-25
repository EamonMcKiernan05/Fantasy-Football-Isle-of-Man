"""FPL-style scoring engine adapted for team-based Fantasy Football.

Since the FullTime API only provides team-level data (no individual player stats),
this scoring system treats each IOM team as a single 'player' in the fantasy game.

Scoring is adapted from FPL rules to work with team-level stats:
- Team matches = player matches
- Team goals = player goals
- Team clean sheets = player clean sheets
- Goal difference serves as a bonus point multiplier
"""
from typing import Optional


# --- Team position mapping ---
# In FPL, each player has a position (GK/DEF/MID/FWD).
# For teams, we map based on league performance/style:
# - Top 4 teams in division = "Premium" (like FWD - high scoring)
# - Teams 5-8 = "Midfield" (balanced)
# - Teams 9-12 = "Defensive" (like DEF)
# - Bottom teams = "Goalkeeper" (concede a lot, low scoring)
# For simplicity, all teams share the same scoring model since we can't
# differentiate individual player positions within a team.


# --- Scoring rules (adapted from FPL) ---

# Base participation
POINTS_PLAYED = 2  # Team played a match (always 90 mins)

# Match result
POINTS_WIN = 6  # Team won
POINTS_DRAW = 2  # Team drew
POINTS_LOSS = 0  # Team lost

# Goals
POINTS_GOAL_SCORED = 2  # Per goal scored
POINTS_GOAL_CONCEDED_PENALTY = -1  # Per goal conceded (max -3)
MAX_GOAL_CONCEDED_PENALTY = -3

# Clean sheet
POINTS_CLEAN_SHEET = 4  # Didn't concede any goals

# Goal difference bonus
POINTS_GOAL_DIFFERENCE_BONUS = 1  # Per 5 goals in GD margin

# Cards (adapted from team discipline records - not available in API,
# so skipped as per user instructions)

# --- Multipliers ---
CAPTAIN_MULTIPLIER = 2  # Captain's team scores double


def calculate_team_points(
    goals_scored: int,
    goals_conceded: int,
    result: str,  # "W", "D", "L"
    is_captain: bool = False,
    gd_bonus_threshold: int = 5,
) -> dict:
    """Calculate fantasy points for a team in a single match.
    
    Args:
        goals_scored: Goals scored by the team
        goals_conceded: Goals conceded by the team
        result: Match result - "W", "D", or "L"
        is_captain: Whether this team is the captain
        gd_bonus_threshold: Goals difference for bonus point
        
    Returns:
        Dict with points breakdown
    """
    points = 0
    breakdown = {}
    
    # Participation
    points += POINTS_PLAYED
    breakdown["participation"] = POINTS_PLAYED
    
    # Match result
    if result == "W":
        points += POINTS_WIN
        breakdown["result"] = POINTS_WIN
    elif result == "D":
        points += POINTS_DRAW
        breakdown["result"] = POINTS_DRAW
    else:
        breakdown["result"] = 0
    
    # Goals scored
    goal_points = goals_scored * POINTS_GOAL_SCORED
    points += goal_points
    breakdown["goals_scored"] = goal_points
    
    # Clean sheet
    if goals_conceded == 0:
        points += POINTS_CLEAN_SHEET
        breakdown["clean_sheet"] = POINTS_CLEAN_SHEET
    else:
        breakdown["clean_sheet"] = 0
    
    # Goals conceded penalty
    conceded_penalty = max(-goals_conceded, MAX_GOAL_CONCEDED_PENALTY) * POINTS_GOAL_CONCEDED_PENALTY
    points += conceded_penalty
    breakdown["goals_conceded"] = conceded_penalty
    
    # Goal difference bonus
    gd = goals_scored - goals_conceded
    if gd >= gd_bonus_threshold:
        gd_bonus = 1
        points += gd_bonus
        breakdown["gd_bonus"] = gd_bonus
    else:
        breakdown["gd_bonus"] = 0
    
    breakdown["base_total"] = points
    
    # Captain multiplier
    if is_captain:
        breakdown["base_total"] = points
        points = points * CAPTAIN_MULTIPLIER
        breakdown["captain_multiplier"] = CAPTAIN_MULTIPLIER
    else:
        breakdown["captain_multiplier"] = 1
    
    breakdown["total"] = points
    
    return breakdown


def calculate_bonus_points(
    player_fixtures: list,
) -> dict:
    """Calculate bonus points (1-3) for teams in a gameweek.
    
    Uses FPL's bonus point algorithm:
    1. Rank teams by base points scored
    2. For tiebreakers, use contribution stats (goals scored, clean sheets, etc.)
    3. Top 3 get 3, 2, 1 bonus points respectively
    
    Args:
        player_fixtures: List of PlayerFixture objects with base points
        
    Returns:
        Dict mapping squad_player_id to bonus points (1, 2, or 3)
    """
    if not player_fixtures:
        return {}
    
    # Sort by base points, then by contribution stats
    def sort_key(pf):
        return (
            pf.points,           # Base points
            pf.goals_scored,     # Goals scored
            1 if pf.clean_sheet else 0,  # Clean sheet
            -pf.goals_conceded,  # Fewer goals conceded
        )
    
    ranked = sorted(player_fixtures, key=sort_key, reverse=True)
    
    bonus_map = {}
    for i, pf in enumerate(ranked):
        if i < 3:
            bonus_map[pf.id] = 3 - i  # 3, 2, 1
        else:
            bonus_map[pf.id] = 0
    
    return bonus_map


def calculate_gameweek_scores(
    fixtures: list,
    squad: list,
    captain_id: int,
    vice_captain_id: Optional[int] = None,
) -> dict:
    """Calculate total gameweek score for a fantasy team.
    
    Args:
        fixtures: List of Fixture objects for the gameweek
        squad: List of SquadPlayer objects
        captain_id: The team_id of the captain
        vice_captain_id: The team_id of the vice-captain
        
    Returns:
        Dict with total points and per-team breakdown
    """
    # Build lookup: team_name -> fixture result
    fixture_results = {}
    for fixture in fixtures:
        if not fixture.played:
            continue
        
        home_result = "W" if fixture.home_score > fixture.away_score else (
            "D" if fixture.home_score == fixture.away_score else "L"
        )
        away_result = "W" if fixture.away_score > fixture.home_score else (
            "D" if fixture.away_score == fixture.home_score else "L"
        )
        
        fixture_results[fixture.home_team] = {
            "result": home_result,
            "goals_scored": fixture.home_score,
            "goals_conceded": fixture.away_score,
            "opponent": fixture.away_team,
            "is_home": True,
            "fixture_id": fixture.id,
        }
        fixture_results[fixture.away_team] = {
            "result": away_result,
            "goals_scored": fixture.away_score,
            "goals_conceded": fixture.home_score,
            "opponent": fixture.home_team,
            "is_home": False,
            "fixture_id": fixture.id,
        }
    
    # Check if captain played; if not, use vice-captain
    actual_captain_id = captain_id
    captain_played = any(
        sp.team_id == captain_id and sp.team.name in fixture_results
        for sp in squad
    )
    if not captain_played and vice_captain_id:
        vc_played = any(
            sp.team_id == vice_captain_id and sp.team.name in fixture_results
            for sp in squad
        )
        if vc_played:
            actual_captain_id = vice_captain_id
    
    total = 0
    breakdown = {}
    
    for sp in squad:
        team_name = sp.team.name
        if team_name not in fixture_results:
            # Team didn't play this gameweek
            breakdown[sp.team_id] = {
                "team": team_name,
                "points": 0,
                "detail": "Did not play",
            }
            continue
        
        result = fixture_results[team_name]
        is_captain = (sp.team_id == actual_captain_id)
        
        points = calculate_team_points(
            goals_scored=result["goals_scored"],
            goals_conceded=result["goals_conceded"],
            result=result["result"],
            is_captain=is_captain,
        )
        
        total += points["total"]
        breakdown[sp.team_id] = {
            "team": team_name,
            "points": points["total"],
            "detail": points,
            "captain": is_captain,
            "fixture_id": result["fixture_id"],
            "opponent": result["opponent"],
            "is_home": result["is_home"],
        }
    
    return {
        "total": total,
        "breakdown": breakdown,
    }
