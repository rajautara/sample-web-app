"""
Contoh Flask webapp untuk intranet: tsidsgdev01:9000

Ciri:
  - Papar siapa yang login (Windows login, tanpa password)
  - Nota peribadi: setiap user nampak nota sendiri sahaja (SQLite)
  - Log akses: setiap lawatan direkod
  - Halaman /admin: hanya untuk ahli AD group ADMIN_GROUP

pip install flask waitress pywin32
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, url_for

import winauth

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "app.db"

app = Flask(__name__)
# Tukar kepada nama group AD sebenar, contoh "TSIDSG\\WebApp-Admins"
app.config["ADMIN_GROUP"] = os.environ.get("ADMIN_GROUP", "")
winauth.init_app(app)


# ---------- Database ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                body TEXT NOT NULL,
                created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                path TEXT NOT NULL,
                at TEXT NOT NULL
            );
        """)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.before_request
def log_access():
    # Berjalan selepas winauth, jadi g.user sudah ada
    if request.endpoint != "static":
        db = get_db()
        db.execute("INSERT INTO access_log (user, path, at) VALUES (?, ?, ?)",
                   (g.user, request.path, now()))
        db.commit()


# ---------- Routes ----------

@app.route("/")
def index():
    notes = get_db().execute(
        "SELECT id, body, created FROM notes WHERE owner = ? ORDER BY id DESC",
        (g.user,),
    ).fetchall()
    return render_template("index.html", notes=notes)


@app.post("/notes")
def add_note():
    body = request.form.get("body", "").strip()
    if body:
        db = get_db()
        db.execute("INSERT INTO notes (owner, body, created) VALUES (?, ?, ?)",
                   (g.user, body[:1000], now()))
        db.commit()
    return redirect(url_for("index"))


@app.post("/notes/<int:note_id>/delete")
def delete_note(note_id):
    db = get_db()
    # Syarat owner = g.user: user tak boleh padam nota orang lain
    db.execute("DELETE FROM notes WHERE id = ? AND owner = ?", (note_id, g.user))
    db.commit()
    return redirect(url_for("index"))


@app.route("/admin")
@winauth.admin_required
def admin():
    db = get_db()
    users = db.execute("""
        SELECT user, COUNT(*) AS visits, MAX(at) AS last_seen
        FROM access_log GROUP BY user ORDER BY last_seen DESC
    """).fetchall()
    recent = db.execute(
        "SELECT user, path, at FROM access_log ORDER BY id DESC LIMIT 20"
    ).fetchall()
    return render_template("admin.html", users=users, recent=recent)


@app.errorhandler(401)
def unauthorized(_e):
    return render_template("error.html", code=401,
                           msg="Login Windows tidak dikesan. Buka dari PC syarikat."), 401


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403,
                           msg="Anda tiada akses ke halaman ini."), 403


init_db()

if __name__ == "__main__":
    from waitress import serve

    # IIS beri port rawak melalui HTTP_PLATFORM_PORT. 5000 hanya untuk test sendiri.
    port = int(os.environ.get("HTTP_PLATFORM_PORT", 5000))
    serve(app, host="127.0.0.1", port=port)
