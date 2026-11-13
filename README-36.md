# Voratoon Web API by Nat

API untuk **voratoon.web.id** — v1.0.2 · By: Nat

## Endpoint
- `/api/latest?page=1`
- `/api/search?q=judul`
- `/api/detail/{slug}`
- `/api/chapter?slug=series&chapter=chapter-1`

## Deploy
Root repo → Vercel → Deploy.

Opsional env: `VORATOON_WEB_BASE`, `VORATOON_WEB_TIMEOUT`, `VORATOON_WEB_PAGE_SIZE`

Sumber kadang 503; API sudah retry + backoff.
