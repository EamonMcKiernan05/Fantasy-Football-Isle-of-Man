"""Squad creation utilities."""
from app.models import SquadPlayer, FantasyTeam, Player


def create_default_squad(fantasy_team: FantasyTeam, players: list, db):
    """Create a default squad for a fantasy team.

    Selects 13 players (no position restrictions) within £90m budget.
    10 starting players + 3 subs.
    """
    budget = 90.0

    # Sort all active players by price (cheapest first)
    sorted_players = sorted(
        [p for p in players if p.is_active],
        key=lambda p: p.price,
    )

    selected = []
    club_counts = {}
    slot_num = 0

    for player in sorted_players:
        if len(selected) >= 13:
            break
        if budget < player.price:
            continue

        # Max 3 players from same club
        club_key = player.team_id
        if club_counts.get(club_key, 0) >= 3:
            continue

        sp = SquadPlayer(
            fantasy_team=fantasy_team,
            player=player,
            position_slot=slot_num + 1,
            is_starting=(slot_num < 10),
            is_captain=(slot_num == 0),
            is_vice_captain=(slot_num == 1),
            purchase_price=player.price,
            selling_price=player.price,
            bench_priority=(slot_num - 9) if slot_num >= 10 else 99,
        )
        selected.append(sp)
        budget -= player.price
        club_counts[club_key] = club_counts.get(club_key, 0) + 1
        slot_num += 1

    fantasy_team.budget_remaining = max(0, round(budget, 1))

    for sp in selected:
        db.add(sp)

    return selected
