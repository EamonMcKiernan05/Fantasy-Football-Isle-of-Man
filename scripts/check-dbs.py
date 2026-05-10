#!/usr/bin/env python3
"""Check current state of both databases."""
import sqlite3

GAME_DB = "/home/eamon/Fantasy-Football-Isle-of-Man/data/fantasy_iom.db"
FFIOM_DB = "/home/eamon/FFIOM-DB/data/fantasy_iom.db"

def check_db(path, label):
    print(f"\n{'='*60}")
    print(f"{label}: {path}")
    print(f"{'='*60}")
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM [{t}]')
        cnt = cur.fetchone()[0]
        cols = [c[1] for c in cur.execute(f'PRAGMA table_info([{t}])').fetchall()]
        print(f"  {t}: {cnt} rows | cols: {', '.join(cols[:10])}{'...' if len(cols) > 10 else ''}")
    conn.close()

check_db(GAME_DB, "GAME DB")
check_db(FFIOM_DB, "FFIOM-DB")
