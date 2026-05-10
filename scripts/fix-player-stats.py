#!/usr/bin/env python3
"""Fix player stats: update total_points_season from PGP records.

Also verifies data integrity.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "fantasy_iom.db"


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Recalculate total_points_season from PGP records
    c.execute("""
        UPDATE players SET total_points_season = (
            SELECT COALESCE(SUM(total_points), 0)
            FROM player_gameweek_points
            WHERE player_gameweek_points.player_id = players.id
        )
        WHERE is_active = 1
    """)
    updated = c.rowcount
    print(f"Updated total_points_season for {updated} players")

    # Verify key players
    c.execute("""
        SELECT p.name, p.total_points_season, p.goals, p.price, p.price_start
        FROM players p
        WHERE p.name IN ('Tomas Brown', 'Ryan Edwards', 'Jason Charmer', 'Josh Ridings', 'Shaun Kelly', 'Tyler Hughes')
        ORDER BY p.total_points_season DESC
    """)
    print(f"\nKey players after update:")
    for r in c.fetchall():
        print(f"  {r['name']:<25} pts={r['total_points_season']:<5} goals={r['goals']:<4} price={r['price']:<5} start={r['price_start']}")

    # Stats summary
    c.execute("SELECT COUNT(*), MIN(total_points_season), MAX(total_points_season), AVG(total_points_season) FROM players WHERE is_active=1")
    r = c.fetchone()
    print(f"\nActive players: {r[0]}, min_pts={r[1]}, max_pts={r[2]}, avg_pts={r[3]:.1f}")

    # Check how many have PGP data vs season stats
    c.execute("""
        SELECT COUNT(DISTINCT player_id) FROM player_gameweek_points
    """)
    print(f"Players with PGP records: {c.fetchone()[0]}")

    conn.commit()
    conn.close()
    print(f"\nDone.")


if __name__ == "__main__":
    main()
