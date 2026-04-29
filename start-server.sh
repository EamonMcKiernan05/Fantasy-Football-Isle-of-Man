#!/bin/bash
cd ~/Fantasy-Football-Isle-of-Man
source venv/bin/activate
pkill -f "python run.py" 2>/dev/null
sleep 1
setsid python run.py > ~/fantasy-iom.log 2>&1 &
disown
echo "Server started on http://0.0.0.0:8000"
echo "Logs at ~/fantasy-iom.log"
