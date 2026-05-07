#!/usr/bin/env python3
"""Add missing chip half-usage columns to fantasy_teams table.

Run after adding the columns to the FantasyTeam model.
Idempotent — safe to run multiple times.
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fantasy_iom.db")

COLUMNS = [
    "wildcard_first_half BOOLEAN DEFAULT 0",
    "wildcard_second_half BOOLEAN DEFAULT 0",
    "free_hit_first_half BOOLEAN DEFAULT 0",
    "free_hit_second_half BOOLEAN DEFAULT 0",
    "bench_boost_first_half BOOLEAN DEFAULT 0",
    "bench_boost_second_half BOOLEAN DEFAULT 0",
    "triple_captain_first_half BOOLEAN DEFAULT 0",
    "triple_captain_second_half BOOLEAN DEFAULT 0",
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(fantasy_teams)")
    existing = {row[1] for row in cursor.fetchall()}

    added = []
    for col_def in COLUMNS:
        col_name = col_def.split()[0]
        if col_name not in existing:
            print(f"Adding column: {col_name}")
            cursor.execute(f"ALTER TABLE fantasy_teams ADD COLUMN {col_name}")
            added.append(col_name)

    if added:
        # Copy values from _used flags to half columns
        for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
            cursor.execute(
                f"UPDATE fantasy_teams SET "
                f"{chip}_first_half = COALESCE({chip}_first_half, 0) OR COALESCE({chip}_used, 0), "
                f"{chip}_second_half = COALESCE({chip}_second_half, 0) OR COALESCE({chip}_used, 0) "
                f"WHERE {chip}_used = 1"
            )

        conn.commit()
        print(f"Migrated {len(added)} columns successfully.")
    else:
        print("All columns already exist. Nothing to do.")

    conn.close()

if __name__ == "__main__":
    main()
