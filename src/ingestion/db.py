"""SQLite tracking of which Telegram messages have already been downloaded."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloaded_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    newspaper TEXT NOT NULL,
    published_at TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    local_path TEXT NOT NULL,
    UNIQUE(channel, message_id)
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
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
