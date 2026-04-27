"""Squad creation utilities."""
from app.models import SquadPlayer, FantasyTeam, Player


def create_default_squad(fantasy_team: FantasyTeam, players: list, db):
    """Create a default squad for a fantasy team.

    Selects 15 players (2 GK, 5 DEF, 5 MID, 3 FWD) within budget.
    """
    budget = 100.0

    # Sort players by position and price
    gks = sorted([p for p in players if p.position == 'GK'], key=lambda p: p.price)
    defs = sorted([p for p in players if p.position == 'DEF'], key=lambda p: p.price)
    mids = sorted([p for p in players if p.position == 'MID'], key=lambda p: p.price)
    fwds = sorted([p for p in players if p.position == 'FWD'], key=lambda p: p.price)

    selected = []
    slots = [
        ("GK", 2, gks),
        ("DEF", 5, defs),
        ("MID", 5, mids),
        ("FWD", 3, fwds),
    ]

    slot_num = 0
    for pos, count, player_list in slots:
        for i in range(min(count, len(player_list))):
            player = player_list[i]
            sp = SquadPlayer(
                fantasy_team=fantasy_team,
                player=player,
                position_slot=slot_num + 1,
                is_starting=(slot_num < 11),
                is_captain=(slot_num == 0),
                is_vice_captain=(slot_num == 1),
                purchase_price=player.price,
                selling_price=player.price,
                bench_priority=slot_num + 1 if slot_num >= 11 else 99,
            )
            selected.append(sp)
            budget -= player.price
            slot_num += 1

    fantasy_team.budget_remaining = max(0, budget)

    for sp in selected:
        db.add(sp)

    return selected
