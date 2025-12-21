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
    'Cabo Verde Islands': 'Cabo Verde',
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
                logger.warning("Rate limited. Waiting 60 seconds...")
                time.sleep(60)
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

# ============================================
# MATCH PROCESSOR
# ============================================

class MatchProcessor:
    """Processes API match data and updates the tournament database"""
    
    def __init__(self):
        self.processed_matches = self._load_processed_matches()
    
    def _load_processed_matches(self) -> set:
        """Load set of already processed match IDs"""
        try:
            with open('processed_matches.json', 'r') as f:
                return set(json.load(f))
        except FileNotFoundError:
            return set()
    
    def _save_processed_matches(self):
        """Save processed match IDs to file"""
        with open('processed_matches.json', 'w') as f:
            json.dump(list(self.processed_matches), f)
    
    def _get_match_result(self, match: dict) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Extract match result from API data
        
        Returns:
            Tuple of (winner_name, loser_name, is_draw)
            For draws: (team1_name, team2_name, True)
        """
        home_team = normalize_team_name(match['homeTeam']['name'])
        away_team = normalize_team_name(match['awayTeam']['name'])
        
        score = match.get('score', {})
        
        # Get the final score (handle extra time and penalties)
        # Priority: penalties > extraTime > fullTime > halfTime
        final_score = None
        for score_type in ['penalties', 'extraTime', 'fullTime']:
            if score.get(score_type) and score[score_type].get('home') is not None:
                final_score = score[score_type]
                break
        
        if not final_score:
            logger.warning(f"No score found for match {match['id']}")
            return None, None, False
        
        home_goals = final_score['home']
        away_goals = final_score['away']
        
        if home_goals > away_goals:
            return home_team, away_team, False  # Home team wins
        elif away_goals > home_goals:
            return away_team, home_team, False  # Away team wins
        else:
            # Check if there was a penalty shootout winner
            if score.get('penalties') and score['penalties'].get('home') is not None:
                pen_home = score['penalties']['home']
                pen_away = score['penalties']['away']
                if pen_home > pen_away:
                    return home_team, away_team, False
                elif pen_away > pen_home:
                    return away_team, home_team, False
            
            # It's a draw (only valid in group stage)
            return home_team, away_team, True
    
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
        
        # Record the match
        with app.app_context():
            if is_draw:
                success, message = record_draw(winner, loser)  # winner/loser are team1/team2 for draws
                result_type = "draw"
            else:
                success, message = record_match(winner, loser)
                result_type = "win"
            
            if success:
                self.processed_matches.add(match_id)
                self._save_processed_matches()
                
                home_team = normalize_team_name(match['homeTeam']['name'])
                away_team = normalize_team_name(match['awayTeam']['name'])
                score_str = f"{match['score']['fullTime']['home']}-{match['score']['fullTime']['away']}"
                
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
            # Only process group stage standings
            if standing.get('stage') != 'GROUP_STAGE':
                continue
            if standing.get('type') != 'TOTAL':
                continue
            
            group_name = standing.get('group', '')
            # Extract group letter (e.g., 'GROUP_A' -> 'A')
            if group_name.startswith('GROUP_'):
                group_letter = group_name.replace('GROUP_', '')
            else:
                group_letter = group_name
            
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
            return False, "Failed to fetch standings from API"
        
        # Check if all groups are complete
        if not self.check_group_stage_complete(groups):
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
        
        # Get all finished matches
        matches = self.client.get_finished_matches()
        
        if matches is None:
            logger.error("Failed to fetch matches")
            return 0
        
        logger.info(f"Found {len(matches)} finished matches")
        
        # Process matches
        processed = self.processor.process_all_finished_matches(matches)
        
        logger.info(f"Processed {processed} new matches")
        
        # Check if we should automatically advance to knockout rounds
        with app.app_context():
            current_round = get_current_round()
        
        if current_round == "Group Stage":
            logger.info("Checking if group stage is complete for automatic advancement...")
            success, message = self.standings_processor.attempt_automatic_advancement()
            if success:
                logger.info(f"✓ Automatic advancement: {message}")
            else:
                logger.debug(f"Advancement check: {message}")
        
        return processed
    
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
        success, message = self.standings_processor.attempt_automatic_advancement()
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
        return
    
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
        logger.info("✓ All team names match!")

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
