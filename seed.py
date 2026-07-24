"""
Script de demo : cree un compte agence + 2 clients + projets + usage varie
sur les 30 derniers jours, pour voir l'app tourner immediatement.

Usage: python seed.py
"""
import random
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

from db import get_db, init_db, now

DEMO_EMAIL = "demo@agence.test"
DEMO_PASSWORD = "demo1234"


def run():
    init_db()
    db = get_db()

    existing = db.execute("SELECT * FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if existing:
        print("Compte demo deja present, seed ignore.")
        return

    cur = db.execute(
        "INSERT INTO users (email, password_hash, agency_name, created_at) VALUES (?, ?, ?, ?) RETURNING id",
        (DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD), "Studio Neon (demo)", now()),
    )
    demo_user_id = cur.fetchone()["id"]

    clients_data = [
        ("Boutique Lumen", "contact@lumen-shop.fr", 30),
        ("Cabinet Arès Conseil", "hello@ares-conseil.fr", 25),
        ("Atelier Verba", "contact@atelier-verba.com", 40),
    ]
    client_ids = []
    for name, email, markup in clients_data:
        cur = db.execute(
            "INSERT INTO clients (user_id, name, contact_email, default_markup_pct, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (demo_user_id, name, email, markup, "", now()),
        )
        client_ids.append(cur.fetchone()["id"])

    projects_data = {
        client_ids[0]: ["Chatbot support client", "Generation de descriptions produits"],
        client_ids[1]: ["Assistant de redaction de rapports"],
        client_ids[2]: ["Chatbot FAQ", "Resume automatique d'articles"],
    }
    project_ids = {}
    for client_id, names in projects_data.items():
        project_ids[client_id] = []
        for n in names:
            cur = db.execute(
                "INSERT INTO projects (client_id, name, created_at) VALUES (?, ?, ?) RETURNING id",
                (client_id, n, now()),
            )
            project_ids[client_id].append(cur.fetchone()["id"])

    providers_models = [
        ("OpenAI", "gpt-4o"),
        ("OpenAI", "gpt-4o-mini"),
        ("Anthropic", "claude-sonnet-5"),
        ("Anthropic", "claude-haiku-4-5"),
    ]
    descriptions = [
        "Reponses support client", "Generation de fiches produit", "Resume de document",
        "Redaction d'email", "Classification de tickets", "Extraction de donnees",
    ]

    today = date.today()
    for client_id, pids in project_ids.items():
        for pid in pids:
            n_entries = random.randint(6, 14)
            for _ in range(n_entries):
                days_ago = random.randint(0, 29)
                entry_date = (today - timedelta(days=days_ago)).isoformat()
                provider, model = random.choice(providers_models)
                cost = round(random.uniform(0.8, 45.0), 4)
                desc = random.choice(descriptions)
                db.execute(
                    """INSERT INTO usage_entries
                       (project_id, entry_date, provider, model, description, cost_usd, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (pid, entry_date, provider, model, desc, cost, now()),
                )

    db.commit()
    db.close()

    print("Seed termine.")
    print(f"Connexion demo -> email: {DEMO_EMAIL} / mot de passe: {DEMO_PASSWORD}")


if __name__ == "__main__":
    run()
