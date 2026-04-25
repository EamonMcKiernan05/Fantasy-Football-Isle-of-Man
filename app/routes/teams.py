"""Teams API routes - fetch and manage IOM league teams."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Team, Division, League
from app.schemas import TeamResponse, DivisionResponse
from app import api_client

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("/refresh")
def refresh_teams(db: Session = Depends(get_db)):
    """Refresh team data from FullTime API for all divisions."""
    client = api_client.FullTimeAPIClient()
    divisions = client.get_league_divisions()
    
    # Ensure league exists
    league = db.query(League).filter(League.ft_id == api_client.FullTimeAPIClient.IOM_LEAGUE_ID).first()
    if not league:
        league = League(
            ft_id=api_client.FullTimeAPIClient.IOM_LEAGUE_ID,
            name="Isle of Man Senior Men's Leagues",
        )
        db.add(league)
    
    updated = 0
    for div_data in divisions:
        div_id = div_data["id"]
        div_name = div_data["name"]
        
        # Ensure division exists
        division = db.query(Division).filter(Division.ft_id == div_id).first()
        if not division:
            division = Division(
                ft_id=div_id,
                name=div_name,
                league_id=league.id,
            )
            db.add(division)
        
        # Get league table
        table = client.get_league_table(div_id)
        
        for entry in table:
            team_name = entry["teamName"]
            
            # Find or create team
            team = db.query(Team).filter(
                Team.name == team_name,
                Team.division_id == division.id,
            ).first()
            
            if not team:
                team = Team(
                    name=team_name,
                    division_id=division.id,
                    short_name=team_name.replace(" First", "").replace(" Combination", ""),
                    current_position=entry.get("position"),
                    current_points=entry.get("points"),
                    games_played=entry.get("gamesPlayed"),
                    games_won=entry.get("gamesWon"),
                    games_drawn=entry.get("gamesDrawn"),
                    games_lost=entry.get("gamesLost"),
                    goal_difference=entry.get("goalDifference"),
                )
                db.add(team)
                updated += 1
            else:
                # Update stats
                team.current_position = entry.get("position")
                team.current_points = entry.get("points")
                team.games_played = entry.get("gamesPlayed")
                team.games_won = entry.get("gamesWon")
                team.games_drawn = entry.get("gamesDrawn")
                team.games_lost = entry.get("gamesLost")
                team.goal_difference = entry.get("goalDifference")
                updated += 1
        
        db.commit()
    
    return {"status": "success", "teams_updated": updated, "divisions": len(divisions)}


@router.get("/divisions")
def list_divisions(db: Session = Depends(get_db)):
    """List all divisions with their teams."""
    divisions = db.query(Division).order_by(Division.name).all()
    result = []
    for div in divisions:
        teams = db.query(Team).filter(
            Team.division_id == div.id
        ).order_by(Team.current_position).all()
        result.append({
            "id": div.id,
            "ft_id": div.ft_id,
            "name": div.name,
            "teams": [
                {
                    "id": t.id,
                    "name": t.name,
                    "position": t.current_position,
                    "points": t.current_points,
                    "games_played": t.games_played,
                }
                for t in teams
            ],
        })
    return result


@router.get("/", response_model=List[TeamResponse])
def list_teams(
    division_id: int = Query(None, description="Filter by division ID"),
    db: Session = Depends(get_db),
):
    """List all IOM league teams."""
    query = db.query(Team)
    if division_id:
        query = query.filter(Team.division_id == division_id)
    return query.order_by(Team.name).all()


@router.get("/{team_id}", response_model=TeamResponse)
def get_team(team_id: int, db: Session = Depends(get_db)):
    """Get a specific team."""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team
