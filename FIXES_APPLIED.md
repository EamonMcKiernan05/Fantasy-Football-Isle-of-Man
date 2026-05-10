# Fixes Applied

## 1. Rankings Page - Position Filter (CRITICAL)

**Problem:** Rankings page was empty because both backend and frontend filtered out players without positions.

**Backend Fix (app/routes/players.py):**
- Changed query from `Player.position.isnot(None)` to just `Player.is_active == True`
- Players without positions are now included in rankings

**Frontend Fix (static/js/app.js):**
- Removed `filter(p => p.position)` from both `loadRankings()` and `handleRankingsSort()`
- Added position filter dropdown to rankings page (static/index.html)
- Updated `loadRankings()` and `handleRankingsSort()` to pass position parameter to backend

## 2. Fixtures - Null Difficulty Badges

**Problem:** Fixtures showed "null" text for difficulty badges when difficulty wasn't set.

**Fix (static/js/app.js):**
- Added null check before rendering difficulty badges
- Only renders badge if `f.home_difficulty` or `f.away_difficulty` is truthy

## 3. Gameweeks - Sync Fixtures Button

**Problem:** Sync Fixtures button showed error "'NoneType' object is not callable" due to BoundSessionLocal being None.

**Frontend Fix (static/js/app.js):**
- Changed `syncGameweeks()` to check `data.status === 'completed'` instead of `r.ok`
- Now properly shows error messages from the backend

**Backend Fix (app/scheduler.py):**
- Changed `sync_fixtures()` to import `BoundSessionLocal` lazily inside the function
- This ensures the database module is fully initialized before using BoundSessionLocal

## 4. Transfers - Sub 3 Button (Empty Bench Slots)

**Problem:** Clicking empty bench slots ("Sub 1", "Sub 2", "Sub 3") did nothing when squad had < 13 players.

**Fix (static/js/app.js):**
- Updated `scrollToPlayerList()` to wait for `loadTransferPlayers()` if cache is empty
- Now properly auto-adds the cheapest available player when clicking empty bench slots

## Testing

Test the sync endpoint:
```bash
cd /home/eamon/Fantasy-Football-Isle-of-Man && python3 test_sync.py
```

Expected response: `{"status": "completed", "message": "Fixtures synced and scores updated"}`
