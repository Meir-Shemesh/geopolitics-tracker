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
}

TABLE_CONSTRAINTS: dict[str, list[str]] = {
    "downloaded_files": ["UNIQUE(channel, message_id)"],
    "extracted_pages": ["UNIQUE(file_id, page_number)"],
    "page_screening": ["UNIQUE(file_id, page_number)"],
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
) -> None:
    conn.execute(
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
