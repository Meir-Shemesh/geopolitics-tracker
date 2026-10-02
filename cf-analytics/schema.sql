-- Schema for the privacy-protected analytics D1 database (geopolitics-analytics-db).
--
-- Deliberately 6 separate single-dimension tables, not one wide table combining
-- every field per row. A row is always (date + exactly one breakdown value) plus
-- a count - never a cross-tabulation of country+language+referrer+device together,
-- which would let rare combinations act as quasi-identifiers for a single visit.
-- There is no per-visit event log anywhere in this schema, ever - every write is
-- an increment to an existing or new aggregate counter, never an INSERT of a new
-- row per request.
--
-- No column in any table can hold a raw IP address, a cookie value, or any other
-- persistent per-visitor identifier - this is enforced by the schema itself, not
-- just by application code discipline (see src/index.js's handleCollect()).

CREATE TABLE IF NOT EXISTS daily_totals (
  date  TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date)
);

CREATE TABLE IF NOT EXISTS daily_country (
  date    TEXT NOT NULL,
  country TEXT NOT NULL,  -- ISO 3166-1 alpha-2, or "XX" when Cloudflare can't determine it
  count   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, country)
);

CREATE TABLE IF NOT EXISTS daily_language (
  date     TEXT NOT NULL,
  language TEXT NOT NULL,  -- primary language subtag only, e.g. "he", "en", "de"
  count    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, language)
);

CREATE TABLE IF NOT EXISTS daily_referrer (
  date          TEXT NOT NULL,
  referrer_host TEXT NOT NULL,  -- hostname only (e.g. "www.google.com"), never the full URL
  count         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, referrer_host)
);

CREATE TABLE IF NOT EXISTS daily_device (
  date          TEXT NOT NULL,
  device_family TEXT NOT NULL,  -- "mobile" | "desktop" | "other"
  count         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, device_family)
);

CREATE TABLE IF NOT EXISTS daily_browser (
  date           TEXT NOT NULL,
  browser_family TEXT NOT NULL,  -- "Chrome" | "Safari" | "Firefox" | "Edge" | "Other"
  count          INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, browser_family)
);
