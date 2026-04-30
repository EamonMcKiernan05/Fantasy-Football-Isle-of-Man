#!/usr/bin/env python3
"""Migration: Replace 2x-per-half chip flags with 1x-per-season flags.

Old columns (per chip): _first_half, _second_half
New columns (per chip): _used
"""
import sys
sys.path.insert(0, "/home/eamon/Fantasy-Football-Isle-of-Man")

from app.database import engine
from sqlalchemy import text

def migrate():
    # Check if old columns exist (SQLite pragma)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(fantasy_teams)"))
        columns = [row[1] for row in result.fetchall()]

    if "wildcard_first_half" not in columns:
        print("Old chip columns not found - already migrated or schema mismatch.")
        return

    print(f"Current fantasy_teams columns: {columns}")

    # Check SQLite version
    with engine.connect() as conn:
        version = conn.execute(text("SELECT sqlite_version()"))
        ver = version.fetchone()[0]
        major, minor = map(int, ver.split(".")[:2])

    print(f"SQLite version: {ver}")
    can_drop = major > 3 or (major == 3 and minor >= 35)

    # For each chip, add new _used column and copy data
    for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
        with engine.connect() as conn:
            if f"{chip}_used" not in columns:
                conn.execute(text(f"ALTER TABLE fantasy_teams ADD COLUMN {chip}_used BOOLEAN DEFAULT 0"))
                conn.commit()
                print(f"  {chip}: added {chip}_used column")

            # Copy data
            conn.execute(text(f"""
                UPDATE fantasy_teams SET {chip}_used = 1
                WHERE {chip}_first_half = 1 OR {chip}_second_half = 1
            """))
            conn.commit()
            print(f"  {chip}: copied data from old columns")

    # Drop old columns if SQLite supports it
    if can_drop:
        for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
            for suffix in ["_first_half", "_second_half"]:
                col = f"{chip}{suffix}"
                with engine.connect() as conn:
                    try:
                        conn.execute(text(f"ALTER TABLE fantasy_teams DROP COLUMN {col}"))
                        conn.commit()
                        print(f"  Dropped {col}")
                    except Exception as e:
                        print(f"  Warning dropping {col}: {e}")
    else:
        print("SQLite version too old for DROP COLUMN - old columns retained (harmless)")
        print("They will be ignored by the new code which reads *_used columns")

    print("Migration complete!")

if __name__ == "__main__":
    migrate()
