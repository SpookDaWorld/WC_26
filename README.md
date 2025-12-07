# World Cup 2026 Tournament Scorer

A Flask web application for tracking and scoring the FIFA World Cup 2026 tournament. This is a conversion of the original Tkinter desktop application to a multi-user web interface.

## Features

- **Dashboard**: Overview of tournament status, top teams, and quick actions
- **Leaderboard**: Full standings with filtering by active/eliminated teams
- **Match Recording**: Record wins and draws with automatic point calculations
- **Match History**: Complete history of all recorded matches
- **Tournament Bracket**: Visual bracket for knockout stages
- **Statistics**: Charts and analytics by team and confederation
- **User Competition**: Pick 3-4 teams and compete with friends based on combined scores

## Installation

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python app.py
   ```

3. **Open in browser**:
   Navigate to `http://localhost:5000`

## How the Scoring System Works

### Point Values
- Each team starts with a point value based on their FIFA ranking
- Top-ranked teams have higher point values (e.g., Spain starts with 48 points)
- Lower-ranked teams have lower point values (minimum 2 points)

### Scoring Matches
- **Wins**: The winner earns points equal to the loser's current point value
- **Draws** (Group Stage only): Each team earns half of the opponent's point value
- **Knockout Rounds**: Winner takes the loser's point value for future matches

### Tournament Flow
1. **Group Stage**: Record all group matches (wins and draws allowed)
2. **Advance to Knockout**: Select teams that qualify for Round of 32
3. **Knockout Rounds**: Only wins allowed, losers are eliminated
4. **Finals**: Track through Semi-finals, Third Place, and Final

## Project Structure

```
wc2026/
├── app.py              # Main Flask application with routes and logic
├── requirements.txt    # Python dependencies
├── data/
│   ├── fifa_2025.csv   # FIFA world rankings
│   └── qualified.csv   # Qualified teams with confederations
├── templates/
│   ├── base.html           # Base template with navigation
│   ├── index.html          # Dashboard
│   ├── leaderboard.html    # Full standings
│   ├── record_match.html   # Match recording form
│   ├── match_history.html  # Match history list
│   ├── bracket.html        # Tournament bracket
│   ├── statistics.html     # Charts and stats
│   ├── team_detail.html    # Individual team page
│   ├── user_competition.html   # User team selection
│   └── advance_knockout.html   # Team advancement selection
└── static/
    ├── css/
    ├── js/
    └── images/
```

## API Endpoints

- `GET /api/teams` - All teams with full details
- `GET /api/leaderboard?active_only=true&top_n=10` - Filtered leaderboard
- `GET /api/match-history` - Match history as JSON
- `POST /api/create-selection` - Create user team selection

## Updating Qualified Teams

When the final 6 teams qualify in March 2026, update `data/qualified.csv` with the new teams. Make sure country names match exactly with `data/fifa_2025.csv`.

## Admin Actions

- **Change Round**: Manually set the current tournament round
- **Advance to Knockout**: Transition from group stage, eliminating non-advancing teams
- **Undo Last Match**: Reverse the most recent match result
- **Reset Tournament**: Clear all data and reinitialize from CSVs

## Technologies

- **Backend**: Flask, SQLAlchemy, SQLite
- **Frontend**: Jinja2 templates, vanilla JavaScript
- **Charts**: Chart.js
- **Styling**: Custom CSS with CSS variables

## Future Enhancements

- User authentication for team selections
- Real-time updates with WebSockets
- More detailed bracket visualization
- Export/import tournament state
- Mobile-optimized responsive design
