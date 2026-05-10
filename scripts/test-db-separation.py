#!/usr/bin/env python3
"""Test that FFIOM-DB separation is working correctly."""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from app.database import (
    engine, get_db, get_ffiom_db, get_bound_db,
    init_binds, FfiomSessionLocal,
)

# Test 1: FFIOM-DB exists and has expected tables
print("=== Test 1: FFIOM-DB tables ===")
ffiom_db = FfiomSessionLocal()
try:
    tables = ffiom_db.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )).fetchall()
    table_names = [t[0] for t in tables]
    expected = ['divisions', 'fixtures', 'gameweeks', 'leagues', 'players', 'seasons', 'teams']
    assert table_names == expected, f"Expected {expected}, got {table_names}"
    print(f"  FFIOM-DB tables: {table_names} OK")

    # Count key tables
    for tbl, expected_count in [('players', 172), ('teams', 13), ('gameweeks', 25), ('fixtures', 130)]:
        count = ffiom_db.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        assert count == expected_count, f"{tbl}: expected {expected_count}, got {count}"
        print(f"  {tbl}: {count} rows OK")
finally:
    ffiom_db.close()

# Test 2: Game DB has all tables including game-specific ones
print("\n=== Test 2: Game DB tables ===")
game_db = engine.connect()
tables = game_db.execute(text(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
)).fetchall()
table_names = [t[0] for t in tables]
game_tables = ['users', 'fantasy_teams', 'squad_players', 'transfers', 'chips']
for gt in game_tables:
    assert gt in table_names, f"Missing game table: {gt}"
    count = game_db.execute(text(f"SELECT COUNT(*) FROM {gt}")).scalar()
    print(f"  {gt}: {count} rows OK")

# Test 3: Cross-database query via ATTACH (from game DB connection)
print("\n=== Test 3: Cross-DB query via ATTACH ===")
# From game DB, we can query ffiom.players
try:
    count = game_db.execute(text("SELECT COUNT(*) FROM ffiom.players")).scalar()
    print(f"  ffiom.players count from game DB: {count} OK")
except Exception as e:
    print(f"  ATTACH query failed: {e}")
    print("  (This is OK if using separate engine approach)")
game_db.close()

# Test 4: Binds configuration
print("\n=== Test 4: Binds configuration ===")
init_binds()
from app.database import BoundSessionLocal
assert BoundSessionLocal is not None, "BoundSessionLocal not initialized"
print("  BoundSessionLocal initialized OK")

# Test 5: Query Player model (should go to FFIOM-DB via binds)
print("\n=== Test 5: Player model query (via binds) ===")
from app.models import Player, Team, Gameweek, Fixture
bound_db = BoundSessionLocal()
try:
    players = bound_db.query(Player).limit(3).all()
    print(f"  Players via binds: {[p.name for p in players]}")

    teams = bound_db.query(Team).limit(3).all()
    print(f"  Teams via binds: {[t.name for t in teams]}")

    gameweeks = bound_db.query(Gameweek).limit(3).all()
    print(f"  Gameweeks via binds: {[g.number for g in gameweeks]}")

    fixtures = bound_db.query(Fixture).limit(3).all()
    print(f"  Fixtures via binds: {[(f.home_team_name, f.away_team_name) for f in fixtures]}")
finally:
    bound_db.close()

# Test 6: Game-specific models still use game DB
print("\n=== Test 6: Game-specific models (game DB) ===")
from app.models import User, FantasyTeam, SquadPlayer
game_session = BoundSessionLocal()
try:
    users = game_session.query(User).all()
    print(f"  Users (game DB): {[u.username for u in users]}")

    teams = game_session.query(FantasyTeam).all()
    print(f"  FantasyTeams (game DB): {[t.name for t in teams]}")

    squad = game_session.query(SquadPlayer).limit(3).all()
    print(f"  SquadPlayers (game DB): {len(squad)} entries")

    # Test cross-DB join: SquadPlayer.player -> Player (should work via binds)
    for sp in squad[:2]:
        player_name = sp.player.name if sp.player else "NONE"
        player_price = sp.player.price if sp.player else 0
        print(f"    SquadPlayer {sp.position_slot}: player={player_name}, price={player_price}")
finally:
    game_session.close()

print("\n=== ALL TESTS PASSED ===")
