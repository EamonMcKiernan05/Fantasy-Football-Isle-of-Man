"""FPL-accurate scoring engine for Fantasy Football Isle of Man.

Implements the official Fantasy Premier League 2025/26 scoring rules adapted for
Isle of Man leagues where individual match stats may be limited.

FPL Scoring Rules (2025/26) - Official Premier League:
- Played up to 60 mins: 1 pt, Played 60+ mins: 2 pts
- GK Goal: +10, DEF Goal: +6, MID Goal: +5, FWD Goal: +4
- Assist: +3 (all positions)
- Clean sheet GK/DEF: +4, Clean sheet MID: +1, FWD: N/A
- Every 3 saves (GK): +1
- Penalty save (GK): +5
- Defensive contributions DEF: 10 = +2, MID: 12 = +2, FWD: 12 = +2
- Bonus points: +1/+2/+3 based on BPS ranking (per fixture)
- Penalty miss: -2 (all)
- Penalty goal: +2 bonus (all)
- Yellow card: -1
- Red card: -3
- Own goal: -2
- Every 2 goals conceded (GK/DEF): -1
- Influence/Creativity/Threat (ICT) used for BPS tiebreaker
"""

# FPL constants
TRANSFER_HIT = 4  # -4 per extra transfer
MAX_ROLLOVER_TRANSFERS = 4  # FPL: max 4 rollover (5 total with current GW)
MAX_TRANSFERS_PER_GW = 20  # FPL: max 20 transfers per GW (excluding chips)
FREE_TRANSFER_PER_GW = 1  # FPL: 1 free transfer per gameweek
MAX_PLAYERS_PER_CLUB = 3  # FPL: max 3 players from any single club


# FPL 2025/26 Official Scoring Reference
# Points for:
#   Playing 60+ min: 2pts, Playing < 60 min: 1pt
#   Goal: GK=10, DEF=6, MID=5, FWD=4
#   Assist: +3 (all positions)
#   Clean sheet: GK/DEF=+4, MID=+1
#   Every 3 saves (GK): +1
#   Penalty save (GK): +5
#   Penalty miss: -2
#   Yellow card: -1
#   Red card: -3
#   Own goal: -2
#   Every 2 goals conceded (GK/DEF): -1
#   Bonus points: 3/2/1 based on BPS
#
# Chips (2x per season each, 1 per half):
#   Wildcard: Unlimited permanent transfers, no hit
#   Free Hit: One-off full squad change, reverts next GW
#   Bench Boost: All 15 players' points count
#   Triple Captain: Captain gets 3x instead of 2x


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
    defensive_contributions: int = 0,
) -> int:
    """Calculate FPL points for a player in a single gameweek.

    Uses official FPL 2025/26 scoring rules.
    Returns the total points scored.
    """
    points = 0

    # Participation bonus (FPL 2025/26)
    if minutes_played >= 60:
        points += 2
    elif minutes_played >= 1:
        points += 1  # Playing any minutes gives 1 pt

    # Goals - position dependent
    if goals_scored > 0:
        goal_points = {
            "GK": 10,   # CHANGED 2025/26: was 6
            "DEF": 6,
            "MID": 5,
            "FWD": 4,
        }.get(position, 5)
        points += goals_scored * goal_points

        # Penalty goal bonus (+2 for scoring a penalty, FPL rule)
        if was_penalty_goal:
            points += 2

    # Assists (+3 for any position)
    points += assists * 3

    # Clean sheet - position dependent
    if clean_sheet:
        clean_sheet_points = {
            "GK": 4,
            "DEF": 4,
            "MID": 1,   # CHANGED 2025/26: was 3
            "FWD": 0,   # Forwards don't get clean sheet points
        }.get(position, 0)
        points += clean_sheet_points

    # Saves (GK only, +1 per 3 saves in official FPL)
    if position == "GK":
        points += saves // 3  # CHANGED 2025/26: was saves * 1

        # Penalty saves (GK only, +5 each)
        points += penalties_saved * 5

    # Defensive contributions (NEW 2025/26)
    # DEF: 10 contributions = +2, MID/FWD: 12 contributions = +2
    if position == "DEF" and defensive_contributions >= 10:
        points += 2
    elif position in ("MID", "FWD") and defensive_contributions >= 12:
        points += 2

    # Goals conceded (GK and DEF only, every 2 = -1)
    if position in ("GK", "DEF"):
        conceded_penalty = goals_conceded // 2  # CHANGED 2025/26: was min(goals_conceded, 3)
        points -= conceded_penalty

    # Cards
    if yellow_card:
        points -= 1
    if red_card:
        points -= 3

    # Own goal
    if own_goal:
        points -= 2

    # Penalty missed (-2 each)
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
    clearances: int = 0,
    blocks: int = 0,
    yellow_card: bool = False,
    red_card: bool = False,
    own_goal: bool = False,
    penalties_saved: int = 0,
    penalties_missed: int = 0,
    minutes_played: int = 0,
    was_penalty_goal: bool = False,
    bonus_points: int = 0,
    ball_recoveries: int = 0,
) -> int:
    """Calculate BPS (Bonus Points System) score for a player.

    BPS is used to determine which players get bonus points (3, 2, 1)
    in each fixture. Based on FPL 2025/26 BPS weights.

    FPL 2025/26 BPS weights (based on observed values):
    - Goals: position-dependent (FWD: 8, MID: 10, DEF/GK: 12)
    - Penalty goals: +2 extra
    - Assists: +8 each
    - Clean sheet: GK: 10, DEF: 8, MID: 5
    - Saves: +2 each
    - Penalty saves: +11 (8 for thwarted spot-kick + 3 for saving a shot)
    - Tackles: +3 each
    - Interceptions: +3 each
    - Clearances: +3 each (for DEF)
    - Blocks: +3 each (for DEF)
    - Yellow card: -1
    - Red card: -5
    - Own goal: -3
    - Goals conceded: -2 each
    - Penalty missed: -3 each
    - Minutes: 1 BPS per 15 min after 15 min
    """
    bps = 0

    # Only players who played get BPS
    if minutes_played < 1:
        return 0

    # Goals (heavy weight, position-dependent)
    if goals_scored > 0:
        if position == "FWD":
            bps += goals_scored * 8
        elif position == "MID":
            bps += goals_scored * 10
        else:  # GK, DEF
            bps += goals_scored * 12

        if was_penalty_goal:
            bps += 2  # Extra BPS for penalty goals

    # Assists
    bps += assists * 8

    # Clean sheet (position-dependent)
    if clean_sheet:
        if position == "GK":
            bps += 10
        elif position == "DEF":
            bps += 8
        elif position == "MID":
            bps += 5

    # Saves (GK)
    bps += saves * 2
    # Penalty saves: 11 BPS (FPL 2025/26: 8 for thwarted spot-kick + 3 for saving shot)
    bps += penalties_saved * 11

    # Defending
    bps += tackles * 3
    bps += interceptions * 3
    # Clearances and blocks (DEF specific)
    if position == "DEF":
        bps += clearances * 3
        bps += blocks * 3

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
    """Award bonus points to top players by BPS in a fixture.

    FPL 2025/26 tie-breaking rules:
    - 3 bonus points awarded total: 3 for 1st, 2 for 2nd, 1 for 3rd
    - If tie for 1st: tied players get 3 pts, next distinct gets 1 pt (skips 2)
    - If tie for 2nd: player 1 gets 3, tied players get 2 pts each (no 1 pt awarded)
    - If tie for 3rd: player 1 gets 3, player 2 gets 2, tied players get 1 pt each
    - More than 3 players can earn bonus points if ties exist

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
    bps_values = [p["bps"] for p in sorted_players]

    # Check for ties at position 1
    if bps_values[0] == bps_values[1]:
        # Tie for first: all tied get 3, next distinct gets 1 (skips position 2)
        idx = 0
        while idx < len(sorted_players) and bps_values[idx] == bps_values[0]:
            bonus_map[sorted_players[idx]["player_id"]] = 3
            idx += 1
        # Next distinct BPS gets 1 point
        if idx < len(sorted_players):
            bonus_map[sorted_players[idx]["player_id"]] = 1
    else:
        bonus_map[sorted_players[0]["player_id"]] = 3
        # Check for ties at position 2
        if len(sorted_players) >= 3 and bps_values[1] == bps_values[2]:
            # Tie for second: tied players get 2, no 1-point awarded
            idx = 1
            while idx < len(sorted_players) and bps_values[idx] == bps_values[1]:
                bonus_map[sorted_players[idx]["player_id"]] = 2
                idx += 1
            # No more bonus points - positions 2 and 3 are consumed by the tie
        else:
            bonus_map[sorted_players[1]["player_id"]] = 2
            # Check for ties at position 3
            if len(sorted_players) >= 4 and bps_values[2] == bps_values[3]:
                idx = 2
                while idx < len(sorted_players) and bps_values[idx] == bps_values[2]:
                    bonus_map[sorted_players[idx]["player_id"]] = 1
                    idx += 1
            else:
                bonus_map[sorted_players[2]["player_id"]] = 1

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

    starting_points = 0
    bench_pts = 0

    for sp in squad_points:
        base = sp.get("base_points", 0)
        is_starting = sp.get("is_starting", True)
        did_play = sp.get("did_play", True)

        # Determine if this player contributes
        if chip == "bench_boost":
            # All 15 players contribute (bench boost chip)
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

    FPL Rule:
    If a player's price rises after purchase, you keep half of the increase
    when selling, rounded down to the nearest 0.1m.

    Example: bought for 7.5m, now worth 7.8m -> selling price = 7.5 + floor((7.8-7.5)/2) = 7.6m
    Example: bought for 5.0m, now worth 4.5m -> selling price = 4.5m (no half rule for decreases)

    Args:
        purchase_price: The price when this manager bought the player
        current_price: The player's current market price

    Returns:
        The effective selling price for budget calculations
    """
    if current_price > purchase_price:
        # Half-increase rule: keep half the gain, rounded down to 0.1m
        increase = current_price - purchase_price
        half_increase = floor_to_01(increase / 2)
        return purchase_price + half_increase
    else:
        # No increase -> selling at current price (or lower)
        return current_price


def floor_to_01(value: float) -> float:
    """Round down to nearest 0.1 (FPL rounding)."""
    import math
    return math.floor(value * 10) / 10


def update_player_price(
    selected_by_change: float,
    gw_points: int,
    current_price: float,
) -> float:
    """Calculate player price change for a gameweek.

    FPL price rules:
    - +0.1m for every 50% increase in ownership
    - -0.1m for every 50% decrease
    - Price rounded to nearest 0.1m
    - Min price 1.0m, max 15.0m

    Args:
        selected_by_change: Change in selection percentage (can be negative)
        gw_points: Points scored this gameweek (minor influence)
        current_price: Current price in millions

    Returns:
        New price capped to [1.0, 15.0]
    """
    change = 0.0

    # Primary: ownership change drives price
    if selected_by_change >= 50:
        change += 0.2
    elif selected_by_change >= 25:
        change += 0.1
    elif selected_by_change <= -50:
        change -= 0.2
    elif selected_by_change <= -25:
        change -= 0.1

    # Secondary: high scorers get slight boost
    if gw_points >= 20:
        change += 0.1

    new_price = current_price + change
    return round(max(1.0, min(15.0, new_price)), 1)


def calculate_form(points_history: list, weeks: int = 5) -> float:
    """Calculate player form (average points over last N gameweeks)."""
    recent = points_history[-weeks:] if len(points_history) >= weeks else points_history
    if not recent:
        return 0.0
    return round(sum(recent) / len(recent), 1)


def calculate_ict_index(influence: float, creativity: float, threat: float) -> float:
    """Calculate ICT index (Influence + Creativity + Threat).

    FPL: ICT = (influence + creativity + threat) / 10
    """
    return round((influence + creativity + threat) / 10, 1)


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

    # Available bench players, sort by bench_priority then position priority
    bench = [sp for sp in squad if not sp.get("is_starting")]
    bench.sort(key=lambda sp: (sp.get("bench_priority", 99), -POSITION_PRIORITY.get(sp["player"]["position"], 0)))

    for starter in non_playing_starters:
        starter_pos = starter["player"]["position"]

        # Find a suitable replacement from bench
        replacement = None

        for bench_player in bench:
            if bench_player["player_id"] in non_playing_ids:
                continue
            if bench_player.get("is_starting"):
                continue
            bench_pos = bench_player["player"]["position"]

            # GK must be replaced by GK
            if starter_pos == "GK":
                if bench_pos == "GK":
                    replacement = bench_player
                    break
                continue

            # Direct position match
            if bench_pos == starter_pos:
                replacement = bench_player
                break

            # Flex: DEF <-> MID can swap
            if starter_pos in ("DEF", "MID") and bench_pos in ("DEF", "MID"):
                replacement = bench_player
                break

        if replacement:
            starter["is_starting"] = False
            starter["was_autosub"] = True
            replacement["is_starting"] = True
            replacement["was_autosub"] = True

    return squad


def calculate_free_transfers(
    current_free: int,
    transfers_made: int,
    max_free: int = MAX_ROLLOVER_TRANSFERS + 1,  # 5 total (4 rollover + 1 current)
    is_wildcard: bool = False,
) -> int:
    """Calculate free transfers after a gameweek.

    FPL rules:
    - Get 1 free transfer per gameweek (plus rollover, max 5 total)
    - Wildcard resets to 1
    - Free Hit doesn't affect free transfers

    Returns:
        New free transfer count for next GW.
    """
    if is_wildcard:
        return 1  # Reset to 1 on wildcard (gets +1 next GW = 2 max)

    used = transfers_made
    remaining = max(0, current_free - used)
    # Add 1 for the next gameweek, cap at max_free
    return min(max_free, remaining + 1)


def check_chip_availability(
    fantasy_team,
    chip_name: str,
    current_gw_number: int,
    season_cutoff: int = 19,
) -> tuple[bool, str]:
    """Check if a chip is available to use.

    FPL 2025/26 rules:
    - All chips (except Wildcard) are available 2x per season
    - First half: GW 1-19, Second half: GW 20+
    - Only one chip per gameweek
    - Free Hit cannot be used in consecutive gameweeks
    - Unused first-half chips do NOT carry over (deadline GW19 18:30 GMT)

    Returns:
        (available: bool, message: str)
    """
    # Check if already using a chip this GW
    if fantasy_team.active_chip:
        return False, f"Already using {fantasy_team.active_chip} this gameweek"

    gw_num = current_gw_number or 1
    is_first_half = gw_num <= season_cutoff

    if chip_name == "wildcard":
        if is_first_half:
            if fantasy_team.wildcard_first_half:
                return False, "First half wildcard already used"
            return True, "Available"
        else:
            if fantasy_team.wildcard_second_half:
                return False, "Second half wildcard already used"
            return True, "Available"

    elif chip_name == "free_hit":
        if is_first_half:
            if fantasy_team.free_hit_first_half:
                return False, "First half Free Hit already used"
            return True, "Available"
        else:
            if fantasy_team.free_hit_second_half:
                return False, "Second half Free Hit already used"
            return True, "Available"

    elif chip_name == "bench_boost":
        if is_first_half:
            if fantasy_team.bench_boost_first_half:
                return False, "First half Bench Boost already used"
            return True, "Available"
        else:
            if fantasy_team.bench_boost_second_half:
                return False, "Second half Bench Boost already used"
            return True, "Available"

    elif chip_name == "triple_captain":
        if is_first_half:
            if fantasy_team.triple_captain_first_half:
                return False, "First half Triple Captain already used"
            return True, "Available"
        else:
            if fantasy_team.triple_captain_second_half:
                return False, "Second half Triple Captain already used"
            return True, "Available"

    return False, f"Unknown chip: {chip_name}"


def activate_chip(
    fantasy_team,
    chip_name: str,
    current_gw_number: int,
    season_cutoff: int = 19,
) -> tuple[bool, str]:
    """Activate a chip for the current gameweek.

    Returns:
        (success: bool, message: str)
    """
    available, message = check_chip_availability(fantasy_team, chip_name, current_gw_number, season_cutoff)
    if not available:
        return False, message

    gw_num = current_gw_number or 1
    is_first_half = gw_num <= season_cutoff

    # Set active chip
    fantasy_team.active_chip = chip_name

    # Mark the appropriate half as used
    if chip_name == "wildcard":
        if is_first_half:
            fantasy_team.wildcard_first_half = True
        else:
            fantasy_team.wildcard_second_half = True
    elif chip_name == "free_hit":
        if is_first_half:
            fantasy_team.free_hit_first_half = True
        else:
            fantasy_team.free_hit_second_half = True
    elif chip_name == "bench_boost":
        if is_first_half:
            fantasy_team.bench_boost_first_half = True
        else:
            fantasy_team.bench_boost_second_half = True
    elif chip_name == "triple_captain":
        if is_first_half:
            fantasy_team.triple_captain_first_half = True
        else:
            fantasy_team.triple_captain_second_half = True

    return True, f"{chip_name.replace('_', ' ').title()} activated for GW {gw_num}"


def cancel_chip(fantasy_team, chip_name: str, current_gw_number: int, season_cutoff: int = 19) -> tuple[bool, str]:
    """Cancel a chip before the deadline.

    FPL rules: Bench Boost, Triple Captain, Wildcard can be cancelled before deadline.
    Free Hit cannot be cancelled once confirmed.

    Returns:
        (success: bool, message: str)
    """
    if fantasy_team.active_chip != chip_name:
        return False, f"No active chip to cancel (currently: {fantasy_team.active_chip})"

    # Free Hit cannot be cancelled
    if chip_name == "free_hit":
        return False, "Free Hit cannot be cancelled once confirmed"

    # Reset the chip usage
    gw_num = current_gw_number or 1
    is_first_half = gw_num <= season_cutoff

    if chip_name == "wildcard":
        if is_first_half:
            fantasy_team.wildcard_first_half = False
        else:
            fantasy_team.wildcard_second_half = False
    elif chip_name == "bench_boost":
        if is_first_half:
            fantasy_team.bench_boost_first_half = False
        else:
            fantasy_team.bench_boost_second_half = False
    elif chip_name == "triple_captain":
        if is_first_half:
            fantasy_team.triple_captain_first_half = False
        else:
            fantasy_team.triple_captain_second_half = False

    fantasy_team.active_chip = None
    return True, f"{chip_name.replace('_', ' ').title()} cancelled"


def get_chip_status(fantasy_team, current_gw_number: int = 0, season_cutoff: int = 19) -> dict:
    """Get comprehensive chip status for a fantasy team.

    Returns dict with all chip availability info.
    """
    gw_num = current_gw_number or 1
    is_first_half = gw_num <= season_cutoff

    return {
        "wildcard_first_half_used": fantasy_team.wildcard_first_half,
        "wildcard_second_half_used": fantasy_team.wildcard_second_half,
        "wildcard_first_half_available": not fantasy_team.wildcard_first_half,
        "wildcard_second_half_available": not fantasy_team.wildcard_second_half,
        "free_hit_first_half_used": fantasy_team.free_hit_first_half,
        "free_hit_second_half_used": fantasy_team.free_hit_second_half,
        "free_hit_first_half_available": not fantasy_team.free_hit_first_half,
        "free_hit_second_half_available": not fantasy_team.free_hit_second_half,
        "bench_boost_first_half_used": fantasy_team.bench_boost_first_half,
        "bench_boost_second_half_used": fantasy_team.bench_boost_second_half,
        "bench_boost_first_half_available": not fantasy_team.bench_boost_first_half,
        "bench_boost_second_half_available": not fantasy_team.bench_boost_second_half,
        "triple_captain_first_half_used": fantasy_team.triple_captain_first_half,
        "triple_captain_second_half_used": fantasy_team.triple_captain_second_half,
        "triple_captain_first_half_available": not fantasy_team.triple_captain_first_half,
        "triple_captain_second_half_available": not fantasy_team.triple_captain_second_half,
        "active_chip": fantasy_team.active_chip,
        "current_half": "first" if is_first_half else "second",
    }
