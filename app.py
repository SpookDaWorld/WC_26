"""
World Cup 2026 Tournament Scorer - Flask Application
Adapted from the original Tkinter application
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import numpy as np
import pandas as pd
import os
import json

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'wc2026-dev-key-change-in-production')

# Database configuration
# Priority: DATABASE_URL (PostgreSQL) > RENDER_DISK (persistent SQLite) > local SQLite
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # PostgreSQL - Render uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
elif os.path.exists('/var/data'):
    # Render persistent disk
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////var/data/tournament.db'
else:
    # Local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tournament.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Admin password - set via environment variable in production
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'wc2026admin')

db = SQLAlchemy(app)


# ----------------------------------------------------
# ADMIN AUTHENTICATION
# ----------------------------------------------------

from functools import wraps

def admin_required(f):
    """Decorator to require admin login for protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access admin features', 'error')
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# ----------------------------------------------------
# DATABASE MODELS
# ----------------------------------------------------

class Team(db.Model):
    """Team model storing all team information"""
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(100), unique=True, nullable=False)
    fifa_rank = db.Column(db.Integer)
    tournament_rank = db.Column(db.Integer)
    confederation = db.Column(db.String(20))
    group = db.Column(db.String(1))  # Group A-L
    base_points = db.Column(db.Integer)
    current_points = db.Column(db.Float)  # Float to support half points from draws
    total_score = db.Column(db.Float, default=0.0)
    wins = db.Column(db.Integer, default=0)
    draws = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    eliminated = db.Column(db.Boolean, default=False)
    elimination_round = db.Column(db.String(50), default='')
    
    @property # Need to update with the final 6 teams once they qualify so that the flags all in there
    def flag_code(self):
        """Return ISO country code for flag display"""
        country_codes = {
            'United States': 'us',
            'Canada': 'ca',
            'Mexico': 'mx',
            'Argentina': 'ar',
            'Brazil': 'br',
            'Uruguay': 'uy',
            'Colombia': 'co',
            'Ecuador': 'ec',
            'Paraguay': 'py',
            'Spain': 'es',
            'England': 'gb-eng',
            'France': 'fr',
            'Germany': 'de',
            'Portugal': 'pt',
            'Netherlands': 'nl',
            'Belgium': 'be',
            'Switzerland': 'ch',
            'Croatia': 'hr',
            'Austria': 'at',
            'Norway': 'no',
            'Scotland': 'gb-sct',
            'Japan': 'jp',
            'Australia': 'au',
            'Iran': 'ir',
            'South Korea': 'kr',
            'Saudi Arabia': 'sa',
            'Qatar': 'qa',
            'Jordan': 'jo',
            'Uzbekistan': 'uz',
            'Morocco': 'ma',
            'Senegal': 'sn',
            'Egypt': 'eg',
            'Algeria': 'dz',
            'Tunisia': 'tn',
            "Côte d'Ivoire": 'ci',
            'South Africa': 'za',
            'Ghana': 'gh',
            'Cabo Verde': 'cv',
            'Panama': 'pa',
            'Curacao': 'cw',
            'Haiti': 'ht',
            'New Zealand': 'nz',
        }
        return country_codes.get(self.country, 'un')
    
    def to_dict(self):
        return {
            'id': self.id,
            'country': self.country,
            'fifa_rank': self.fifa_rank,
            'tournament_rank': self.tournament_rank,
            'confederation': self.confederation,
            'group': self.group,
            'base_points': self.base_points,
            'current_points': self.current_points,
            'total_score': self.total_score,
            'wins': self.wins,
            'draws': self.draws,
            'losses': self.losses,
            'eliminated': self.eliminated,
            'elimination_round': self.elimination_round,
            'flag_code': self.flag_code
        }


class Match(db.Model):
    """Match history model"""
    id = db.Column(db.Integer, primary_key=True)
    match_number = db.Column(db.Integer)
    match_type = db.Column(db.String(10))  # 'win' or 'draw'
    round_name = db.Column(db.String(50))
    team1_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    team2_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    winner_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    points_earned = db.Column(db.Float)
    team1_earned = db.Column(db.Float, nullable=True)
    team2_earned = db.Column(db.Float, nullable=True)
    # Match scores
    team1_score = db.Column(db.Integer, nullable=True)  # Goals scored by team1
    team2_score = db.Column(db.Integer, nullable=True)  # Goals scored by team2
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    team1 = db.relationship('Team', foreign_keys=[team1_id], backref='matches_as_team1')
    team2 = db.relationship('Team', foreign_keys=[team2_id], backref='matches_as_team2')
    winner = db.relationship('Team', foreign_keys=[winner_id], backref='matches_won')
    
    @property
    def score_display(self):
        """Return formatted score string like '2-1' or None if no score"""
        if self.team1_score is not None and self.team2_score is not None:
            return f"{self.team1_score}-{self.team2_score}"
        return None

class TournamentState(db.Model):
    """Stores global tournament state"""
    id = db.Column(db.Integer, primary_key=True)
    current_round = db.Column(db.String(50), default='Group Stage')
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)


class UserTeamSelection(db.Model):
    """User's team selections for competition"""
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Store team IDs as JSON array
    team_ids = db.Column(db.Text)  # JSON string of team IDs
    
    def get_teams(self):
        if self.team_ids:
            ids = json.loads(self.team_ids)
            return Team.query.filter(Team.id.in_(ids)).all()
        return []
    
    def set_teams(self, teams):
        self.team_ids = json.dumps([t.id for t in teams])
    
    def get_total_score(self):
        teams = self.get_teams()
        return sum(t.total_score for t in teams)


# ----------------------------------------------------
# TOURNAMENT LOGIC
# ----------------------------------------------------

ROUNDS = ["Group Stage", "Round of 32", "Round of 16", "Quarter-finals", 
          "Semi-finals", "Third Place", "Final"]

# Maximum active teams allowed for each round
ROUND_TEAM_LIMITS = {
    "Group Stage": 48,      # All teams active
    "Round of 32": 32,      # 32 teams advance from groups
    "Round of 16": 16,      # 16 teams remain
    "Quarter-finals": 8,    # 8 teams remain
    "Semi-finals": 4,       # 4 teams remain
    "Third Place": 4,       # 2 semi-final losers + 2 finalists (losers not eliminated yet)
    "Final": 2              # 2 teams remain (after 3rd place match)
}


def get_current_round():
    """Get current tournament round"""
    state = TournamentState.query.first()
    if state:
        return state.current_round
    return "Group Stage"


def set_current_round(round_name, force=False):
    """Set current tournament round with validation"""
    if round_name not in ROUNDS:
        return False, f"Invalid round: {round_name}"
    
    # Check team count unless forced (used internally)
    if not force:
        active_count = Team.query.filter_by(eliminated=False).count()
        max_allowed = ROUND_TEAM_LIMITS.get(round_name, 48)
        
        if active_count > max_allowed:
            return False, f"Cannot advance to {round_name}: {active_count} teams still active, maximum allowed is {max_allowed}"
    
    state = TournamentState.query.first()
    if not state:
        state = TournamentState(current_round=round_name)
        db.session.add(state)
    else:
        state.current_round = round_name
        state.last_updated = datetime.utcnow()
    db.session.commit()
    
    return True, f"Round set to {round_name}"


def calculate_starting_points(tournament_rank):
    """Calculate starting points based on tournament rank"""
    A = 64  # max starting points at rank 1
    k = 0.1  # exponential decay constant
    return int(round(A * np.exp(-k * (tournament_rank - 1))))


def initialize_teams():
    """Initialize teams from CSV files"""
    # Clear existing data
    Match.query.delete()
    Team.query.delete()
    TournamentState.query.delete()
    
    # Read CSV files
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    fifa_df = pd.read_csv(os.path.join(data_dir, 'fifa_2026.csv'))
    qualified_df = pd.read_csv(os.path.join(data_dir, 'qualified_test.csv')) #update to just qualified.csv once it has been updated with all actual qualified teams
    
    # Merge and sort
    merged_df = qualified_df.merge(fifa_df, on='Country', how='left')
    merged_df = merged_df.sort_values('Rank').reset_index(drop=True)
    
    # Create teams
    for idx, row in merged_df.iterrows():
        tournament_rank = idx + 1
        base_points = calculate_starting_points(tournament_rank)
        
        team = Team(
            country=row['Country'],
            fifa_rank=int(row['Rank']) if pd.notna(row['Rank']) else 999,
            tournament_rank=tournament_rank,
            confederation=row['Confederation'],
            group=row.get('Group', ''),  # Get group from CSV
            base_points=base_points,
            current_points=base_points,
            total_score=0.0
        )
        db.session.add(team)
    
    # Initialize tournament state
    state = TournamentState(current_round='Group Stage')
    db.session.add(state)
    
    db.session.commit()
    return len(merged_df)


def record_match(winner_country, loser_country, winner_score=None, loser_score=None):
    """Record a match result with optional score"""
    current_round = get_current_round()
    
    winner = Team.query.filter_by(country=winner_country).first()
    loser = Team.query.filter_by(country=loser_country).first()
    
    if not winner:
        return False, f"'{winner_country}' not found in qualified teams"
    if not loser:
        return False, f"'{loser_country}' not found in qualified teams"
    
    if winner.eliminated:
        return False, f"{winner_country} has already been eliminated"
    if loser.eliminated:
        return False, f"{loser_country} has already been eliminated"
    
    # Calculate points earned based on round
    if current_round == "Group Stage":
        # In group stage, earn opponent's BASE points (initial seeding value)
        points_earned = loser.base_points
    else:
        # In knockout rounds, earn opponent's CURRENT value (earned points)
        points_earned = loser.current_points
    
    # Update winner's stats
    winner.total_score += points_earned
    winner.wins += 1
    
    # Update loser's stats
    loser.losses += 1
    
    # Handle current_points changes based on round
    if current_round == "Group Stage":
        # Current points stay as base_points during group stage
        pass
    elif current_round == "Semi-finals":
        # Winner takes loser's point value
        winner.current_points = loser.current_points
        # Semi-final loser: reduce current_points to 75% for 3rd place match
        loser.current_points = loser.current_points * 0.75
        loser.elimination_round = 'Semi-finals (Available for 3rd Place)'
    elif current_round == "Third Place":
        # Winner takes loser's point value (the reduced 75% value)
        winner.current_points = loser.current_points
        # Both teams get eliminated after 3rd place match
        winner.eliminated = True
        winner.elimination_round = '3rd Place'
        loser.eliminated = True
        loser.elimination_round = '4th Place'
        loser.current_points = 0
    elif current_round == "Final":
        # Winner takes loser's point value
        winner.current_points = loser.current_points
        # Mark final results
        winner.elimination_round = 'Champion'
        loser.eliminated = True
        loser.elimination_round = '2nd Place'
        loser.current_points = 0
    else:
        # Regular knockout rounds (R32, R16, QF)
        # Winner takes loser's point value
        winner.current_points = loser.current_points
        # Loser is eliminated
        loser.eliminated = True
        loser.elimination_round = current_round
        loser.current_points = 0
    
    # Record match history
    match_count = Match.query.count()
    match = Match(
        match_number=match_count + 1,
        match_type='win',
        round_name=current_round,
        team1_id=winner.id,
        team2_id=loser.id,
        winner_id=winner.id,
        points_earned=points_earned,
        team1_score=winner_score,
        team2_score=loser_score
    )
    db.session.add(match)
    db.session.commit()
    
    # Build message with score if provided
    if winner_score is not None and loser_score is not None:
        message = f"✓ {winner_country} {winner_score}-{loser_score} {loser_country}\n"
    else:
        message = f"✓ {winner_country} defeated {loser_country}\n"
    message += f"Points earned: {points_earned}\n"
    message += f"{winner_country}'s total score: {winner.total_score:.1f}"
    
    if current_round != "Group Stage":
        message += f"\n{winner_country}'s new current value: {winner.current_points}"
    
    if current_round == "Semi-finals":
        message += f"\n{loser_country} available for Third Place match (value: {loser.current_points})"
    elif current_round == "Third Place":
        message += f"\n{winner_country} finishes 3rd, {loser_country} finishes 4th"
    elif current_round == "Final":
        message += f"\n🏆 {winner_country} is the CHAMPION! 🏆"
        message += f"\n{loser_country} finishes 2nd"
    elif current_round != "Group Stage":
        message += f"\n{loser_country} has been ELIMINATED"
    
    return True, message


def record_draw(team1_country, team2_country, team1_score=None, team2_score=None):
    """Record a draw (group stage only) with optional score"""
    current_round = get_current_round()
    
    if current_round != "Group Stage":
        return False, "Draws are only allowed in Group Stage"
    
    team1 = Team.query.filter_by(country=team1_country).first()
    team2 = Team.query.filter_by(country=team2_country).first()
    
    if not team1:
        return False, f"'{team1_country}' not found in qualified teams"
    if not team2:
        return False, f"'{team2_country}' not found in qualified teams"
    
    if team1.eliminated:
        return False, f"{team1_country} has already been eliminated"
    if team2.eliminated:
        return False, f"{team2_country} has already been eliminated"
    
    # Each team gets half of opponent's BASE points (initial seeding value)
    team1_earns = team2.base_points / 2
    team2_earns = team1.base_points / 2
    
    # Update stats
    team1.total_score += team1_earns
    team1.draws += 1
    
    team2.total_score += team2_earns
    team2.draws += 1
    
    # Record match
    match_count = Match.query.count()
    match = Match(
        match_number=match_count + 1,
        match_type='draw',
        round_name=current_round,
        team1_id=team1.id,
        team2_id=team2.id,
        team1_earned=team1_earns,
        team2_earned=team2_earns,
        team1_score=team1_score,
        team2_score=team2_score
    )
    db.session.add(match)
    db.session.commit()
    
    # Build message with score if provided
    if team1_score is not None and team2_score is not None:
        message = f"↔ {team1_country} {team1_score}-{team2_score} {team2_country}\n"
    else:
        message = f"↔ {team1_country} drew with {team2_country}\n"
    message += f"{team1_country} earned: {team1_earns:.1f} points (half of {team2_country}'s {team2.base_points} base)\n"
    message += f"{team2_country} earned: {team2_earns:.1f} points (half of {team1_country}'s {team1.base_points} base)"
    
    return True, message


def advance_to_knockout(advancing_countries):
    """Advance teams to knockout rounds"""
    current_round = get_current_round()
    
    if current_round != "Group Stage":
        return False, "Can only advance to knockout from Group Stage"
    
    # Check that all 72 group stage matches have been played (6 matches per group × 12 groups)
    REQUIRED_GROUP_MATCHES = 72
    group_matches_played = Match.query.filter_by(round_name="Group Stage").count()
    
    if group_matches_played < REQUIRED_GROUP_MATCHES:
        return False, f"Cannot advance to knockout: Only {group_matches_played} of {REQUIRED_GROUP_MATCHES} group stage matches have been played"
    
    # Verify exactly 32 teams are advancing
    if len(advancing_countries) != 32:
        return False, f"Exactly 32 teams must advance to knockout rounds (got {len(advancing_countries)})"
    
    # Verify all teams exist
    for country in advancing_countries:
        team = Team.query.filter_by(country=country).first()
        if not team:
            return False, f"'{country}' not found in tournament"
    
    # Mark non-advancing teams as eliminated
    all_teams = Team.query.all()
    for team in all_teams:
        if team.country not in advancing_countries:
            team.eliminated = True
            team.elimination_round = 'Group Stage'
        else:
            # Update point value to total score (preserve decimals)
            team.current_points = max(1.0, team.total_score)
    
    set_current_round("Round of 32", force=True)  # Force because we just set the team count
    db.session.commit()
    
    eliminated_count = len(all_teams) - len(advancing_countries)
    message = f"Advanced to Round of 32\n"
    message += f"{len(advancing_countries)} teams advancing\n"
    message += f"{eliminated_count} teams eliminated from Group Stage"
    
    return True, message


def undo_last_match():
    """Undo the last recorded match"""
    last_match = Match.query.order_by(Match.id.desc()).first()
    
    if not last_match:
        return False, "No matches to undo"
    
    if last_match.match_type == 'draw':
        team1 = Team.query.get(last_match.team1_id)
        team2 = Team.query.get(last_match.team2_id)
        
        team1.total_score -= last_match.team1_earned
        team1.draws -= 1
        
        team2.total_score -= last_match.team2_earned
        team2.draws -= 1
        
        message = f"↶ Undid draw between {team1.country} and {team2.country}"
    else:
        winner = Team.query.get(last_match.winner_id)
        loser = Team.query.get(last_match.team2_id) if last_match.team1_id == last_match.winner_id else Team.query.get(last_match.team1_id)
        
        winner.total_score -= last_match.points_earned
        winner.wins -= 1
        loser.losses -= 1
        
        round_name = last_match.round_name
        
        if round_name == "Group Stage":
            # Group stage: no current_points changes needed
            message = f"↶ Undid: {winner.country} defeated {loser.country}"
        
        elif round_name == "Semi-finals":
            # Restore winner's previous current_points
            prev_match = Match.query.filter(
                Match.winner_id == winner.id,
                Match.id < last_match.id,
                Match.round_name != "Group Stage"
            ).order_by(Match.id.desc()).first()
            
            if prev_match:
                winner.current_points = prev_match.points_earned
            else:
                # First knockout match - restore to total_score at end of groups
                winner.current_points = winner.total_score
            
            # Restore loser's current_points (undo the 0.75 reduction)
            # The loser's value before semi was points_earned (what winner took)
            loser.current_points = last_match.points_earned
            loser.elimination_round = ''
            
            message = f"↶ Undid Semi-final: {winner.country} defeated {loser.country}"
            message += f"\n{loser.country} restored (value: {loser.current_points})"
        
        elif round_name == "Third Place":
            # Restore winner's previous current_points (the 0.75 reduced value from semi loss)
            # Need to figure out what it was - it was 0.75 * their value going into semis
            # The points they earned = loser's 0.75 value, so winner's was similar
            # Actually, we need to find their semi-final match to restore properly
            semi_match = Match.query.filter(
                ((Match.team1_id == winner.id) | (Match.team2_id == winner.id)),
                Match.round_name == "Semi-finals"
            ).first()
            
            if semi_match:
                # Winner of 3rd place was a semi-final loser
                # Their value going into 3rd place was 0.75 * their semi value
                # Their semi value = points_earned in that match (what the semi winner took)
                winner.current_points = semi_match.points_earned * 0.75 if semi_match.winner_id != winner.id else semi_match.points_earned
            
            # Restore loser similarly
            semi_match_loser = Match.query.filter(
                ((Match.team1_id == loser.id) | (Match.team2_id == loser.id)),
                Match.round_name == "Semi-finals"
            ).first()
            
            if semi_match_loser:
                loser.current_points = semi_match_loser.points_earned * 0.75 if semi_match_loser.winner_id != loser.id else semi_match_loser.points_earned
            
            winner.elimination_round = 'Semi-finals (Available for 3rd Place)'
            loser.eliminated = False
            loser.elimination_round = 'Semi-finals (Available for 3rd Place)'
            
            message = f"↶ Undid Third Place match: {winner.country} vs {loser.country}"
            message += f"\nBoth teams restored for Third Place match"
        
        elif round_name == "Final":
            # Restore winner's previous current_points
            prev_match = Match.query.filter(
                Match.winner_id == winner.id,
                Match.id < last_match.id,
                Match.round_name != "Group Stage"
            ).order_by(Match.id.desc()).first()
            
            if prev_match:
                winner.current_points = prev_match.points_earned
            
            # Restore loser
            prev_match_loser = Match.query.filter(
                Match.winner_id == loser.id,
                Match.id < last_match.id,
                Match.round_name != "Group Stage"
            ).order_by(Match.id.desc()).first()
            
            if prev_match_loser:
                loser.current_points = prev_match_loser.points_earned
            
            winner.elimination_round = ''
            loser.eliminated = False
            loser.elimination_round = ''
            
            message = f"↶ Undid Final: {winner.country} vs {loser.country}"
            message += f"\nBoth teams restored for Final"
        
        else:
            # Regular knockout rounds (R32, R16, QF)
            # Restore winner's previous current_points
            prev_match = Match.query.filter(
                Match.winner_id == winner.id,
                Match.id < last_match.id,
                Match.round_name != "Group Stage"
            ).order_by(Match.id.desc()).first()
            
            if prev_match:
                winner.current_points = prev_match.points_earned
            else:
                # First knockout match - restore to total_score at end of groups
                winner.current_points = winner.total_score
            
            # Restore loser's current_points (what the winner earned = loser's value)
            loser.current_points = last_match.points_earned
            loser.eliminated = False
            loser.elimination_round = ''
            
            message = f"↶ Undid: {winner.country} defeated {loser.country}"
            message += f"\n{loser.country} restored to tournament (value: {loser.current_points})"
    
    db.session.delete(last_match)
    db.session.commit()
    
    return True, message


def get_leaderboard(top_n=None, active_only=False, eliminated_only=False):
    """Get tournament leaderboard"""
    query = Team.query
    
    if active_only:
        query = query.filter_by(eliminated=False)
    elif eliminated_only:
        query = query.filter_by(eliminated=True)
    
    teams = query.order_by(Team.total_score.desc()).all()
    
    if top_n:
        teams = teams[:top_n]
    
    return teams


def get_active_teams():
    """Get list of active teams"""
    current_round = get_current_round()
    
    if current_round == "Third Place":
        # Include semi-final losers
        return Team.query.filter(
            db.or_(
                Team.eliminated == False,
                Team.elimination_round == 'Semi-finals (Available for 3rd Place)'
            )
        ).order_by(Team.country).all()
    
    return Team.query.filter_by(eliminated=False).order_by(Team.country).all()


def get_match_history():
    """Get all match history"""
    return Match.query.order_by(Match.id.desc()).all()


def get_confederation_stats():
    """Get statistics by confederation"""
    confederations = db.session.query(Team.confederation).distinct().all()
    stats = []
    
    for (conf,) in confederations:
        teams = Team.query.filter_by(confederation=conf).all()
        active = [t for t in teams if not t.eliminated]
        total_score = sum(t.total_score for t in teams)
        
        stats.append({
            'confederation': conf,
            'total_teams': len(teams),
            'active_teams': len(active),
            'eliminated_teams': len(teams) - len(active),
            'total_score': total_score,
            'avg_score': total_score / len(teams) if teams else 0
        })
    
    return sorted(stats, key=lambda x: x['total_score'], reverse=True)


# ----------------------------------------------------
# ROUTES
# ----------------------------------------------------

@app.route('/')
def index():
    """Main dashboard"""
    teams = get_leaderboard(top_n=20)
    current_round = get_current_round()
    active_count = Team.query.filter_by(eliminated=False).count()
    total_count = Team.query.count()
    match_count = Match.query.count()
    
    return render_template('index.html', 
                          teams=teams,
                          current_round=current_round,
                          active_count=active_count,
                          total_count=total_count,
                          match_count=match_count,
                          rounds=ROUNDS)


@app.route('/leaderboard')
def leaderboard():
    """Full leaderboard view"""
    filter_type = request.args.get('filter', 'all')
    top_n = request.args.get('top_n', None)
    
    if top_n and top_n != 'all':
        top_n = int(top_n)
    else:
        top_n = None
    
    active_only = filter_type == 'active'
    eliminated_only = filter_type == 'eliminated'
    
    teams = get_leaderboard(top_n=top_n, active_only=active_only, eliminated_only=eliminated_only)
    
    return render_template('leaderboard.html',
                          teams=teams,
                          current_round=get_current_round(),
                          filter_type=filter_type,
                          top_n=top_n or 'all')


@app.route('/results')
def match_results():
    """Match results page - shows live scores and completed matches"""
    filter_type = request.args.get('filter', 'all')
    
    # Get all matches from database, organized by type
    all_matches = Match.query.order_by(Match.id.desc()).all()
    
    # Build match data for display
    matches = []
    live_matches = []
    
    for m in all_matches:
        team1 = Team.query.get(m.team1_id)
        team2 = Team.query.get(m.team2_id)
        
        if not team1 or not team2:
            continue
        
        # Determine home/away and scores
        if m.match_type == 'win':
            winner = Team.query.get(m.winner_id)
            if m.team1_id == m.winner_id:
                home_team, away_team = team1.country, team2.country
                home_flag, away_flag = team1.flag_code, team2.flag_code
                home_score, away_score = 1, 0  # We don't store actual goals, just who won
            else:
                home_team, away_team = team2.country, team1.country
                home_flag, away_flag = team2.flag_code, team1.flag_code
                home_score, away_score = 0, 1
        else:
            home_team, away_team = team1.country, team2.country
            home_flag, away_flag = team1.flag_code, team2.flag_code
            home_score, away_score = 0, 0  # Draw
        
        match_data = {
            'id': m.id,
            'home_team': home_team,
            'away_team': away_team,
            'home_flag': home_flag,
            'away_flag': away_flag,
            'home_score': home_score,
            'away_score': away_score,
            'status': 'FINISHED',
            'stage': m.round_name,
            'date': m.timestamp.strftime('%Y-%m-%d') if m.timestamp else '',
            'date_formatted': m.timestamp.strftime('%A, %B %d, %Y') if m.timestamp else '',
            'time': m.timestamp.strftime('%H:%M') if m.timestamp else '',
            'penalties': None
        }
        matches.append(match_data)
    
    # Filter based on request
    if filter_type == 'live':
        matches = []  # Live matches come from API, not DB
    elif filter_type == 'finished':
        pass  # All DB matches are finished
    elif filter_type == 'upcoming':
        matches = []  # Upcoming matches would come from API
    elif filter_type == 'today':
        today = datetime.utcnow().strftime('%Y-%m-%d')
        matches = [m for m in matches if m['date'] == today]
    
    # Count qualified teams
    qualified_count = Team.query.count()
    
    return render_template('match_results.html',
                          matches=matches,
                          live_matches=live_matches,
                          filter=filter_type,
                          qualified_count=qualified_count,
                          current_round=get_current_round())


@app.route('/record-match', methods=['GET', 'POST'])
@admin_required
def record_match_view():
    """Record match results (Admin only)"""
    if request.method == 'POST':
        match_type = request.form.get('match_type')
        
        if match_type == 'win':
            winner = request.form.get('winner')
            loser = request.form.get('loser')
            
            if winner == loser:
                flash('Winner and loser must be different teams', 'error')
            else:
                success, message = record_match(winner, loser)
                flash(message, 'success' if success else 'error')
        
        elif match_type == 'draw':
            team1 = request.form.get('team1')
            team2 = request.form.get('team2')
            
            if team1 == team2:
                flash('Teams must be different', 'error')
            else:
                success, message = record_draw(team1, team2)
                flash(message, 'success' if success else 'error')
        
        return redirect(url_for('record_match_view'))
    
    active_teams = get_active_teams()
    all_teams = Team.query.order_by(Team.country).all()
    current_round = get_current_round()
    
    return render_template('record_match.html',
                          active_teams=active_teams,
                          all_teams=all_teams,
                          current_round=current_round,
                          is_group_stage=current_round == 'Group Stage')


@app.route('/match-history')
def match_history():
    """View match history"""
    matches = get_match_history()
    return render_template('match_history.html', 
                          matches=matches,
                          current_round=get_current_round())


@app.route('/team/<country>')
def team_detail(country):
    """Team detail view"""
    team = Team.query.filter_by(country=country).first_or_404()
    
    # Get matches involving this team
    matches = Match.query.filter(
        db.or_(Match.team1_id == team.id, Match.team2_id == team.id)
    ).order_by(Match.id.desc()).all()
    
    return render_template('team_detail.html',
                          team=team,
                          matches=matches,
                          current_round=get_current_round())


@app.route('/bracket')
def bracket():
    """Tournament bracket view"""
    teams = Team.query.order_by(Team.total_score.desc()).all()
    matches = Match.query.filter(Match.round_name != 'Group Stage').order_by(Match.id).all()
    
    # Organize matches by round
    bracket_data = {round_name: [] for round_name in ROUNDS if round_name != 'Group Stage'}
    for match in matches:
        if match.round_name in bracket_data:
            bracket_data[match.round_name].append(match)
    
    return render_template('bracket.html',
                          bracket_data=bracket_data,
                          teams=teams,
                          current_round=get_current_round(),
                          rounds=ROUNDS[1:])  # Exclude Group Stage


@app.route('/statistics')
def statistics():
    """Statistics and charts"""
    conf_stats = get_confederation_stats()
    teams = get_leaderboard()
    
    # Prepare chart data
    score_distribution = {
        'labels': [t.country for t in teams[:15]],
        'scores': [t.total_score for t in teams[:15]]
    }
    
    conf_chart = {
        'labels': [s['confederation'] for s in conf_stats],
        'scores': [s['total_score'] for s in conf_stats],
        'active': [s['active_teams'] for s in conf_stats]
    }
    
    return render_template('statistics.html',
                          conf_stats=conf_stats,
                          score_distribution=score_distribution,
                          conf_chart=conf_chart,
                          current_round=get_current_round())


@app.route('/api/top-scorers')
def api_top_scorers():
    """API endpoint to fetch top scorers from Football-Data.org"""
    import requests
    
    api_key = os.environ.get('FOOTBALL_DATA_API_KEY', '')
    
    if not api_key:
        return jsonify({'success': False, 'error': 'API key not configured'}), 500
    
    try:
        headers = {'X-Auth-Token': api_key}
        response = requests.get(
            'https://api.football-data.org/v4/competitions/WC/scorers',
            headers=headers,
            params={'limit': 20},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            scorers = data.get('scorers', [])
            
            # Format the data
            formatted_scorers = []
            for scorer in scorers:
                player = scorer.get('player', {})
                team = scorer.get('team', {})
                formatted_scorers.append({
                    'name': player.get('name', 'Unknown'),
                    'nationality': player.get('nationality', ''),
                    'team': team.get('name', 'Unknown'),
                    'goals': scorer.get('goals', 0),
                    'assists': scorer.get('assists'),
                    'penalties': scorer.get('penalties', 0),
                    'matches_played': scorer.get('playedMatches', 0)
                })
            
            return jsonify({'success': True, 'scorers': formatted_scorers})
        else:
            return jsonify({'success': False, 'error': f'API error: {response.status_code}'}), response.status_code
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/user-competition')
def user_competition():
    """User team selection competition"""
    selections = UserTeamSelection.query.all()
    
    # Calculate scores for each selection
    selection_data = []
    for sel in selections:
        teams = sel.get_teams()
        total = sum(t.total_score for t in teams)
        selection_data.append({
            'id': sel.id,
            'user_name': sel.user_name,
            'teams': teams,
            'total_score': total,
            'created_at': sel.created_at
        })
    
    # Sort by total score
    selection_data.sort(key=lambda x: x['total_score'], reverse=True)
    
    # Get all teams organized by group
    all_teams = Team.query.order_by(Team.group, Team.country).all()
    
    # Organize teams into groups
    teams_by_group = {}
    for team in all_teams:
        group = team.group or 'Unknown'
        if group not in teams_by_group:
            teams_by_group[group] = []
        teams_by_group[group].append(team)
    
    # Sort groups alphabetically
    sorted_groups = sorted(teams_by_group.keys())
    
    # Check if admin is logged in
    is_admin = session.get('admin_logged_in', False)
    
    # Check if tournament has started (selections locked)
    tournament_locked = Match.query.count() > 0
    
    return render_template('user_competition.html',
                          selections=selection_data,
                          all_teams=all_teams,
                          teams_by_group=teams_by_group,
                          sorted_groups=sorted_groups,
                          is_admin=is_admin,
                          tournament_locked=tournament_locked,
                          current_round=get_current_round())


@app.route('/api/create-selection', methods=['POST'])
def create_selection():
    """API to create user team selection"""
    import re
    
    # Check if tournament has started (any matches played)
    match_count = Match.query.count()
    if match_count > 0:
        return jsonify({'success': False, 'message': 'Team selection is locked - the tournament has already started'}), 400
    
    data = request.json
    user_name = data.get('user_name', '').strip()
    team_ids = data.get('team_ids', [])
    
    if not user_name:
        return jsonify({'success': False, 'message': 'User name required'}), 400
    
    # Sanitize: only allow letters, numbers, spaces, hyphens, underscores
    user_name = re.sub(r'[^A-Za-z0-9 _-]', '', user_name).strip()
    
    if not user_name:
        return jsonify({'success': False, 'message': 'Name must contain letters or numbers'}), 400
    
    if len(user_name) > 20:
        return jsonify({'success': False, 'message': 'Name must be 20 characters or less'}), 400
    
    if len(team_ids) < 3 or len(team_ids) > 4:
        return jsonify({'success': False, 'message': 'Select 3-4 teams'}), 400
    
    # Check if user already has a selection
    existing = UserTeamSelection.query.filter_by(user_name=user_name).first()
    if existing:
        return jsonify({'success': False, 'message': 'User already has a selection'}), 400
    
    selection = UserTeamSelection(user_name=user_name, team_ids=json.dumps(team_ids))
    db.session.add(selection)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Selection created!'})


@app.route('/admin/delete-selection/<int:selection_id>', methods=['POST'])
@admin_required
def delete_selection(selection_id):
    """Delete a user's team selection (Admin only)"""
    selection = UserTeamSelection.query.get(selection_id)
    
    if selection:
        user_name = selection.user_name
        db.session.delete(selection)
        db.session.commit()
        flash(f'Deleted selection for "{user_name}"', 'success')
    else:
        flash('Selection not found', 'error')
    
    return redirect(url_for('user_competition'))


# ----------------------------------------------------
# ADMIN ROUTES
# ----------------------------------------------------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Logged in successfully', 'success')
            next_url = request.args.get('next')
            return redirect(next_url or url_for('admin_dashboard'))
        else:
            flash('Invalid password', 'error')
    
    return render_template('admin_login.html', current_round=get_current_round())


@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.pop('admin_logged_in', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    return render_template('admin_dashboard.html',
                          current_round=get_current_round(),
                          rounds=ROUNDS,
                          teams=get_leaderboard(),
                          active_count=Team.query.filter_by(eliminated=False).count(),
                          total_count=Team.query.count())


@app.route('/admin/set-round', methods=['POST'])
@admin_required
def admin_set_round():
    """Set tournament round"""
    round_name = request.form.get('round')
    if round_name in ROUNDS:
        success, message = set_current_round(round_name)
        if success:
            flash(f'Round set to: {round_name}', 'success')
        else:
            flash(message, 'error')
    else:
        flash('Invalid round name', 'error')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/advance-knockout', methods=['GET', 'POST'])
@admin_required
def admin_advance_knockout():
    """Advance to knockout rounds"""
    if request.method == 'POST':
        advancing = request.form.getlist('advancing')
        success, message = advance_to_knockout(advancing)
        flash(message, 'success' if success else 'error')
        return redirect(url_for('admin_dashboard'))
    
    teams = get_leaderboard()
    return render_template('advance_knockout.html',
                          teams=teams,
                          current_round=get_current_round())


@app.route('/admin/undo-match', methods=['POST'])
@admin_required
def admin_undo_match():
    """Undo last match"""
    success, message = undo_last_match()
    flash(message, 'success' if success else 'error')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/recalculate-points', methods=['POST'])
@admin_required
def admin_recalculate_points():
    """Recalculate base points using current formula (doesn't reset match history)"""
    teams = Team.query.all()
    for team in teams:
        new_base = calculate_starting_points(team.tournament_rank)
        # Update base_points and current_points (current = base for fresh start)
        team.base_points = new_base
        team.current_points = new_base
    db.session.commit()
    flash(f'Recalculated base points for {len(teams)} teams using new formula (A=64, k=0.1)', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reset', methods=['POST'])
@admin_required
def admin_reset():
    """Reset tournament"""
    count = initialize_teams()
    flash(f'Tournament reset! {count} teams initialized.', 'success')
    return redirect(url_for('admin_dashboard'))


# ----------------------------------------------------
# API ROUTES
# ----------------------------------------------------

@app.route('/api/teams')
def api_teams():
    """API endpoint for teams data"""
    teams = Team.query.order_by(Team.total_score.desc()).all()
    return jsonify([t.to_dict() for t in teams])


@app.route('/api/leaderboard')
def api_leaderboard():
    """API endpoint for leaderboard"""
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    top_n = request.args.get('top_n', None, type=int)
    
    teams = get_leaderboard(top_n=top_n, active_only=active_only)
    return jsonify([t.to_dict() for t in teams])


@app.route('/api/match-history')
def api_match_history():
    """API endpoint for match history"""
    matches = get_match_history()
    result = []
    for m in matches:
        result.append({
            'match_number': m.match_number,
            'type': m.match_type,
            'round': m.round_name,
            'team1': Team.query.get(m.team1_id).country,
            'team2': Team.query.get(m.team2_id).country,
            'winner': Team.query.get(m.winner_id).country if m.winner_id else None,
            'points_earned': m.points_earned,
            'team1_earned': m.team1_earned,
            'team2_earned': m.team2_earned,
            'timestamp': m.timestamp.isoformat()
        })
    return jsonify(result)


# ----------------------------------------------------
# INITIALIZATION
# ----------------------------------------------------

def check_and_migrate_db():
    """Check if database schema needs updating and migrate if necessary"""
    with app.app_context():
        try:
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            
            # Check team table columns
            team_columns = [col['name'] for col in inspector.get_columns('team')]
            
            if 'group' not in team_columns:
                print("Database schema outdated - adding 'group' column to team...")
                with db.engine.connect() as conn:
                    conn.execute(db.text('ALTER TABLE team ADD COLUMN "group" VARCHAR(1)'))
                    conn.commit()
                print("Added 'group' column!")
                update_team_groups()
            
            # Check match table columns for score fields
            if 'match' in inspector.get_table_names():
                match_columns = [col['name'] for col in inspector.get_columns('match')]
                
                if 'team1_score' not in match_columns:
                    print("Adding 'team1_score' column to match table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text('ALTER TABLE "match" ADD COLUMN team1_score INTEGER'))
                        conn.commit()
                    print("Added 'team1_score' column!")
                
                if 'team2_score' not in match_columns:
                    print("Adding 'team2_score' column to match table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text('ALTER TABLE "match" ADD COLUMN team2_score INTEGER'))
                        conn.commit()
                    print("Added 'team2_score' column!")
                
        except Exception as e:
            # Table might not exist yet, that's fine
            print(f"Migration check: {e}")

def update_team_groups():
    """Update existing teams with group data from CSV"""
    with app.app_context():
        try:
            qualified_df = pd.read_csv('data/qualified.csv')
            for _, row in qualified_df.iterrows():
                team = Team.query.filter_by(country=row['Country']).first()
                if team and 'Group' in row:
                    team.group = row['Group']
            db.session.commit()
            print("Team groups updated from CSV!")
        except Exception as e:
            print(f"Error updating groups: {e}")

def init_db():
    """Initialize database"""
    with app.app_context():
        db.create_all()
        
        # Run migrations if needed
        check_and_migrate_db()
        
        # Check if teams exist
        try:
            count = Team.query.count()
            if count == 0:
                initialize_teams()
                print("Database initialized with teams!")
        except Exception as e:
            # If there's still an error, drop and recreate
            print(f"Database error, recreating: {e}")
            db.drop_all()
            db.create_all()
            initialize_teams()
            print("Database recreated with teams!")


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
