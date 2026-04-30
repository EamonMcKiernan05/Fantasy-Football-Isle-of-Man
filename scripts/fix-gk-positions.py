#!/usr/bin/env python3
"""Identify and fix goalkeeper positions based on API data."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from app.database import SessionLocal
from app.models import Player, Team, SquadPlayer, FantasyTeam

db = SessionLocal()

# Load cached player stats
with open("data/player_stats_cache.json") as f:
    stats_cache = json.load(f)

# Find players with 25+ apps, 0 goals, 0 assists - almost certainly GKs
# Also check the cache for additional data
print("Analyzing players for GK identification...")

# First, let's see all players with 0 goals, 0 assists, and many apps
candidates = db.query(Player).filter(
    Player.is_active == True,
    Player.goals == 0,
    Player.assists == 0,
    Player.apps >= 20
).order_by(Player.apps.desc()).all()

print(f"\nPlayers with {len(candidates)} candidates (0 goals, 0 assists, 20+ apps):")
for p in candidates:
    team = p.team
    print(f"  {p.name:<30} apps={p.apps:>3} team={team.name if team else '?':<15} pos={p.position}")

# Now cross-reference with the stats cache
print("\nCross-referencing with cached API data:")
# Cache is dict keyed by personID: {"614634143": {"name": "...", "appearances": N, ...}}
cache_list = list(stats_cache.values()) if isinstance(stats_cache, dict) else []

gk_names = set()
for entry in cache_list:
    if isinstance(entry, dict):
        if entry.get("appearances", 0) >= 24 and entry.get("goals", 0) == 0 and entry.get("assists", 0) == 0:
            name = entry.get("name", "").strip()
            if name:
                gk_names.add(name.lower())

print(f"\nPlayers identified as likely GKs from cache: {len(gk_names)}")
for name in sorted(gk_names):
    print(f"  {name}")

# Update GK positions
count = 0
for p in candidates:
    if p.name.lower() in gk_names and p.position != "GK":
        print(f"\nUpdating {p.name} ({p.team.name if p.team else '?'}) to GK")
        p.position = "GK"
        count += 1
    elif p.name.lower() not in gk_names:
        # Check if player plays for a team that already has a GK
        existing_gks = db.query(Player).filter(
            Player.team_id == p.team_id,
            Player.position == "GK"
        ).all()
        if not existing_gks and p.name.lower() in gk_names:
            p.position = "GK"
            count += 1

db.commit()
print(f"\nUpdated {count} players to GK position")
print(f"Total GKs now: {db.query(Player).filter(Player.position == 'GK').count()}")

# Show final GK list
gks = db.query(Player).filter(Player.position == "GK", Player.is_active == True).all()
print("\nFinal GK roster:")
for p in gks:
    print(f"  {p.name:<30} apps={p.apps:>3} team={p.team.name if p.team else '?':<15}")

# Now fix the test user's squad to include GKs
print("\n\n=== Fixing test squad ===")
ft = db.query(FantasyTeam).filter_by(user_id=1).first()
if ft:
    # Remove existing squad
    old_squad = db.query(SquadPlayer).filter_by(fantasy_team_id=ft.id).all()
    for sp in old_squad:
        db.delete(sp)
    db.commit()
    
    # Build new squad with GKs
    gks = db.query(Player).filter(Player.is_active == True, Player.position == "GK").order_by(Player.apps.desc()).all()
    defs = db.query(Player).filter(Player.is_active == True, Player.position == "DEF").order_by((Player.goals + Player.apps).desc()).all()
    mids = db.query(Player).filter(Player.is_active == True, Player.position == "MID").order_by((Player.goals + Player.apps).desc()).all()
    fwds = db.query(Player).filter(Player.is_active == True, Player.position == "FWD").order_by((Player.goals + Player.apps).desc()).all()
    
    squad = []
    budget = 100.0
    
    # Pick 2 GKs
    for gk in gks[:2]:
        if budget >= gk.price:
            squad.append(gk)
            budget -= gk.price
    
    # Pick 5 DEFs
    for d in defs[:5]:
        if budget >= d.price and len([s for s in squad if s.position == "DEF"]) < 5:
            squad.append(d)
            budget -= d.price
    
    # Pick 5 MIDs
    for m in mids[:10]:
        if budget >= m.price and len([s for s in squad if s.position == "MID"]) < 5:
            squad.append(m)
            budget -= m.price
    
    # Pick 3 FWDs
    for f in fwds[:6]:
        if budget >= f.price and len([s for s in squad if s.position == "FWD"]) < 3:
            squad.append(f)
            budget -= f.price
    
    print(f"Selected {len(squad)} players (budget remaining: {budget:.1f}m)")
    for s in squad:
        print(f"  {s.name:<30} {s.position:<4} {s.price}m")
    
    # Create squad entries
    for i, player in enumerate(squad):
        sp = SquadPlayer(
            fantasy_team_id=ft.id,
            player_id=player.id,
            position_slot=i + 1,
            is_starting=i < 11,
            is_captain=i == 0,
            is_vice_captain=i == 1,
            bench_priority=0 if i < 11 else i - 10,
        )
        db.add(sp)
    
    db.commit()
    print(f"\nSquad rebuilt with {len(squad)} players")
else:
    print("No fantasy team found for user 1")

db.close()
