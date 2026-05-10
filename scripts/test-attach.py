#!/usr/bin/env python3
"""Test SQLite ATTACH DATABASE for reading FFIOM-DB from game DB."""
import sqlite3

GAME_DB = "/home/eamon/Fantasy-Football-Isle-of-Man/data/fantasy_iom.db"
FFIOM_DB = "/home/eamon/FFIOM-DB/data/fantasy_iom.db"

conn = sqlite3.connect(GAME_DB)
cur = conn.cursor()

# Attach FFIOM-DB as a second database
cur.execute(f"ATTACH DATABASE '{FFIOM_DB}' AS ffiom")

# Query players from FFIOM-DB
cur.execute("SELECT COUNT(*) FROM ffiom.players")
print(f"FFIOM-DB players: {cur.fetchone()[0]}")

# Query players from game DB (local)
cur.execute("SELECT COUNT(*) FROM main.players")
print(f"Game DB players: {cur.fetchone()[0]}")

# Query teams from FFIOM-DB
cur.execute("SELECT name FROM ffiom.teams ORDER BY id LIMIT 5")
print(f"FFIOM-DB teams (first 5): {[r[0] for r in cur.fetchall()]}")

# Query squad_players from game DB
cur.execute("SELECT COUNT(*) FROM main.squad_players")
print(f"Game DB squad_players: {cur.fetchone()[0]}")

# Cross-database join test: squad_players (game DB) -> players (FFIOM-DB)
cur.execute("""
    SELECT ffiom.players.name, ffiom.players.price, ffiom.players.total_points_season
    FROM main.squad_players
    JOIN ffiom.players ON main.squad_players.player_id = ffiom.players.id
    ORDER BY ffiom.players.price DESC
""")
rows = cur.fetchall()
print(f"\nCross-DB join (squad from game, players from FFIOM-DB):")
for name, price, pts in rows[:5]:
    print(f"  {name}: price={price}, pts={pts}")

cur.execute("DETACH DATABASE ffiom")
conn.close()
print("\nATTACH DATABASE test PASSED!")
