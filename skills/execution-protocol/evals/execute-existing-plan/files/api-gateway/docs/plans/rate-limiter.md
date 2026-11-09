# Rate limiter for /api routes

We're getting hammered by a few clients. Add per-client rate limiting to everything under `/api/`.

## Requirements
- Limit each client (by IP) to 5 requests per 10 seconds on `/api/*` routes.
- `/health` is never rate limited.
- When over the limit, respond 429 with JSON `{"error": "rate limited"}` and a `Retry-After` header (seconds until the client can retry).
- Limits are per client — one noisy client shouldn't affect others.
- After the window passes the client can make requests again.

## Implementation notes
I was thinking a fixed window counter in a Map, something like:

```js
const hits = new Map();
function allow(ip) {
  const now = Date.now();
  const e = hits.get(ip) || { count: 0, start: now };
  if (now - e.start > 10000) { e.count = 0; e.start = now; }
  e.count++;
  hits.set(ip, e);
  return e.count <= 5;
}
```

Put it in `src/rateLimit.js`.
