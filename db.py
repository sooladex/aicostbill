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
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
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

-- Cle Admin API (OpenAI / Anthropic) de l'agence, une par fournisseur.
-- La cle elle-meme n'est jamais stockee en clair (voir crypto.py).
CREATE TABLE IF NOT EXISTS api_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    encrypted_key TEXT NOT NULL,
    label TEXT,
    last_synced_at TEXT,
    last_sync_error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, provider)
);

-- Association entre un client de l'agence et son "project" OpenAI /
-- "workspace" Anthropic cote fournisseur, pour attribuer automatiquement
-- les couts recuperes via l'API au bon client.
CREATE TABLE IF NOT EXISTS client_provider_links (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(client_id, provider)
);
"""


# Migration : les deploiements d'avant le multi-compte ont une table clients
# sans user_id. On l'ajoute si besoin et on rattache les clients orphelins
# au premier compte existant, sans rien supprimer.
# On ajoute aussi sync_key sur usage_entries pour la synchronisation
# automatique (idempotence : une ligne par jour/fournisseur/projet externe).
MIGRATION = """
ALTER TABLE clients ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
UPDATE clients SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1)
WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users);

ALTER TABLE usage_entries ADD COLUMN IF NOT EXISTS sync_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS usage_entries_sync_key_idx ON usage_entries(sync_key) WHERE sync_key IS NOT NULL;
"""


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.executescript(MIGRATION)
    conn.close()


def now():
    return datetime.utcnow().isoformat()


if __name__ == "__main__":
    init_db()
    print("Base Postgres initialisee.")
