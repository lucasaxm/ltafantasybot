# CBLOL Fantasy Migration Plan

## Executive Summary

Migration from LTA Fantasy (api.ltafantasy.com) to CBLOL Fantasy (api.cblol.gg) for the 2026 first split. Key changes: new API domain, addition of coach as 6th roster position, and minor field changes.

## API Endpoints Comparison

### ✅ No Changes Required (Same Structure)

1. **GET /leagues/{slug}/rounds**
   - ✅ Response structure identical
   - ✅ Status values: `market_open`, `in_progress`, `completed`, `upcoming`
   - ✅ Fields: `id`, `name`, `status`, `indexInSplit`, `marketOpensAt`, `marketClosesAt`, `splitId`
   - **NEW**: Added `splitName` field (e.g., "Split 1 2026")
   - **NEW**: Added `isOpen` boolean field

2. **GET /leagues/{slug}/ranking**
   - ✅ Query params: `roundId`, `orderBy=split_score`
   - ✅ Response structure identical
   - ✅ Fields: `score`, `rank`, `userTeam{id, name, ownerName, etc.}`

3. **GET /rosters/per-round/{roundId}/{teamId}**
   - ✅ Response structure maintained
   - ⚠️ **BREAKING**: Now returns 6 players instead of 5
   - ⚠️ **NEW ROLE**: `coach` role added (6th pick)
   - ✅ Fields: `rosterPlayers[]`, `round`, `roundRoster`

4. **GET /user-teams/{id}/round-stats**
   - ✅ Response structure identical
   - ✅ Fields: `id`, `name`, `indexInSplit`, `status`, `score`, `participated`

5. **GET /users/me**
   - ✅ Response structure identical
   - ✅ Fields: `id`, `riotPuuid`, `riotGameName`, `isVerified`

## Code Changes Required

### 1. Configuration Updates (PRIORITY: HIGH)

**File: `ltabot/config.py`**

```python
# Change default API URL
LTA_API_URL: str = os.getenv("LTA_API_URL", "https://api.cblol.gg").strip()
```

**File: `.env`** (user configuration)
```bash
# Update default API URL
LTA_API_URL=https://api.cblol.gg

# Update session token (users must get new token from cblol.gg)
X_SESSION_TOKEN=<new_cblol_session_token>
```

### 2. Roster Format Updates (PRIORITY: HIGH)

**File: `ltabot/formatting.py`**

**Line 142-143**: Add coach to role mappings
```python
# OLD
role_emojis = {"top": "⚔️", "jungle": "🌿", "mid": "🔮", "bottom": "🏹", "support": "🛡️"}
role_order = ["top", "jungle", "mid", "bottom", "support"]

# NEW
role_emojis = {"top": "⚔️", "jungle": "🌿", "mid": "🔮", "bottom": "🏹", "support": "🛡️", "coach": "👔"}
role_order = ["top", "jungle", "mid", "bottom", "support", "coach"]
```

**Line 306**: Add coach to role_order
```python
# OLD
role_order = ["top", "jungle", "mid", "bottom", "support"]

# NEW
role_order = ["top", "jungle", "mid", "bottom", "support", "coach"]
```

### 3. Coach Champion ID Handling (PRIORITY: MEDIUM)

**File: `ltabot/formatting.py`**

**Line ~165 (format_player_section)**: Skip champion display for coach
```python
# Add condition to skip champion pick for coach role
if owner_champion_id and role != "coach":
    # existing champion pick logic
```

**Reasoning**: Coaches have `championId: "-1"` and no games array, so champion lookup is not applicable.

### 4. Documentation Updates (PRIORITY: LOW)

**File: `README.md`**
- Update all references from "LTA Fantasy" to "CBLOL Fantasy"
- Update API domain references
- Update example league slugs (e.g., `regata-hk3pujmlpw`)
- Add note about coach as 6th pick

**File: `AGENTS.md`**
- Update project overview description
- Update API endpoint examples
- Add coach role to roster examples

### 5. Cloudflare Worker Updates (PRIORITY: MEDIUM)

**File: `cloudflare-worker/worker.js`**

Update target API domain:
```javascript
// OLD
const API_BASE = 'https://api.ltafantasy.com';

// NEW
const API_BASE = 'https://api.cblol.gg';
```

Also update any hardcoded headers or domain-specific logic.

### 6. Wiremock Test Data (PRIORITY: LOW)

**Files: `wiremock/__files/*.json`**

Update all mock responses to:
- Include 6 roster players with coach role
- Add new fields: `splitName`, `isOpen` to round responses
- Use CBLOL-like team names and IDs for testing

## Breaking Changes Summary

### User Impact
1. **Session Token**: Users MUST obtain new session token from cblol.gg
2. **League Slugs**: Old LTA league slugs won't work; users need new CBLOL league slugs
3. **Roster Display**: Team display now shows 6 players including coach

### Bot Behavior
1. **Points Calculation**: Coach points are now included in team totals
2. **Champion Picks**: Coach has no champion pick (championId: "-1")
3. **Price Tracking**: Coach prices are tracked like other positions

## Migration Steps

### Phase 1: Code Updates (Immediate)
1. ✅ Test API endpoints (COMPLETED)
2. ⬜ Update config.py default API URL
3. ⬜ Update formatting.py role mappings (2 locations)
4. ⬜ Add coach champion handling in format_player_section
5. ⬜ Update cloudflare-worker API domain

### Phase 2: Documentation (Immediate)
1. ⬜ Update README.md
2. ⬜ Update AGENTS.md
3. ⬜ Create migration notice for users

### Phase 3: Testing (Before Deployment)
1. ⬜ Update wiremock test data
2. ⬜ Run test suite with new API
3. ⬜ Test with real CBLOL league
4. ⬜ Verify watcher state transitions
5. ⬜ Test all commands with coach roster

### Phase 4: Deployment
1. ⬜ Deploy cloudflare worker (if used)
2. ⬜ Update .env on VPS with new API URL and token
3. ⬜ Restart bot
4. ⬜ Monitor logs for errors
5. ⬜ Notify users about migration

## Testing Checklist

- [ ] `/scores <league>` shows 6 players including coach
- [ ] Coach points are included in total
- [ ] Coach has no champion pick displayed
- [ ] Watcher transitions work (PRE_MARKET → MARKET_OPEN → LIVE)
- [ ] Reminders trigger correctly (1h, 24h before market close)
- [ ] Charts generation works with 6 players
- [ ] Price changes tracked for coach
- [ ] Round completion detection works
- [ ] Split rankings calculated correctly

## API Field Changes Reference

### New Fields in Rounds Response
```json
{
  "splitName": "Split 1 2026",  // NEW
  "isOpen": true               // NEW
}
```

### Coach Player Structure
```json
{
  "role": "coach",
  "championId": "-1",          // Always -1 for coach
  "points": 27.332,
  "pointsPartial": 27.33,
  "games": []                  // Always empty for coach
}
```

## Risks & Mitigations

### Risk 1: Session Token Expiry
**Impact**: High - Bot won't work
**Mitigation**: Document how to get new token, implement `/auth` command reminder

### Risk 2: API Rate Limiting
**Impact**: Medium - Potential polling issues
**Mitigation**: Keep current caching strategy (TTL cache with 80% of poll interval)

### Risk 3: Roster Length Assumptions
**Impact**: Medium - Code expecting 5 players might break
**Mitigation**: Code review for hardcoded length checks, use dynamic iteration

### Risk 4: Champion Data for Coach
**Impact**: Low - Champion lookup will fail for championId "-1"
**Mitigation**: Add role check before champion name lookup

## Compatibility Notes

- ✅ Python 3.8+ compatibility maintained
- ✅ Telegram Bot API version unchanged
- ✅ State file formats unchanged (`group_settings.json`, `runtime_state.json`)
- ✅ Watcher phase enum unchanged
- ✅ Polling/backoff logic unchanged

## Post-Migration Monitoring

1. Monitor error logs for API 404s or 401s
2. Check watcher status transitions
3. Verify reminder scheduling works
4. Confirm chart generation with 6 players
5. Watch for cache-related issues

---

**Migration Prepared**: January 20, 2026
**Status**: Ready for implementation
