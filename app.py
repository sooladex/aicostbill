import os
import csv
import io
from functools import wraps
from datetime import datetime, date

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, send_file, g
)
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db, init_db, now

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-prod")

PROVIDERS = ["OpenAI", "Anthropic", "Google", "Mistral", "Autre"]


# ---------- helpers ----------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_uid():
    return session.get("user_id")


def get_current_user(db):
    uid = session.get("user_id")
    if not uid:
        return None
    return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def get_owned_client(db, client_id):
    """Renvoie le client s'il existe ET appartient a l'utilisateur connecte, sinon None."""
    return db.execute(
        "SELECT * FROM clients WHERE id = ? AND user_id = ?", (client_id, current_uid())
    ).fetchone()


@app.before_request
def load_db():
    g.db = get_db()


@app.teardown_request
def close_db(exc):
    db = getattr(g, "db", None)
    if db is not None:
        db.close()


# ---------- auth ----------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    db = g.db
    if request.method == "POST":
        agency_name = request.form.get("agency_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email et mot de passe requis.", "error")
            return redirect(url_for("signup"))

        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("Un compte existe deja avec cet email. Connecte-toi plutot.", "error")
            return redirect(url_for("login"))

        cur = db.execute(
            "INSERT INTO users (email, password_hash, agency_name, created_at) VALUES (?, ?, ?, ?) RETURNING id",
            (email, generate_password_hash(password), agency_name or "Mon agence", now()),
        )
        user_id = cur.fetchone()["id"]
        db.commit()

        session["user_id"] = user_id
        flash("Compte cree avec succes. Bienvenue !", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    db = g.db

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Identifiants incorrects.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- landing page ----------

@app.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


# ---------- dashboard ----------

@app.route("/dashboard")
@login_required
def dashboard():
    db = g.db
    uid = current_uid()
    clients = db.execute("SELECT * FROM clients WHERE user_id = ? ORDER BY name", (uid,)).fetchall()

    total_cost = db.execute("""
        SELECT COALESCE(SUM(u.cost_usd),0) AS s FROM usage_entries u
        JOIN projects p ON p.id = u.project_id
        JOIN clients c ON c.id = p.client_id
        WHERE c.user_id = ?
    """, (uid,)).fetchone()["s"]

    total_billed = db.execute("""
        SELECT COALESCE(SUM(i.total_billed),0) AS s FROM invoices i
        JOIN clients c ON c.id = i.client_id WHERE c.user_id = ?
    """, (uid,)).fetchone()["s"]

    total_invoiced_cost = db.execute("""
        SELECT COALESCE(SUM(i.subtotal_cost),0) AS s FROM invoices i
        JOIN clients c ON c.id = i.client_id WHERE c.user_id = ?
    """, (uid,)).fetchone()["s"]

    uninvoiced_cost = db.execute("""
        SELECT COALESCE(SUM(u.cost_usd),0) AS s FROM usage_entries u
        JOIN projects p ON p.id = u.project_id
        JOIN clients c ON c.id = p.client_id
        WHERE c.user_id = ? AND u.invoice_id IS NULL
    """, (uid,)).fetchone()["s"]

    margin = total_billed - total_invoiced_cost

    per_client = db.execute("""
        SELECT c.id, c.name, c.default_markup_pct,
               COALESCE(SUM(u.cost_usd), 0) AS total_cost,
               COALESCE(SUM(CASE WHEN u.invoice_id IS NULL THEN u.cost_usd ELSE 0 END), 0) AS uninvoiced_cost
        FROM clients c
        LEFT JOIN projects p ON p.client_id = c.id
        LEFT JOIN usage_entries u ON u.project_id = p.id
        WHERE c.user_id = ?
        GROUP BY c.id
        ORDER BY total_cost DESC
    """, (uid,)).fetchall()

    recent_entries = db.execute("""
        SELECT u.*, p.name AS project_name, c.name AS client_name
        FROM usage_entries u
        JOIN projects p ON p.id = u.project_id
        JOIN clients c ON c.id = p.client_id
        WHERE c.user_id = ?
        ORDER BY u.entry_date DESC, u.id DESC
        LIMIT 8
    """, (uid,)).fetchall()

    return render_template(
        "dashboard.html",
        clients=clients,
        total_cost=total_cost,
        total_billed=total_billed,
        margin=margin,
        uninvoiced_cost=uninvoiced_cost,
        per_client=per_client,
        recent_entries=recent_entries,
    )


# ---------- clients ----------

@app.route("/clients", methods=["GET", "POST"])
@login_required
def clients():
    db = g.db
    uid = current_uid()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("contact_email", "").strip()
        markup = float(request.form.get("default_markup_pct") or 30)
        notes = request.form.get("notes", "").strip()
        if name:
            db.execute(
                "INSERT INTO clients (user_id, name, contact_email, default_markup_pct, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, name, email, markup, notes, now()),
            )
            db.commit()
            flash(f"Client '{name}' cree.", "success")
        return redirect(url_for("clients"))

    all_clients = db.execute("SELECT * FROM clients WHERE user_id = ? ORDER BY name", (uid,)).fetchall()
    return render_template("clients.html", clients=all_clients)


@app.route("/clients/<int:client_id>", methods=["GET", "POST"])
@login_required
def client_detail(client_id):
    db = g.db
    client = get_owned_client(db, client_id)
    if not client:
        flash("Client introuvable.", "error")
        return redirect(url_for("clients"))

    if request.method == "POST":
        form = request.form.get("form_name")
        if form == "new_project":
            name = request.form.get("project_name", "").strip()
            if name:
                db.execute(
                    "INSERT INTO projects (client_id, name, created_at) VALUES (?, ?, ?)",
                    (client_id, name, now()),
                )
                db.commit()
                flash(f"Projet '{name}' ajoute.", "success")
        elif form == "update_markup":
            markup = float(request.form.get("default_markup_pct") or 30)
            db.execute("UPDATE clients SET default_markup_pct = ? WHERE id = ?", (markup, client_id))
            db.commit()
            flash("Marge par defaut mise a jour.", "success")
        return redirect(url_for("client_detail", client_id=client_id))

    projects = db.execute(
        "SELECT * FROM projects WHERE client_id = ? ORDER BY name", (client_id,)
    ).fetchall()

    project_ids = [p["id"] for p in projects]
    entries = []
    total_cost = 0
    uninvoiced_cost = 0
    if project_ids:
        qmarks = ",".join("?" * len(project_ids))
        entries = db.execute(
            f"""SELECT u.*, p.name AS project_name FROM usage_entries u
                JOIN projects p ON p.id = u.project_id
                WHERE u.project_id IN ({qmarks})
                ORDER BY u.entry_date DESC LIMIT 30""",
            project_ids,
        ).fetchall()
        total_cost = db.execute(
            f"SELECT COALESCE(SUM(cost_usd),0) AS s FROM usage_entries WHERE project_id IN ({qmarks})",
            project_ids,
        ).fetchone()["s"]
        uninvoiced_cost = db.execute(
            f"""SELECT COALESCE(SUM(cost_usd),0) AS s FROM usage_entries
                WHERE project_id IN ({qmarks}) AND invoice_id IS NULL""",
            project_ids,
        ).fetchone()["s"]

    invoices = db.execute(
        "SELECT * FROM invoices WHERE client_id = ? ORDER BY created_at DESC", (client_id,)
    ).fetchall()

    return render_template(
        "client_detail.html",
        client=client, projects=projects, entries=entries,
        total_cost=total_cost, uninvoiced_cost=uninvoiced_cost, invoices=invoices,
    )


# ---------- usage entries ----------

@app.route("/usage", methods=["GET", "POST"])
@login_required
def usage():
    db = g.db
    uid = current_uid()
    if request.method == "POST":
        project_id = request.form.get("project_id")
        entry_date = request.form.get("entry_date") or date.today().isoformat()
        provider = request.form.get("provider", "Autre")
        model = request.form.get("model", "").strip()
        description = request.form.get("description", "").strip()
        cost_usd = request.form.get("cost_usd")
        try:
            cost_usd = float(cost_usd)
        except (TypeError, ValueError):
            flash("Cout invalide.", "error")
            return redirect(url_for("usage"))

        owns_project = db.execute("""
            SELECT p.id FROM projects p JOIN clients c ON c.id = p.client_id
            WHERE p.id = ? AND c.user_id = ?
        """, (project_id, uid)).fetchone()

        if project_id and owns_project:
            db.execute(
                """INSERT INTO usage_entries
                   (project_id, entry_date, provider, model, description, cost_usd, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, entry_date, provider, model, description, cost_usd, now()),
            )
            db.commit()
            flash("Usage enregistre.", "success")
        else:
            flash("Projet invalide.", "error")
        return redirect(url_for("usage"))

    projects = db.execute("""
        SELECT p.id, p.name, c.name AS client_name
        FROM projects p JOIN clients c ON c.id = p.client_id
        WHERE c.user_id = ?
        ORDER BY c.name, p.name
    """, (uid,)).fetchall()

    recent = db.execute("""
        SELECT u.*, p.name AS project_name, c.name AS client_name
        FROM usage_entries u
        JOIN projects p ON p.id = u.project_id
        JOIN clients c ON c.id = p.client_id
        WHERE c.user_id = ?
        ORDER BY u.entry_date DESC, u.id DESC
        LIMIT 50
    """, (uid,)).fetchall()

    return render_template("usage.html", projects=projects, entries=recent, providers=PROVIDERS)


@app.route("/usage/import", methods=["POST"])
@login_required
def usage_import():
    db = g.db
    uid = current_uid()
    file = request.files.get("csv_file")
    if not file:
        flash("Aucun fichier fourni.", "error")
        return redirect(url_for("usage"))

    owned_project_ids = {
        str(r["id"]) for r in db.execute("""
            SELECT p.id FROM projects p JOIN clients c ON c.id = p.client_id
            WHERE c.user_id = ?
        """, (uid,)).fetchall()
    }

    stream = io.StringIO(file.stream.read().decode("utf-8"))
    reader = csv.DictReader(stream)
    # colonnes attendues : project_id, entry_date, provider, model, description, cost_usd
    count = 0
    for row in reader:
        if row.get("project_id") not in owned_project_ids:
            continue
        try:
            db.execute(
                """INSERT INTO usage_entries
                   (project_id, entry_date, provider, model, description, cost_usd, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["project_id"], row["entry_date"], row.get("provider", "Autre"),
                    row.get("model", ""), row.get("description", ""),
                    float(row["cost_usd"]), now(),
                ),
            )
            count += 1
        except Exception:
            continue
    db.commit()
    flash(f"{count} lignes importees.", "success")
    return redirect(url_for("usage"))


# ---------- invoices ----------

@app.route("/invoices", methods=["GET", "POST"])
@login_required
def invoices():
    db = g.db
    uid = current_uid()

    if request.method == "POST":
        client_id = request.form.get("client_id")
        period_start = request.form.get("period_start")
        period_end = request.form.get("period_end")
        markup_pct = request.form.get("markup_pct")

        client = get_owned_client(db, client_id)
        if not client:
            flash("Client invalide.", "error")
            return redirect(url_for("invoices"))

        markup_pct = float(markup_pct) if markup_pct else client["default_markup_pct"]

        rows = db.execute("""
            SELECT u.id, u.cost_usd FROM usage_entries u
            JOIN projects p ON p.id = u.project_id
            WHERE p.client_id = ? AND u.invoice_id IS NULL
              AND u.entry_date >= ? AND u.entry_date <= ?
        """, (client_id, period_start, period_end)).fetchall()

        if not rows:
            flash("Aucun usage non facture sur cette periode pour ce client.", "error")
            return redirect(url_for("invoices"))

        subtotal = round(sum(r["cost_usd"] for r in rows), 2)
        total_billed = round(subtotal * (1 + markup_pct / 100), 2)

        cur = db.execute(
            """INSERT INTO invoices
               (client_id, period_start, period_end, subtotal_cost, markup_pct, total_billed, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'draft', ?) RETURNING id""",
            (client_id, period_start, period_end, subtotal, markup_pct, total_billed, now()),
        )
        invoice_id = cur.fetchone()["id"]

        ids = [r["id"] for r in rows]
        qmarks = ",".join("?" * len(ids))
        db.execute(f"UPDATE usage_entries SET invoice_id = ? WHERE id IN ({qmarks})", [invoice_id] + ids)
        db.commit()

        flash(f"Facture INV-{invoice_id:05d} generee : {total_billed:.2f} USD.", "success")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))

    all_clients = db.execute("SELECT * FROM clients WHERE user_id = ? ORDER BY name", (uid,)).fetchall()
    all_invoices = db.execute("""
        SELECT i.*, c.name AS client_name FROM invoices i
        JOIN clients c ON c.id = i.client_id
        WHERE c.user_id = ?
        ORDER BY i.created_at DESC
    """, (uid,)).fetchall()

    return render_template("invoices.html", clients=all_clients, invoices=all_invoices, today=date.today().isoformat())


def get_owned_invoice(db, invoice_id):
    return db.execute("""
        SELECT i.* FROM invoices i
        JOIN clients c ON c.id = i.client_id
        WHERE i.id = ? AND c.user_id = ?
    """, (invoice_id, current_uid())).fetchone()


@app.route("/invoices/<int:invoice_id>")
@login_required
def invoice_detail(invoice_id):
    db = g.db
    invoice = get_owned_invoice(db, invoice_id)
    if not invoice:
        flash("Facture introuvable.", "error")
        return redirect(url_for("invoices"))
    client = db.execute("SELECT * FROM clients WHERE id = ?", (invoice["client_id"],)).fetchone()
    items = db.execute("""
        SELECT u.*, p.name AS project_name FROM usage_entries u
        JOIN projects p ON p.id = u.project_id
        WHERE u.invoice_id = ?
        ORDER BY u.entry_date
    """, (invoice_id,)).fetchall()
    return render_template("invoice_detail.html", invoice=invoice, client=client, items=items)


@app.route("/invoices/<int:invoice_id>/pdf")
@login_required
def invoice_pdf_download(invoice_id):
    from invoice_pdf import build_invoice_pdf
    db = g.db
    invoice = get_owned_invoice(db, invoice_id)
    if not invoice:
        flash("Facture introuvable.", "error")
        return redirect(url_for("invoices"))
    client = db.execute("SELECT * FROM clients WHERE id = ?", (invoice["client_id"],)).fetchone()
    items = db.execute("""
        SELECT u.*, p.name AS project_name FROM usage_entries u
        JOIN projects p ON p.id = u.project_id
        WHERE u.invoice_id = ?
        ORDER BY u.entry_date
    """, (invoice_id,)).fetchall()

    user = get_current_user(db)
    agency_name = user["agency_name"] if user else "Mon agence"

    pdf_bytes = build_invoice_pdf(agency_name, invoice, client, items)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"facture-INV-{invoice_id:05d}.pdf",
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=True)
