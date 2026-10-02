# geopolitics-analytics (Cloudflare Worker + D1)

Privacy-protected, aggregate-only analytics for geopolitics.meirshemesh.com,
decided and specified 2026-10-02 (see PROJECT_LOG). Self-contained, separate
from the main Python pipeline - same convention as `scripts/` standing apart
from `src/`, just a different runtime (Cloudflare Workers, JavaScript) since
the site itself is 100% static (GitHub Pages, no backend - confirmed by
checking `docs/CNAME` and the absence of any `.github/workflows` or existing
serverless config before this was designed).

## Why this architecture

- The site has **no backend at all** - GitHub Pages serves `docs/` as static
  files. Any analytics collection needs a small separate service.
- Cloudflare Workers' free tier (100k requests/day) is far more than this
  site needs, and deploys to a `*.workers.dev` subdomain by default - **no
  DNS change needed** on `geopolitics.meirshemesh.com` at all.
- Cloudflare's edge resolves `request.cf.country` **before** the Worker code
  runs. `src/index.js` never reads `CF-Connecting-IP` or any other raw-IP
  header at all - the raw IP literally never enters this code's data flow,
  stronger than "use it momentarily then discard."
- D1 (serverless SQLite) holds 6 small aggregate-counter tables (see
  `schema.sql`) - never a per-visit event log. Every write is `count = count
  + 1` on an existing row, never an INSERT of a new per-visit record. No
  table has a column that could hold a raw IP, a cookie value, or any other
  persistent per-visitor identifier.

## Deployment (one-time)

Requires `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in the project's
root `.env` (same convention as every other secret in this project - never
committed; see `.env.example`). The token needs Account-level **Workers
Scripts: Edit** and **D1: Edit** permissions.

```bash
# from cf-analytics/, with CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID exported:
npx --yes wrangler d1 create geopolitics-analytics-db
# -> copy the printed database_id into wrangler.toml's database_id field

npx --yes wrangler d1 execute geopolitics-analytics-db --remote --file=schema.sql

npx --yes wrangler secret put ADMIN_DASHBOARD_PASSWORD
# -> paste a password when prompted - this gates GET /admin/analytics via
#    HTTP Basic Auth, is stored only in Cloudflare's own secret store, never
#    in wrangler.toml or .env, and is never printed/logged by any step here.
#    Unlike a token in a URL, Basic Auth credentials aren't exposed in browser
#    history or (typically) server/proxy logs - this replaced the original
#    GET /stats?token=... design (2026-10-02) for exactly that reason.

npx --yes wrangler deploy
# -> prints the live *.workers.dev URL - needed for the next step
```

## Still pending after first deploy

The static site itself does not yet send any ping - that's a separate,
deliberately sequenced follow-up: the beacon snippet needs the Worker's real
deployed URL, which is only known after the `wrangler deploy` above. Once
that URL is confirmed, the beacon (a `navigator.sendBeacon` call sending only
`document.referrer`, fired once per page load, no cookies) gets added to the
site's shared page-chrome (`render.py`/`publish.py`, same place as the theme-
toggle script and favicon links), which - per CLAUDE.md's standing rule on
any `render.py`/`publish.py` change - requires a full archive regeneration
and `publish.py` run, verified before committing, same as this session's
footer/contact/privacy-page change.

## Viewing the data

**Dashboard**: `https://<worker-url>/admin/analytics` - protected by HTTP
Basic Auth (any username, password = `ADMIN_DASHBOARD_PASSWORD`). Not linked
from anywhere on the public site, lives entirely on this Worker's own origin
(never on geopolitics.meirshemesh.com), and serves a `noindex, nofollow` meta
tag plus a disallow-all `/robots.txt` as defense in depth - Basic Auth is
still the real enforcement, this just reduces incidental crawl/discovery
noise. Takes `?days=7|30|90|all` (default 30). Shows a daily-visits trend
(inline SVG bar chart, no client library) plus 5 independent breakdown
tables (country, language, referrer, device family, browser family) - and
states explicitly, in the page itself, that no cross-tabulation between
these is possible (no unified per-visit record exists - see schema.sql).

**Scheduled summary emails**: `scripts/analytics_report.py --period
weekly|monthly` (run from the project root, not here) queries this same D1
database directly over Cloudflare's REST API - no Node/wrangler needed for
that - and emails a summary via the project's existing Gmail SMTP mechanism.
See that script's own docstring for details.
