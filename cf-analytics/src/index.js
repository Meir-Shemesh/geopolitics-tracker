/**
 * Privacy-protected, cookie-free, aggregate-only analytics for
 * geopolitics.meirshemesh.com. Three routes:
 *
 *   POST /collect   - fired once per page load (navigator.sendBeacon from the
 *                      static site). Increments 6 small aggregate counters and
 *                      discards everything else. No cookies are read or set.
 *                      No per-visit row is ever written anywhere.
 *
 *   GET  /admin/analytics?days=7|30|90|all - a private dashboard, protected by
 *                      HTTP Basic Auth (ADMIN_DASHBOARD_PASSWORD, a Wrangler
 *                      secret - never in .env/code/the repo). Not linked from
 *                      anywhere on the public site, and lives on this Worker's
 *                      own origin (never on geopolitics.meirshemesh.com itself),
 *                      so it is not part of that site's sitemap/crawl surface
 *                      at all - Basic Auth is still the real enforcement, this
 *                      is defense in depth, not the primary protection.
 *                      Replaces the earlier GET /stats?token=... (2026-10-02) -
 *                      a token sitting in a URL is weaker than Basic Auth
 *                      (browser history, referrer leaks), and maintaining two
 *                      auth mechanisms for the same data wasn't worth it.
 *
 *   GET  /robots.txt - disallows everything, defense in depth (see above).
 *
 * Privacy design (see cf-analytics/README.md for the full writeup):
 *   - request.cf.country comes from Cloudflare's own edge, resolved BEFORE
 *     this code runs. This code never reads request.headers.get("CF-Connecting-IP")
 *     or any other raw-IP header at all - the raw IP literally never enters
 *     this code's data flow, which is a stronger guarantee than "read it then
 *     discard it".
 *   - No unique/persistent identifier is ever created (no cookie, no
 *     fingerprint hash, no fixed per-visitor id of any kind) - see
 *     handleCollect() below: every write is `count = count + 1` on an
 *     existing aggregate row, never an INSERT of a new per-visit record.
 *   - The dashboard deliberately shows only independent single-dimension
 *     breakdowns, never a cross-tabulation (e.g. "visitors from Israel who
 *     use Hebrew") - that data physically does not exist, since no unified
 *     per-visit record is ever written (see schema.sql's header comment).
 *     The dashboard states this explicitly rather than let it be assumed.
 */

const ALLOWED_ORIGINS = new Set([
  "https://geopolitics.meirshemesh.com",
]);

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  const headers = { "Access-Control-Allow-Methods": "POST, GET, OPTIONS" };
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
  }
  return headers;
}

// Order matters: check more specific markers before the generic ones they're
// built on top of (Edge's UA string also contains "Chrome", Safari's doesn't
// reliably exclude false positives from other WebKit browsers without this
// ordering either).
function classifyBrowserFamily(userAgent) {
  const ua = userAgent || "";
  if (/Edg\//.test(ua)) return "Edge";
  if (/OPR\//.test(ua)) return "Opera";
  if (/Chrome\//.test(ua)) return "Chrome";
  if (/Firefox\//.test(ua)) return "Firefox";
  if (/Safari\//.test(ua) && /Version\//.test(ua)) return "Safari";
  return "Other";
}

function classifyDeviceFamily(userAgent) {
  const ua = userAgent || "";
  if (/Mobi|Android|iPhone|iPod/.test(ua)) return "mobile";
  if (/iPad|Tablet/.test(ua)) return "mobile"; // tablets grouped with mobile - coarse, 2-way split only
  if (!ua) return "other";
  return "desktop";
}

function primaryLanguage(acceptLanguageHeader) {
  const raw = (acceptLanguageHeader || "").split(",")[0]?.trim();
  if (!raw) return "unknown";
  // "en-US" -> "en", "he" -> "he"
  return raw.split("-")[0].split(";")[0].toLowerCase() || "unknown";
}

function referrerHost(referrerValue) {
  if (!referrerValue) return "direct";
  try {
    return new URL(referrerValue).hostname || "direct";
  } catch {
    return "direct";
  }
}

function todayUTC() {
  return new Date().toISOString().slice(0, 10); // "YYYY-MM-DD"
}

async function upsertCount(db, table, columns, values) {
  // `columns` is ONLY the non-count columns (e.g. ["date"] or ["date", "country"]) -
  // these ARE the table's full primary key, so they are ALSO the full ON CONFLICT
  // column list, with no slicing. `count` is appended separately below, both in the
  // insert column list and as the DO UPDATE target - it is never part of `columns`
  // itself. (Bug found and fixed 2026-10-02: an earlier version did
  // `columns.slice(0, -1)` here, wrongly assuming `columns` already included
  // `count` at the end - for daily_totals (columns=["date"]) that sliced away the
  // ONLY column, producing `ON CONFLICT()` with empty parens - a real SQL syntax
  // error, caught via `wrangler tail` against the live deployment, not guessed at.)
  const colList = columns.join(", ");
  const placeholders = columns.map(() => "?").join(", ");
  const conflictCols = columns.join(", ");
  const stmt = `
    INSERT INTO ${table} (${colList}, count) VALUES (${placeholders}, 1)
    ON CONFLICT(${conflictCols}) DO UPDATE SET count = count + 1
  `;
  return db.prepare(stmt).bind(...values);
}

async function handleCollect(request, env) {
  let referrerValue = "";
  try {
    const bodyText = await request.text();
    if (bodyText) {
      const parsed = JSON.parse(bodyText);
      referrerValue = typeof parsed.referrer === "string" ? parsed.referrer : "";
    }
  } catch {
    // Malformed body - still count the visit under "direct", never fail the ping.
  }

  const date = todayUTC();
  // request.cf.country is edge-resolved by Cloudflare itself - this is the ONLY
  // place this code ever touches anything IP-derived, and it is never the raw
  // IP address itself. "XX" (ISO reserved/unassigned) covers local dev and the
  // rare case Cloudflare can't determine a country.
  const country = request.cf?.country || "XX";
  const language = primaryLanguage(request.headers.get("Accept-Language"));
  const userAgent = request.headers.get("User-Agent") || "";
  const deviceFamily = classifyDeviceFamily(userAgent);
  const browserFamily = classifyBrowserFamily(userAgent);
  const refHost = referrerHost(referrerValue);

  const db = env.DB;
  const statements = [
    await upsertCount(db, "daily_totals", ["date"], [date]),
    await upsertCount(db, "daily_country", ["date", "country"], [date, country]),
    await upsertCount(db, "daily_language", ["date", "language"], [date, language]),
    await upsertCount(db, "daily_referrer", ["date", "referrer_host"], [date, refHost]),
    await upsertCount(db, "daily_device", ["date", "device_family"], [date, deviceFamily]),
    await upsertCount(db, "daily_browser", ["date", "browser_family"], [date, browserFamily]),
  ];
  await db.batch(statements);

  return new Response(null, { status: 204, headers: corsHeaders(request) });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// Fixed-length digest comparison (SHA-256 both sides first) rather than a
// direct string/length compare - avoids leaking the stored password's length
// via early-exit timing, using the Workers runtime's native
// crypto.subtle.timingSafeEqual on the resulting equal-length digests.
async function safeCompare(a, b) {
  const encoder = new TextEncoder();
  const [hashA, hashB] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  return crypto.subtle.timingSafeEqual(hashA, hashB);
}

async function checkBasicAuth(request, env) {
  if (!env.ADMIN_DASHBOARD_PASSWORD) return false;
  const authHeader = request.headers.get("Authorization");
  if (!authHeader || !authHeader.startsWith("Basic ")) return false;
  let decoded;
  try {
    decoded = atob(authHeader.slice(6));
  } catch {
    return false;
  }
  // HTTP Basic Auth sends "username:password" - only the password half is
  // checked; the username value is accepted as-is (not itself a secret here).
  const colonIndex = decoded.indexOf(":");
  const password = colonIndex === -1 ? decoded : decoded.slice(colonIndex + 1);
  return safeCompare(password, env.ADMIN_DASHBOARD_PASSWORD);
}

function unauthorizedResponse() {
  return new Response("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Analytics Dashboard"' },
  });
}

function resolveSinceDate(daysParam) {
  if (daysParam === "all") return "2000-01-01"; // effectively unbounded
  const days = Math.max(1, Math.min(365, parseInt(daysParam || "30", 10) || 30));
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}

// Ordered by total DESC - for the 5 independent breakdown tables (country,
// language, referrer, device, browser). Each is single-dimension only - see
// the file header comment on why no cross-tabulation is ever computed here.
async function topRows(db, table, dimensionCol, sinceDate, limit = 15) {
  const { results } = await db
    .prepare(
      `SELECT ${dimensionCol} AS label, SUM(count) AS total FROM ${table}
       WHERE date >= ? GROUP BY ${dimensionCol} ORDER BY total DESC LIMIT ?`
    )
    .bind(sinceDate, limit)
    .all();
  return results || [];
}

// Ordered by date ASC - specifically for the trend chart, which needs
// chronological order, unlike the ranked breakdown tables above.
async function dailyTotalsInRange(db, sinceDate) {
  const { results } = await db
    .prepare(`SELECT date, count FROM daily_totals WHERE date >= ? ORDER BY date ASC`)
    .bind(sinceDate)
    .all();
  return results || [];
}

function renderTrendChart(rows) {
  if (!rows.length) return "<p><em>No data yet.</em></p>";
  const width = 760;
  const height = 220;
  const padding = { top: 10, right: 10, bottom: 30, left: 40 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const maxCount = Math.max(...rows.map((r) => r.count), 1);
  const barWidth = plotWidth / rows.length;

  const bars = rows
    .map((r, i) => {
      const barHeight = (r.count / maxCount) * plotHeight;
      const x = padding.left + i * barWidth;
      const y = padding.top + (plotHeight - barHeight);
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(barWidth * 0.8).toFixed(1)}" height="${barHeight.toFixed(1)}" fill="#8f2c22"><title>${escapeHtml(r.date)}: ${r.count}</title></rect>`;
    })
    .join("");

  // Label every Nth date to avoid crowding on longer ranges.
  const labelEvery = Math.max(1, Math.ceil(rows.length / 10));
  const labels = rows
    .map((r, i) => {
      if (i % labelEvery !== 0 && i !== rows.length - 1) return "";
      const x = padding.left + i * barWidth + barWidth * 0.4;
      const y = height - padding.bottom + 14;
      return `<text x="${x.toFixed(1)}" y="${y}" font-size="10" text-anchor="middle" fill="#5f5240">${escapeHtml(r.date.slice(5))}</text>`;
    })
    .join("");

  const maxLabel = `<text x="${padding.left - 6}" y="${padding.top + 10}" font-size="10" text-anchor="end" fill="#5f5240">${maxCount}</text>`;
  const zeroLabel = `<text x="${padding.left - 6}" y="${height - padding.bottom}" font-size="10" text-anchor="end" fill="#5f5240">0</text>`;

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" style="max-width:${width}px" role="img" aria-label="Daily visits trend">
    <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="#cdb98d" />
    <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#cdb98d" />
    ${bars}
    ${labels}
    ${maxLabel}
    ${zeroLabel}
  </svg>`;
}

function renderBreakdownTable(title, rows) {
  if (!rows.length) return `<h2>${escapeHtml(title)}</h2><p><em>No data yet.</em></p>`;
  const body = rows
    .map((r) => `<tr><td>${escapeHtml(r.label)}</td><td style="text-align:right">${r.total}</td></tr>`)
    .join("\n");
  return `<h2>${escapeHtml(title)}</h2><table><tbody>${body}</tbody></table>`;
}

const DAY_OPTIONS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "all", label: "All time" },
];

async function handleAdminAnalytics(request, env) {
  if (!(await checkBasicAuth(request, env))) return unauthorizedResponse();

  const url = new URL(request.url);
  const daysParam = url.searchParams.get("days") || "30";
  const since = resolveSinceDate(daysParam);

  const db = env.DB;
  const trendRows = await dailyTotalsInRange(db, since);
  const totalSum = trendRows.reduce((acc, r) => acc + r.count, 0);
  const countries = await topRows(db, "daily_country", "country", since);
  const languages = await topRows(db, "daily_language", "language", since);
  const referrers = await topRows(db, "daily_referrer", "referrer_host", since);
  const devices = await topRows(db, "daily_device", "device_family", since);
  const browsers = await topRows(db, "daily_browser", "browser_family", since);

  const dayLinks = DAY_OPTIONS.map((opt) => {
    const isActive = opt.value === daysParam;
    return `<a href="?days=${opt.value}" style="${isActive ? "font-weight:700;text-decoration:underline;" : ""}margin-inline-end:1rem;">${opt.label}</a>`;
  }).join("");

  const html = `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Analytics dashboard</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #1c1712; background: #e8dfc9; }
  h1 { margin-bottom: .25rem; }
  h2 { margin-top: 2rem; color: #8f2c22; }
  table { border-collapse: collapse; width: 100%; max-width: 420px; background: #fffbf2; }
  td { border: 1px solid #cdb98d; padding: .4rem .7rem; }
  .note { background: #fffbf2; border: 1px solid #cdb98d; border-radius: 6px; padding: .9rem 1.1rem; font-size: .9rem; }
  .day-nav { margin: 1rem 0 1.5rem; }
  a { color: #8f2c22; }
</style>
</head>
<body>
<h1>Analytics dashboard</h1>
<p class="note"><strong>Note:</strong> each breakdown below is independent - there is
no unified per-visit record (see the privacy policy), so a question like "how many
visitors from Israel use Hebrew" cannot be answered from this data. This is a
deliberate consequence of the aggregate-only design, not a missing feature.</p>
<div class="day-nav">${dayLinks}</div>
<p><strong>Total views in range: ${totalSum}</strong></p>
<h2>Daily visits trend</h2>
${renderTrendChart(trendRows)}
${renderBreakdownTable("By country", countries)}
${renderBreakdownTable("By language", languages)}
${renderBreakdownTable("By referrer", referrers)}
${renderBreakdownTable("By device family", devices)}
${renderBreakdownTable("By browser family", browsers)}
</body></html>`;

  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(request) });
    }
    if (url.pathname === "/robots.txt") {
      return new Response("User-agent: *\nDisallow: /\n", { headers: { "Content-Type": "text/plain" } });
    }
    if (request.method === "POST" && url.pathname === "/collect") {
      return handleCollect(request, env);
    }
    if (request.method === "GET" && url.pathname === "/admin/analytics") {
      return handleAdminAnalytics(request, env);
    }
    return new Response("Not found", { status: 404 });
  },
};
