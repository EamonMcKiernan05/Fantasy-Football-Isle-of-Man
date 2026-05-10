#!/usr/bin/env python3
"""Recalculate player prices from scratch.

1. Load last season (2024-25) stats from FullTime website
2. Calculate fantasy points for each player from last season
3. Set starting prices based on last season performance
4. Calculate gradual price increases based on current season points
5. Update team budget when owned players increase in price

Pricing rules:
- Starting price: 4.0m base + 0.05m per last season fantasy point, capped at 12.0m
- Per-GW increase: 0.1m for every 15 current season points (cumulative)
- Per-GW decrease: 0.1m for every 15 points below baseline
- Budget adjustment: when a player in your team increases price, you get half the increase added to your budget

Fantasy points formula (simplified):
- Goals: 4 pts each
- Assists: 3 pts each
- Yellow cards: -1 each
- Red cards: -3 each
- Penalties scored: +2 bonus each
"""

import json
import math
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "fantasy_iom.db"
LAST_SEASON_FILE = Path(__file__).parent.parent / "data" / "last_season_stats.json"

# Premier League team name mapping (strip " First" suffix)
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

# Reverse map: FullTime team name -> DB team name
REVERSE_TEAM_MAP = {v: k for k, v in TEAM_MAP.items()}


def normalize_team(team_name):
    """Convert FullTime team name to DB team name."""
    for db_name, ft_name in TEAM_MAP.items():
        if ft_name.lower() == team_name.lower():
            return db_name
    return None


def calculate_fantasy_points(goals, assists, pens, yellows, reds):
    """Calculate fantasy points from season stats."""
    pts = goals * 4 + assists * 3 - yellows - reds * 3
    if pens > 0:
        pts += pens * 2  # penalty bonus
    return max(0, pts)


def calculate_starting_price(fantasy_pts):
    """Calculate starting price from last season fantasy points.

    Base 4.0m + 0.05m per fantasy point, capped at 12.0m.
    """
    price = 4.0 + (fantasy_pts * 0.05)
    return round(min(12.0, max(4.0, price)), 1)


def calculate_current_price(starting_price, current_season_points):
    """Calculate current price based on starting price + gradual increases.

    0.1m increase for every 15 points scored this season.
    """
    if current_season_points <= 0:
        return starting_price

    increase_per_15 = 0.1
    increase = (current_season_points // 15) * increase_per_15
    price = starting_price + increase
    return round(min(12.0, max(4.0, price)), 1)


def match_player_to_last_season(player_name, player_team, last_season_data):
    """Match a current player to their last season stats."""
    player_lower = player_name.lower()

    # First try exact match
    for ls_player in last_season_data:
        if ls_player["name"].lower() == player_lower:
            return ls_player

    # Try team-filtered match
    team_match = None
    for ls_player in last_season_data:
        if ls_player["name"].lower() == player_lower:
            ls_team = normalize_team(ls_player["team"])
            if ls_team == player_team:
                return ls_player
            if team_match is None:
                team_match = ls_player

    return team_match


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Load last season data
    with open(LAST_SEASON_FILE) as f:
        last_season_data = json.load(f)["players"]

    print(f"Loaded {len(last_season_data)} last season player records")

    # Get all active players
    c.execute("""
        SELECT p.id, p.name, p.position, t.name as team
        FROM players p
        LEFT JOIN teams t ON p.team_id = t.id
        WHERE p.is_active = 1
        ORDER BY p.name
    """)
    players = c.fetchall()
    print(f"Found {len(players)} active players")

    # Get current season points from PGP
    c.execute("""
        SELECT player_id, SUM(total_points) as total_pts,
               SUM(goals_scored) as total_goals,
               SUM(assists) as total_assists,
               SUM(minutes_played) as total_mins
        FROM player_gameweek_points
        GROUP BY player_id
    """)
    current_points = {r["player_id"]: dict(r) for r in c.fetchall()}

    # Get fantasy team and squad
    c.execute("SELECT id FROM fantasy_teams LIMIT 1")
    ft_row = c.fetchone()
    if ft_row:
        ft_id = ft_row["id"]
        c.execute("SELECT id FROM squad_players WHERE fantasy_team_id = ?", (ft_id,))
        squad_player_ids = [r["id"] for r in c.fetchall()]
        c.execute("SELECT player_id FROM squad_players WHERE fantasy_team_id = ?", (ft_id,))
        squad_player_ids_set = set(r["player_id"] for r in c.fetchall())
    else:
        ft_id = None
        squad_player_ids_set = set()
        squad_player_ids = []

    print(f"Fantasy team: {ft_id}, squad: {len(squad_player_ids)} players")

    # Track price changes for budget calculation
    total_price_increase_owned = 0.0

    # Process each player
    updated = 0
    not_matched = []
    price_changes = []

    for player in players:
        pid = player["id"]
        name = player["name"]
        pos = player["position"] or "FWD"
        team = player["team"]

        # Match to last season
        ls = match_player_to_last_season(name, team, last_season_data)

        if ls:
            last_pts = calculate_fantasy_points(
                ls["goals"], ls["assists"], ls["pens"], ls["yellows"], ls["reds"]
            )
            starting_price = calculate_starting_price(last_pts)
        else:
            # No last season data - use default
            last_pts = 0
            starting_price = 4.0
            not_matched.append(name)

        # Get current season points
        cp = current_points.get(pid, {})
        cur_pts = cp.get("total_pts", 0) or 0

        # Fallback: if no PGP data but season stats exist, calculate from those
        if cur_pts == 0:
            c.execute("SELECT goals, assists, yellow_cards FROM players WHERE id = ?", (pid,))
            season_row = c.fetchone()
            if season_row and (season_row["goals"] or 0) > 0:
                cur_pts = (season_row["goals"] or 0) * 4 + (season_row["assists"] or 0) * 3 - (season_row["yellow_cards"] or 0)
                cur_pts = max(0, cur_pts)
                print(f"  Fallback points for {name}: {cur_pts} (from {season_row['goals']}g {season_row['assists']}a {season_row['yellow_cards']}y)")

        # Calculate current price
        current_price = calculate_current_price(starting_price, cur_pts)

        # Check if this player is in our squad
        is_owned = pid in squad_player_ids_set
        old_price = None
        if is_owned:
            c.execute("SELECT price FROM players WHERE id = ?", (pid,))
            old_price = c.fetchone()[0]
            if old_price and current_price > old_price:
                total_price_increase_owned += (current_price - old_price)

        # Update player
        c.execute("""
            UPDATE players SET
                price = ?,
                price_start = ?,
                price_change = ?
            WHERE id = ?
        """, (current_price, starting_price, round(current_price - starting_price, 1), pid))

        price_changes.append({
            "name": name,
            "team": team,
            "pos": pos,
            "last_season_pts": last_pts,
            "cur_season_pts": cur_pts,
            "starting_price": starting_price,
            "current_price": current_price,
            "owned": is_owned,
        })
        updated += 1

    # Update fantasy team budget with half of owned player price increases
    if ft_id and total_price_increase_owned > 0:
        budget_addition = round(total_price_increase_owned / 2, 1)
        c.execute("SELECT budget, budget_remaining FROM fantasy_teams WHERE id = ?", (ft_id,))
        old_budget = c.fetchone()
        new_budget = old_budget["budget"] + budget_addition
        new_remaining = old_budget["budget_remaining"] + budget_addition
        c.execute("""
            UPDATE fantasy_teams SET
                budget = ?,
                budget_remaining = ?
            WHERE id = ?
        """, (new_budget, new_remaining, ft_id))
        print(f"\nBudget adjustment: +{budget_addition}m (half of {total_price_increase_owned}m owned increase)")
        print(f"New budget: {new_budget}m, remaining: {new_remaining}m")

    conn.commit()

    # Print summary
    print(f"\nUpdated {updated} players")
    if not_matched:
        print(f"\nNot matched to last season ({len(not_matched)}):")
        for n in not_matched[:20]:
            print(f"  - {n}")

    # Show top 20 by price
    print(f"\n--- Top 20 by price ---")
    sorted_changes = sorted(price_changes, key=lambda x: x["current_price"], reverse=True)
    for pc in sorted_changes[:20]:
        owned_mark = " [OWNED]" if pc["owned"] else ""
        print(f"  {pc['name']:<25} {pc['team']:<18} {pc['pos']:<3} "
              f"last_pts={pc['last_season_pts']:<4} cur_pts={pc['cur_season_pts']:<4} "
              f"start={pc['starting_price']:<5} price={pc['current_price']:<5}{owned_mark}")

    # Show key players
    print(f"\n--- Key players ---")
    for name in ["Tomas Brown", "Ryan Edwards", "Josh Ridings", "Tyler Hughes", "Shaun Kelly"]:
        for pc in price_changes:
            if pc["name"].lower() == name.lower():
                owned_mark = " [OWNED]" if pc["owned"] else ""
                print(f"  {pc['name']:<25} last_pts={pc['last_season_pts']:<4} cur_pts={pc['cur_season_pts']:<4} "
                      f"start={pc['starting_price']:<5} price={pc['current_price']:<5}{owned_mark}")
                break
        else:
            print(f"  {name}: NOT FOUND")

    conn.close()
    print(f"\nDone.")


if __name__ == "__main__":
    main()
