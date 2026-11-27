import os
import sqlite3

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "users.db")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


with app.app_context():
    db().execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL
        )
    """)


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=error.description), error.code


@app.errorhandler(sqlite3.Error)
def database_error(error):
    app.logger.error("SQLite: %s", error)
    return jsonify(error="Error de base de datos"), 500


def get_user(id):
    row = db().execute(
        "SELECT id, name, email FROM users WHERE id = ?", (id,)
    ).fetchone()
    return dict(row) if row else None


@app.get("/users")
def list_users():
    rows = db().execute("SELECT id, name, email FROM users ORDER BY id")
    return jsonify([dict(row) for row in rows])


@app.get("/users/<int:id>")
def read_user(id):
    user = get_user(id)
    return jsonify(user) if user else (jsonify(error="Usuario no encontrado"), 404)


@app.route("/users", methods=["POST"])
@app.route("/users/<int:id>", methods=["PATCH"])
def save_user(id=None):
    body = request.get_json(silent=True)
    allowed = {"name", "email", "password"}
    if not isinstance(body, dict) or not body or body.keys() - allowed:
        return jsonify(error="Envía un objeto con name, email o password"), 400
    if id is None and body.keys() != allowed:
        return jsonify(error="name, email y password son obligatorios"), 400
    if any(not isinstance(value, str) or not value.strip() for value in body.values()):
        return jsonify(error="Los campos deben ser textos no vacíos"), 400

    values = {}
    if "name" in body:
        values["name"] = body["name"].strip()
    if "email" in body:
        email = body["email"].strip()
        if email.count("@") != 1 or any(c.isspace() for c in email) or not all(email.split("@")):
            return jsonify(error="Correo inválido"), 400
        values["email"] = email
    if "password" in body:
        values["password_hash"] = generate_password_hash(body["password"])

    try:
        with db() as connection:
            if id is None:
                cursor = connection.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (:name, :email, :password_hash)",
                    values,
                )
                return jsonify(get_user(cursor.lastrowid)), 201
            assignments = ", ".join(f"{column} = ?" for column in values)
            cursor = connection.execute(
                f"UPDATE users SET {assignments} WHERE id = ?", (*values.values(), id)
            )
            if cursor.rowcount == 0:
                return jsonify(error="Usuario no encontrado"), 404
            return jsonify(get_user(id))
    except sqlite3.IntegrityError:
        return jsonify(error="El correo ya está registrado"), 409


@app.delete("/users/<int:id>")
def delete_user(id):
    with db() as connection:
        cursor = connection.execute("DELETE FROM users WHERE id = ?", (id,))
    if cursor.rowcount == 0:
        return jsonify(error="Usuario no encontrado"), 404
    return jsonify(deleted=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
