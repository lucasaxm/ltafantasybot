/**
 * Cloudflare Worker Proxy for CBLOL Fantasy API
 * 
 * This worker acts as a proxy to bypass Cloudflare challenges that
 * may block VPS deployments from directly accessing the CBLOL Fantasy API.
 * 
 * It forwards only allowed API paths with the correct Bruno runtime
 * headers that bypass Cloudflare's bot detection.
 */

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url);
  
  // Security: Only allow specific API paths we need
  const allowedPaths = [
    '/leagues/',          // League information and rounds
    '/rosters/per-round/', // Team rosters and scores
    '/user-teams/',       // User team round statistics
    '/users/me'           // User profile endpoint for authentication testing
  ];
  
  const isAllowed = allowedPaths.some(path => url.pathname.startsWith(path));
  if (!isAllowed) {
    return new Response('Path not allowed', { status: 403 });
  }
  
  // Build the target URL for CBLOL Fantasy API
  const targetUrl = `https://api.cblol.gg${url.pathname}${url.search}`;
  
  // Forward request with Bruno runtime headers that bypass Cloudflare
  const headers = {
    'Accept': '*/*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'User-Agent': 'bruno-runtime/2.9.0',  // Key header for bypass
    'Origin': 'https://cblol.gg',
    'Referer': 'https://cblol.gg/',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
    'DNT': '1'
  };
  
  // Forward x-session-token if present (required for authenticated endpoints)
  const sessionToken = request.headers.get('x-session-token');
  if (sessionToken) {
    headers['x-session-token'] = sessionToken;
  }
  
  try {
    // Make the proxied request
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: headers,
      body: request.method !== 'GET' ? request.body : undefined,
    });
    
    // Return response with CORS headers for browser compatibility
    const newResponse = new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, x-session-token',
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    });
    
    return newResponse;
  } catch (error) {
    return new Response(`Proxy error: ${error.message}`, { 
      status: 500,
      headers: { 'Access-Control-Allow-Origin': '*' }
    });
  }
}
