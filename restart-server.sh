#!/bin/bash
pkill -9 -f uvicorn 2>/dev/null
sleep 2
cd /home/eamon/Fantasy-Football-Isle-of-Man
source venv/bin/activate 2>/dev/null
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
