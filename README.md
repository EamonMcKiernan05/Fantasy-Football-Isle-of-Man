# Fantasy Football Isle of Man

FPL-style fantasy football for the **Canada Life Premier League**.

Built with FastAPI, SQLite, and vanilla JavaScript. Data sourced from the [FullTime API](https://github.com/jwhughes-work/FullTimeAPI) (unofficial FA FullTime scraper).

## Features

- **FPL-Style Scoring**: Team-level points based on match results, goals, and clean sheets
- **Weekly Deadlines**: Team deadline every Saturday at 11:00 AM
- **Captain System**: Choose a captain each week for 2x points
- **Transfers**: Swap teams in and out of your squad
- **Live Data**: Auto-syncs fixtures, results, and league tables from FullTime API


## Setup

```bash
# Clone and enter
cd Fantasy-Football-Isle-of-Man

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env

# Run
python run.py
```

The app will be available at `http://localhost:8000`.

## API Endpoints

### Teams
- `GET /api/teams/` - List all IOM league teams
- `GET /api/teams/refresh` - Refresh team data from FullTime API
- `GET /api/teams/divisions` - List divisions with teams

### Users
- `POST /api/users/register` - Register a new manager
- `GET /api/users/{id}/team` - Get fantasy team
- `POST /api/users/{id}/team/create` - Create fantasy team (random squad)
- `PUT /api/users/{id}/team/captain` - Set captain/vice-captain
- `PUT /api/users/{id}/team/transfer` - Make a transfer

### Gameweeks
- `GET /api/gameweeks/` - List all gameweeks
- `GET /api/gameweeks/{id}` - Get gameweek with fixtures
- `GET /api/gameweeks/current` - Get current active gameweek
- `GET /api/gameweeks/{id}/score/{user_id}` - Get user's gameweek score
- `POST /api/gameweeks/sync` - Sync fixtures from FullTime API

### Leaderboard
- `GET /api/leaderboard/` - Overall leaderboard
- `GET /api/leaderboard/gameweek/{id}` - Gameweek-specific leaderboard

## Architecture

```
Fantasy-Football-Isle-of-Man/
├── app/
│   ├── main.py           # FastAPI application
│   ├── database.py        # SQLAlchemy setup
│   ├── models.py          # Database models
│   ├── schemas.py         # Pydantic schemas
│   ├── api_client.py      # FullTime API client
│   ├── scoring.py         # FPL scoring engine
│   ├── scheduler.py       # APScheduler tasks
│   └── routes/            # API routes
├── static/
│   ├── index.html         # Main SPA
│   ├── css/style.css      # Styles
│   └── js/app.js          # Frontend logic
├── data/                  # SQLite database
├── requirements.txt
└── run.py                 # Entry point
```

## Notes

- The FullTime API has an expired SSL certificate - requests use `verify=False`
- Individual player stats are not available for IOM leagues, so scoring is team-based
- The API scrapes `fulltime.thefa.com` - data availability depends on league secretaries updating results
- SSL warnings are suppressed to work around the expired certificate

## License

MIT
