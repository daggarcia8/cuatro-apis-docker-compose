# Cuatro APIs con Docker Compose

| Servicio | Lenguaje | Puerto local | Base de datos | Volumen |
| --- | --- | --- | --- | --- |
| Users | Python | 8000 | `users.db` | `users-data` |
| Auth | Java | 8001 | `auth.db` | `auth-data` |
| Orders | Go | 8002 | `orders.db` | `orders-data` |
| Products | JavaScript | 8003 | `products.db` | `products-data` |

Cada servicio crea sus tablas al iniciar. Cada contenedor monta exclusivamente su volumen en `/data`.

## Ejecutar y detener

Desde el directorio del repositorio, con Docker en ejecución y Docker Compose disponible:

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail 20
docker compose stop
docker compose start
docker compose down
docker compose up -d
```

`stop` detiene los contenedores. `down` los elimina y conserva los volúmenes. Al volver a ejecutar `up`, cada API recupera los datos de su volumen. La opción `down -v` elimina también los volúmenes y sus bases de datos.

## Endpoints

Envía los cuerpos con `Content-Type: application/json`. Sustituye `{id}` por el identificador devuelto al crear el registro.

| Puerto | Método | Ruta | Ejemplo de cuerpo |
| --- | --- | --- | --- |
| 8000 | POST | `/users` | `{"name":"Ana","email":"ana@example.com","password":"demo-password"}` |
| 8000 | GET | `/users` | |
| 8000 | GET | `/users/{id}` | |
| 8000 | PATCH | `/users/{id}` | `{"name":"Ana Gómez"}` |
| 8000 | DELETE | `/users/{id}` | |
| 8001 | GET | `/health` | |
| 8001 | POST | `/login` | `{"username":"demo","password":"demo-password"}` |
| 8002 | POST | `/orders` | `{"item":"Teclado","quantity":2}` |
| 8002 | GET | `/orders` | |
| 8002 | GET | `/orders/{id}` | |
| 8002 | PATCH | `/orders/{id}` | `{"status":"shipped"}` |
| 8002 | DELETE | `/orders/{id}` | |
| 8003 | POST | `/products` | `{"name":"Teclado","price":45.5,"description":"USB","stock":10}` |
| 8003 | GET | `/products` | |
| 8003 | GET | `/products/{id}` | |
| 8003 | PATCH | `/products/{id}` | `{"stock":7}` |
| 8003 | DELETE | `/products/{id}` | |

Puedes consultar las cuatro APIs desde el navegador o un cliente HTTP en `http://localhost:8000/users`, `http://localhost:8001/health`, `http://localhost:8002/orders` y `http://localhost:8003/products`.

Los pedidos empiezan en `pending`. Los estados admitidos son `pending`, `processing`, `shipped`, `delivered` y `cancelled`. La fecha se registra en UTC.

Auth mantiene su propia cuenta inicial y guarda los intentos de autenticación en `auth.db`. El login devuelve HTTP 200 con `{"valid":true}` o HTTP 401 con `{"valid":false}`. Las credenciales iniciales de demostración son `demo` y `demo-password`. Para usar otras, establece `AUTH_USERNAME` y `AUTH_PASSWORD` en el entorno antes del primer arranque con un volumen de Auth nuevo. Users guarda las contraseñas de sus usuarios como hashes y omite ese campo en las respuestas.

## Demostración

Con Docker Compose y Python 3.10 o posterior, ejecuta desde la raíz:

```sh
python demo.py
```

La demostración construye y levanta los servicios, prueba los endpoints en sus cuatro puertos y comprueba los códigos HTTP y las respuestas JSON. Detiene y arranca los contenedores, inspecciona copias de las cuatro bases SQLite y vuelve a comprobar los datos después de eliminar y recrear los contenedores con los mismos volúmenes. Al final muestra el estado y los logs, elimina los registros de ejemplo de Users, Orders y Products mediante HTTP y detiene la arquitectura conservando los volúmenes. Los intentos de login quedan registrados en Auth.
