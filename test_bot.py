#!/usr/bin/env python3
"""
LTA Fantasy Bot Test Suite
Tests API connectivity and basic bot functionality
"""

import sys
import os
import asyncio
import traceback
from pathlib import Path
import pytest

# Add current directory to path for bot imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from ltabot import BASE, make_session, fetch_json
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file for testing
except ImportError as e:
    print(f"❌ Failed to import required modules: {e}")
    print("Make sure you're in the correct directory and all dependencies are installed")
    print("Try: pip install python-dotenv")
    sys.exit(1)


def test_environment_variables():
    """Test that required environment variables are configured"""
    print("🔧 Testing environment configuration...")
    
    required_vars = {
        'BOT_TOKEN': 'Telegram Bot Token',
        'ALLOWED_USER_ID': 'Allowed Telegram User ID',
        'X_SESSION_TOKEN': 'LTA Fantasy Session Token'
    }
    
    missing_vars = []
    
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            print(f"  ❌ {var} ({description}) - Not set")
            missing_vars.append(var)
        else:
            # Mask sensitive tokens for security
            if 'TOKEN' in var:
                masked_value = f"{value[:8]}...{value[-8:]}" if len(value) > 16 else "***"
                print(f"  ✅ {var} - {masked_value}")
            else:
                print(f"  ✅ {var} - {value}")
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file")
        assert False, f"Missing environment variables: {', '.join(missing_vars)}"
    else:
        print("✅ All required environment variables are configured")


@pytest.mark.asyncio
async def test_lta_authentication():
    """Test LTA Fantasy API authentication using /users/me endpoint"""
    print("🔐 Testing LTA Fantasy authentication...")
    
    session = make_session()
    try:
        # Test the user profile endpoint - better than /leagues/active
        user_data = await fetch_json(session, f'{BASE}/users/me')
        
        assert user_data is not None, "No response from LTA API"
        assert 'data' in user_data, "Invalid response format from /users/me endpoint"
        
        user_info = user_data['data']
        display_name = user_info.get('riotGameName', 'Unknown')
        tag_line = user_info.get('riotTagLine', 'Unknown')
        user_id = user_info.get('id', 'Unknown')[:8] + '...'  # Mask user ID
        
        print(f'✅ Authenticated as: {display_name}#{tag_line} (ID: {user_id})')
        print('✅ LTA Fantasy API authentication successful')
            
    except Exception as e:
        error_msg = str(e)
        if '401' in error_msg or 'Unauthorized' in error_msg:
            print('❌ Authentication failed - Session token invalid or expired')
            print('Please update your X_SESSION_TOKEN in .env file')
            pytest.fail("LTA API authentication failed - invalid session token")
        elif '404' in error_msg:
            print('❌ Endpoint not found - Check if worker supports /users/me')
            pytest.fail("LTA API endpoint not found")
        else:
            print(f'❌ LTA API authentication issue: {error_msg}')
            pytest.fail(f"LTA API error: {error_msg}")
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_telegram_bot_token():
    """Test Telegram Bot token validity by calling getMe API"""
    print("🤖 Testing Telegram Bot API connection...")
    
    bot_token = os.getenv('BOT_TOKEN')
    assert bot_token, "BOT_TOKEN not configured"
    
    # Basic token format validation
    assert ':' in bot_token and len(bot_token.split(':')) == 2, "BOT_TOKEN format invalid (should be ID:SECRET)"
    
    # Test actual connection to Telegram API using getMe
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    assert data.get('ok'), f"Telegram API returned error: {data.get('description', 'Unknown error')}"
                    
                    bot_info = data.get('result', {})
                    username = bot_info.get('username', 'Unknown')
                    first_name = bot_info.get('first_name', 'Unknown')
                    bot_id = bot_info.get('id', 'Unknown')
                    
                    print("✅ Connected to Telegram API successfully")
                    print(f"✅ Bot: @{username} ({first_name}) - ID: {bot_id}")
                    
                elif response.status == 401:
                    print("❌ Invalid bot token - Telegram API returned 401 Unauthorized")
                    print("Please check your BOT_TOKEN in .env file")
                    pytest.fail("Invalid bot token")
                else:
                    pytest.fail(f"Telegram API request failed with status {response.status}")
                    
    except Exception as e:
        print(f"❌ Failed to connect to Telegram API: {e}")
        pytest.fail(f"Telegram API connection error: {e}")



def test_imports():
    """Test that all required modules can be imported"""
    print("📦 Testing module imports...")
    
    required_modules = [
        'os',
        'sys',
        'aiohttp',
        'dotenv',
        'asyncio',
        'json',
        'logging'
    ]
    
    failed_imports = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except ImportError:
            print(f"  ❌ {module}")
            failed_imports.append(module)
    
    assert not failed_imports, f"Missing dependencies: {', '.join(failed_imports)}"
    print("✅ All required modules imported successfully")


def test_bot_configuration():
    """Test bot configuration and environment variables"""
    print("⚙️ Testing bot configuration...")
    
    # Check if BASE URL is configured
    assert BASE, "Base URL not configured"
    print(f"  ✅ Base URL: {BASE}")
    
    # Check for other important configuration
    # These are functions, so we check if they're callable
    assert callable(make_session), "make_session function not available"
    assert callable(fetch_json), "fetch_json function not available"
    
    print("✅ Bot configuration looks good")


@pytest.mark.asyncio
async def test_session_creation():
    """Test that we can create and close HTTP sessions properly"""
    print("🔗 Testing session management...")
    
    session = make_session()
    assert session is not None, "Failed to create session"
    print("  ✅ Session created successfully")
    
    await session.close()
    print("  ✅ Session closed successfully")


# Note: This file is now configured for pytest usage
# Run with: pytest test_bot.py -v


async def run_all_tests():
    """Run all tests and return overall status"""
    print("🧪 Starting LTA Fantasy Bot Test Suite")
    print("=" * 50)
    
    tests = [
        ("Environment Variables Test", test_environment_variables, False),  # Synchronous
        ("Import Test", test_imports, False),  # Synchronous
        ("Bot Configuration Test", test_bot_configuration, False),  # Synchronous
        ("Telegram Bot Token Test", test_telegram_bot_token, True),  # Async
        ("Session Management Test", test_session_creation, True),  # Async
        ("LTA Authentication Test", test_lta_authentication, True),  # Async
    ]
    
    results = []
    
    for test_name, test_func, is_async in tests:
        print(f"\n🔍 Running {test_name}...")
        try:
            if is_async:
                await test_func()
            else:
                test_func()
            results.append((test_name, True))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            print("Traceback:")
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results Summary:")
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {test_name}")
        if result:
            passed += 1
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Bot is ready to run.")
        return True
    else:
        print("⚠️ Some tests failed. Please check the issues above.")
        return False


if __name__ == "__main__":
    # Run tests
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {e}")
        traceback.print_exc()
        sys.exit(1)
