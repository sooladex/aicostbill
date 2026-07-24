import os
from datetime import datetime

import psycopg2
import psycopg2.extras


DATABASE_URL = os.environ.get("DATABASE_URL")


class PGConnection:
    """
    Petit adaptateur autour de psycopg2 qui imite l'API pratique de
    sqlite3.Connection (conn.execute(sql, params) -> curseur avec
    fetchone()/fetchall(), lignes accessibles comme des dicts).
    Permet de garder le reste de l'appli quasi inchange.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql_pg = sql.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql_pg, params)
        return cur

    def executescript(self, script):
        cur = self._conn.cursor()
        cur.execute(script)
        self._conn.commit()
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return PGConnection(conn)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    agency_name TEXT NOT NULL DEFAULT 'Mon agence',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    contact_email TEXT,
    default_markup_pct REAL NOT NULL DEFAULT 30,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    subtotal_cost REAL NOT NULL,
    markup_pct REAL NOT NULL,
    total_billed REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_entries (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entry_date TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    description TEXT,
    cost_usd REAL NOT NULL,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
"""


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.close()


def now():
    return datetime.utcnow().isoformat()


if __name__ == "__main__":
    init_db()
    print("Base Postgres initialisee.")
