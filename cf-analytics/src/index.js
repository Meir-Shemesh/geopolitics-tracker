/**
 * Privacy-protected, cookie-free, aggregate-only analytics for
 * geopolitics.meirshemesh.com. Two routes:
 *
 *   POST /collect   - fired once per page load (navigator.sendBeacon from the
 *                      static site). Increments 6 small aggregate counters and
 *                      discards everything else. No cookies are read or set.
 *                      No per-visit row is ever written anywhere.
 *
 *   GET  /stats?token=...&days=30 - a simple token-gated HTML summary page.
 *                      Not a public endpoint; the token is a Wrangler secret
 *                      (STATS_VIEW_TOKEN), never committed, never logged.
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

function renderTable(title, rows) {
  if (!rows.length) return `<h2>${escapeHtml(title)}</h2><p><em>No data yet.</em></p>`;
  const body = rows
    .map((r) => `<tr><td>${escapeHtml(r.label)}</td><td style="text-align:right">${r.total}</td></tr>`)
    .join("\n");
  return `<h2>${escapeHtml(title)}</h2><table border="1" cellpadding="6" style="border-collapse:collapse"><tbody>${body}</tbody></table>`;
}

async function handleStats(request, env) {
  const url = new URL(request.url);
  const token = url.searchParams.get("token") || "";
  if (!env.STATS_VIEW_TOKEN || token !== env.STATS_VIEW_TOKEN) {
    return new Response("Forbidden", { status: 403 });
  }
  const days = Math.max(1, Math.min(365, parseInt(url.searchParams.get("days") || "30", 10) || 30));
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);

  const db = env.DB;
  const totalsRows = await topRows(db, "daily_totals", "date", since, 60);
  const totalSum = totalsRows.reduce((acc, r) => acc + r.total, 0);
  const countries = await topRows(db, "daily_country", "country", since);
  const languages = await topRows(db, "daily_language", "language", since);
  const referrers = await topRows(db, "daily_referrer", "referrer_host", since);
  const devices = await topRows(db, "daily_device", "device_family", since);
  const browsers = await topRows(db, "daily_browser", "browser_family", since);

  const html = `<!doctype html>
<html><head><meta charset="utf-8"><title>Analytics - last ${days} days</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 700px; margin: 2rem auto;">
<h1>Analytics summary - last ${days} day(s)</h1>
<p><strong>Total views: ${totalSum}</strong></p>
${renderTable("By day", totalsRows)}
${renderTable("Top countries", countries)}
${renderTable("Languages", languages)}
${renderTable("Top referrers", referrers)}
${renderTable("Device family", devices)}
${renderTable("Browser family", browsers)}
</body></html>`;

  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(request) });
    }
    if (request.method === "POST" && url.pathname === "/collect") {
      return handleCollect(request, env);
    }
    if (request.method === "GET" && url.pathname === "/stats") {
      return handleStats(request, env);
    }
    return new Response("Not found", { status: 404 });
  },
};
