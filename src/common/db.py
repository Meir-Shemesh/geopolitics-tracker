"""Shared SQLite tracking DB (data/processed/tracker.db) for the pipeline stages.

Tables are declared once in TABLE_COLUMNS below. init_db() both creates missing
tables and migrates existing ones by adding any column present in TABLE_COLUMNS
but missing from the actual table (checked via PRAGMA table_info) - so adding a
new column here is enough for existing tracker.db files to pick it up on the
next run, with no manual migration step or need to delete the DB.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "tracker.db"

TABLE_COLUMNS: dict[str, dict[str, str]] = {
    "downloaded_files": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "channel": "TEXT NOT NULL",
        "message_id": "INTEGER NOT NULL",
        "file_name": "TEXT NOT NULL",
        "newspaper": "TEXT NOT NULL",
        "published_at": "TEXT NOT NULL",
        "downloaded_at": "TEXT NOT NULL",
        "local_path": "TEXT NOT NULL",
        "extraction_status": "TEXT NOT NULL DEFAULT 'pending'",
        "extraction_error": "TEXT",
    },
    "extracted_pages": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "file_id": "INTEGER NOT NULL REFERENCES downloaded_files(id)",
        "page_number": "INTEGER NOT NULL",
        "raw_text": "TEXT NOT NULL",
        "extracted_at": "TEXT NOT NULL",
    },
    "page_screening": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "file_id": "INTEGER NOT NULL REFERENCES downloaded_files(id)",
        "page_number": "INTEGER NOT NULL",
        "is_relevant": "INTEGER NOT NULL",
        "screening_reasoning": "TEXT NOT NULL",
        "screened_at": "TEXT NOT NULL",
        "model_used": "TEXT NOT NULL",
        "analysis_status": "TEXT NOT NULL DEFAULT 'pending'",
    },
    "articles": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "file_id": "INTEGER NOT NULL REFERENCES downloaded_files(id)",
        "page_number": "INTEGER NOT NULL",
        "newspaper": "TEXT NOT NULL",
        "language": "TEXT NOT NULL",
        "headline": "TEXT NOT NULL",
        "author": "TEXT NOT NULL",
        "region_topic": "TEXT NOT NULL",
        "stance_summary": "TEXT NOT NULL",
        "key_excerpt": "TEXT NOT NULL",
        "analyzed_at": "TEXT NOT NULL",
    },
    "article_countries": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "article_id": "INTEGER NOT NULL REFERENCES articles(id)",
        "country_code": "TEXT NOT NULL",
    },
    "article_conflict_zones": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "article_id": "INTEGER NOT NULL REFERENCES articles(id)",
        "conflict_zone": "TEXT NOT NULL",
    },
    "reports": {
        "report_date": "TEXT PRIMARY KEY",
        "sources_included": "TEXT NOT NULL",
        "created_at": "TEXT NOT NULL",
    },
    "report_sections": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "report_date": "TEXT NOT NULL REFERENCES reports(report_date)",
        "topic_label_he": "TEXT NOT NULL",
        "topic_label_en": "TEXT NOT NULL",
        "comparison_text_he": "TEXT NOT NULL",
        "comparison_text_en": "TEXT NOT NULL",
        "category": "TEXT NOT NULL DEFAULT 'other'",
        "created_at": "TEXT NOT NULL",
    },
    "report_section_articles": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "section_id": "INTEGER NOT NULL REFERENCES report_sections(id)",
        "article_id": "INTEGER NOT NULL REFERENCES articles(id)",
    },
}

TABLE_CONSTRAINTS: dict[str, list[str]] = {
    "downloaded_files": ["UNIQUE(channel, message_id)"],
    "extracted_pages": ["UNIQUE(file_id, page_number)"],
    "page_screening": ["UNIQUE(file_id, page_number)"],
    "report_section_articles": ["UNIQUE(section_id, article_id)"],
    "article_countries": ["UNIQUE(article_id, country_code)"],
    "article_conflict_zones": ["UNIQUE(article_id, conflict_zone)"],
}


def _create_table_sql(table: str) -> str:
    columns = [f"{name} {ddl}" for name, ddl in TABLE_COLUMNS[table].items()]
    columns += TABLE_CONSTRAINTS.get(table, [])
    return f"CREATE TABLE IF NOT EXISTS {table} (\n    " + ",\n    ".join(columns) + "\n)"


def _migrate_table(conn: sqlite3.Connection, table: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, ddl in TABLE_COLUMNS[table].items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    for table in TABLE_COLUMNS:
        conn.execute(_create_table_sql(table))
        _migrate_table(conn, table)
    conn.commit()


def is_downloaded(conn: sqlite3.Connection, channel: str, message_id: int) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM downloaded_files WHERE channel = ? AND message_id = ?",
        (channel, message_id),
    )
    return cursor.fetchone() is not None


def mark_downloaded(
    conn: sqlite3.Connection,
    channel: str,
    message_id: int,
    file_name: str,
    newspaper: str,
    published_at: str,
    downloaded_at: str,
    local_path: str,
) -> None:
    conn.execute(
        """
        INSERT INTO downloaded_files
            (channel, message_id, file_name, newspaper, published_at, downloaded_at, local_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (channel, message_id, file_name, newspaper, published_at, downloaded_at, local_path),
    )
    conn.commit()


def get_pending_extraction_files(conn: sqlite3.Connection):
    cursor = conn.execute(
        "SELECT id, file_name, local_path FROM downloaded_files WHERE extraction_status = 'pending'"
    )
    return cursor.fetchall()


def set_extraction_result(
    conn: sqlite3.Connection,
    file_id: int,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE downloaded_files SET extraction_status = ?, extraction_error = ? WHERE id = ?",
        (status, error, file_id),
    )
    conn.commit()


def insert_extracted_page(
    conn: sqlite3.Connection,
    file_id: int,
    page_number: int,
    raw_text: str,
    extracted_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at)
        VALUES (?, ?, ?, ?)
        """,
        (file_id, page_number, raw_text, extracted_at),
    )
    conn.commit()


def get_unscreened_pages(conn: sqlite3.Connection, file_name_contains: str | None = None):
    query = """
        SELECT ep.file_id, ep.page_number, ep.raw_text
        FROM extracted_pages ep
        JOIN downloaded_files df ON df.id = ep.file_id
        LEFT JOIN page_screening ps ON ps.file_id = ep.file_id AND ps.page_number = ep.page_number
        WHERE ps.id IS NULL
    """
    params: tuple = ()
    if file_name_contains is not None:
        query += " AND df.file_name LIKE ?"
        params = (f"%{file_name_contains}%",)
    query += " ORDER BY ep.file_id, ep.page_number"
    return conn.execute(query, params).fetchall()


def insert_page_screening(
    conn: sqlite3.Connection,
    file_id: int,
    page_number: int,
    is_relevant: bool,
    reasoning: str,
    screened_at: str,
    model_used: str,
) -> None:
    conn.execute(
        """
        INSERT INTO page_screening
            (file_id, page_number, is_relevant, screening_reasoning, screened_at, model_used)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (file_id, page_number, int(is_relevant), reasoning, screened_at, model_used),
    )
    conn.commit()


def get_pages_pending_analysis(conn: sqlite3.Connection, file_id: int | None = None):
    query = """
        SELECT ps.file_id, ps.page_number, ep.raw_text, df.newspaper
        FROM page_screening ps
        JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
        JOIN downloaded_files df ON df.id = ps.file_id
        WHERE ps.is_relevant = 1 AND ps.analysis_status = 'pending'
    """
    params: tuple = ()
    if file_id is not None:
        query += " AND ps.file_id = ?"
        params = (file_id,)
    query += " ORDER BY ps.file_id, ps.page_number"
    return conn.execute(query, params).fetchall()


def set_analysis_status(conn: sqlite3.Connection, file_id: int, page_number: int, status: str) -> None:
    conn.execute(
        "UPDATE page_screening SET analysis_status = ? WHERE file_id = ? AND page_number = ?",
        (status, file_id, page_number),
    )
    conn.commit()


def insert_article(
    conn: sqlite3.Connection,
    file_id: int,
    page_number: int,
    newspaper: str,
    language: str,
    headline: str,
    author: str,
    region_topic: str,
    stance_summary: str,
    key_excerpt: str,
    analyzed_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO articles
            (file_id, page_number, newspaper, language, headline, author,
             region_topic, stance_summary, key_excerpt, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            page_number,
            newspaper,
            language,
            headline,
            author,
            region_topic,
            stance_summary,
            key_excerpt,
            analyzed_at,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_articles_for_date(conn: sqlite3.Connection, report_date: str):
    query = """
        SELECT a.id, a.newspaper, a.headline, a.region_topic, a.stance_summary, a.key_excerpt
        FROM articles a
        JOIN downloaded_files df ON df.id = a.file_id
        WHERE date(df.published_at) = ?
        ORDER BY a.newspaper, a.id
    """
    return conn.execute(query, (report_date,)).fetchall()


def get_sources_for_date(conn: sqlite3.Connection, report_date: str) -> list[str]:
    query = """
        SELECT DISTINCT df.newspaper
        FROM downloaded_files df
        JOIN articles a ON a.file_id = df.id
        WHERE date(df.published_at) = ?
        ORDER BY df.newspaper
    """
    return [row["newspaper"] for row in conn.execute(query, (report_date,)).fetchall()]


def report_exists(conn: sqlite3.Connection, report_date: str) -> bool:
    cursor = conn.execute("SELECT 1 FROM reports WHERE report_date = ?", (report_date,))
    return cursor.fetchone() is not None


def delete_report(conn: sqlite3.Connection, report_date: str) -> None:
    conn.execute(
        """
        DELETE FROM report_section_articles
        WHERE section_id IN (SELECT id FROM report_sections WHERE report_date = ?)
        """,
        (report_date,),
    )
    conn.execute("DELETE FROM report_sections WHERE report_date = ?", (report_date,))
    conn.execute("DELETE FROM reports WHERE report_date = ?", (report_date,))
    conn.commit()


def insert_report(conn: sqlite3.Connection, report_date: str, sources_included: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO reports (report_date, sources_included, created_at) VALUES (?, ?, ?)",
        (report_date, sources_included, created_at),
    )
    conn.commit()


def insert_report_section(
    conn: sqlite3.Connection,
    report_date: str,
    topic_label_he: str,
    topic_label_en: str,
    comparison_text_he: str,
    comparison_text_en: str,
    category: str,
    created_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO report_sections
            (report_date, topic_label_he, topic_label_en, comparison_text_he, comparison_text_en, category, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (report_date, topic_label_he, topic_label_en, comparison_text_he, comparison_text_en, category, created_at),
    )
    conn.commit()
    return cursor.lastrowid


def link_section_article(conn: sqlite3.Connection, section_id: int, article_id: int) -> None:
    conn.execute(
        "INSERT INTO report_section_articles (section_id, article_id) VALUES (?, ?)",
        (section_id, article_id),
    )
    conn.commit()


def get_report(conn: sqlite3.Connection, report_date: str):
    return conn.execute(
        "SELECT report_date, sources_included, created_at FROM reports WHERE report_date = ?",
        (report_date,),
    ).fetchone()


def get_all_reports(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT report_date, sources_included FROM reports ORDER BY report_date DESC"
    ).fetchall()


def get_report_sections_for_date(conn: sqlite3.Connection, report_date: str):
    return conn.execute(
        """
        SELECT id, topic_label_he, topic_label_en, comparison_text_he, comparison_text_en, category
        FROM report_sections
        WHERE report_date = ?
        ORDER BY id
        """,
        (report_date,),
    ).fetchall()


def get_section_articles(conn: sqlite3.Connection, section_id: int):
    return conn.execute(
        """
        SELECT DISTINCT a.newspaper
        FROM articles a
        JOIN report_section_articles rsa ON rsa.article_id = a.id
        WHERE rsa.section_id = ?
        ORDER BY a.newspaper
        """,
        (section_id,),
    ).fetchall()


def get_section_citations(conn: sqlite3.Connection, section_id: int):
    return conn.execute(
        """
        SELECT a.newspaper, a.page_number, a.headline, date(df.published_at) AS published_date
        FROM articles a
        JOIN report_section_articles rsa ON rsa.article_id = a.id
        JOIN downloaded_files df ON df.id = a.file_id
        WHERE rsa.section_id = ?
        ORDER BY a.newspaper, a.page_number
        """,
        (section_id,),
    ).fetchall()


def insert_article_countries(conn: sqlite3.Connection, article_id: int, country_codes: list[str]) -> None:
    for code in country_codes:
        conn.execute(
            "INSERT OR IGNORE INTO article_countries (article_id, country_code) VALUES (?, ?)",
            (article_id, code),
        )
    conn.commit()


def insert_article_conflict_zones(conn: sqlite3.Connection, article_id: int, conflict_zones: list[str]) -> None:
    for zone in conflict_zones:
        conn.execute(
            "INSERT OR IGNORE INTO article_conflict_zones (article_id, conflict_zone) VALUES (?, ?)",
            (article_id, zone),
        )
    conn.commit()


def get_countries_for_article(conn: sqlite3.Connection, article_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT country_code FROM article_countries WHERE article_id = ? ORDER BY country_code",
        (article_id,),
    ).fetchall()
    return [r["country_code"] for r in rows]


def get_conflict_zones_for_article(conn: sqlite3.Connection, article_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT conflict_zone FROM article_conflict_zones WHERE article_id = ? ORDER BY conflict_zone",
        (article_id,),
    ).fetchall()
    return [r["conflict_zone"] for r in rows]


def get_geo_tags_for_section(conn: sqlite3.Connection, section_id: int) -> dict:
    countries = conn.execute(
        """
        SELECT DISTINCT ac.country_code
        FROM report_section_articles rsa
        JOIN article_countries ac ON ac.article_id = rsa.article_id
        WHERE rsa.section_id = ?
        ORDER BY ac.country_code
        """,
        (section_id,),
    ).fetchall()
    zones = conn.execute(
        """
        SELECT DISTINCT acz.conflict_zone
        FROM report_section_articles rsa
        JOIN article_conflict_zones acz ON acz.article_id = rsa.article_id
        WHERE rsa.section_id = ?
        ORDER BY acz.conflict_zone
        """,
        (section_id,),
    ).fetchall()
    return {
        "countries": [r["country_code"] for r in countries],
        "conflict_zones": [r["conflict_zone"] for r in zones],
    }


def get_articles_without_geo_tags(conn: sqlite3.Connection, report_date: str | None = None):
    query = """
        SELECT a.id, a.headline, a.region_topic, a.stance_summary
        FROM articles a
        LEFT JOIN article_countries ac ON ac.article_id = a.id
        LEFT JOIN article_conflict_zones acz ON acz.article_id = a.id
    """
    conditions = ["ac.id IS NULL", "acz.id IS NULL"]
    params: list = []
    if report_date is not None:
        query += " JOIN downloaded_files df ON df.id = a.file_id"
        conditions.append("date(df.published_at) = ?")
        params.append(report_date)
    query += " WHERE " + " AND ".join(conditions) + " ORDER BY a.id"
    return conn.execute(query, params).fetchall()
