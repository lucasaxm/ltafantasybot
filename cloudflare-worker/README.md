# Cloudflare Worker Proxy for CBLOL Fantasy Bot

This Cloudflare Worker acts as a proxy to bypass Cloudflare challenges that may block VPS deployments from directly accessing the CBLOL Fantasy API.

## When Do You Need This?

If you're running the CBLOL Fantasy Bot on a VPS and encounter Cloudflare challenges that block direct API access, this worker provides a solution by proxying requests with the correct headers.

## How It Works

The worker:
- Receives requests from your bot
- Forwards them to the CBLOL Fantasy API with Bruno runtime headers
- Returns the API response back to your bot
- Only allows specific API paths for security
- Automatically forwards session tokens for authentication

## Setup

### Prerequisites

- A Cloudflare account
- Node.js and npm installed locally

### Installation

1. **Navigate to the worker directory**:
   ```bash
   cd cloudflare-worker
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Login to Cloudflare**:
   ```bash
   npx wrangler login
   ```

4. **Deploy the worker**:
   ```bash
   npm run deploy
   ```

5. **Get your worker URL**:
   After deployment, you'll see output like:
   ```
   ✅ Deployment complete! Take a flight over to https://cblol-fantasy-proxy.your-subdomain.workers.dev
   ```

6. **Configure your bot**:
   Update your bot's `.env` file to use the worker URL:
   ```bash
   LTA_API_URL=https://cblol-fantasy-proxy.your-subdomain.workers.dev
   ```

## Available Scripts

```bash
# Deploy worker to Cloudflare
npm run deploy

# Test worker locally (useful for development)
npm run dev

# View live logs from deployed worker
npm run tail
```

## Security Features

- **Path Filtering**: Only allows specific API endpoints needed by the bot
- **Header Forwarding**: Properly forwards authentication tokens
- **CORS Support**: Includes proper CORS headers for browser compatibility

## Allowed API Paths

The worker only proxies these specific paths for security:
- `/leagues/` - League information, rounds, and rankings
- `/rosters/per-round/` - Team rosters and scores per round
- `/user-teams/` - User team round statistics (primary endpoint for round data)
- `/users/me` - User profile endpoint for authentication testing

## Configuration

The worker is configured via `wrangler.toml`:
- **name**: `cblol-fantasy-proxy` (you can customize this)
- **compatibility_date**: Uses Cloudflare Workers runtime features
- **main**: Points to `worker.js` as the entry point

## Troubleshooting

### Worker not deploying
- Ensure you're logged in: `npx wrangler login`
- Check your Cloudflare account has Workers enabled
- Verify `wrangler.toml` configuration is correct

### Bot still getting blocked
- Check that you've updated `LTA_API_URL` in your bot's `.env` file
- Verify the worker URL is accessible by testing it in a browser
- Check worker logs: `npm run tail`

### Testing the Worker

You can test the worker by making a request to test the `/users/me` endpoint:

```bash
curl -H "x-session-token: YOUR_SESSION_TOKEN" https://your-worker.workers.dev/users/me
```

## Development

To modify the worker:

1. Edit `worker.js` with your changes
2. Test locally: `npm run dev`
3. Deploy: `npm run deploy`

The worker code is well-documented and follows security best practices by only allowing specific API paths and properly handling authentication headers.
