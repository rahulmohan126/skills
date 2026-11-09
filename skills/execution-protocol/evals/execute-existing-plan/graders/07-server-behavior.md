---
type: llm
focus: trace
weight: 1
---

Against the running server, the 6th POST to /api/echo from one client within 10 seconds returns 429 with a Retry-After header and body {"error": "rate limited"}, while /health still returns 200
