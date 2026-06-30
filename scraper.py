"""
World Cup 2026 Live Match Scraper
Automatically fetches match results from Football-Data.org API and updates the tournament database.

Usage:
    1. Get a free API key from https://www.football-data.org/client/register
    2. Set the API_KEY environment variable or update it in this file
    3. Run: python scraper.py
    
The scraper can run in two modes:
    - One-time: python scraper.py --once
    - Continuous: python scraper.py (polls every 5 minutes during matches)
"""

import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Team, Match, TournamentState, record_match, record_draw, get_current_round, set_current_round

# ============================================
# CONFIGURATION
# ============================================

# Get API key from environment variable or set it here
API_KEY = os.environ.get('FOOTBALL_DATA_API_KEY', 'YOUR_API_KEY_HERE')

# Football-Data.org API base URL
API_BASE_URL = 'https://api.football-data.org/v4'

# World Cup competition code
COMPETITION_CODE = 'WC'

# Polling interval in seconds (5 minutes)
POLL_INTERVAL = 300

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# TEAM NAME MAPPING
# ============================================

# Map API team names to our database team names
# This handles differences in naming conventions
TEAM_NAME_MAP = {
    # Add mappings as needed when API names differ from your database
    # 'API Name': 'Database Name',
    'USA': 'United States',
    'United States of America': 'United States',
    'Korea Republic': 'South Korea',
    'Republic of Korea': 'South Korea',
    'IR Iran': 'Iran',
    'Ivory Coast': "Côte d'Ivoire",
    'Cote d\'Ivoire': "Côte d'Ivoire",
    'Türkiye': 'Türkiye',
    'Turkey': 'Türkiye',
    'Cape Verde': 'Cabo Verde',
    'Cape Verde Islands': 'Cabo Verde',
    'Cabo Verde Islands': 'Cabo Verde',
    'Bosnia-Herzegovina': 'Bosnia & Herzegovina',
    'Bosnia and Herzegovina': 'Bosnia & Herzegovina',
    'Czech Republic': 'Czechia',
    'Curaçao': 'Curacao',
    'Congo DR': 'DR Congo',
    'Democratic Republic of the Congo': 'DR Congo',
}

def normalize_team_name(api_name: str) -> str:
    """Convert API team name to our database team name"""
    return TEAM_NAME_MAP.get(api_name, api_name)

# ============================================
# API CLIENT
# ============================================

class FootballDataClient:
    """Client for Football-Data.org API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            'X-Auth-Token': api_key
        }
        self.base_url = API_BASE_URL
    
    def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make a request to the API"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Don't block here - the caller may be a web request handler.
                # Just log and back off; the next scheduled/cached call will retry.
                logger.warning("Rate limited (429) by Football-Data.org API")
                return None
            else:
                logger.error(f"API error {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None
    
    def get_competition(self) -> Optional[dict]:
        """Get World Cup competition info"""
        return self._request(f"/competitions/{COMPETITION_CODE}")
    
    def get_matches(self, status: str = None, matchday: int = None, 
                    date_from: str = None, date_to: str = None) -> Optional[List[dict]]:
        """
        Get World Cup matches with optional filters
        
        Args:
            status: SCHEDULED, LIVE, IN_PLAY, PAUSED, FINISHED, POSTPONED, CANCELLED, SUSPENDED
            matchday: Filter by matchday number
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
        """
        params = {}
        if status:
            params['status'] = status
        if matchday:
            params['matchday'] = matchday
        if date_from:
            params['dateFrom'] = date_from
        if date_to:
            params['dateTo'] = date_to
            
        data = self._request(f"/competitions/{COMPETITION_CODE}/matches", params)
        
        if data and 'matches' in data:
            return data['matches']
        return None
    
    def get_live_matches(self) -> Optional[List[dict]]:
        """Get currently live matches"""
        return self.get_matches(status='LIVE')
    
    def get_finished_matches(self, date_from: str = None) -> Optional[List[dict]]:
        """Get finished matches, optionally from a specific date"""
        return self.get_matches(status='FINISHED', date_from=date_from)
    
    def get_todays_matches(self) -> Optional[List[dict]]:
        """Get all matches scheduled for today"""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')
        return self.get_matches(date_from=today, date_to=tomorrow)
    
    def get_standings(self) -> Optional[dict]:
        """
        Get World Cup standings (group tables)
        
        Returns dict with structure:
        {
            'standings': [
                {
                    'stage': 'GROUP_STAGE',
                    'type': 'TOTAL',
                    'group': 'GROUP_A',
                    'table': [
                        {'position': 1, 'team': {'name': '...'}, 'points': X, ...},
                        ...
                    ]
                },
                ...
            ]
        }
        """
        return self._request(f"/competitions/{COMPETITION_CODE}/standings")
    
    def get_scorers(self, limit: int = 20) -> Optional[List[dict]]:
        """
        Get top scorers for the World Cup
        
        Args:
            limit: Maximum number of scorers to return (default 20)
        
        Returns:
            List of scorer data:
            [
                {
                    'player': {'id': X, 'name': '...', 'nationality': '...'},
                    'team': {'id': X, 'name': '...'},
                    'goals': X,
                    'assists': X,  # May be None on free tier
                    'penalties': X
                },
                ...
            ]
        """
        params = {'limit': limit}
        data = self._request(f"/competitions/{COMPETITION_CODE}/scorers", params)
        
        if data and 'scorers' in data:
            return data['scorers']
        return None

# ============================================
# MATCH PROCESSOR
# ============================================

class MatchProcessor:
    """Processes API match data and updates the tournament database"""
    
    def __init__(self):
        self.processed_matches = self._load_processed_matches()
    
    def _processed_matches_path(self) -> str:
        """
        Return the path for the processed-matches tracking file.

        This must live on the persistent disk (same as tournament.db) -
        otherwise it gets wiped on every redeploy, causing already-recorded
        matches to be re-processed (and re-scored) again.
        """
        if os.path.exists('/var/data'):
            return '/var/data/processed_matches.json'
        return 'processed_matches.json'
    
    def _load_processed_matches(self) -> set:
        """Load set of already processed match IDs"""
        try:
            with open(self._processed_matches_path(), 'r') as f:
                return set(json.load(f))
        except FileNotFoundError:
            return set()
    
    def _save_processed_matches(self):
        """Save processed match IDs to file"""
        with open(self._processed_matches_path(), 'w') as f:
            json.dump(list(self.processed_matches), f)
    
    def _get_match_result(self, match: dict) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Extract match result from API data.

        Returns:
            Tuple of (winner_name, loser_name, is_draw)
            For draws: (team1_name, team2_name, True)

        Notes on this API's actual data shape (observed in production):
          - 'duration' tells us how the match was decided: 'REGULAR',
            'EXTRA_TIME', or 'PENALTY_SHOOTOUT'.
          - 'fullTime' is the AGGREGATE result and is the most reliable
            field. For a shootout it already includes the shootout outcome
            (e.g. regulationTime 1-1 -> fullTime 4-5 reflects the winner).
          - The 'penalties' sub-object and 'winner' field can be unreliable
            / incomplete (e.g. penalties showing 4-4 and winner None on a
            decided shootout), so we do NOT depend on them to pick a winner.
        """
        home_team = normalize_team_name(match['homeTeam']['name'])
        away_team = normalize_team_name(match['awayTeam']['name'])

        score = match.get('score', {}) or {}
        duration = (score.get('duration') or '').upper()

        full_time = score.get('fullTime') or {}
        regular_time = score.get('regularTime') or {}
        extra_time = score.get('extraTime') or {}
        penalties = score.get('penalties') or {}
        winner_field = score.get('winner')

        # ---- 1. fullTime aggregate: the most reliable decisive signal. --
        # On this API, fullTime reflects the final outcome including any
        # extra time and penalty shootout, so a non-tied fullTime is
        # authoritative for the winner.
        if full_time.get('home') is not None and full_time.get('away') is not None:
            fh, fa = full_time['home'], full_time['away']
            if fh > fa:
                return home_team, away_team, False
            elif fa > fh:
                return away_team, home_team, False
            # fullTime is tied - fall through to the tie-breakers below.

        # ---- 2. Penalty shootout: use the penalties sub-object if it has
        #         a decisive result.
        if penalties.get('home') is not None and penalties.get('away') is not None:
            ph, pa = penalties['home'], penalties['away']
            if ph > pa:
                return home_team, away_team, False
            elif pa > ph:
                return away_team, home_team, False

        # ---- 3. Explicit winner field (overall winner incl. ET/pens). ---
        if winner_field == 'HOME_TEAM':
            return home_team, away_team, False
        elif winner_field == 'AWAY_TEAM':
            return away_team, home_team, False

        # ---- 4. Extra time / regulation numeric scores. -----------------
        for block in (extra_time, full_time, regular_time):
            if block.get('home') is not None and block.get('away') is not None:
                h, a = block['home'], block['away']
                if h > a:
                    return home_team, away_team, False
                elif a > h:
                    return away_team, home_team, False
                break  # tied on the first usable block; stop and resolve below

        # ---- 5. Resolve a tie. ------------------------------------------
        # A shootout that we couldn't resolve above means the data is
        # incomplete - defer for retry rather than mis-recording.
        if duration == 'PENALTY_SHOOTOUT':
            logger.warning(
                f"Match {match['id']} ({home_team} vs {away_team}) is a penalty "
                f"shootout but no decisive score could be read - deferring for retry. "
                f"Raw score: {score}"
            )
            return None, None, False

        if winner_field == 'DRAW':
            return home_team, away_team, True

        # In a knockout round a genuine tie shouldn't happen; defer for retry.
        # In the group stage, a tie is a legitimate draw.
        current_round = get_current_round()
        if current_round == "Group Stage":
            # Only call it a draw if we actually saw a tied numeric score.
            if (full_time.get('home') is not None and full_time.get('away') is not None) or \
               (regular_time.get('home') is not None and regular_time.get('away') is not None):
                return home_team, away_team, True

        logger.warning(f"No decisive result for match {match['id']} "
                       f"({home_team} vs {away_team}, status={match.get('status')}, duration={duration})")
        logger.warning(f"Raw score data: {score}")
        return None, None, False
    
    def _determine_round(self, match: dict) -> str:
        """Determine the tournament round from API match data"""
        stage = match.get('stage', '').upper()
        
        stage_mapping = {
            'GROUP_STAGE': 'Group Stage',
            'LAST_64': 'Round of 64',
            'LAST_32': 'Round of 32',
            'ROUND_OF_16': 'Round of 16',
            'QUARTER_FINALS': 'Quarter-finals',
            'QUARTER_FINAL': 'Quarter-finals',
            'SEMI_FINALS': 'Semi-finals',
            'SEMI_FINAL': 'Semi-finals',
            'THIRD_PLACE': 'Third Place',
            '3RD_PLACE': 'Third Place',
            'FINAL': 'Final',
        }
        
        return stage_mapping.get(stage, 'Group Stage')
    
    def process_match(self, match: dict) -> bool:
        """
        Process a single match and update the database
        
        Returns:
            True if match was processed successfully, False otherwise
        """
        match_id = match['id']
        
        # Skip if already processed
        if match_id in self.processed_matches:
            logger.debug(f"Match {match_id} already processed, skipping")
            return False
        
        # Only process finished matches
        if match['status'] != 'FINISHED':
            return False
        
        # Get match result
        winner, loser, is_draw = self._get_match_result(match)
        
        if winner is None:
            logger.warning(f"Could not determine result for match {match_id}")
            return False
        
        # Extract scores for display. Prefer the score that reflects how
        # the match was ultimately decided in regulation/extra time:
        # fullTime (includes ET on this API) > regularTime > extraTime.
        # Penalty shootout scores are tracked separately, not as the headline.
        # Extract the headline score and any penalty shootout score.
        #
        # On this API:
        #   - regularTime / extraTime hold the on-pitch score.
        #   - fullTime is the AGGREGATE (for a shootout it bakes in the
        #     winner, e.g. regulation 1-1 -> fullTime 4-5).
        #   - The 'penalties' sub-object is sometimes unreliable (e.g. 4-4
        #     on a decided shootout).
        #
        # For display we want the on-pitch result as the headline (e.g.
        # "1-1") plus the actual shootout score. We derive the shootout
        # score from fullTime minus the pre-shootout score when needed.
        score = match.get('score', {}) or {}
        duration = (score.get('duration') or '').upper()
        full_time = score.get('fullTime') or {}
        regular_time = score.get('regularTime') or {}
        extra_time = score.get('extraTime') or {}
        pens_block = score.get('penalties') or {}

        # Pre-shootout on-pitch score: prefer the score at the end of play.
        # If extra time was played and is non-zero use the combined
        # regulation+ET; otherwise use regulation; otherwise fall back to
        # fullTime.
        def _combined(a, b):
            if a.get('home') is not None and b.get('home') is not None:
                return a['home'] + b['home'], a['away'] + b['away']
            return None, None

        home_score = away_score = None
        is_shootout = (duration == 'PENALTY_SHOOTOUT') or (
            pens_block.get('home') is not None and pens_block.get('away') is not None
        )

        if regular_time.get('home') is not None:
            # On-pitch score at the end of extra time (regulation + ET).
            if extra_time.get('home') is not None and (extra_time.get('home') or extra_time.get('away')):
                home_score, away_score = _combined(regular_time, extra_time)
            else:
                home_score, away_score = regular_time['home'], regular_time['away']
        elif full_time.get('home') is not None and not is_shootout:
            home_score, away_score = full_time['home'], full_time['away']

        # Last-resort default so we never store/display None
        if home_score is None or away_score is None:
            home_score = 0 if home_score is None else home_score
            away_score = 0 if away_score is None else away_score

        # Determine the penalty shootout score.
        home_pens = away_pens = None
        if is_shootout:
            ph, pa = pens_block.get('home'), pens_block.get('away')
            # If the penalties sub-object is decisive, trust it.
            if ph is not None and pa is not None and ph != pa:
                home_pens, away_pens = ph, pa
            else:
                # Otherwise derive the shootout score from the fullTime
                # aggregate minus the pre-shootout on-pitch score.
                if full_time.get('home') is not None and full_time.get('away') is not None:
                    derived_h = full_time['home'] - home_score
                    derived_a = full_time['away'] - away_score
                    if derived_h >= 0 and derived_a >= 0 and (derived_h or derived_a):
                        home_pens, away_pens = derived_h, derived_a
                    elif ph is not None and pa is not None:
                        home_pens, away_pens = ph, pa
        
        # Get team names for determining which score belongs to which team
        home_team = normalize_team_name(match['homeTeam']['name'])
        away_team = normalize_team_name(match['awayTeam']['name'])
        
        # Parse the actual match kickoff time (UTC) from the API so we can
        # store and display the real match date rather than the time we
        # happened to record it.
        match_date = None
        utc_date_str = match.get('utcDate', '')
        if utc_date_str:
            try:
                match_date = datetime.strptime(utc_date_str, '%Y-%m-%dT%H:%M:%SZ')
            except (ValueError, TypeError):
                match_date = None
        
        # Determine and set the round
        match_round = self._determine_round(match)
        current_round = get_current_round()
        
        # Update round if needed (only advance, never go back)
        rounds_order = ["Group Stage", "Round of 32", "Round of 16", 
                       "Quarter-finals", "Semi-finals", "Third Place", "Final"]
        
        if match_round in rounds_order and current_round in rounds_order:
            if rounds_order.index(match_round) > rounds_order.index(current_round):
                logger.info(f"Attempting to advance round from {current_round} to {match_round}")
                success, msg = set_current_round(match_round)
                if success:
                    logger.info(f"Advanced round to {match_round}")
                else:
                    logger.warning(f"Could not advance round: {msg}")
        
        # Record the match with scores
        with app.app_context():
            # Safety net: even if processed_matches.json was reset (e.g. by a
            # redeploy), don't double-record a result we already have for
            # this pair of teams in this round.
            home_team_obj = Team.query.filter_by(country=home_team).first()
            away_team_obj = Team.query.filter_by(country=away_team).first()
            
            if home_team_obj and away_team_obj:
                existing = Match.query.filter(
                    Match.round_name == match_round,
                    db.or_(
                        db.and_(Match.team1_id == home_team_obj.id, Match.team2_id == away_team_obj.id),
                        db.and_(Match.team1_id == away_team_obj.id, Match.team2_id == home_team_obj.id),
                    )
                ).first()
                
                if existing:
                    logger.info(f"Match {match_id} ({home_team} vs {away_team}, {match_round}) "
                                f"already recorded in database - marking as processed and skipping")
                    self.processed_matches.add(match_id)
                    self._save_processed_matches()
                    return False
            
            if is_draw:
                # For draws, winner/loser are team1/team2
                # team1 is home, team2 is away
                success, message = record_draw(winner, loser, home_score, away_score, match_date)
                result_type = "draw"
            else:
                # Determine winner and loser scores (and penalty scores)
                if winner == home_team:
                    winner_score, loser_score = home_score, away_score
                    winner_pens, loser_pens = home_pens, away_pens
                else:
                    winner_score, loser_score = away_score, home_score
                    winner_pens, loser_pens = away_pens, home_pens
                success, message = record_match(winner, loser, winner_score, loser_score,
                                                match_date, winner_pens, loser_pens)
                result_type = "win"
            
            if success:
                self.processed_matches.add(match_id)
                self._save_processed_matches()
                
                score_str = f"{home_score}-{away_score}"
                
                logger.info(f"✓ Recorded {result_type}: {home_team} {score_str} {away_team}")
                logger.info(f"  {message.split(chr(10))[0]}")  # First line of message
                return True
            else:
                logger.error(f"Failed to record match: {message}")
                return False
    
    def process_all_finished_matches(self, matches: List[dict]) -> int:
        """
        Process all finished matches
        
        Returns:
            Number of matches processed
        """
        processed_count = 0
        
        # Sort by date to process in chronological order
        sorted_matches = sorted(matches, key=lambda m: m.get('utcDate', ''))
        
        for match in sorted_matches:
            if self.process_match(match):
                processed_count += 1
        
        return processed_count


# ============================================
# STANDINGS PROCESSOR
# ============================================

class StandingsProcessor:
    """Processes standings data and handles automatic advancement to knockout rounds"""
    
    def __init__(self, client: FootballDataClient):
        self.client = client
    
    def get_group_standings(self) -> Optional[Dict[str, List[dict]]]:
        """
        Fetch and parse group standings from API
        
        Returns:
            Dict mapping group name to list of teams in order:
            {'A': [{'name': 'Spain', 'points': 9, 'goalDifference': 5, ...}, ...], ...}
        """
        data = self.client.get_standings()
        
        if not data or 'standings' not in data:
            logger.error("Failed to fetch standings data")
            return None
        
        groups = {}
        
        for standing in data['standings']:
            # The API returns group-stage tables with type 'TOTAL' and a
            # group label like 'Group A'. The 'stage' field is 'ALL' (not
            # 'GROUP_STAGE'), so we key off the presence of a group label
            # plus type == 'TOTAL' rather than filtering on stage.
            if standing.get('type') != 'TOTAL':
                continue
            
            group_name = standing.get('group')
            if not group_name:
                # No group label -> not a group-stage table (e.g. a
                # knockout bracket standing); skip it.
                continue
            
            # Extract the group letter from any of these formats:
            #   'Group A', 'GROUP_A', 'Group_A', 'A'
            group_letter = (group_name
                            .replace('GROUP_', '')
                            .replace('Group_', '')
                            .replace('Group ', '')
                            .replace('GROUP ', '')
                            .strip())
            
            table = standing.get('table', [])
            teams_in_group = []
            
            for entry in table:
                team_data = entry.get('team', {})
                team_name = normalize_team_name(team_data.get('name', ''))
                
                teams_in_group.append({
                    'name': team_name,
                    'position': entry.get('position', 0),
                    'points': entry.get('points', 0),
                    'goalDifference': entry.get('goalDifference', 0),
                    'goalsFor': entry.get('goalsFor', 0),
                    'playedGames': entry.get('playedGames', 0),
                    'won': entry.get('won', 0),
                    'draw': entry.get('draw', 0),
                    'lost': entry.get('lost', 0)
                })
            
            # Sort by position
            teams_in_group.sort(key=lambda t: t['position'])
            groups[group_letter] = teams_in_group
        
        return groups
    
    def check_group_stage_complete(self, groups: Dict[str, List[dict]]) -> bool:
        """
        Check if all group stage matches are complete
        
        Each team plays 3 matches in groups, so each group should have
        all 4 teams with 3 played games each.
        """
        if not groups:
            return False
        
        # World Cup 2026 has 12 groups (A-L)
        expected_groups = 12
        
        if len(groups) < expected_groups:
            logger.info(f"Only {len(groups)} groups found, expected {expected_groups}")
            return False
        
        for group_letter, teams in groups.items():
            if len(teams) < 4:
                logger.info(f"Group {group_letter} has only {len(teams)} teams")
                return False
            
            for team in teams:
                if team['playedGames'] < 3:
                    logger.info(f"Group {group_letter}: {team['name']} has only played {team['playedGames']} games")
                    return False
        
        return True
    
    def determine_advancing_teams(self, groups: Dict[str, List[dict]]) -> List[str]:
        """
        Determine which 32 teams advance to knockout rounds.
        
        World Cup 2026 format:
        - Top 2 from each group (12 groups × 2 = 24 teams)
        - Best 8 third-place teams (based on points, then goal difference, then goals scored)
        
        Returns:
            List of 32 team names that advance
        """
        advancing = []
        third_place_teams = []
        
        # Get top 2 from each group + collect 3rd place teams
        for group_letter in sorted(groups.keys()):
            teams = groups[group_letter]
            
            if len(teams) >= 2:
                # Top 2 advance automatically
                advancing.append(teams[0]['name'])
                advancing.append(teams[1]['name'])
                logger.info(f"Group {group_letter}: {teams[0]['name']} (1st), {teams[1]['name']} (2nd) advance")
            
            if len(teams) >= 3:
                # Collect 3rd place team for comparison
                third_place_teams.append({
                    'name': teams[2]['name'],
                    'group': group_letter,
                    'points': teams[2]['points'],
                    'goalDifference': teams[2]['goalDifference'],
                    'goalsFor': teams[2]['goalsFor']
                })
        
        # Sort 3rd place teams by: points (desc), goal difference (desc), goals scored (desc)
        third_place_teams.sort(
            key=lambda t: (t['points'], t['goalDifference'], t['goalsFor']),
            reverse=True
        )
        
        # Take best 8 third-place teams
        best_third = third_place_teams[:8]
        for team in best_third:
            advancing.append(team['name'])
            logger.info(f"Group {team['group']} 3rd place: {team['name']} advances (pts: {team['points']}, gd: {team['goalDifference']})")
        
        # Log teams that didn't make it
        eliminated_third = third_place_teams[8:]
        for team in eliminated_third:
            logger.info(f"Group {team['group']} 3rd place: {team['name']} ELIMINATED (pts: {team['points']}, gd: {team['goalDifference']})")
        
        return advancing
    
    def attempt_automatic_advancement(self) -> Tuple[bool, str]:
        """
        Check if group stage is complete and automatically advance teams if so.
        
        Returns:
            Tuple of (success, message)
        """
        with app.app_context():
            current_round = get_current_round()
            
            if current_round != "Group Stage":
                return False, f"Not in Group Stage (current: {current_round})"
            
            # Check if we already have 72 matches
            from app import Match as AppMatch
            group_matches = AppMatch.query.filter_by(round_name="Group Stage").count()
            
            if group_matches < 72:
                return False, f"Only {group_matches}/72 group stage matches recorded"
        
        # Fetch standings from API
        logger.info("Fetching standings from API...")
        groups = self.get_group_standings()
        
        if not groups:
            logger.warning("Advancement halted: get_group_standings() returned no groups. "
                           "Check /api/debug-standings - the API standings response shape "
                           "may not match the parser's stage/type/group filters.")
            return False, "Failed to fetch standings from API"
        
        logger.info(f"Parsed {len(groups)} group(s) from standings")
        
        # Check if all groups are complete
        if not self.check_group_stage_complete(groups):
            logger.info("Advancement halted: group stage not yet complete per standings.")
            return False, "Group stage not yet complete"
        
        # Determine advancing teams
        advancing = self.determine_advancing_teams(groups)
        
        if len(advancing) != 32:
            return False, f"Expected 32 advancing teams, got {len(advancing)}"
        
        # Perform the advancement
        logger.info("=" * 50)
        logger.info("GROUP STAGE COMPLETE - ADVANCING TO KNOCKOUT")
        logger.info("=" * 50)
        
        with app.app_context():
            from app import advance_to_knockout
            success, message = advance_to_knockout(advancing)
            
            if success:
                logger.info("✓ Successfully advanced to Round of 32!")
                logger.info(f"  {len(advancing)} teams advancing")
            else:
                logger.error(f"Failed to advance: {message}")
            
            return success, message
    
    def attempt_knockout_advancement(self) -> Tuple[bool, str]:
        """
        Check if current knockout round is complete and advance to next round.
        
        Knockout round progression:
        - Round of 32: 32 teams -> 16 matches -> 16 teams remain -> Round of 16
        - Round of 16: 16 teams -> 8 matches -> 8 teams remain -> Quarter-finals
        - Quarter-finals: 8 teams -> 4 matches -> 4 teams remain -> Semi-finals
        - Semi-finals: 4 teams -> 2 matches -> 2 winners + 2 losers (not eliminated) -> Third Place & Final
        - Third Place: 2 semi-final losers -> 1 match -> both eliminated -> Final ready
        - Final: 2 teams -> 1 match -> Champion crowned
        
        Returns:
            Tuple of (success, message)
        """
        with app.app_context():
            from app import Match as AppMatch, Team, set_current_round, ROUND_TEAM_LIMITS
            
            current_round = get_current_round()
            
            # Define round progression and match requirements
            knockout_progression = {
                "Round of 32": {
                    "matches_needed": 16,
                    "teams_after": 16,
                    "next_round": "Round of 16"
                },
                "Round of 16": {
                    "matches_needed": 8,
                    "teams_after": 8,
                    "next_round": "Quarter-finals"
                },
                "Quarter-finals": {
                    "matches_needed": 4,
                    "teams_after": 4,
                    "next_round": "Semi-finals"
                },
                "Semi-finals": {
                    "matches_needed": 2,
                    "teams_after": 4,  # 2 finalists + 2 semi-final losers (not eliminated yet)
                    "next_round": "Third Place"  # Third Place and Final happen in parallel
                },
                "Third Place": {
                    "matches_needed": 1,
                    "teams_after": 2,  # Only 2 finalists remain active
                    "next_round": "Final"
                },
                "Final": {
                    "matches_needed": 1,
                    "teams_after": 0,  # Tournament complete
                    "next_round": None
                }
            }
            
            if current_round not in knockout_progression:
                return False, f"Not in a knockout round (current: {current_round})"
            
            config = knockout_progression[current_round]
            
            # Count matches in current round
            round_matches = AppMatch.query.filter_by(round_name=current_round).count()
            
            if round_matches < config["matches_needed"]:
                return False, f"{current_round}: {round_matches}/{config['matches_needed']} matches played"
            
            # Count active teams
            active_teams = Team.query.filter_by(eliminated=False).count()
            
            # Special handling for Semi-finals
            # After semis, we have 2 finalists (not eliminated) + 2 semi-final losers (not eliminated, marked for 3rd place)
            if current_round == "Semi-finals":
                # Check that we have exactly 2 matches and 4 teams still "active" (2 finalists + 2 for 3rd place)
                semi_losers = Team.query.filter(
                    Team.eliminated == False,
                    Team.elimination_round == 'Semi-finals (Available for 3rd Place)'
                ).count()
                
                finalists = Team.query.filter(
                    Team.eliminated == False,
                    Team.elimination_round == ''
                ).count()
                
                if semi_losers != 2 or finalists != 2:
                    return False, f"Semi-finals not complete: {finalists} finalists, {semi_losers} 3rd place contenders"
                
                # Ready to advance - Third Place and Final can now be played
                logger.info("=" * 50)
                logger.info("SEMI-FINALS COMPLETE")
                logger.info("=" * 50)
                
                success, msg = set_current_round("Third Place", force=True)
                if success:
                    logger.info("✓ Advanced to Third Place / Final stage")
                    return True, "Advanced to Third Place match"
                else:
                    return False, f"Failed to advance: {msg}"
            
            # Special handling for Third Place
            elif current_round == "Third Place":
                # After 3rd place match, both participants should be eliminated
                # Only 2 finalists should remain active
                if active_teams != 2:
                    return False, f"Third Place not complete: {active_teams} teams still active (expected 2 finalists)"
                
                logger.info("=" * 50)
                logger.info("THIRD PLACE COMPLETE - READY FOR FINAL")
                logger.info("=" * 50)
                
                success, msg = set_current_round("Final", force=True)
                if success:
                    logger.info("✓ Advanced to Final")
                    return True, "Advanced to Final"
                else:
                    return False, f"Failed to advance: {msg}"
            
            # Special handling for Final
            elif current_round == "Final":
                # Check if final has been played (champion crowned)
                final_match = AppMatch.query.filter_by(round_name="Final").first()
                if final_match:
                    champion = Team.query.filter_by(elimination_round='Champion').first()
                    if champion:
                        logger.info("=" * 50)
                        logger.info(f"🏆 TOURNAMENT COMPLETE - {champion.country} ARE WORLD CHAMPIONS! 🏆")
                        logger.info("=" * 50)
                        return True, f"Tournament complete! {champion.country} are World Champions!"
                return False, "Final not yet played"
            
            # Standard knockout round advancement (R32, R16, QF)
            else:
                if active_teams != config["teams_after"]:
                    return False, f"{current_round}: {active_teams} teams active (need {config['teams_after']} for next round)"
                
                next_round = config["next_round"]
                
                logger.info("=" * 50)
                logger.info(f"{current_round.upper()} COMPLETE - ADVANCING TO {next_round.upper()}")
                logger.info("=" * 50)
                
                success, msg = set_current_round(next_round, force=True)
                if success:
                    logger.info(f"✓ Advanced to {next_round}")
                    return True, f"Advanced to {next_round}"
                else:
                    return False, f"Failed to advance: {msg}"

# ============================================
# MAIN SCRAPER
# ============================================

class WorldCupScraper:
    """Main scraper class that orchestrates fetching and processing"""
    
    def __init__(self, api_key: str):
        self.client = FootballDataClient(api_key)
        self.processor = MatchProcessor()
        self.standings_processor = StandingsProcessor(self.client)
        self.running = False
    
    def check_api_connection(self) -> bool:
        """Verify API connection and key are valid"""
        logger.info("Checking API connection...")
        
        data = self.client.get_competition()
        
        if data:
            logger.info(f"✓ Connected to Football-Data.org API")
            logger.info(f"  Competition: {data.get('name', 'Unknown')}")
            
            current_season = data.get('currentSeason', {})
            if current_season:
                logger.info(f"  Season: {current_season.get('startDate', '?')} to {current_season.get('endDate', '?')}")
            
            return True
        else:
            logger.error("✗ Failed to connect to API. Check your API key.")
            return False
    
    def run_once(self) -> int:
        """Run a single scrape cycle"""
        logger.info("Starting scrape cycle...")
        
        # Proactively check for any API team names that don't map to a
        # team in our database, so mismatches surface in the logs before
        # they silently block a match from being recorded.
        self.validate_team_names()
        
        # Get all finished matches
        matches = self.client.get_finished_matches()
        
        if matches is None:
            logger.error("Failed to fetch matches")
            return 0
        
        logger.info(f"Found {len(matches)} finished matches")
        
        # Process matches
        processed = self.processor.process_all_finished_matches(matches)
        
        logger.info(f"Processed {processed} new matches")
        
        # Check if we should automatically advance rounds
        with app.app_context():
            current_round = get_current_round()
        
        if current_round == "Group Stage":
            logger.info("Checking if group stage is complete for automatic advancement...")
            success, message = self.standings_processor.attempt_automatic_advancement()
            if success:
                logger.info(f"✓ Automatic advancement: {message}")
            else:
                logger.debug(f"Advancement check: {message}")
        else:
            # Check knockout round advancement
            logger.info(f"Checking if {current_round} is complete for automatic advancement...")
            success, message = self.standings_processor.attempt_knockout_advancement()
            if success:
                logger.info(f"✓ Automatic advancement: {message}")
            else:
                logger.debug(f"Advancement check: {message}")
        
        return processed
    
    def validate_team_names(self):
        """
        Scan all known World Cup matches and warn about any API team name
        that does not resolve (via normalize_team_name) to a team in our
        database. This catches API-vs-database naming mismatches (e.g.
        'Cape Verde Islands' vs 'Cabo Verde') early, before they silently
        block a match from being recorded.

        Returns the set of unmapped (API name, normalized name) pairs found.
        """
        try:
            matches = self.client.get_matches()
        except Exception as e:
            logger.debug(f"Team name validation skipped (could not fetch matches): {e}")
            return set()

        if not matches:
            return set()

        # Collect every distinct API team name appearing in the schedule
        api_names = set()
        for m in matches:
            home = m.get('homeTeam', {}).get('name')
            away = m.get('awayTeam', {}).get('name')
            if home:
                api_names.add(home)
            if away:
                api_names.add(away)

        # Knockout fixtures use placeholder names before teams are decided
        # (e.g. "Winner Group A", "Runner-up Group B", "1A", "Match 73").
        # Skip those so they don't generate false-positive warnings.
        def is_placeholder(name: str) -> bool:
            lowered = name.lower()
            placeholder_markers = ['winner', 'runner', 'loser', 'group ', 'match ',
                                   'tbd', 'third', '/', 'place ']
            if any(marker in lowered for marker in placeholder_markers):
                return True
            # Short alphanumeric slot codes like "1A", "2B", "W73"
            if len(name) <= 3 and any(ch.isdigit() for ch in name):
                return True
            return False

        unmapped = set()
        with app.app_context():
            for api_name in sorted(api_names):
                if is_placeholder(api_name):
                    continue
                normalized = normalize_team_name(api_name)
                team = Team.query.filter_by(country=normalized).first()
                if team is None:
                    unmapped.add((api_name, normalized))

        if unmapped:
            logger.warning("=" * 60)
            logger.warning(f"TEAM NAME MISMATCH(ES) DETECTED: {len(unmapped)} unmapped name(s)")
            logger.warning("These API team names do not match any team in the database.")
            logger.warning("Add a mapping in TEAM_NAME_MAP in scraper.py to fix:")
            for api_name, normalized in sorted(unmapped):
                logger.warning(f"  API: '{api_name}'  ->  normalized to: '{normalized}'  (NOT in database)")
            logger.warning("=" * 60)
        else:
            logger.debug("Team name validation: all match team names map correctly.")

        return unmapped
    
    def check_standings(self):
        """Manually check and display current standings"""
        logger.info("Fetching current standings...")
        
        groups = self.standings_processor.get_group_standings()
        
        if not groups:
            logger.error("Failed to fetch standings")
            return
        
        for group_letter in sorted(groups.keys()):
            teams = groups[group_letter]
            logger.info(f"\nGroup {group_letter}:")
            for team in teams:
                logger.info(f"  {team['position']}. {team['name']} - {team['points']} pts (GD: {team['goalDifference']}, P: {team['playedGames']})")
    
    def force_advancement_check(self):
        """Force an advancement check (for manual triggering)"""
        logger.info("Forcing advancement check...")
        
        with app.app_context():
            current_round = get_current_round()
        
        if current_round == "Group Stage":
            success, message = self.standings_processor.attempt_automatic_advancement()
        else:
            success, message = self.standings_processor.attempt_knockout_advancement()
        
        logger.info(f"Result: {message}")
        return success
    
    def run_continuous(self):
        """Run continuously, polling for updates"""
        logger.info(f"Starting continuous scraping (polling every {POLL_INTERVAL} seconds)")
        self.running = True
        
        while self.running:
            try:
                self.run_once()
                
                # Check for live matches to determine poll frequency
                live_matches = self.client.get_live_matches()
                
                if live_matches and len(live_matches) > 0:
                    logger.info(f"🔴 {len(live_matches)} live match(es) - checking more frequently")
                    wait_time = 60  # Poll every minute during live matches
                else:
                    wait_time = POLL_INTERVAL
                
                logger.info(f"Waiting {wait_time} seconds until next check...")
                time.sleep(wait_time)
                
            except KeyboardInterrupt:
                logger.info("Stopping scraper...")
                self.running = False
            except Exception as e:
                logger.error(f"Error in scrape cycle: {e}")
                time.sleep(60)  # Wait a minute before retrying
    
    def stop(self):
        """Stop the scraper"""
        self.running = False

# ============================================
# UTILITY FUNCTIONS
# ============================================

def verify_team_mapping():
    """Verify that all teams in the database can be found via the API"""
    logger.info("Verifying team name mappings...")
    
    with app.app_context():
        db_teams = [t.country for t in Team.query.all()]
    
    client = FootballDataClient(API_KEY)
    data = client._request(f"/competitions/{COMPETITION_CODE}/teams")
    
    if not data or 'teams' not in data:
        logger.error("Could not fetch teams from API")
    else:
        api_teams = [normalize_team_name(t['name']) for t in data['teams']]
        
        # Find mismatches
        missing_in_api = set(db_teams) - set(api_teams)
        missing_in_db = set(api_teams) - set(db_teams)
        
        if missing_in_api:
            logger.warning(f"Teams in DB but not in API: {missing_in_api}")
            logger.warning("Add these to TEAM_NAME_MAP in scraper.py")
        
        if missing_in_db:
            logger.info(f"Teams in API but not in DB: {missing_in_db}")
        
        if not missing_in_api and not missing_in_db:
            logger.info("✓ All team names from /teams endpoint match!")
    
    # Also check team names as they appear in actual match fixtures - this
    # is where mismatches like 'Cape Verde Islands' actually show up.
    logger.info("Checking team names in match fixtures...")
    scraper = WorldCupScraper(API_KEY)
    unmapped = scraper.validate_team_names()
    if not unmapped:
        logger.info("✓ All match fixture team names map correctly!")

def show_upcoming_matches():
    """Display upcoming matches"""
    client = FootballDataClient(API_KEY)
    matches = client.get_todays_matches()
    
    if not matches:
        logger.info("No matches scheduled for today")
        return
    
    logger.info(f"\n{'='*60}")
    logger.info("TODAY'S MATCHES")
    logger.info(f"{'='*60}")
    
    for match in matches:
        home = match['homeTeam']['name']
        away = match['awayTeam']['name']
        status = match['status']
        time_str = match.get('utcDate', 'TBD')
        
        if status == 'FINISHED':
            score = match['score']['fullTime']
            logger.info(f"✓ {home} {score['home']}-{score['away']} {away} (FINISHED)")
        elif status in ['IN_PLAY', 'PAUSED']:
            score = match['score']['fullTime']
            logger.info(f"🔴 {home} {score['home']}-{score['away']} {away} (LIVE)")
        else:
            logger.info(f"⏳ {home} vs {away} ({time_str})")

# ============================================
# MAIN ENTRY POINT
# ============================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='World Cup 2026 Live Match Scraper')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--verify', action='store_true', help='Verify team name mappings')
    parser.add_argument('--upcoming', action='store_true', help='Show upcoming matches')
    parser.add_argument('--standings', action='store_true', help='Show current group standings')
    parser.add_argument('--advance', action='store_true', help='Force advancement check')
    parser.add_argument('--api-key', type=str, help='Football-Data.org API key')
    
    args = parser.parse_args()
    
    # Set API key if provided
    global API_KEY
    if args.api_key:
        API_KEY = args.api_key
    
    if API_KEY == 'YOUR_API_KEY_HERE':
        logger.error("Please set your Football-Data.org API key!")
        logger.error("Either set FOOTBALL_DATA_API_KEY environment variable")
        logger.error("Or pass it with --api-key argument")
        logger.error("Get a free key at: https://www.football-data.org/client/register")
        sys.exit(1)
    
    # Initialize scraper
    scraper = WorldCupScraper(API_KEY)
    
    # Check API connection
    if not scraper.check_api_connection():
        sys.exit(1)
    
    # Run requested mode
    if args.verify:
        verify_team_mapping()
    elif args.upcoming:
        show_upcoming_matches()
    elif args.standings:
        scraper.check_standings()
    elif args.advance:
        scraper.force_advancement_check()
    elif args.once:
        scraper.run_once()
    else:
        scraper.run_continuous()

if __name__ == '__main__':
    main()
