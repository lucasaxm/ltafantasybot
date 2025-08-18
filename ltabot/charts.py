"""
Chart generation utilities for LTA Fantasy Bot.
"""
import io
from typing import Dict, List, Tuple, Any, Optional
from .config import logger

try:
    import matplotlib.pyplot as plt
    import matplotlib.style as style
    import seaborn as sns
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False
    logger.warning("Charts not available: matplotlib/seaborn not installed")


def generate_race_chart(teams_data: Dict[str, Dict[int, float]]) -> Optional[io.BytesIO]:
    """
    Generate a mobile-friendly race chart showing team progression across rounds.
    
    Args:
        teams_data: Dict[team_name, Dict[round_index, cumulative_score]]
        
    Returns:
        BytesIO buffer containing the PNG image, or None if error
    """
    if not CHARTS_AVAILABLE:
        logger.warning("Charts not available: matplotlib/seaborn not installed")
        return None
        
    try:
        # Set a clean style optimized for mobile
        plt.style.use('default')
        sns.set_palette("husl")
        
        # Create the plot with vertical mobile-friendly settings
        plt.figure(figsize=(8, 10))  # More vertical aspect ratio for mobile
        
        # Plot lines for each team with mobile-optimized styling
        for team_name, round_data in teams_data.items():
            rounds = list(round_data.keys())
            scores = list(round_data.values())
            plt.plot(rounds, scores, marker='o', linewidth=3.5, markersize=8, label=team_name)
        
        # Mobile-friendly styling
        plt.xlabel('Round', fontsize=16, fontweight='bold')
        plt.ylabel('Points', fontsize=16, fontweight='bold')
        plt.grid(True, alpha=0.3)
        plt.legend(loc='lower right', fontsize=14, framealpha=0.9)
        
        # Force integer ticks on x-axis (no half rounds)
        if teams_data:
            max_round = max(max(rounds.keys()) for rounds in teams_data.values())
            plt.xticks(range(1, max_round + 1), fontsize=14)
        
        # Larger tick labels for mobile readability
        plt.yticks(fontsize=14)
        
        # Tight layout to maximize chart area
        plt.tight_layout()
        
        # Save to BytesIO buffer
        buffer = io.BytesIO()
        plt.savefig(buffer, format='PNG', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        plt.close()  # Clean up the figure
        
        logger.info(f"Generated race chart for {len(teams_data)} teams")
        return buffer
        
    except Exception as e:
        logger.error(f"Failed to generate race chart: {e}")
        plt.close()  # Clean up any partial figure
        return None


async def get_all_teams_round_stats(session, league: str) -> Dict[str, Dict[int, float]]:
    """
    Get comprehensive round statistics for all teams in a league.
    
    Returns:
        Dict[team_name, Dict[round_index, cumulative_score]]
    """
    from .api import get_rounds, get_league_ranking, get_user_team_round_stats, get_team_round_roster, pick_latest_round
    
    try:
        # Get team list from latest round
        rounds = await get_rounds(session, league)
        if not rounds:
            return {}
        
        latest_round = pick_latest_round(rounds)
        if not latest_round:
            return {}
            
        ranking = await get_league_ranking(session, league, latest_round["id"])
        if not ranking:
            return {}
            
        # Build team list with IDs and names
        teams_info = [(item["userTeam"]["id"], item["userTeam"]["name"]) for item in ranking]
        
        teams_data: Dict[str, Dict[int, float]] = {}
        
        for team_id, team_name in teams_info:
            try:
                # Get all round stats for this team
                round_stats = await get_user_team_round_stats(session, team_id)
                
                team_progression = {}
                cumulative_score = 0.0
                
                for round_stat in round_stats:
                    round_status = round_stat.get("status", "")
                    if round_status in ["completed", "in_progress"]:
                        round_index = round_stat.get("indexInSplit", 0) + 1  # 1-based indexing for display
                        
                        # For completed rounds, use the score from round-stats
                        # For in_progress rounds, score will be null, so get live score
                        score = round_stat.get("score")
                        if score is not None:
                            cumulative_score += float(score)
                        elif round_status == "in_progress":
                            # Get live score for in_progress round
                            try:
                                round_id = round_stat["id"]
                                roster = await get_team_round_roster(session, round_id, team_id)
                                rr = roster.get("roundRoster") or {}
                                live_pts = rr.get("pointsPartial")
                                if live_pts is None:
                                    live_pts = rr.get("points") or 0.0
                                cumulative_score += float(live_pts)
                            except Exception as e:
                                logger.warning(f"Could not get live score for team {team_name} in round {round_id}: {e}")
                        
                        team_progression[round_index] = cumulative_score
                
                teams_data[team_name] = team_progression
                
            except Exception as e:
                logger.warning(f"Could not get round stats for team {team_name} ({team_id}): {e}")
                teams_data[team_name] = {}
        
        logger.info(f"Retrieved round stats for {len(teams_data)} teams")
        return teams_data
        
    except Exception as e:
        logger.error(f"Failed to get all teams round stats: {e}")
        return {}
