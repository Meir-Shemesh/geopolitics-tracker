"""Weekly/monthly summary email for the cf-analytics D1 database.

Deliberately reuses existing infrastructure only - no new email provider, no
Node/wrangler dependency:
  - Reads the D1 database directly over Cloudflare's REST API (the same API
    `wrangler d1 execute --remote` itself uses under the hood), using the
    CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID already in .env for the
    Worker's own deployment - read-only here, no new credentials needed.
  - Sends via the same Gmail SMTP mechanism as scripts/daily_autorun.py and
    scripts/scheduler_notify.py (AUTOMATION_GMAIL_ADDRESS/
    AUTOMATION_GMAIL_APP_PASSWORD/AUTOMATION_ALERT_TO, already in .env).
This was an explicit decision (2026-10-02, see PROJECT_LOG): adding a new
email provider right after narrowing the privacy policy's infrastructure
disclosure to "just Cloudflare" was judged not worth it, and this project's
existing Gmail/Task-Scheduler automation already accepts the same
same-machine-must-be-on constraint this inherits.

Usage:
    python -m scripts.analytics_report --period weekly
    python -m scripts.analytics_report --period monthly

Weekly: the 7 days ending yesterday, vs. the 7 days before that.
Monthly: the previous full calendar month, vs. the one before that, plus a
within-month week-by-week breakdown.

No alarm-email-on-failure mechanism here (unlike scheduler_notify.py) - this
is a lower-stakes, secondary feature; a failure just exits non-zero and
Task Scheduler's own "Last Result" reflects it. Never prints the Gmail app
password or the Cloudflare API token in any output.
"""
import argparse
import json
import smtplib
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Matches cf-analytics/wrangler.toml's database_id (fixed, one-time-created resource).
D1_DATABASE_ID = "5f5a2813-2ee7-4b4a-8122-7e36f0970603"
TABLES = {
    "country": ("daily_country", "country"),
    "language": ("daily_language", "language"),
    "referrer": ("daily_referrer", "referrer_host"),
}


def load_env_minimal() -> dict:
    """Same pattern as scheduler_notify.py - parses .env directly, no
    python-dotenv dependency, never prints any value it reads."""
    env: dict[str, str] = {}
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def query_d1(sql: str, params: list, env: dict) -> list[dict]:
    token = env.get("CLOUDFLARE_API_TOKEN")
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account_id:
        raise RuntimeError("CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID missing from .env")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{D1_DATABASE_ID}/query"
    body = json.dumps({"sql": sql, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Safe to include: Cloudflare's error body never echoes the bearer token.
        raise RuntimeError(f"D1 query HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
    if not data.get("success"):
        raise RuntimeError(f"D1 query failed: {data.get('errors')}")
    return data["result"][0]["results"]


def total_visits(since: str, until: str, env: dict) -> int:
    rows = query_d1(
        "SELECT COALESCE(SUM(count), 0) AS total FROM daily_totals WHERE date >= ? AND date <= ?",
        [since, until], env,
    )
    return rows[0]["total"] if rows else 0


def top5(dimension: str, since: str, until: str, env: dict) -> list[tuple[str, int]]:
    table, column = TABLES[dimension]
    rows = query_d1(
        f"SELECT {column} AS label, SUM(count) AS total FROM {table} "
        f"WHERE date >= ? AND date <= ? GROUP BY {column} ORDER BY total DESC LIMIT 5",
        [since, until], env,
    )
    return [(r["label"], r["total"]) for r in rows]


def pct_change(current: int, previous: int) -> str:
    if previous == 0:
        return "n/a (no prior data)" if current == 0 else "new (no prior data)"
    change = (current - previous) / previous * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def format_top5_block(title: str, rows: list[tuple[str, int]]) -> str:
    if not rows:
        return f"{title}:\n  (no data)\n"
    lines = "\n".join(f"  {i}. {label} - {total}" for i, (label, total) in enumerate(rows, 1))
    return f"{title}:\n{lines}\n"


def weekly_range(today: date) -> tuple[date, date, date, date]:
    """(this_start, this_end, prev_start, prev_end) - the 7 days ending
    yesterday, and the 7 days before that."""
    this_end = today - timedelta(days=1)
    this_start = this_end - timedelta(days=6)
    prev_end = this_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return this_start, this_end, prev_start, prev_end


def monthly_range(today: date) -> tuple[date, date, date, date]:
    """(this_start, this_end, prev_start, prev_end) - the previous full
    calendar month, and the one before that."""
    first_of_this_month = today.replace(day=1)
    this_end = first_of_this_month - timedelta(days=1)
    this_start = this_end.replace(day=1)
    prev_end = this_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return this_start, this_end, prev_start, prev_end


def within_month_weeks(month_start: date, month_end: date) -> list[tuple[date, date]]:
    """Splits [month_start, month_end] into 7-day chunks (last chunk may be
    shorter) - an approximate, easy-to-read week-by-week view, not calendar-
    week-aligned."""
    chunks = []
    cursor = month_start
    while cursor <= month_end:
        chunk_end = min(cursor + timedelta(days=6), month_end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def build_weekly_report(env: dict) -> tuple[str, str]:
    today = date.today()
    this_start, this_end, prev_start, prev_end = weekly_range(today)

    this_total = total_visits(this_start.isoformat(), this_end.isoformat(), env)
    prev_total = total_visits(prev_start.isoformat(), prev_end.isoformat(), env)

    lines = [
        f"Weekly analytics summary: {this_start.isoformat()} to {this_end.isoformat()}",
        "",
        f"Total visits this week: {this_total} "
        f"(previous week {prev_start.isoformat()}..{prev_end.isoformat()}: {prev_total}, "
        f"change: {pct_change(this_total, prev_total)})",
        "",
    ]
    for dimension, label in (("country", "Top 5 countries"), ("language", "Top 5 languages"),
                             ("referrer", "Top 5 referrers")):
        rows = top5(dimension, this_start.isoformat(), this_end.isoformat(), env)
        lines.append(format_top5_block(label, rows))

    subject = f"[Geopolitics Tracker] Weekly analytics summary - {this_start.isoformat()} to {this_end.isoformat()}"
    return subject, "\n".join(lines)


def build_monthly_report(env: dict) -> tuple[str, str]:
    today = date.today()
    this_start, this_end, prev_start, prev_end = monthly_range(today)
    month_label = this_start.strftime("%Y-%m")

    this_total = total_visits(this_start.isoformat(), this_end.isoformat(), env)
    prev_total = total_visits(prev_start.isoformat(), prev_end.isoformat(), env)

    lines = [
        f"Monthly analytics summary: {month_label} ({this_start.isoformat()} to {this_end.isoformat()})",
        "",
        f"Total visits this month: {this_total} "
        f"(previous month {prev_start.strftime('%Y-%m')}: {prev_total}, "
        f"change: {pct_change(this_total, prev_total)})",
        "",
    ]
    for dimension, label in (("country", "Top 5 countries"), ("language", "Top 5 languages"),
                             ("referrer", "Top 5 referrers")):
        rows = top5(dimension, this_start.isoformat(), this_end.isoformat(), env)
        lines.append(format_top5_block(label, rows))

    lines.append("Week-by-week within the month (approximate, 7-day chunks):")
    for chunk_start, chunk_end in within_month_weeks(this_start, this_end):
        chunk_total = total_visits(chunk_start.isoformat(), chunk_end.isoformat(), env)
        lines.append(f"  {chunk_start.isoformat()} to {chunk_end.isoformat()}: {chunk_total}")
    lines.append("")

    subject = f"[Geopolitics Tracker] Monthly analytics summary - {month_label}"
    return subject, "\n".join(lines)


def send_email(subject: str, body: str, env: dict) -> bool:
    address = env.get("AUTOMATION_GMAIL_ADDRESS")
    app_password = env.get("AUTOMATION_GMAIL_APP_PASSWORD")
    to_address = env.get("AUTOMATION_ALERT_TO") or address or ""
    if not address or not app_password or not to_address:
        print(f"EMAIL NOT SENT (missing Gmail config in .env) - Subject: {subject}\n\n{body}")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to_address
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as server:
            server.starttls()
            server.login(address, app_password)
            server.sendmail(address, [to_address], msg.as_string())
        return True
    except Exception as e:
        # Safe to print: SMTP exceptions never include the password itself.
        print(f"EMAIL SEND FAILED: {e!r}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=["weekly", "monthly"], required=True)
    args = parser.parse_args()

    env = load_env_minimal()
    try:
        if args.period == "weekly":
            subject, body = build_weekly_report(env)
        else:
            subject, body = build_monthly_report(env)
    except RuntimeError as e:
        print(f"FAILED to build {args.period} report: {e}")
        return 1

    print(body)
    ok = send_email(subject, body, env)
    print(f"email sent: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
