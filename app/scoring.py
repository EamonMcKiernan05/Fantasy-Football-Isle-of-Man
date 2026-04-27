"""FPL-accurate scoring engine for Fantasy Football Isle of Man.

Implements the official Fantasy Premier League scoring rules adapted for
Isle of Man leagues where individual match stats may be limited.

FPL Scoring Rules (2025/26):
- GK Goal: +6, DEF Goal: +6, MID Goal: +5, FWD Goal: +4
- Assist: +3 (all positions)
- Clean sheet GK: +4, Clean sheet DEF: +4, Clean sheet MID: +3, FWD: N/A
- Bonus points: +1/+2/+3 based on BPS ranking
- Played 60+ mins: +2
- Save: +1 (GK only)
- Penalty save: +5 (GK only)
- Penalty miss: -2 (all)
- Penalty goal: +2 bonus (all)
- Yellow card: -1
- Red card: -3
- Own goal: -2
- Goals conceded: -1 (GK/DEF), max -3
- Influence/Creativity/Threat (ICT) used for tiebreaker
"""


def calculate_player_points(
    *,
    position: str,
    goals_scored: int = 0,
    assists: int = 0,
    clean_sheet: bool = False,
    goals_conceded: int = 0,
    saves: int = 0,
    yellow_card: bool = False,
    red_card: bool = False,
    own_goal: bool = False,
    penalties_saved: int = 0,
    penalties_missed: int = 0,
    minutes_played: int = 0,
    was_penalty_goal: bool = False,
    bonus_points: int = 0,
) -> int:
    """Calculate FPL points for a player in a single gameweek.

    Returns the total points scored.
    """
    points = 0

    # Participation bonus (played 60+ minutes)
    if minutes_played >= 60:
        points += 2

    # Goals - position dependent
    if goals_scored > 0:
        goal_points = {
            "GK": 6,
            "DEF": 6,
            "MID": 5,
            "FWD": 4,
        }.get(position, 5)
        points += goals_scored * goal_points

        # Penalty goal bonus
        if was_penalty_goal:
            points += 2

    # Assists
    points += assists * 3

    # Clean sheet - position dependent
    if clean_sheet:
        clean_sheet_points = {
            "GK": 4,
            "DEF": 4,
            "MID": 3,
            "FWD": 0,
        }.get(position, 0)
        points += clean_sheet_points

    # Goals conceded (GK and DEF only)
    if position in ("GK", "DEF"):
        conceded_penalty = min(goals_conceded, 3)  # Max 3 point penalty
        points -= conceded_penalty

    # Saves (GK only)
    if position == "GK":
        points += saves

        # Penalty saves (GK only)
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
    points -= penalties_missed * 2

    # Bonus points (awarded after BPS calculation)
    points += bonus_points

    return points


def calculate_bps(
    *,
    position: str,
    goals_scored: int = 0,
    assists: int = 0,
    clean_sheet: bool = False,
    goals_conceded: int = 0,
    saves: int = 0,
    tackles: int = 0,
    interceptions: int = 0,
    yellow_card: bool = False,
    red_card: bool = False,
    own_goal: bool = False,
    penalties_saved: int = 0,
    penalties_missed: int = 0,
    minutes_played: int = 0,
    was_penalty_goal: bool = False,
    bonus_points: int = 0,
) -> int:
    """Calculate BPS (Bonus Points System) score for a player.

    BPS is used to determine which 3 players get bonus points (3, 2, 1)
    in each fixture. Based on FPL's underlying stat weighting.

    FPL BPS weights (approximate, based on observed values):
    """
    bps = 0

    # Only players who played get BPS
    if minutes_played < 1:
        return 0

    # Goals (heavy weight)
    if goals_scored > 0:
        if position == "FWD":
            bps += goals_scored * 8
        elif position == "MID":
            bps += goals_scored * 10
        else:  # GK, DEF
            bps += goals_scored * 12

        if was_penalty_goal:
            bps += 2

    # Assists
    bps += assists * 8

    # Clean sheet
    if clean_sheet:
        if position == "GK":
            bps += 10
        elif position == "DEF":
            bps += 8
        elif position == "MID":
            bps += 5

    # Saves (GK)
    bps += saves * 2
    bps += penalties_saved * 10

    # Defending
    bps += tackles * 3
    bps += interceptions * 3

    # Negative events
    if yellow_card:
        bps -= 1
    if red_card:
        bps -= 5
    if own_goal:
        bps -= 3
    bps -= goals_conceded * 2
    bps -= penalties_missed * 3

    # Minutes played contribution (small weight)
    bps += max(0, (minutes_played - 15) // 15)  # 1 BPS per 15 min after 15 min

    return max(0, bps)


def award_bonus_points(players_with_bps: list) -> dict:
    """Award bonus points to top 3 players by BPS.

    Args:
        players_with_bps: List of dicts with 'player_id' and 'bps' keys.

    Returns:
        Dict mapping player_id -> bonus_points (3, 2, or 1).
    """
    if len(players_with_bps) < 3:
        return {}

    # Sort by BPS descending
    sorted_players = sorted(players_with_bps, key=lambda x: x["bps"], reverse=True)

    bonus_map = {}
    bonus_values = [3, 2, 1]
    for i in range(3):
        player_id = sorted_players[i]["player_id"]
        bonus_map[player_id] = bonus_values[i]

    return bonus_map


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
    - Unused transfers rollover (max 5)
    - Extra transfers: -4 points each
    - Wildcard: no transfer limit, no point hit
    """
    if is_wildcard:
        return 0

    if transfers_made <= free_transfers_available:
        return 0

    extra = transfers_made - free_transfers_available
    return extra * 4  # -4 per extra transfer


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
        squad_points: List of dicts with 'id', 'base_points', 'is_captain', 'is_starting'
        captain_id: SquadPlayer ID of captain
        vice_captain_id: SquadPlayer ID of vice-captain
        transfers_cost: Point hit from transfers
        chip: Active chip name

    Returns:
        Dict with total, captain, bench_boost, transfer details.
    """
    captain_played = False
    total = 0
    bench_points = 0
    captain_points = 0

    # Find if captain played
    captain_entry = next((sp for sp in squad_points if sp.get("id") == captain_id), None)
    vice_entry = next((sp for sp in squad_points if sp.get("id") == vice_captain_id), None)

    # Determine effective captain (vice takes over if captain didn't play)
    effective_captain_id = captain_id
    if captain_entry and not captain_entry.get("did_play", True):
        effective_captain_id = vice_captain_id
    elif not captain_entry:
        effective_captain_id = vice_captain_id

    for sp in squad_points:
        base = sp.get("base_points", 0)
        is_starting = sp.get("is_starting", True)
        did_play = sp.get("did_play", True)

        # Determine if this player contributes
        if chip == "bench_boost":
            # All 15 players contribute
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
        else:
            points = base

        total += points

    # Apply transfer hit
    total -= transfers_cost

    return {
        "total_points": total,
        "captain_points": captain_points,
        "transfers_cost": transfers_cost,
        "chip": chip,
    }


def update_player_price(selected_by_percent: float, gw_points: int, current_price: float) -> float:
    """Calculate player price change for a gameweek.

    FPL price rules:
    - +0.1m for every 50% increase in ownership
    - -0.1m for every 50% decrease
    - Price rounded to nearest 0.1m
    - Min price 1.0m, max 15.0m
    """
    # Price change based on selection percentage
    change = 0

    if selected_by_percent >= 50:
        change += 0.1
    elif selected_by_percent >= 30:
        change += 0.05
    elif selected_by_percent <= -50:
        change -= 0.1
    elif selected_by_percent <= -30:
        change -= 0.05

    new_price = current_price + change
    return round(max(1.0, min(15.0, new_price)), 1)


def calculate_form(points_history: list, weeks: int = 5) -> float:
    """Calculate player form (average points over last N gameweeks)."""
    recent = points_history[-weeks:] if len(points_history) >= weeks else points_history
    if not recent:
        return 0.0
    return round(sum(recent) / len(recent), 1)


# FPL Position mappings for formation validation
STARTING_XI_SLOTS = {
    "GK": [1],
    "DEF": [2, 3, 4, 5],
    "MID": [6, 7, 8, 9, 10],
    "FWD": [11, 12],
}

# Minimum players per position in starting XI
MIN_STARTING = {"GK": 1, "DEF": 3, "MID": 1, "FWD": 1}
MAX_STARTING = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
TOTAL_STARTING = 11
TOTAL_SQUAD = 15

# Valid formations (DEF-MID-FWD)
VALID_FORMATIONS = [
    {"name": "3-4-3", "def": 3, "mid": 4, "fwd": 3},
    {"name": "3-5-2", "def": 3, "mid": 5, "fwd": 2},
    {"name": "4-3-3", "def": 4, "mid": 3, "fwd": 3},
    {"name": "4-4-2", "def": 4, "mid": 4, "fwd": 2},
    {"name": "4-5-1", "def": 4, "mid": 5, "fwd": 1},
    {"name": "5-3-2", "def": 5, "mid": 3, "fwd": 2},
    {"name": "5-4-1", "def": 5, "mid": 4, "fwd": 1},
]


def validate_formation(formation_name: str) -> dict | None:
    """Validate a formation string like '4-3-3'."""
    for f in VALID_FORMATIONS:
        if f["name"] == formation_name:
            return f
    return None


def validate_starting_xi(squad: list[dict], formation: dict) -> bool:
    """Validate that a starting XI matches a formation.

    Args:
        squad: List of squad players with 'is_starting', 'player.position'
        formation: Dict with 'def', 'mid', 'fwd' counts.

    Returns:
        True if valid.
    """
    starters = [sp for sp in squad if sp.get("is_starting")]
    gk_count = sum(1 for sp in starters if sp["player"]["position"] == "GK")
    def_count = sum(1 for sp in starters if sp["player"]["position"] == "DEF")
    mid_count = sum(1 for sp in starters if sp["player"]["position"] == "MID")
    fwd_count = sum(1 for sp in starters if sp["player"]["position"] == "FWD")

    return (
        gk_count == 1
        and def_count == formation["def"]
        and mid_count == formation["mid"]
        and fwd_count == formation["fwd"]
        and len(starters) == 11
    )


def auto_sub_squad(
    squad: list[dict],
    non_playing_ids: list[int],
    formation: dict,
) -> list[dict]:
    """FPL-style auto-sub: replace non-playing starters with bench players.

    Rules:
    - Sub the lowest-positioned non-playing starter first (FWD > MID > DEF > GK)
    - Sub in the highest-positioned bench player (GK < DEF < MID < FWD)
    - Respect position constraints: don't put a FWD in DEF slot
    - GK can only be replaced by a GK
    - DEF/MID can flex (DEF out -> MID in, MID out -> DEF in)

    Args:
        squad: Full squad of 15 with is_starting flag.
        non_playing_ids: Player IDs who didn't play (injured/DNP).
        formation: Formation dict with def/mid/fwd counts.

    Returns:
        Updated squad list with is_starting flags modified.
    """
    POSITION_PRIORITY = {"FWD": 4, "MID": 3, "DEF": 2, "GK": 1}

    # Find non-playing starters, sort by position priority (sub lowest position first)
    non_playing_starters = [
        sp for sp in squad
        if sp.get("is_starting") and sp["player_id"] in non_playing_ids
    ]
    non_playing_starters.sort(key=lambda sp: POSITION_PRIORITY.get(sp["player"]["position"], 0), reverse=True)

    # Available bench players, sort by position priority (sub in highest position first)
    bench = [sp for sp in squad if not sp.get("is_starting")]
    bench.sort(key=lambda sp: POSITION_PRIORITY.get(sp["player"]["position"], 0), reverse=True)

    bench_idx = 0
    for starter in non_playing_starters:
        starter_pos = starter["player"]["position"]

        # Find a suitable replacement from bench
        replacement = None
        used_bench = []

        for i, bench_player in enumerate(bench):
            if bench_player["player_id"] in non_playing_ids:
                continue
            bench_pos = bench_player["player"]["position"]

            # GK must be replaced by GK
            if starter_pos == "GK":
                if bench_pos == "GK":
                    replacement = bench_player
                    used_bench.append(i)
                    break
                continue

            # Direct position match
            if bench_pos == starter_pos:
                replacement = bench_player
                used_bench.append(i)
                break

            # Flex: DEF <-> MID can swap
            if starter_pos in ("DEF", "MID") and bench_pos in ("DEF", "MID"):
                replacement = bench_player
                used_bench.append(i)
                break

        if replacement:
            starter["is_starting"] = False
            starter["was_autosubbed"] = True
            replacement["is_starting"] = True
            replacement["was_autosubbed"] = True

    return squad


def calculate_free_transfers(
    current_free: int,
    transfers_made: int,
    max_free: int = 2,
    is_wildcard: bool = False,
) -> int:
    """Calculate free transfers after a gameweek.

    FPL rules:
    - Get 1 free transfer per gameweek (plus rollover, max 2)
    - Wildcard resets to 1 (or 2 if already had rollover)

    Returns:
        New free transfer count.
    """
    if is_wildcard:
        return max_free  # Reset to max on wildcard

    used = transfers_made
    remaining = max(0, current_free - used)
    # Add 1 for the next gameweek, cap at max_free
    return min(max_free, remaining + 1)
