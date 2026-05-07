"""Simplified scoring engine for Fantasy Football Isle of Man.

Scoring based on available FullTime API data:
- Goals, assists, appearances, minutes played, clean sheets, yellow/red cards, own goals
- 24 gameweeks per season

Scoring Rules:
- Goal scored: +4
- Assist: +2
- Clean sheet: +3
- Yellow card: -1
- Red card: -3
- Own goal: -2
- Played 60+ min: +2
- Played 1-59 min: +1
"""

# Constants
TRANSFER_HIT = 4  # -4 per extra transfer
MAX_ROLLOVER_TRANSFERS = 4  # max 4 rollover (5 total with current GW)
MAX_TRANSFERS_PER_GW = 20  # max 20 transfers per GW (excluding chips)
FREE_TRANSFER_PER_GW = 1  # 1 free transfer per gameweek
MAX_PLAYERS_PER_CLUB = 3  # max 3 players from any single club

# Squad configuration
TOTAL_SQUAD = 13
TOTAL_STARTING = 10
TOTAL_BENCH = 3

# Scoring constants
GOAL_POINTS = 4
ASSIST_POINTS = 2  # Half of FPL value (FPL = 3, we use 2)
CLEAN_SHEET_POINTS = 3
MINUTES_60_PLUS_POINTS = 2
MINUTES_UNDER_60_POINTS = 1
YELLOW_CARD_POINTS = -1
RED_CARD_POINTS = -3
OWN_GOAL_POINTS = -2
PENALTY_MISSED_POINTS = -2
PENALTY_GOAL_BONUS = 2
PENALTY_SAVE_POINTS = 5
SAVES_PER_POINT = 3
DEFENSIVE_CONTRIBUTION_THRESHOLD = 10
DEFENSIVE_CONTRIBUTION_POINTS = 2
GOALS_CONCEDED_PER_PENALTY = 2

# Season configuration
TOTAL_GAMEWEEKS = 24
SEASON_CUTOFF = 11  # First half GW 1-11, second half GW 12-24


# Position-based scoring constants (FPL 2025/26 rules)
GOAL_POINTS_BY_POSITION = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_POINTS = 3  # All positions: 3 pts per assist
CLEAN_SHEET_POINTS_BY_POSITION = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
DEFENSIVE_CONTRIBUTION_THRESHOLD_BY_POSITION = {"DEF": 10, "MID": 12, "FWD": 12}

# Valid formations (FPL style): GK always 1, DEF 3-5, MID 1-5, FWD 1-3
VALID_FORMATIONS = [
    {"name": "3-5-2", "gk": 1, "def": 3, "mid": 5, "fwd": 2},
    {"name": "3-4-3", "gk": 1, "def": 3, "mid": 4, "fwd": 3},
    {"name": "4-3-3", "gk": 1, "def": 4, "mid": 3, "fwd": 3},
    {"name": "4-4-2", "gk": 1, "def": 4, "mid": 4, "fwd": 2},
    {"name": "4-5-1", "gk": 1, "def": 4, "mid": 5, "fwd": 1},
    {"name": "5-2-3", "gk": 1, "def": 5, "mid": 2, "fwd": 3},
    {"name": "5-3-2", "gk": 1, "def": 5, "mid": 3, "fwd": 2},
    {"name": "5-4-1", "gk": 1, "def": 5, "mid": 4, "fwd": 1},
]


def calculate_player_points(
    *,
    position: str = None,
    goals_scored: int = 0,
    assists: int = 0,
    clean_sheet: bool = False,
    yellow_card: bool = False,
    red_card: bool = False,
    own_goal: bool = False,
    minutes_played: int = 0,
    saves: int = 0,
    penalties_saved: int = 0,
    penalties_missed: int = 0,
    was_penalty_goal: bool = False,
    defensive_contributions: int = 0,
    goals_conceded: int = 0,
    bonus_points: int = 0,
) -> int:
    """Calculate points for a player in a single gameweek.

    FPL 2025/26 rules with position-based scoring:
    - Goals: GK=10, DEF=6, MID=5, FWD=4
    - Assists: 3 for all positions
    - Clean sheets: GK=4, DEF=4, MID=1, FWD=0
    - Defensive contributions: DEF threshold=10, MID/FWD threshold=12
    - Cards: yellow=-1, red=-3 (all positions)
    - Own goal: -2
    - Played 60+ min: +2, 1-59 min: +1
    - Saves: +1 per 3 (GK)
    - Penalty save: +5
    - Goals conceded: -1 per 2
    - Penalty goal bonus: +2
    - Penalty missed: -2

    Args:
        position: Player position (GK, DEF, MID, FWD). Defaults to FWD if None.
        ...other stats...
    Returns:
        Total points scored this gameweek.
    """
    pos = position or "FWD"
    points = 0

    # Minutes played bonus
    if minutes_played >= 60:
        points += 2
    elif minutes_played >= 1:
        points += 1  # Playing any minutes gives 1 pt

    # Goals - position-based
    goal_pts = GOAL_POINTS_BY_POSITION.get(pos, 4)
    points += goals_scored * goal_pts

    # Assists - 3 for all positions
    points += assists * ASSIST_POINTS

    # Penalty goal bonus
    if was_penalty_goal:
        points += 2

    # Clean sheet - position-based
    if clean_sheet:
        cs_pts = CLEAN_SHEET_POINTS_BY_POSITION.get(pos, 0)
        points += cs_pts

    # Saves (GK)
    points += saves // 3

    # Penalty saves
    points += penalties_saved * 5

    # Cards
    if yellow_card:
        points -= 1
    if red_card:
        points -= 3

    # Own goal
    if own_goal:
        points -= 2

    # Penalty missed
    if penalties_missed:
        points -= 2 * penalties_missed

    # Defensive contributions - position-based threshold
    def_thresh = DEFENSIVE_CONTRIBUTION_THRESHOLD_BY_POSITION.get(pos, 999)
    if defensive_contributions >= def_thresh:
        points += 2

    # Goals conceded penalty (every 2 goals = -1)
    points -= goals_conceded // 2

    # Bonus points
    points += bonus_points

    return points


def calculate_captain_points(base_points: int, is_captain: bool, chip: str = None) -> int:
    """Calculate captain multiplier points.

    Captain gets 2x (or 3x with triple captain chip).
    """
    if not is_captain:
        return base_points

    multiplier = 3 if chip == "triple_captain" else 2
    return base_points * multiplier


def calculate_transfer_hit(
    transfers_made: int,
    free_transfers_available: int,
    is_wildcard: bool = False,
) -> int:
    """Calculate point hit for transfers.

    Rules:
    - 1 free transfer per gameweek
    - Unused transfers rollover (max 4)
    - Extra transfers: -4 points each
    - Wildcard: no transfer limit, no point hit
    """
    if is_wildcard:
        return 0

    if transfers_made <= free_transfers_available:
        return 0

    extra = transfers_made - free_transfers_available
    return extra * TRANSFER_HIT  # -4 per extra transfer


def calculate_gameweek_score(
    *,
    squad_points: list,
    captain_id: int,
    vice_captain_id: int,
    transfers_cost: int = 0,
    chip: str = None,
) -> dict:
    """Calculate a fantasy team's total score for a gameweek.

    Args:
        squad_points: List of dicts with 'id', 'base_points', 'is_starting', 'did_play'
        captain_id: SquadPlayer ID of captain
        vice_captain_id: SquadPlayer ID of vice-captain
        transfers_cost: Point hit from transfers
        chip: Active chip name (bench_boost, triple_captain, free_hit, wildcard)

    Returns:
        Dict with total, captain, bench_boost, transfer details.
    """
    total = 0
    captain_points = 0

    # Find captain and vice-captain entries
    captain_entry = next((sp for sp in squad_points if sp.get("id") == captain_id), None)
    vice_entry = next((sp for sp in squad_points if sp.get("id") == vice_captain_id), None)

    # Determine effective captain (vice takes over if captain didn't play)
    effective_captain_id = captain_id
    if captain_entry and not captain_entry.get("did_play", True):
        effective_captain_id = vice_captain_id
    elif not captain_entry:
        effective_captain_id = vice_captain_id

    starting_points = 0
    bench_pts = 0

    for sp in squad_points:
        base = sp.get("base_points", 0)
        is_starting = sp.get("is_starting", True)
        did_play = sp.get("did_play", True)

        # Determine if this player contributes
        if chip == "bench_boost":
            # All 13 players contribute (bench boost chip)
            contributes = did_play
        else:
            contributes = is_starting and did_play

        if not contributes:
            continue

        # Apply captain multiplier
        points = base
        if sp.get("id") == effective_captain_id:
            multiplier = 3 if chip == "triple_captain" else 2
            points = base * multiplier
            captain_points = points - base

        if is_starting:
            starting_points += points
        else:
            bench_pts += points

        total += points

    # Apply transfer hit
    total -= transfers_cost

    return {
        "total_points": total,
        "starting_points": starting_points,
        "bench_points": bench_pts,
        "captain_points": captain_points,
        "transfers_cost": transfers_cost,
        "chip": chip,
    }


def calculate_selling_price(purchase_price: float, current_price: float) -> float:
    """Calculate FPL selling price with half-increase rule.

    If a player's price rises after purchase, you keep half of the increase
    when selling, rounded down to the nearest 0.1m.

    Example: bought for 7.5m, now worth 7.8m -> selling price = 7.5 + floor((7.8-7.5)/2) = 7.6m
    Example: bought for 5.0m, now worth 4.5m -> selling price = 4.5m (no half rule for decreases)
    """
    import math
    if current_price > purchase_price:
        increase = current_price - purchase_price
        half_increase = math.floor(increase / 2 * 10) / 10
        return purchase_price + half_increase
    else:
        return current_price


def floor_to_01(value: float) -> float:
    """Round down to nearest 0.1 (FPL rounding)."""
    import math
    return math.floor(value * 10) / 10


def update_player_price(
    selected_by_change: float,
    gw_points: int,
    current_price: float,
    position: str = "MID",
    total_points_season: int = 0,
    apps: int = 0,
) -> float:
    """Calculate player price change for a gameweek.

    Performance-based pricing system inspired by FPL 2024/25 season:
    - Gabriel (Arsenal DEF): 5.0m -> 6.0m over season (20 GWs)
    - Watkins (AVL FWD): 7.5m -> 8.0m over season
    - Palmer (Chelsea MID): 5.5m -> 10.0m over season (biggest riser)

    Price changes are gradual (±0.1-0.2m per GW), based on:
    1. Points scored this gameweek (primary driver)
    2. Season form / PPG (secondary driver)
    3. Position-based baselines

    Args:
        selected_by_change: Change in selection percentage (minor influence)
        gw_points: Points scored this gameweek
        current_price: Current price in millions
        position: Player position (GK, DEF, MID, FWD)
        total_points_season: Total season points
        apps: Total appearances

    Returns:
        New price capped to [1.0, 15.0]
    """
    change = 0.0

    # Primary: gameweek performance drives price
    # Thresholds by position
    if position == "GK":
        if gw_points >= 10:
            change += 0.2
        elif gw_points >= 6:
            change += 0.1
        elif gw_points <= 0:
            change -= 0.1
    elif position == "DEF":
        if gw_points >= 12:
            change += 0.2
        elif gw_points >= 7:
            change += 0.1
        elif gw_points <= 0:
            change -= 0.1
    elif position == "MID":
        if gw_points >= 12:
            change += 0.2
        elif gw_points >= 8:
            change += 0.1
        elif gw_points <= 0:
            change -= 0.1
    else:  # FWD
        if gw_points >= 10:
            change += 0.2
        elif gw_points >= 6:
            change += 0.1
        elif gw_points <= 0:
            change -= 0.1

    # Secondary: season form / PPG bonus for consistent performers
    if apps > 0:
        ppg = total_points_season / apps
        if ppg >= 10:  # Elite performer
            change += 0.05
        elif ppg >= 7:  # Good performer
            change += 0.03
        elif ppg < 2:  # Underperforming
            change -= 0.05

    # Minor: ownership change still has some effect (FPL-style)
    if selected_by_change >= 30:
        change += 0.05
    elif selected_by_change <= -30:
        change -= 0.05

    # Clamp to reasonable per-GW change range (±0.3m max)
    change = max(-0.3, min(0.3, change))

    new_price = current_price + change
    return round(max(1.0, min(15.0, new_price)), 1)


def calculate_form(points_history: list, weeks: int = 5) -> float:
    """Calculate player form (average points over last N gameweeks)."""
    recent = points_history[-weeks:] if len(points_history) >= weeks else points_history
    if not recent:
        return 0.0
    return round(sum(recent) / len(recent), 1)


def auto_sub_squad(
    squad: list[dict],
    non_playing_ids: list[int],
    formation: dict = None,
) -> list[dict]:
    """Auto-sub: replace non-playing starters with bench players.

    Simple approach: sub in bench players in bench_priority order.
    No position restrictions - any bench player can replace any starter.

    Args:
        squad: Full squad of 13 with is_starting flag.
        non_playing_ids: Player IDs who didn't play (injured/DNP).
        formation: Optional dict (ignored - no position restrictions).

    Returns:
        Updated squad list with is_starting flags modified.
    """
    # Find non-playing starters
    non_playing_starters = [
        sp for sp in squad
        if sp.get("is_starting") and sp["player_id"] in non_playing_ids
    ]

    # Available bench players, sort by bench_priority
    bench = sorted(
        [sp for sp in squad if not sp.get("is_starting")],
        key=lambda sp: sp.get("bench_priority", 99),
    )

    bench_idx = 0
    for starter in non_playing_starters:
        if bench_idx >= len(bench):
            break

        bench_player = bench[bench_idx]
        if bench_player["player_id"] in non_playing_ids:
            bench_idx += 1
            continue
        if bench_player.get("is_starting"):
            bench_idx += 1
            continue

        starter["is_starting"] = False
        starter["was_autosub"] = True
        bench_player["is_starting"] = True
        bench_player["was_autosub"] = True
        bench_idx += 1

    return squad


def calculate_free_transfers(
    current_free: int,
    transfers_made: int,
    max_free: int = MAX_ROLLOVER_TRANSFERS + 1,  # 5 total (4 rollover + 1 current)
    is_wildcard: bool = False,
) -> int:
    """Calculate free transfers after a gameweek.

    Returns:
        New free transfer count for next GW.
    """
    if is_wildcard:
        return 1

    used = transfers_made
    remaining = max(0, current_free - used)
    return min(max_free, remaining + 1)


def check_chip_availability(
    fantasy_team,
    chip_name: str,
    current_gw_number: int,
    season_cutoff: int = SEASON_CUTOFF,
) -> tuple[bool, str]:
    """Check if a chip is available to use.

    Chips can be used once per half of the season (2x total).
    First half: GW 1 to season_cutoff (default 11)
    Second half: GW season_cutoff+1 to end (default 12-24)
    """
    if getattr(fantasy_team, 'active_chip', None):
        return False, f"Already using {fantasy_team.active_chip} this gameweek"

    current_half = "first" if current_gw_number <= season_cutoff else "second"
    half_attr = f"{chip_name}_{'first' if current_half == 'first' else 'second'}_half"

    # Check half-specific usage if available
    if hasattr(fantasy_team, half_attr):
        if getattr(fantasy_team, half_attr):
            return False, f"{chip_name.replace('_', ' ').title()} already used in the {current_half} half"

    # Fallback to old-style single flag
    used_attr = f"{chip_name}_used"
    if hasattr(fantasy_team, used_attr) and getattr(fantasy_team, used_attr):
        return False, f"{chip_name.replace('_', ' ').title()} already used this season"

    return True, "Available"


def activate_chip(
    fantasy_team,
    chip_name: str,
    current_gw_number: int,
    season_cutoff: int = SEASON_CUTOFF,
) -> tuple[bool, str]:
    """Activate a chip for the current gameweek."""
    available, message = check_chip_availability(fantasy_team, chip_name, current_gw_number, season_cutoff)
    if not available:
        return False, message

    gw_num = current_gw_number or 1
    current_half = "first" if current_gw_number <= season_cutoff else "second"

    fantasy_team.active_chip = chip_name

    # Set half-specific flag
    half_attr = f"{chip_name}_{'first' if current_half == 'first' else 'second'}_half"
    if hasattr(fantasy_team, half_attr):
        setattr(fantasy_team, half_attr, True)

    # Also set the old-style used flag for backward compatibility
    used_attr = f"{chip_name}_used"
    if hasattr(fantasy_team, used_attr):
        setattr(fantasy_team, used_attr, True)

    return True, f"{chip_name.replace('_', ' ').title()} activated for GW {gw_num}"


def cancel_chip(
    fantasy_team,
    chip_name: str,
    current_gw_number: int,
    season_cutoff: int = SEASON_CUTOFF,
) -> tuple[bool, str]:
    """Cancel a chip before the deadline.

    Free Hit cannot be cancelled once confirmed.
    """
    if getattr(fantasy_team, 'active_chip', None) != chip_name:
        return False, f"No active chip to cancel (currently: {getattr(fantasy_team, 'active_chip', None)})"

    if chip_name == "free_hit":
        return False, "Free Hit cannot be cancelled once confirmed"

    # Reset half-specific flag
    current_half = "first" if current_gw_number <= season_cutoff else "second"
    half_attr = f"{chip_name}_{'first' if current_half == 'first' else 'second'}_half"
    if hasattr(fantasy_team, half_attr):
        setattr(fantasy_team, half_attr, False)

    # Also reset the old-style used flag if no other half has used it
    used_attr = f"{chip_name}_used"
    other_half_attr = f"{chip_name}_{'second' if current_half == 'first' else 'first'}_half"
    if hasattr(fantasy_team, used_attr):
        if hasattr(fantasy_team, other_half_attr) and getattr(fantasy_team, other_half_attr):
            pass  # Other half still used, keep used=True
        else:
            setattr(fantasy_team, used_attr, False)

    fantasy_team.active_chip = None
    return True, f"{chip_name.replace('_', ' ').title()} cancelled"


def get_chip_status(
    fantasy_team,
    current_gw_number: int = 0,
    season_cutoff: int = SEASON_CUTOFF,
) -> dict:
    """Get comprehensive chip status for a fantasy team."""
    current_half = "first" if current_gw_number <= season_cutoff else "second"

    # Check first/second half usage
    wildcard_first = getattr(fantasy_team, 'wildcard_first_half', False) or (hasattr(fantasy_team, 'wildcard_used') and fantasy_team.wildcard_used and current_gw_number <= season_cutoff)
    wildcard_second = getattr(fantasy_team, 'wildcard_second_half', False) or (hasattr(fantasy_team, 'wildcard_used') and fantasy_team.wildcard_used and current_gw_number > season_cutoff)
    free_hit_first = getattr(fantasy_team, 'free_hit_first_half', False)
    free_hit_second = getattr(fantasy_team, 'free_hit_second_half', False)
    bench_boost_first = getattr(fantasy_team, 'bench_boost_first_half', False)
    bench_boost_second = getattr(fantasy_team, 'bench_boost_second_half', False)
    triple_captain_first = getattr(fantasy_team, 'triple_captain_first_half', False)
    triple_captain_second = getattr(fantasy_team, 'triple_captain_second_half', False)

    status = {
        "wildcard_used": fantasy_team.wildcard_used if hasattr(fantasy_team, 'wildcard_used') else False,
        "wildcard_available": not fantasy_team.wildcard_used if hasattr(fantasy_team, 'wildcard_used') else True,
        "free_hit_used": fantasy_team.free_hit_used if hasattr(fantasy_team, 'free_hit_used') else False,
        "free_hit_available": not fantasy_team.free_hit_used if hasattr(fantasy_team, 'free_hit_used') else True,
        "bench_boost_used": fantasy_team.bench_boost_used if hasattr(fantasy_team, 'bench_boost_used') else False,
        "bench_boost_available": not fantasy_team.bench_boost_used if hasattr(fantasy_team, 'bench_boost_used') else True,
        "triple_captain_used": fantasy_team.triple_captain_used if hasattr(fantasy_team, 'triple_captain_used') else False,
        "triple_captain_available": not fantasy_team.triple_captain_used if hasattr(fantasy_team, 'triple_captain_used') else True,
        "active_chip": fantasy_team.active_chip if hasattr(fantasy_team, 'active_chip') else None,
        "current_half": current_half,
        # Half-specific availability
        "wildcard_first_half": wildcard_first,
        "wildcard_second_half": wildcard_second,
        "wildcard_first_half_available": not wildcard_first,
        "wildcard_second_half_available": not wildcard_second,
        "free_hit_first_half": free_hit_first,
        "free_hit_second_half": free_hit_second,
        "bench_boost_first_half": bench_boost_first,
        "bench_boost_second_half": bench_boost_second,
        "triple_captain_first_half": triple_captain_first,
        "triple_captain_second_half": triple_captain_second,
    }

    return status


def calculate_bps(
    *,
    position: str = None,
    goals_scored: int = 0,
    assists: int = 0,
    clean_sheet: bool = False,
    saves: int = 0,
    penalties_saved: int = 0,
    yellow_card: bool = False,
    red_card: bool = False,
    goals_conceded: int = 0,
    minutes_played: int = 0,
    tackles: int = 0,
    blocks: int = 0,
    interceptions: int = 0,
    was_penalty_goal: bool = False,
    was_pen_winner: bool = False,
    own_goal: bool = False,
    penalties_missed: int = 0,
    **kwargs,
) -> int:
    """Calculate Bonus Points System (BPS) score for a player.

    BPS is used to award bonus points (3, 2, 1) to the top 3 players
    in each match. Based on FPL BPS rules.

    Args:
        position: Player position (GK/DEF/MID/FWD)
        goals_scored: Number of goals
        assists: Number of assists
        clean_sheet: Whether player kept a clean sheet
        saves: Number of saves (GK)
        penalties_saved: Number of penalties saved
        yellow_card: Whether player got a yellow card
        red_card: Whether player got a red card
        goals_conceded: Number of goals conceded
        minutes_played: Minutes played
        tackles, blocks, interceptions: Defensive stats
        was_penalty_goal, was_pen_winner, own_goal, penalties_missed: Penalty stats

    Returns:
        BPS score (higher is better)
    """
    bps = 0

    # Minutes played: (minutes - 15) // 15
    if minutes_played > 15:
        bps += (minutes_played - 15) // 15

    # Goals
    if goals_scored:
        if position == "MID":
            bps += goals_scored * 10
        elif position == "FWD":
            bps += goals_scored * 8
        elif position == "DEF":
            bps += goals_scored * 12
        elif position == "GK":
            bps += goals_scored * 16
        else:
            bps += goals_scored * 8  # default

    # Penalty goal bonus
    if was_penalty_goal:
        bps += 2
    if was_pen_winner:
        bps += 5

    # Assists: 8 BPS
    bps += assists * 8

    # Saves (GK): 2 per save
    bps += saves * 2

    # Penalty save (GK): 15
    bps += penalties_saved * 15

    # Clean sheet
    if clean_sheet:
        if position == "GK":
            bps += 10
        elif position == "DEF":
            bps += 5
        elif position == "MID":
            bps += 3
        # FWD: 0 for clean sheet

    # Defensive actions
    bps += tackles * 1
    bps += blocks * 1
    bps += interceptions * 1

    # Negative contributions
    bps -= yellow_card * 3
    bps -= red_card * 8
    bps -= own_goal * 4
    bps -= penalties_missed * 10
    bps -= goals_conceded * 2

    return max(0, bps)


def award_bonus_points(
    players: list,
    gameweek_id: int = None,
    db=None,
) -> dict:
    """Award bonus points based on BPS (FPL rules).

    FPL bonus rules: 6 points total (3+2+1). Top 3 by BPS get 3, 2, 1.
    Ties use standard competition ranking (1, 1, 3, 4...) - tied players
    share the same bonus, next rank skips positions.

    Args:
        players: List of PlayerGameweekPoints objects or dicts with 'player_id' and 'bps'.
        gameweek_id: Gameweek ID for tracking (optional)
        db: Database session (optional, for updating records)

    Returns:
        Dict mapping player_id -> bonus_points awarded (3/2/1).
        Only top players by BPS are included.
    """
    # Build list of (player_id, bps_score)
    scored = []
    for p in players:
        pid = p.get("player_id") if isinstance(p, dict) else p.player_id

        # Use pre-computed BPS if available, otherwise calculate
        if isinstance(p, dict):
            bps = p.get("bps", 0)
        else:
            bps = getattr(p, "bps_score", None)
            if bps is None:
                bps = calculate_bps(
                    goals_scored=getattr(p, "goals_scored", 0),
                    assists=getattr(p, "assists", 0),
                    clean_sheet=getattr(p, "clean_sheet", False),
                    saves=getattr(p, "saves", 0),
                    penalties_saved=getattr(p, "penalties_saved", 0),
                    yellow_card=getattr(p, "yellow_card", False),
                    red_card=getattr(p, "red_card", False),
                    goals_conceded=getattr(p, "goals_conceded", 0),
                    minutes_played=getattr(p, "minutes_played", 0),
                )
            if hasattr(p, "bps_score"):
                p.bps_score = bps
        scored.append((pid, bps))

    # Sort by BPS descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Golf ranking: rank 1 = 3pts, rank 2 = 2pts, rank 3 = 1pt
    # Ties share the same rank, next rank skips positions.
    # Only players ranked 1-3 get bonus.
    bonus_map = {1: 3, 2: 2, 3: 1}
    bonus = {}
    if not scored:
        return bonus

    rank = 1
    i = 0
    while i < len(scored):
        pid, bps = scored[i]

        # Find all players at this BPS level (ties)
        tied_players = []
        j = i
        while j < len(scored) and scored[j][1] == bps:
            tied_players.append(scored[j][0])
            j += 1

        # Award bonus if rank is within top 3
        if rank in bonus_map:
            for tied_pid in tied_players:
                bonus[tied_pid] = bonus_map[rank]

        rank += len(tied_players)  # Skip positions for ties
        if rank > 3:
            break  # No more bonus available

        i = j

    return bonus


def validate_formation(formation: str) -> dict | None:
    """Validate a formation string.

    Accepts formations like "3-4-3", "4-3-3", etc.
    Returns dict with GK, DEF, MID, FWD counts or None if invalid.

    Supports both 10-player (no GK) and 11-player (with GK) formats.
    Valid formations: GK 1, DEF 3-5, MID 1-5, FWD 1-3
    Note: With no position restrictions, all formations are valid
    as long as they total 10 (without GK) or 11 (with GK).
    """
    try:
        parts = formation.split("-")
        if len(parts) != 3:
            return None
        nums = [int(p) for p in parts]

        # Check for valid totals
        total = sum(nums)
        if total == 10:
            # 10-player formation (no GK)
            gk, def_, mid, fwd = 1, nums[0], nums[1], nums[2]
            # Validate ranges
            if not (3 <= def_ <= 5 and 1 <= mid <= 5 and 1 <= fwd <= 3):
                return None
            return {"gk": gk, "def": def_, "mid": mid, "fwd": fwd}
        elif total == 11:
            # 11-player formation (GK included in first number)
            gk = max(1, nums[0])
            return {
                "gk": gk,
                "def": nums[1],
                "mid": nums[2],
                "fwd": 0,
            }
        return None
    except (ValueError, IndexError):
        return None


def validate_starting_xi(squad: list[dict], formation: dict = None) -> bool:
    """Validate a starting XI against formation requirements.

    Args:
        squad: List of squad player dicts. Supports two formats:
            - Flat: {'position': 'GK', 'is_starting': True}
            - Nested: {'player': {'position': 'GK'}, 'is_starting': True}
        formation: Dict with 'gk', 'def', 'mid', 'fwd' counts

    Returns:
        True if valid, False otherwise.
        When formation is provided, uses strict matching (== not >=).
    """
    starters = [sp for sp in squad if sp.get("is_starting")]

    if not formation:
        # No position restrictions - just need at least 10 starters
        return len(starters) >= 10

    pos_counts = {"gk": 0, "def": 0, "mid": 0, "fwd": 0}
    for sp in starters:
        # Handle both flat and nested dict formats
        player_data = sp.get("player", {}) if isinstance(sp.get("player"), dict) else {}
        pos = (player_data.get("position") or sp.get("position") or "").lower()
        if pos in pos_counts:
            pos_counts[pos] += 1

    return (
        pos_counts["gk"] == formation.get("gk", 1) and
        pos_counts["def"] == formation.get("def", 0) and
        pos_counts["mid"] == formation.get("mid", 0) and
        pos_counts["fwd"] == formation.get("fwd", 0)
    )


def calculate_ict_index(
    *,
    influence: float = 0.0,
    creativity: float = 0.0,
    threat: float = 0.0,
) -> float:
    """Calculate ICT index: (influence + creativity + threat) / 10."""
    return round((influence + creativity + threat) / 10, 1)
