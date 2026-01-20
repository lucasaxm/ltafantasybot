#!/usr/bin/env python3
"""
Quick verification script to test CBLOL Fantasy API migration
Tests the new API endpoints with the token from the attached request
"""

import asyncio
from ltabot import make_session, fetch_json, BASE
from ltabot.config import logger

async def verify_migration():
    """Verify that all critical endpoints work with CBLOL API"""
    
    print(f"🔍 Verifying CBLOL Fantasy API migration...")
    print(f"📡 API Base URL: {BASE}\n")
    
    session = make_session()
    
    try:
        # Test 1: User authentication
        print("1️⃣  Testing /users/me endpoint...")
        user_data = await fetch_json(session, f'{BASE}/users/me')
        if user_data and 'data' in user_data:
            user = user_data['data']
            print(f"   ✅ Authenticated as: {user.get('riotGameName')}#{user.get('riotTagLine')}\n")
        else:
            print("   ❌ Failed to get user data\n")
            return False
        
        # Test 2: Get rounds (use the league slug from the attached request)
        print("2️⃣  Testing /leagues/{slug}/rounds endpoint...")
        league_slug = "regata-hk3pujmlpw"  # From the example request
        rounds_data = await fetch_json(session, f'{BASE}/leagues/{league_slug}/rounds')
        if rounds_data and 'data' in rounds_data:
            rounds = rounds_data['data']
            print(f"   ✅ Found {len(rounds)} rounds")
            for r in rounds[:2]:  # Show first 2
                print(f"      - {r.get('name')} ({r.get('status')}) - Split: {r.get('splitName', 'N/A')}")
            print()
        else:
            print("   ❌ Failed to get rounds\n")
            return False
        
        # Test 3: Get ranking
        print("3️⃣  Testing /leagues/{slug}/ranking endpoint...")
        latest_round = rounds[0] if rounds else None
        if latest_round:
            round_id = latest_round['id']
            ranking_data = await fetch_json(
                session, 
                f'{BASE}/leagues/{league_slug}/ranking',
                params={"roundId": round_id, "orderBy": "split_score"}
            )
            if ranking_data and 'data' in ranking_data:
                ranking = ranking_data['data']
                print(f"   ✅ Retrieved ranking with {len(ranking)} teams")
                print(f"      Top team: {ranking[0]['userTeam']['name']} ({ranking[0]['score']:.2f} pts)\n")
            else:
                print("   ❌ Failed to get ranking\n")
                return False
        
        # Test 4: Get roster (with coach!)
        print("4️⃣  Testing /rosters/per-round/{roundId}/{teamId} endpoint...")
        if ranking:
            team_id = ranking[0]['userTeam']['id']
            # Use a completed round to ensure we have data
            completed_rounds = [r for r in rounds if r.get('status') == 'completed']
            if completed_rounds:
                test_round_id = completed_rounds[0]['id']
                roster_data = await fetch_json(
                    session,
                    f'{BASE}/rosters/per-round/{test_round_id}/{team_id}'
                )
                if roster_data and 'data' in roster_data:
                    roster_players = roster_data['data'].get('rosterPlayers', [])
                    print(f"   ✅ Retrieved roster with {len(roster_players)} players")
                    
                    # Check for coach role
                    coach = next((p for p in roster_players if p.get('role') == 'coach'), None)
                    if coach:
                        coach_name = coach.get('roundEsportsPlayer', {}).get('proPlayer', {}).get('name', 'Unknown')
                        coach_pts = coach.get('pointsPartial', 0)
                        print(f"      👔 Coach found: {coach_name} ({coach_pts:.2f} pts)")
                        print(f"      ✅ Coach role successfully supported!")
                    else:
                        print(f"      ⚠️  Warning: No coach role found in roster")
                    
                    # Show all roles
                    roles = [p.get('role') for p in roster_players]
                    print(f"      Roles: {', '.join(roles)}\n")
                else:
                    print("   ❌ Failed to get roster\n")
                    return False
        
        # Test 5: User team stats
        print("5️⃣  Testing /user-teams/{id}/round-stats endpoint...")
        if ranking:
            user_team_id = ranking[0]['userTeam']['id']
            stats_data = await fetch_json(session, f'{BASE}/user-teams/{user_team_id}/round-stats')
            if stats_data and 'data' in stats_data:
                stats = stats_data['data']
                print(f"   ✅ Retrieved stats for {len(stats)} rounds")
                if stats:
                    print(f"      Latest: {stats[0].get('name')} - {stats[0].get('score', 'N/A')} pts\n")
            else:
                print("   ❌ Failed to get user team stats\n")
                return False
        
        print("=" * 60)
        print("🎉 All CBLOL Fantasy API endpoints working correctly!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await session.close()

if __name__ == "__main__":
    success = asyncio.run(verify_migration())
    exit(0 if success else 1)
