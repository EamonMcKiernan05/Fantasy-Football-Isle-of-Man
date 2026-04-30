#!/usr/bin/env bash
# git-push-db.sh — Commit and push database changes to GitHub
# Called after DB updates (fetch-and-score, scoring scripts, etc.)
set -e

cd "$(dirname "$0")/.."

# Only push if DB has changed
if git diff --quiet HEAD -- data/fantasy_iom.db 2>/dev/null || git diff --cached --quiet -- data/fantasy_iom.db 2>/dev/null; then
    echo "No DB changes to push"
    exit 0
fi

git add data/fantasy_iom.db
git commit -m "Auto-update: database snapshot $(date +%Y-%m-%d\ %H:%M)"
git push origin main 2>/dev/null || git push origin master 2>/dev/null || true
echo "Database pushed to GitHub"
