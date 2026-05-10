#!/usr/bin/env python3
"""Verify game DB is intact after FFIOM-DB restructuring."""
import sqlite3

GAME_DB = "/home/eamon/Fantasy-Football-Isle-of-Man/data/fantasy_iom.db"

conn = sqlite3.connect(GAME_DB)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(f"Game DB tables ({len(tables)}):")
for t in tables:
    cur.execute(f'SELECT COUNT(*) FROM [{t}]')
    cnt = cur.fetchone()[0]
    print(f"  {t}: {cnt} rows")

# Key checks
checks = {
    'players': 172,
    'teams': 13,
    'gameweeks': 25,
    'fixtures': 130,
    'users': 1,
    'fantasy_teams': 1,
    'squad_players': 13,
    'player_gameweek_points': 1724,
}
print("\nVerification:")
all_ok = True
for table, expected in checks.items():
    cur.execute(f'SELECT COUNT(*) FROM [{table}]')
    actual = cur.fetchone()[0]
    status = "OK" if actual == expected else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  {table}: expected={expected}, actual={actual} [{status}]")

conn.close()
print(f"\n{'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
