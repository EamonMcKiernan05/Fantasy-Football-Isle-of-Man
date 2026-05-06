#!/usr/bin/env python3
"""Re-price all players based on their current season performance.

This script recalculates player prices based on points per game (PPG) and
position, similar to how FPL prices evolve over a season.

FPL 2024/25 reference pricing:
- Gabriel (Arsenal DEF, 7 PPG): 5.0m -> 6.0m over season
- Watkins (AVL FWD, 6 PPG): 7.5m -> 8.0m over season
- Palmer (Chelsea MID, 7 PPG): 5.5m -> 10.0m over season

Position-based base prices:
- GK: 4.0-6.0m (CS% and saves drive value)
- DEF: 4.0-8.0m (goals, assists, CS drive value)
- MID: 4.5-10.0m (goals, assists drive value)
- FWD: 4.5-12.0m (goals drive value)

Formula: base_price + (ppg - baseline) * multiplier
- GK baseline: 3.0 PPG, multiplier: 0.5
- DEF baseline: 3.0 PPG, multiplier: 0.6
- MID baseline: 3.5 PPG, multiplier: 0.7
- FWD baseline: 3.0 PPG, multiplier: 0.8
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models import Player


def calculate_new_price(player: Player) -> float:
    """Calculate new price based on season performance."""
    position = player.position or "MID"
    total_points = player.total_points_season or 0
    apps = player.apps or 0

    if apps == 0:
        return player.price_start  # No apps, keep start price

    ppg = total_points / apps
    goals = player.goals or 0
    assists = player.assists or 0
    clean_sheets = player.clean_sheets or 0

    # Position-based pricing
    if position == "GK":
        base = 4.0
        baseline_ppg = 3.0
        multiplier = 0.5
        # GKs valued on clean sheets and saves
        cs_bonus = (clean_sheets / apps) * 0.5 if apps > 0 else 0
        price = base + (ppg - baseline_ppg) * multiplier + cs_bonus

    elif position == "DEF":
        base = 4.0
        baseline_ppg = 3.0
        multiplier = 0.6
        # DEFs valued on goals, assists, and clean sheets
        goal_bonus = goals * 0.15
        assist_bonus = assists * 0.05
        cs_bonus = (clean_sheets / apps) * 0.3 if apps > 0 else 0
        price = base + (ppg - baseline_ppg) * multiplier + goal_bonus + assist_bonus + cs_bonus

    elif position == "MID":
        base = 4.5
        baseline_ppg = 3.5
        multiplier = 0.7
        # MIDs valued on goals and assists
        goal_bonus = goals * 0.12
        assist_bonus = assists * 0.08
        price = base + (ppg - baseline_ppg) * multiplier + goal_bonus + assist_bonus

    else:  # FWD
        base = 4.5
        baseline_ppg = 3.0
        multiplier = 0.8
        # FWDs valued primarily on goals
        goal_bonus = goals * 0.15
        assist_bonus = assists * 0.05
        price = base + (ppg - baseline_ppg) * multiplier + goal_bonus + assist_bonus

   # Apply reasonable bounds
    # Min: 3.5m (FPL-style minimum)
    # Max: 12.0m for truly elite players
    # Require minimum 3 apps for significant price boosts
    if apps < 3:
        # Not enough data - don't boost price
        price = min(price, player.price_start + 0.5)
    elif ppg >= 12:  # Elite (Tomas Brown level)
        price = min(price, 12.0)
    elif ppg >= 9:  # Very good
        price = min(price, 10.0)
    elif ppg >= 6:  # Good
        price = min(price, 8.0)
    else:
        price = min(price, 7.0)

    price = max(3.5, price)
    return round(price, 1)


def main():
    db = SessionLocal()
    try:
        players = db.query(Player).filter(Player.is_active == True).all()
        print(f"Repricing {len(players)} active players...\n")

        updated = 0
        for player in players:
            old_price = player.price
            new_price = calculate_new_price(player)

            if abs(old_price - new_price) > 0.05:
                player.price = new_price
                player.price_change = int(round((new_price - old_price) * 10))
                player.price_change_total = int(round((new_price - player.price_start) * 10))
                updated += 1

                position = player.position or "MID"
                total_points = player.total_points_season or 0
                apps = player.apps or 0
                ppg = total_points / apps if apps > 0 else 0

                print(f"  {player.name:<25} ({position}) {old_price:>5.1f}m -> {new_price:>5.1f}m "
                      f"({total_points:>4} pts, {apps:>2} apps, {ppg:.1f} PPG)")

        db.commit()
        print(f"\nUpdated {updated}/{len(players)} players")
        print(f"Price range: {min(p.price for p in players):.1f}m - {max(p.price for p in players):.1f}m")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()