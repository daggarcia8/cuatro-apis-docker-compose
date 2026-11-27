"""Demostración verificable de HTTP, SQLite y persistencia con Docker Compose."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
SERVICES = {
    "users": (8000, "/users"),
    "auth": (8001, "/health"),
    "orders": (8002, "/orders"),
    "products": (8003, "/products"),
}


def docker(*args, capture=False):
    result = subprocess.run(
        ["docker", *args], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else None


def compose(*args, capture=False):
    return docker("compose", *args, capture=capture)


def expect(condition, message):
    if not condition:
        raise RuntimeError(message)


def http(service, method, path, payload=None, expected=200):
    port, _ = SERVICES[service]
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        expect(response.status == expected, f"{method} {port}{path}: HTTP {response.status}, esperado {expected}: {raw!r}")
        expect(response.headers.get_content_type() == "application/json", f"{port}{path} debe responder JSON")
        return json.loads(raw)


def wait_for_services():
    pending = set(SERVICES)
    deadline = time.monotonic() + 60
    while pending and time.monotonic() < deadline:
        for name in sorted(pending):
            port, path = SERVICES[name]
            try:
                http(name, "GET", path)
            except (URLError, RuntimeError, TimeoutError):
                continue
            print(f"{name} disponible en {port}", flush=True)
            pending.remove(name)
        if pending:
            time.sleep(1)
    expect(not pending, f"Servicios sin respuesta: {', '.join(sorted(pending))}")


def inspect_storage():
    volumes = set()
    containers = {}
    for service in SERVICES:
        container_id = compose("ps", "-q", service, capture=True)
        info = json.loads(docker("inspect", container_id, capture=True))[0]
        mounts = info["Mounts"]
        expect(info["State"]["Running"], f"{service} debe estar en ejecución")
        expect(len(mounts) == 1 and mounts[0]["Type"] == "volume" and
               mounts[0]["Destination"] == "/data", f"Montaje inesperado en {service}")
        volumes.add(mounts[0]["Name"])
        containers[service] = (container_id, mounts[0]["Name"])
    expect(len(volumes) == len(SERVICES), "Cada servicio debe tener un volumen distinto")
    return containers


def verify_databases(records, auth_username, invalid_username):
    queries = {
        "users": ("SELECT name, email FROM users WHERE id = ?", ("Ana Gómez", records["users"]["email"])),
        "orders": ("SELECT item, status FROM orders WHERE id = ?", ("Teclado", "shipped")),
        "products": ("SELECT name, stock FROM products WHERE id = ?", ("Teclado", 7)),
    }
    with tempfile.TemporaryDirectory() as directory:
        for name in SERVICES:
            snapshot = Path(directory) / f"{name}.db"
            compose("cp", f"{name}:/data/{name}.db", str(snapshot))
            connection = sqlite3.connect(f"{snapshot.as_uri()}?mode=ro", uri=True)
            try:
                if name == "auth":
                    attempts = connection.execute(
                        "SELECT DISTINCT username, valid FROM login_attempts WHERE username IN (?, ?)",
                        (auth_username, invalid_username),
                    ).fetchall()
                    expect((auth_username, 1) in attempts and (invalid_username, 0) in attempts,
                           "auth.db debe conservar los intentos válido e inválido")
                else:
                    query, expected = queries[name]
                    row = connection.execute(query, (records[name]["id"],)).fetchone()
                    expect(row == expected, f"Datos inesperados en {name}.db: {row!r}")
            finally:
                connection.close()
            print(f"{name}.db verificada", flush=True)


def demo():
    username = os.environ.get("AUTH_USERNAME") or "demo"
    password = os.environ.get("AUTH_PASSWORD") or "demo-password"
    token = uuid4().hex
    invalid_username = f"invalido-{token}"

    compose("version")
    try:
        compose("up", "-d", "--build")
        wait_for_services()
        original = inspect_storage()
        compose("ps")
        expect(http("auth", "GET", "/health") == {"status": "ok"}, "Auth no está listo")
        expect(http("auth", "POST", "/login", {"username": username, "password": password}) == {"valid": True},
               "El login válido debe devolver valid: true")
        expect(http("auth", "POST", "/login", {"username": invalid_username, "password": password}, 401) ==
               {"valid": False}, "El login inválido debe devolver valid: false")

        resources = {
            "users": ({"name": "Ana", "email": f"{token}@example.com", "password": "demo-password"}, {"name": "Ana Gómez"}),
            "orders": ({"item": "Teclado", "quantity": 2}, {"status": "shipped"}),
            "products": ({"name": "Teclado", "price": 45.5, "description": "USB", "stock": 10}, {"stock": 7}),
        }
        records = {}
        for service, (data, changes) in resources.items():
            _, path = SERVICES[service]
            created = http(service, "POST", path, data, 201)
            resource_path = f"{path}/{created['id']}"
            expect(created in http(service, "GET", path), f"Falta el registro creado en {service}")
            expect(http(service, "GET", resource_path) == created, f"Consulta por ID incorrecta en {service}")
            updated = http(service, "PATCH", resource_path, changes)
            expect(all(updated[key] == value for key, value in changes.items()), f"Actualización incorrecta en {service}")
            records[service] = updated
            print(f"{service}: creación, lista, consulta por ID y actualización verificadas", flush=True)

        compose("stop")
        compose("start")
        wait_for_services()
        for service, record in records.items():
            _, path = SERVICES[service]
            expect(http(service, "GET", f"{path}/{record['id']}") == record,
                   f"Datos perdidos al reiniciar {service}")
        verify_databases(records, username, invalid_username)

        compose("down")
        compose("up", "-d")
        wait_for_services()
        recreated = inspect_storage()
        for name, (old_container, old_volume) in original.items():
            new_container, new_volume = recreated[name]
            expect(old_container != new_container and old_volume == new_volume,
                   f"Se esperaba un contenedor nuevo sobre el mismo volumen para {name}")
        verify_databases(records, username, invalid_username)

        for service, record in records.items():
            _, path = SERVICES[service]
            resource_path = f"{path}/{record['id']}"
            expect(http(service, "GET", resource_path) == record, f"Datos perdidos al recrear {service}")
            expect(http(service, "DELETE", resource_path) == {"deleted": True}, f"Falló la eliminación en {service}")
            http(service, "GET", resource_path, expected=404)
            expect(record not in http(service, "GET", path), f"El registro sigue en la lista de {service}")
            print(f"{service}: persistencia y eliminación verificadas", flush=True)

        compose("ps")
        compose("logs", "--tail", "20")
    finally:
        compose("down")
    print("Demostración completada. Los cuatro volúmenes siguen disponibles.", flush=True)


if __name__ == "__main__":
    demo()
