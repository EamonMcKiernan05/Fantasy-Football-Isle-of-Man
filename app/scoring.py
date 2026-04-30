"""Simplified scoring engine for Fantasy Football Isle of Man.

Scoring based on available FullTime API data:
- Goals, appearances, minutes played, clean sheets, yellow/red cards, own goals
- No assists, no saves, no defensive contributions, no BPS bonus points
- No position-dependent scoring (all players score the same for each stat)
- 24 gameweeks per season

Scoring Rules:
- Goal scored: +4
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

# Season configuration
TOTAL_GAMEWEEKS = 24
SEASON_CUTOFF = 11  # First half GW 1-11, second half GW 12-24


def calculate_player_points(
    *,
    goals_scored: int = 0,
    clean_sheet: bool = False,
    yellow_card: bool = False,
    red_card: bool = False,
    own_goal: bool = False,
    minutes_played: int = 0,
) -> int:
    """Calculate points for a player in a single gameweek.

    Uses simplified scoring based on available data.
    Returns the total points scored.
    """
    points = 0

    # Minutes played bonus
    if minutes_played >= 60:
        points += 2
    elif minutes_played >= 1:
        points += 1  # Playing any minutes gives 1 pt

    # Goals
    points += goals_scored * 4

    # Clean sheet
    if clean_sheet:
        points += 3

    # Cards
    if yellow_card:
        points -= 1
    if red_card:
        points -= 3

    # Own goal
    if own_goal:
        points -= 2

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
) -> float:
    """Calculate player price change for a gameweek.

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


def auto_sub_squad(
    squad: list[dict],
    non_playing_ids: list[int],
) -> list[dict]:
    """Auto-sub: replace non-playing starters with bench players.

    Simple approach: sub in bench players in bench_priority order.
    No position restrictions - any bench player can replace any starter.

    Args:
        squad: Full squad of 13 with is_starting flag.
        non_playing_ids: Player IDs who didn't play (injured/DNP).

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

    Returns:
        (available: bool, message: str)
    """
    if fantasy_team.active_chip:
        return False, f"Already using {fantasy_team.active_chip} this gameweek"

    if chip_name == "wildcard":
        if fantasy_team.wildcard_used:
            return False, "Wildcard already used this season"
        return True, "Available"

    elif chip_name == "free_hit":
        if fantasy_team.free_hit_used:
            return False, "Free Hit already used this season"
        return True, "Available"

    elif chip_name == "bench_boost":
        if fantasy_team.bench_boost_used:
            return False, "Bench Boost already used this season"
        return True, "Available"

    elif chip_name == "triple_captain":
        if fantasy_team.triple_captain_used:
            return False, "Triple Captain already used this season"
        return True, "Available"

    return False, f"Unknown chip: {chip_name}"


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

    fantasy_team.active_chip = chip_name

    if chip_name == "wildcard":
        fantasy_team.wildcard_used = True
    elif chip_name == "free_hit":
        fantasy_team.free_hit_used = True
    elif chip_name == "bench_boost":
        fantasy_team.bench_boost_used = True
    elif chip_name == "triple_captain":
        fantasy_team.triple_captain_used = True

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
    if fantasy_team.active_chip != chip_name:
        return False, f"No active chip to cancel (currently: {fantasy_team.active_chip})"

    if chip_name == "free_hit":
        return False, "Free Hit cannot be cancelled once confirmed"

    if chip_name == "wildcard":
        fantasy_team.wildcard_used = False
    elif chip_name == "bench_boost":
        fantasy_team.bench_boost_used = False
    elif chip_name == "triple_captain":
        fantasy_team.triple_captain_used = False

    fantasy_team.active_chip = None
    return True, f"{chip_name.replace('_', ' ').title()} cancelled"


def get_chip_status(
    fantasy_team,
    current_gw_number: int = 0,
    season_cutoff: int = SEASON_CUTOFF,
) -> dict:
    """Get comprehensive chip status for a fantasy team."""
    return {
        "wildcard_used": fantasy_team.wildcard_used,
        "wildcard_available": not fantasy_team.wildcard_used,
        "free_hit_used": fantasy_team.free_hit_used,
        "free_hit_available": not fantasy_team.free_hit_used,
        "bench_boost_used": fantasy_team.bench_boost_used,
        "bench_boost_available": not fantasy_team.bench_boost_used,
        "triple_captain_used": fantasy_team.triple_captain_used,
        "triple_captain_available": not fantasy_team.triple_captain_used,
        "active_chip": fantasy_team.active_chip,
    }
