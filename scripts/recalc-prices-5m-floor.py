#!/usr/bin/env python3
"""Recalculate all player prices with 5.0m floor based on last season's performances."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "fantasy_iom.db"
LAST_SEASON_FILE = Path(__file__).parent.parent / "data" / "last_season_stats.json"

TEAM_MAP = {
    "Ayre United": "Ayre United First",
    "Braddan": "Braddan First",
    "Corinthians": "Corinthians First",
    "DHSOB": "DHSOB First",
    "Foxdale": "Foxdale First",
    "Laxey": "Laxey First",
    "Onchan": "Onchan First",
    "Peel": "Peel First",
    "Ramsey": "Ramsey First",
    "Rushen United": "Rushen United First",
    "St Johns": "St Johns United First",
    "St Marys": "St Marys First",
    "Union Mills": "Union Mills First",
}

def calc_fantasy_points(goals, assists, pens, yellows, reds):
    return max(0, goals * 4 + assists * 3 - yellows - reds * 3 + (pens or 0) * 2)

def calc_starting_price(last_season_pts, min_price=5.0, max_price=17.0):
    return round(min(max_price, max(min_price, min_price + last_season_pts * 0.05)), 1)

def calc_current_price(starting_price, current_pts, min_price=5.0, max_price=17.0):
    if current_pts <= 0:
        return starting_price
    increase = (current_pts // 15) * 0.1
    return round(min(max_price, max(min_price, starting_price + increase)), 1)

def match_last_season(name, team, last_season_data):
    player_lower = name.lower()
    for p in last_season_data:
        if p["name"].lower() == player_lower:
            return p
    return None

def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    with open(LAST_SEASON_FILE) as f:
        last_season_data = json.load(f)["players"]

    # Filter last season data to players with 5+ appearances
    last_season_5plus = [p for p in last_season_data if p["apps"] >= 5]
    print(f"Last season data: {len(last_season_data)} players, {len(last_season_5plus)} with 5+ apps")

    c.execute("""
        SELECT p.id, p.name, p.position, t.name as team,
               p.goals, p.assists, p.yellow_cards, p.red_cards,
               p.apps, p.clean_sheets, p.saves
        FROM players p
        LEFT JOIN teams t ON p.team_id = t.id
        WHERE p.is_active = 1
    """)
    players = c.fetchall()

    c.execute("SELECT id FROM fantasy_teams LIMIT 1")
    ft_row = c.fetchone()
    ft_id = ft_row["id"] if ft_row else None
    squad_player_ids = set()
    if ft_id:
        c.execute("SELECT player_id FROM squad_players WHERE fantasy_team_id = ?", (ft_id,))
        squad_player_ids = set(r["player_id"] for r in c.fetchall())

    total_owned_increase = 0.0
    updated = 0

    for player in players:
        pid = player["id"]
        name = player["name"]
        team = player["team"]
        goals = player["goals"] or 0
        assists = player["assists"] or 0
        yellows = player["yellow_cards"] or 0
        reds = player["red_cards"] or 0
        clean_sheets = player["clean_sheets"] or 0
        saves = player["saves"] or 0

        # Current season points
        current_pts = (goals * 4) + (assists * 3) - yellows - (reds * 3) + (clean_sheets * 4) + (saves // 3)
        current_pts = max(0, current_pts)

        # Match to last season (only if 5+ apps)
        ls = None
        for p in last_season_5plus:
            if p["name"].lower() == name.lower():
                ls = p
                break

        last_pts = 0
        if ls:
            last_pts = calc_fantasy_points(ls["goals"], ls["assists"], ls["pens"], ls["yellows"], ls["reds"])

        starting_price = calc_starting_price(last_pts)
        current_price = calc_current_price(starting_price, current_pts)

        # Budget tracking
        is_owned = pid in squad_player_ids
        if is_owned:
            c.execute("SELECT price FROM players WHERE id = ?", (pid,))
            old_price = c.fetchone()[0]
            if old_price and current_price > old_price:
                total_owned_increase += (current_price - old_price)

        c.execute("""
            UPDATE players SET
                total_points_season = ?,
                price = ?,
                price_start = ?,
                price_change = ?
            WHERE id = ?
        """, (current_pts, current_price, starting_price, round(current_price - starting_price, 1), pid))
        updated += 1

    # Budget adjustment
    if ft_id and total_owned_increase > 0:
        budget_add = round(total_owned_increase / 2, 1)
        c.execute("SELECT budget, budget_remaining FROM fantasy_teams WHERE id = ?", (ft_id,))
        old = c.fetchone()
        c.execute("UPDATE fantasy_teams SET budget = ?, budget_remaining = ? WHERE id = ?",
                  (old["budget"] + budget_add, old["budget_remaining"] + budget_add, ft_id))
        print(f"Budget: +{budget_add}m (half of {total_owned_increase}m owned increase)")
        print(f"New budget: {old['budget'] + budget_add}m, remaining: {old['budget_remaining'] + budget_add}m")
    elif ft_id:
        c.execute("SELECT budget, budget_remaining FROM fantasy_teams WHERE id = ?", (ft_id,))
        old = c.fetchone()
        print(f"Budget unchanged: {old['budget']}m, remaining: {old['budget_remaining']}m")

    conn.commit()

    # Verify key players
    print(f"\nUpdated {updated} players")
    print("\n=== KEY PLAYERS ===")
    for n in ['Tomas Brown', 'Ryan Edwards', 'Josh Ridings', 'Tyler Hughes',
              'Shaun Kelly', 'Tom Creer', 'ETHAN LEIVERS', 'Jason Chatwood', 'Lee Gale', 'Dan Simpson']:
        c.execute("SELECT name, price, price_start, total_points_season, goals, assists, apps FROM players WHERE name LIKE ?", (n,))
        r = c.fetchone()
        if r:
            print(f"  {r['name']:<25} price={r['price']:>5} start={r['price_start']:>5} pts={r['total_points_season']:>4} goals={r['goals']:>3} assists={r['assists']:>3} apps={r['apps']:>3}")

    print(f"\n=== TOP 20 BY PRICE ===")
    c.execute("""
        SELECT p.name, p.price, p.price_start, p.total_points_season, p.goals, p.assists, t.name as team
        FROM players p LEFT JOIN teams t ON p.team_id = t.id
        WHERE p.is_active=1 ORDER BY p.price DESC LIMIT 20
    """)
    for r in c.fetchall():
        print(f"  {r['name']:<25} {r['team']:<18} price={r['price']:>5} start={r['price_start']:>5} pts={r['total_points_season']:>4} goals={r['goals']:>3} assists={r['assists']:>3}")

    # Price distribution
    c.execute("SELECT MIN(price), MAX(price), AVG(price), COUNT(*) FROM players WHERE is_active=1")
    r = c.fetchone()
    print(f"\nPrice distribution: min={r[0]}, max={r[1]}, avg={r[2]:.1f}, count={r[3]}")

    conn.close()
    print("\nDone!")

if __name__ == "__main__":
    main()
