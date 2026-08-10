import sqlite3
import os
from config import DATABASE


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS words (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            word        TEXT NOT NULL UNIQUE,
            definition  TEXT NOT NULL,
            note        TEXT,
            examples    TEXT,
            pos         TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_word_progress (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id             INTEGER REFERENCES words(id) ON DELETE CASCADE,
            interval            INTEGER DEFAULT 1,
            ease_factor         REAL DEFAULT 2.5,
            consecutive_correct INTEGER DEFAULT 0,
            last_reviewed_at    DATETIME,
            next_due_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
            status              TEXT DEFAULT 'new'
        );

        CREATE TABLE IF NOT EXISTS daily_session (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          DATE NOT NULL UNIQUE,
            learn_target  INTEGER DEFAULT 0,
            review_target INTEGER DEFAULT 0,
            test_target   INTEGER DEFAULT 0,
            learn_done    INTEGER DEFAULT 0,
            review_done   INTEGER DEFAULT 0,
            test_done     INTEGER DEFAULT 0,
            completed_at  DATETIME
        );

        CREATE TABLE IF NOT EXISTS daily_word_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            date    DATE NOT NULL,
            word_id INTEGER REFERENCES words(id) ON DELETE CASCADE,
            mode    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_dwl_date ON daily_word_log(date, mode);

        CREATE TABLE IF NOT EXISTS learn_group (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at   DATE NOT NULL,
            completed_at DATE
        );

        CREATE TABLE IF NOT EXISTS learn_group_word (
            group_id INTEGER NOT NULL REFERENCES learn_group(id) ON DELETE CASCADE,
            word_id  INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, word_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            id                  INTEGER PRIMARY KEY DEFAULT 1,
            daily_learn_count   INTEGER DEFAULT 10,
            daily_review_count  INTEGER DEFAULT 20,
            daily_test_count    INTEGER DEFAULT 10
        );
    """)

    # Migrate: add columns that may not exist in older DBs
    for col_sql in [
        "ALTER TABLE settings ADD COLUMN show_word_first INTEGER DEFAULT 1",
        "ALTER TABLE settings ADD COLUMN test_size INTEGER DEFAULT 10",
    ]:
        try:
            c.execute(col_sql)
        except Exception:
            pass

    # Ensure default settings row exists
    c.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
    conn.commit()
    conn.close()
