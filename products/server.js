import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';

const db = new DatabaseSync(process.env.DB_PATH ?? 'products.db');
db.exec(`
  CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    description TEXT NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0)
  )
`);

const list = db.prepare('SELECT * FROM products ORDER BY id');
const read = db.prepare('SELECT * FROM products WHERE id = ?');
const insert = db.prepare(
  'INSERT INTO products (name, price, description, stock) VALUES (?, ?, ?, ?) RETURNING *'
);
const update = db.prepare(
  'UPDATE products SET name = ?, price = ?, description = ?, stock = ? WHERE id = ? RETURNING *'
);
const remove = db.prepare('DELETE FROM products WHERE id = ?');
const validators = {
  name: value => typeof value === 'string' && value.trim().length > 0,
  price: value => Number.isFinite(value) && value >= 0,
  description: value => typeof value === 'string',
  stock: value => Number.isSafeInteger(value) && value >= 0,
};
const fields = Object.keys(validators);

function send(response, status, body) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(body));
}

async function jsonBody(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    size += chunk.length;
    if (size > 65536) {
      request.resume();
      throw new RangeError('El cuerpo es demasiado grande');
    }
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

createServer(async (request, response) => {
  const path = request.url.split('?')[0];
  const match = /^\/products(?:\/([1-9]\d*))?$/.exec(path);
  if (!match) return send(response, 404, { error: 'Ruta no encontrada' });
  const id = match[1] === undefined ? null : Number(match[1]);
  if (id !== null && !Number.isSafeInteger(id)) {
    return send(response, 400, { error: 'ID inválido' });
  }
  const method = request.method;
  const allowed = id === null ? ['GET', 'POST'] : ['GET', 'PATCH', 'DELETE'];
  if (!allowed.includes(method)) {
    response.setHeader('Allow', allowed.join(', '));
    return send(response, 405, { error: 'Método no permitido' });
  }
  const missing = () => send(response, 404, { error: 'Producto no encontrado' });

  try {
    if (method === 'GET' && id === null) return send(response, 200, list.all());
    if (method === 'GET') {
      const product = read.get(id);
      return product ? send(response, 200, product) : missing();
    }
    if (method === 'DELETE') {
      return remove.run(id).changes ? send(response, 200, { deleted: true }) : missing();
    }

    let body;
    try {
      body = await jsonBody(request);
    } catch (error) {
      return send(response, error instanceof RangeError ? 413 : 400, { error: 'Cuerpo JSON inválido o demasiado grande' });
    }
    const keys = body && typeof body === 'object' && !Array.isArray(body) ? Object.keys(body) : [];
    if (!keys.length || (method === 'POST' && keys.length !== fields.length) ||
        keys.some(key => !Object.hasOwn(validators, key) || !validators[key](body[key]))) {
      return send(response, 400, { error: 'Campos inválidos. Usa name, price, description y stock' });
    }

    if (method === 'POST') {
      return send(response, 201, insert.get(body.name.trim(), body.price, body.description, body.stock));
    }
    const existing = read.get(id);
    if (!existing) return missing();
    const product = { ...existing, ...body };
    return send(response, 200, update.get(product.name.trim(), product.price, product.description, product.stock, id));
  } catch (error) {
    console.error(error);
    return send(response, 500, { error: 'Error interno' });
  }
}).listen(8003, '0.0.0.0');
