
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "geotrace.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                destination TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_id INTEGER,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link_code TEXT NOT NULL,
                ip_address TEXT,
                country TEXT,
                city TEXT,
                region TEXT,
                isp TEXT,
                user_agent TEXT,
                consented INTEGER DEFAULT 0,
                visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        new_columns = {
            "latitude": "REAL",
            "longitude": "REAL",
            "altitude": "REAL",
            "accuracy": "REAL",
            "altitude_accuracy": "REAL",
            "heading": "REAL",
            "speed": "REAL",
            "location_status": "TEXT DEFAULT 'not_requested'",
            "location_timestamp": "INTEGER"
        }

        existing_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(visits)"
            ).fetchall()
        }

        for column, data_type in new_columns.items():
            if column not in existing_columns:
                conn.execute(
                    f"ALTER TABLE visits ADD COLUMN {column} {data_type}"
                )

        link_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(links)"
            ).fetchall()
        }

        if "owner_id" not in link_columns:
            conn.execute(
                "ALTER TABLE links ADD COLUMN owner_id INTEGER"
            )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_links_owner
            ON links(owner_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_visits_link_code
            ON visits(link_code)
        """)

        conn.commit()

    print("[+] GeoTrace database initialized")
    print(f"[+] Database: {DB_PATH}")


if __name__ == "__main__":
    initialize_database()
