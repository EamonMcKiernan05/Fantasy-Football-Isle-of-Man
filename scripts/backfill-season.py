#!/usr/bin/env python3
"""Backfill the entire 2025-26 season (GW1-GW35) with historical data.

Populates: team standings, gameweek_stats, fantasy team scores,
transfer history, chip usage, player price history, fantasy team history.

Usage: python scripts/backfill-season.py
"""
import os
import sys
import random
import math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from sqlalchemy import text as sql_text
from app.database import SessionLocal

db = SessionLocal()

random.seed(42)

# ============================================================
# 1. Update team standings from fixtures
# ============================================================
def update_team_standings():
    print("=== 1. Updating team standings ===")
    # First pass: goals and games played
    db.execute(sql_text("""
        UPDATE teams SET
            goals_for = (
                SELECT COALESCE(SUM(
                    CASE WHEN f.home_team_id = teams.id THEN f.home_score ELSE f.away_score END
                ), 0) FROM fixtures f
                WHERE (f.home_team_id = teams.id OR f.away_team_id = teams.id) AND f.played = 1
            ),
            goals_against = (
                SELECT COALESCE(SUM(
                    CASE WHEN f.home_team_id = teams.id THEN f.away_score ELSE f.home_score END
                ), 0) FROM fixtures f
                WHERE (f.home_team_id = teams.id OR f.away_team_id = teams.id) AND f.played = 1
            ),
            games_played = (
                SELECT COUNT(*) FROM fixtures f
                WHERE (f.home_team_id = teams.id OR f.away_team_id = teams.id) AND f.played = 1
            ),
            goal_difference = (
                SELECT COALESCE(SUM(
                    CASE WHEN f.home_team_id = teams.id THEN f.home_score - f.away_score
                         ELSE f.away_score - f.home_score END
                ), 0) FROM fixtures f
                WHERE (f.home_team_id = teams.id OR f.away_team_id = teams.id) AND f.played = 1
            )
    """))

    # Second pass: calculate wins/draws/losses/points per team
    teams = db.execute(sql_text("SELECT id FROM teams")).fetchall()
    for (tid,) in teams:
        wins = db.execute(sql_text("""
            SELECT COUNT(*) FROM fixtures f WHERE f.played = 1 AND (
                (f.home_team_id = :tid AND f.home_score > f.away_score) OR
                (f.away_team_id = :tid AND f.away_score > f.home_score)
            )
        """), {"tid": tid}).scalar()
        draws = db.execute(sql_text("""
            SELECT COUNT(*) FROM fixtures f WHERE f.played = 1 AND (
                (f.home_team_id = :tid AND f.home_score = f.away_score) OR
                (f.away_team_id = :tid AND f.away_score = f.home_score)
            )
        """), {"tid": tid}).scalar()
        losses = db.execute(sql_text("""
            SELECT COUNT(*) FROM fixtures f WHERE f.played = 1 AND (
                (f.home_team_id = :tid AND f.home_score < f.away_score) OR
                (f.away_team_id = :tid AND f.away_score < f.home_score)
            )
        """), {"tid": tid}).scalar()
        points = int(wins) * 3 + int(draws)
        db.execute(sql_text("""
            UPDATE teams SET games_won = :w, games_drawn = :d, games_lost = :l, current_points = :p
            WHERE id = :tid
        """), {"w": wins, "d": draws, "l": losses, "p": points, "tid": tid})

    # Update positions
    ranked = db.execute(sql_text(
        "SELECT id, current_points, goal_difference FROM teams ORDER BY current_points DESC, goal_difference DESC"
    )).fetchall()
    for rank, row in enumerate(ranked, 1):
        db.execute(sql_text("UPDATE teams SET current_position = :r WHERE id = :tid"),
                  {"r": rank, "tid": row[0]})

    db.flush()

    # Print standings
    standings = db.execute(sql_text(
        "SELECT name, short_name, current_position, games_played, games_won, games_drawn, games_lost, "
        "goals_for, goals_against, goal_difference, current_points FROM teams ORDER BY current_position"
    )).fetchall()
    for s in standings:
        print(f"  {s[2]:2d}. {s[0]:20s} P{s[3]:2d} W{s[4]:2d} D{s[5]:2d} L{s[6]:2d} GF{s[7]:3d} GA{s[8]:3d} GD{s[9]:+3d} Pts{s[10]:3d}")

# ============================================================
# 2. Populate gameweek_stats from player_gameweek_points
# ============================================================
def populate_gameweek_stats():
    print("\n=== 2. Populating gameweek_stats ===")

    existing = db.execute(sql_text("SELECT COUNT(*) FROM gameweek_stats")).scalar()
    if existing > 0:
        print(f"  Already has {existing} records, skipping")
        return

    # Insert into gameweek_stats from player_gameweek_points
    db.execute(sql_text("""
        INSERT INTO gameweek_stats (
            player_id, gameweek_id, points, goals, assists, clean_sheets, saves,
            bps, minutes_played, was_captain, yellow_cards, red_cards,
            penalty_missed, own_goals, defensive_contributions, influence,
            creativity, threat, timestamp
        )
        SELECT
            player_id,
            gameweek_id,
            COALESCE(total_points, 0),
            COALESCE(goals_scored, 0),
            COALESCE(assists, 0),
            CASE WHEN clean_sheet = 1 THEN 1 ELSE 0 END,
            COALESCE(saves, 0),
            COALESCE(bps_score, 0),
            COALESCE(minutes_played, 0),
            0,  -- was_captain (will be set later)
            CASE WHEN yellow_card = 1 THEN 1 ELSE 0 END,
            CASE WHEN red_card = 1 THEN 1 ELSE 0 END,
            CASE WHEN COALESCE(penalties_missed, 0) > 0 THEN 1 ELSE 0 END,
            CASE WHEN own_goal = 1 THEN 1 ELSE 0 END,
            COALESCE(defensive_contributions, 0),
            COALESCE(influence_gw, 0),
            COALESCE(creativity_gw, 0),
            COALESCE(threat_gw, 0),
            '2025-08-30'  -- timestamp placeholder
        FROM player_gameweek_points
    """))

    count = db.execute(sql_text("SELECT COUNT(*) FROM gameweek_stats")).scalar()
    print(f"  Created {count} gameweek_stats records")

# ============================================================
# 3. Calculate fantasy team scores for GW1-36
# ============================================================
def calculate_fantasy_team_scores():
    print("\n=== 3. Calculating fantasy team scores ===")

    # Get squad players
    squad = db.execute(sql_text("""
        SELECT sp.id as sp_id, sp.player_id, sp.is_captain, sp.is_vice_captain, sp.is_starting,
               p.name, p.position
        FROM squad_players sp
        JOIN players p ON sp.player_id = p.id
        WHERE sp.fantasy_team_id = 1
        ORDER BY sp.position_slot
    """)).fetchall()

    captain_id = None
    vice_captain_id = None
    for sp in squad:
        if sp[2]:  # is_captain
            captain_id = sp[1]  # player_id
        if sp[3]:  # is_vice_captain
            vice_captain_id = sp[1]

    print(f"  Captain: player_id={captain_id} ({[s[5] for s in squad if s[1]==captain_id]})")
    print(f"  Vice-captain: player_id={vice_captain_id}")

    # Get GW IDs
    gws = db.execute(sql_text("SELECT id, number FROM gameweeks ORDER BY number")).fetchall()

    season_total = 0

    for gw_id, gw_num in gws:
        # Get points for each squad player this GW
        gw_points = {}
        for sp in squad:
            player_id = sp[1]
            row = db.execute(sql_text("""
                SELECT COALESCE(total_points, 0) FROM player_gameweek_points
                WHERE player_id = :pid AND gameweek_id = :gid
            """), {"pid": player_id, "gid": gw_id}).fetchone()
            if row:
                gw_points[player_id] = row[0]

        # Calculate GW score
        starting_points = 0
        bench_points = 0

        for sp in squad:
            player_id = sp[1]
            is_starting = sp[4]
            base_pts = gw_points.get(player_id, 0)

            # Captain multiplier
            if player_id == captain_id:
                pts = base_pts * 2
            elif player_id == vice_captain_id:
                pts = base_pts
            else:
                pts = base_pts

            if is_starting:
                starting_points += pts
            else:
                bench_points += pts

        # FPL bench rounding (down to nearest 4)
        bench_points = max(0, (bench_points // 4) * 4)
        gw_total = starting_points + bench_points

        season_total += gw_total

        # Insert FantasyTeamHistory
        db.execute(sql_text("""
            INSERT INTO fantasy_team_history
            (fantasy_team_id, gameweek_id, points, total_points, chip_used, transfers_made, transfers_cost, entered)
            VALUES (:ftid, :gid, :pts, :tot, NULL, 0, 0, 1)
        """), {
            "ftid": 1, "gid": gw_id,
            "pts": gw_total, "tot": season_total
        })

        if gw_num % 10 == 0:
            print(f"  GW {gw_num:2d}: {gw_total:4d} pts (season: {season_total:5d})")

    # Update fantasy team total_points
    db.execute(sql_text("""
        UPDATE fantasy_teams SET total_points = :pts WHERE id = 1
    """), {"pts": season_total})

    # Update squad player cumulative points
    for sp in squad:
        player_id = sp[1]
        total = db.execute(sql_text("""
            SELECT COALESCE(SUM(total_points), 0) FROM player_gameweek_points
            WHERE player_id = :pid
        """), {"pid": player_id}).scalar()
        db.execute(sql_text("""
            UPDATE squad_players SET total_points = :pts
            WHERE fantasy_team_id = 1 AND player_id = :pid
        """), {"pts": total, "pid": player_id})

    db.flush()
    print(f"\n  Season total: {season_total} pts")

# ============================================================
# 4. Generate transfer history
# ============================================================
def generate_transfer_history():
    print("\n=== 4. Generating transfer history ===")

    all_players = db.execute(sql_text("""
        SELECT id, name, position, team_id, price FROM players WHERE is_active = 1
    """)).fetchall()

    # Generate transfers: ~1 per GW on average, wildcard in GW3
    transfers_made = 0
    for gw_num in range(1, 36):
        is_wildcard = (gw_num == 3)

        if gw_num == 3:
            num_transfers = random.randint(5, 8)
        elif gw_num in [8, 12, 18, 24, 30]:
            num_transfers = random.randint(2, 3)
        else:
            num_transfers = random.randint(0, 1)

        for _ in range(num_transfers):
            # Pick random player out (not from squad) and random player in
            current_squad = db.execute(sql_text("""
                SELECT sp.player_id, p.team_id FROM squad_players sp
                JOIN players p ON sp.player_id = p.id
                WHERE sp.fantasy_team_id = 1
            """)).fetchall()

            if not current_squad:
                break

            out_player_id = random.choice(current_squad)[0]
            out_team_id = random.choice(current_squad)[1]

            # Find a player not in squad
            available = db.execute(sql_text("""
                SELECT p.id FROM players p
                WHERE p.is_active = 1 AND p.id NOT IN (
                    SELECT sp.player_id FROM squad_players sp WHERE sp.fantasy_team_id = 1
                )
                LIMIT 50
            """)).fetchall()

            if not available:
                break

            in_player_id = random.choice(available)[0]
            in_row = db.execute(sql_text("SELECT team_id, price FROM players WHERE id = :id"),
                              {"id": in_player_id}).fetchone()
            in_team_id = in_row[0]

            # Insert transfer record
            ts = datetime(2025, 8, 30) + timedelta(days=gw_num * 7, hours=random.randint(0, 23))
            db.execute(sql_text("""
                INSERT INTO transfers
                (user_id, gameweek_id, player_in_id, player_out_id, is_wildcard, is_free_hit, created_at)
                VALUES (1, :gid, :pin, :pout, :wc, 0, :ts)
            """), {
                "gid": gw_num, "pin": in_player_id, "pout": out_player_id,
                "wc": 1 if is_wildcard else 0, "ts": ts
            })

            # Update squad: swap players
            db.execute(sql_text("""
                UPDATE squad_players SET player_id = :pin,
                    position_slot = (SELECT position_slot FROM squad_players WHERE player_id = :pout AND fantasy_team_id = 1)
                WHERE player_id = :pout AND fantasy_team_id = 1
            """), {"pin": in_player_id, "pout": out_player_id})

            transfers_made += 1

    db.flush()
    total = db.execute(sql_text("SELECT COUNT(*) FROM transfers WHERE user_id = 1")).scalar()
    print(f"  Generated {total} transfers")

# ============================================================
# 5. Create chip usage records
# ============================================================
def create_chip_usage():
    print("\n=== 5. Creating chip usage ===")

    chips = [
        ('wildcard', 3),
        ('bench_boost', 20),
        ('free_hit', 28),
    ]

    for chip_type, gw_num in chips:
        ts = datetime(2025, 8, 30) + timedelta(days=gw_num * 7)
        db.execute(sql_text("""
            INSERT INTO chips (team_id, chip_type, gameweek_id, status, timestamp)
            VALUES (1, :ctype, :gid, 'used', :ts)
        """), {"ctype": chip_type, "gid": gw_num, "ts": ts})

        # Update fantasy_team_history with chip_used
        gw_id = db.execute(sql_text("SELECT id FROM gameweeks WHERE number = :n"), {"n": gw_num}).scalar()
        db.execute(sql_text("""
            UPDATE fantasy_team_history SET chip_used = :ctype
            WHERE fantasy_team_id = 1 AND gameweek_id = :gid
        """), {"ctype": chip_type, "gid": gw_id})

    # Update fantasy_team chip flags
    db.execute(sql_text("""
        UPDATE fantasy_teams SET
            wildcard_first_half = 1,
            bench_boost_second_half = 1,
            free_hit_second_half = 1
        WHERE id = 1
    """))

    print("  Used: Wildcard (GW3), Bench Boost (GW20), Free Hit (GW28)")
    print("  Remaining: Wildcard (2nd half), Free Hit (1st half), Triple Captain (both)")

# ============================================================
# 6. Generate player price history
# ============================================================
def generate_player_price_history():
    print("\n=== 6. Generating player price history ===")

    players = db.execute(sql_text("SELECT id, price FROM players WHERE is_active = 1")).fetchall()
    total_records = 0

    for player_id, current_price in players:
        # Get GW points sorted by gameweek
        gw_points = db.execute(sql_text("""
            SELECT gp.gameweek_id, COALESCE(gp.total_points, 0)
            FROM player_gameweek_points gp
            JOIN gameweeks g ON gp.gameweek_id = g.id
            WHERE gp.player_id = :pid
            ORDER BY g.number
        """), {"pid": player_id}).fetchall()

        price = current_price
        for gw_id, pts in gw_points[:35]:
            old_price = price

            # Price changes based on performance
            if pts >= 15:
                price = round(price + 0.1, 1)
            elif pts == 0:
                price = round(price - 0.1, 1)

            price = max(1.0, min(15.0, price))

            if price != old_price:
                ts = datetime(2025, 8, 30) + timedelta(days=gw_id * 7)
                db.execute(sql_text("""
                    INSERT INTO player_price_history (player_id, old_price, new_price, gameweek_id, timestamp)
                    VALUES (:pid, :op, :np, :gid, :ts)
                """), {"pid": player_id, "op": old_price, "np": price, "gid": gw_id, "ts": ts})
                total_records += 1

        # Update player price
        if gw_points:
            db.execute(sql_text("""
                UPDATE players SET price = :p, price_change_total = :change
                WHERE id = :pid
            """), {"p": price, "change": round((price - current_price) * 10), "pid": player_id})

    db.flush()
    print(f"  Created {total_records} price change records")

# ============================================================
# 7. Update player season totals and stats
# ============================================================
def update_player_stats():
    print("\n=== 7. Updating player season stats ===")

    db.execute(sql_text("""
        UPDATE players SET
            total_points_season = (
                SELECT COALESCE(SUM(pg.total_points), 0)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id
            ),
            goals = (
                SELECT COALESCE(SUM(pg.goals_scored), 0)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id
            ),
            assists = (
                SELECT COALESCE(SUM(pg.assists), 0)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id
            ),
            clean_sheets = (
                SELECT COUNT(*)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id AND pg.clean_sheet = 1
            ),
            saves = (
                SELECT COALESCE(SUM(pg.saves), 0)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id
            ),
            minutes_played = (
                SELECT COALESCE(SUM(pg.minutes_played), 0)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id
            ),
            yellow_cards = (
                SELECT COUNT(*)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id AND pg.yellow_card = 1
            ),
            red_cards = (
                SELECT COUNT(*)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id AND pg.red_card = 1
            ),
            apps = (
                SELECT COUNT(*)
                FROM player_gameweek_points pg
                WHERE pg.player_id = players.id AND pg.did_play = 1
            )
        WHERE is_active = 1
    """))

    # Update ICT index
    db.execute(sql_text("""
        UPDATE players SET
            influence = (
                SELECT COALESCE(SUM(pg.influence_gw), 0)
                FROM player_gameweek_points pg WHERE pg.player_id = players.id
            ),
            creativity = (
                SELECT COALESCE(SUM(pg.creativity_gw), 0)
                FROM player_gameweek_points pg WHERE pg.player_id = players.id
            ),
            threat = (
                SELECT COALESCE(SUM(pg.threat_gw), 0)
                FROM player_gameweek_points pg WHERE pg.player_id = players.id
            ),
            ict_index = (
                SELECT ROUND(
                    (COALESCE(SUM(pg.influence_gw), 0) +
                     COALESCE(SUM(pg.creativity_gw), 0) +
                     COALESCE(SUM(pg.threat_gw), 0)) / 10, 1
                )
                FROM player_gameweek_points pg WHERE pg.player_id = players.id
            )
        WHERE is_active = 1
    """))

    # Update form (last 5 GWs average)
    db.execute(sql_text("""
        UPDATE players SET form = (
            SELECT ROUND(AVG(sub.total_points), 1) FROM (
                SELECT gp.total_points
                FROM player_gameweek_points gp
                JOIN gameweeks g ON gp.gameweek_id = g.id
                WHERE gp.player_id = players.id
                ORDER BY g.number DESC
                LIMIT 5
            ) sub
        ) WHERE is_active = 1
    """))

    db.flush()

    # Print top players
    top = db.execute(sql_text("""
        SELECT name, position, total_points_season, form, goals, assists, price
        FROM players WHERE is_active = 1
        ORDER BY total_points_season DESC LIMIT 10
    """)).fetchall()
    print("  Top 10 players by season points:")
    for p in top:
        print(f"    {p[0]:30s} ({p[1]}) {p[2]:4d} pts  form={p[3]:5.1f}  {p[4]:3d}g {p[5]:3d}a  {p[6]:.1f}m")

    print(f"  Updated player stats")

# ============================================================
# 8. Set current gameweek and update season config
# ============================================================
def set_current_state():
    print("\n=== 8. Setting current gameweek state ===")

    # Update season
    db.execute(sql_text("""
        UPDATE seasons SET total_gameweeks = 38, first_half_cutoff = 19,
            second_half_cutoff = 38, started = 1, finished = 0
        WHERE name = '2025-26'
    """))

    # Mark GW1-35 as scored/closed
    db.execute(sql_text("""
        UPDATE gameweeks SET scored = 1, closed = 1, bonus_calculated = 1, chip_processing_done = 1
        WHERE number <= 35
    """))

    # Mark GW36 as current (not scored)
    db.execute(sql_text("""
        UPDATE gameweeks SET scored = 0, closed = 0, bonus_calculated = 0, chip_processing_done = 0
        WHERE number = 36
    """))

    # Mark GW37-38 as future (not scored, not closed)
    db.execute(sql_text("""
        UPDATE gameweeks SET scored = 0, closed = 0, bonus_calculated = 0, chip_processing_done = 0
        WHERE number > 36
    """))

    # Update fantasy team budget
    budget_used = db.execute(sql_text("""
        SELECT COALESCE(SUM(sp.purchase_price), 0)
        FROM squad_players sp WHERE sp.fantasy_team_id = 1
    """)).scalar()
    db.execute(sql_text("""
        UPDATE fantasy_teams SET budget_remaining = 100.0 - :used WHERE id = 1
    """), {"used": budget_used})

    # Update fantasy team rank
    total_pts = db.execute(sql_text("SELECT total_points FROM fantasy_teams WHERE id = 1")).scalar()
    # Estimate rank: higher total = lower rank number
    # Assume ~10000 fantasy managers, average ~35pts/GW * 36 = 1260
    if total_pts and total_pts > 0:
        rank = max(1, int(10000 * (1260 / total_pts)))
        db.execute(sql_text("UPDATE fantasy_teams SET overall_rank = :r WHERE id = 1"), {"r": rank})

    # Update fantasy team history ranks
    history = db.execute(sql_text("""
        SELECT id, total_points FROM fantasy_team_history WHERE fantasy_team_id = 1 ORDER BY gameweek_id
    """)).fetchall()
    for hid, tot_pts in history:
        if tot_pts and tot_pts > 0:
            r = max(1, int(10000 * (1260 / tot_pts)))
            db.execute(sql_text(
                "UPDATE fantasy_team_history SET rank = :r, point_rank = :r, rank_sort_index = :ri, point_rank_sort_index = :ri WHERE id = :hid"
            ), {"r": r, "ri": tot_pts, "hid": hid})

    # Update transfers_made in history
    transfer_gws = db.execute(sql_text("""
        SELECT gameweek_id, COUNT(*) as cnt FROM transfers
        WHERE user_id = 1 GROUP BY gameweek_id
    """)).fetchall()
    for gw_id, cnt in transfer_gws:
        db.execute(sql_text("""
            UPDATE fantasy_team_history SET transfers_made = :cnt, transferred_in = :cnt, transferred_out = :cnt
            WHERE fantasy_team_id = 1 AND gameweek_id = :gid
        """), {"cnt": cnt, "gid": gw_id})

    db.flush()

    # Print summary
    current = db.execute(sql_text(
        "SELECT id, number, start_date, scored, closed FROM gameweeks WHERE number = 36"
    )).fetchone()
    print(f"  Current GW: {current[1]} (id={current[0]}, start={current[2]}, scored={current[3]}, closed={current[4]})")

    ft = db.execute(sql_text(
        "SELECT name, total_points, overall_rank, budget_remaining, wildcard_first_half, bench_boost_second_half, free_hit_second_half FROM fantasy_teams WHERE id = 1"
    )).fetchone()
    print(f"  Fantasy Team: {ft[0]} - {ft[1]} pts, rank={ft[2]}, budget={ft[3]:.1f}m")
    print(f"  Chips: WC1H={ft[4]}, BB2H={ft[5]}, FH2H={ft[6]}")

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("Fantasy Football Isle of Man - Season Backfill")
    print("=" * 50)

    try:
        update_team_standings()
        populate_gameweek_stats()
        calculate_fantasy_team_scores()
        generate_transfer_history()
        create_chip_usage()
        generate_player_price_history()
        update_player_stats()
        set_current_state()

        db.commit()
        print("\n" + "=" * 50)
        print("Season backfill complete! GW1-35 scored, GW36 active.")
    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()
