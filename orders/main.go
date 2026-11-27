package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

type order struct {
	ID        int64  `json:"id"`
	Item      string `json:"item"`
	Quantity  int64  `json:"quantity"`
	Status    string `json:"status"`
	CreatedAt string `json:"created_at"`
}

type server struct {
	db *sql.DB
}

func send(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		log.Print(err)
	}
}

func failure(w http.ResponseWriter, status int, message string) {
	send(w, status, map[string]string{"error": message})
}

func decode(w http.ResponseWriter, r *http.Request, result any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 65536)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	err := decoder.Decode(result)
	if err == nil {
		if trailing := decoder.Decode(new(any)); trailing != io.EOF {
			err = trailing
			if err == nil {
				err = errors.New("varios valores JSON")
			}
		}
	}
	if err == nil {
		return true
	}
	var size *http.MaxBytesError
	if errors.As(err, &size) {
		failure(w, 413, "El cuerpo es demasiado grande")
	} else {
		failure(w, 400, "Cuerpo JSON inválido")
	}
	return false
}

func scan(row interface{ Scan(...any) error }) (order, error) {
	var result order
	err := row.Scan(&result.ID, &result.Item, &result.Quantity, &result.Status, &result.CreatedAt)
	return result, err
}

const columns = "id, item, quantity, status, created_at"

func orderResult(w http.ResponseWriter, success int, result order, err error) {
	switch {
	case errors.Is(err, sql.ErrNoRows):
		failure(w, 404, "Pedido no encontrado")
	case err != nil:
		log.Print(err)
		failure(w, 500, "Error de base de datos")
	default:
		send(w, success, result)
	}
}

func (s server) list(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.QueryContext(r.Context(), "SELECT "+columns+" FROM orders ORDER BY id")
	if err != nil {
		orderResult(w, 200, order{}, err)
		return
	}
	defer rows.Close()
	result := make([]order, 0)
	for rows.Next() {
		value, err := scan(rows)
		if err != nil {
			orderResult(w, 200, order{}, err)
			return
		}
		result = append(result, value)
	}
	if err := rows.Err(); err != nil {
		orderResult(w, 200, order{}, err)
		return
	}
	send(w, 200, result)
}

func (s server) create(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Item     string `json:"item"`
		Quantity int64  `json:"quantity"`
	}
	if !decode(w, r, &body) {
		return
	}
	item := strings.TrimSpace(body.Item)
	if item == "" || body.Quantity <= 0 {
		failure(w, 400, "item y quantity positiva son obligatorios")
		return
	}
	row := s.db.QueryRowContext(r.Context(),
		"INSERT INTO orders (item, quantity) VALUES (?, ?) RETURNING "+columns, item, body.Quantity)
	result, err := scan(row)
	orderResult(w, 201, result, err)
}

func (s server) byID(w http.ResponseWriter, r *http.Request, id int64) {
	ctx := r.Context()
	switch r.Method {
	case http.MethodGet:
		result, err := scan(s.db.QueryRowContext(ctx, "SELECT "+columns+" FROM orders WHERE id = ?", id))
		orderResult(w, 200, result, err)
	case http.MethodPatch:
		var body struct {
			Status string `json:"status"`
		}
		if !decode(w, r, &body) {
			return
		}
		switch body.Status {
		case "pending", "processing", "shipped", "delivered", "cancelled":
		default:
			failure(w, 400, "Estado inválido")
			return
		}
		row := s.db.QueryRowContext(ctx, "UPDATE orders SET status = ? WHERE id = ? RETURNING "+columns, body.Status, id)
		result, err := scan(row)
		orderResult(w, 200, result, err)
	case http.MethodDelete:
		var deleted int64
		err := s.db.QueryRowContext(ctx, "DELETE FROM orders WHERE id = ? RETURNING id", id).Scan(&deleted)
		if err != nil {
			orderResult(w, 200, order{}, err)
			return
		}
		send(w, 200, map[string]bool{"deleted": true})
	default:
		w.Header().Set("Allow", "GET, PATCH, DELETE")
		failure(w, 405, "Método no permitido")
	}
}

func (s server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/orders" {
		switch r.Method {
		case http.MethodGet:
			s.list(w, r)
		case http.MethodPost:
			s.create(w, r)
		default:
			w.Header().Set("Allow", "GET, POST")
			failure(w, 405, "Método no permitido")
		}
		return
	}
	suffix, found := strings.CutPrefix(r.URL.Path, "/orders/")
	if !found || suffix == "" || strings.Contains(suffix, "/") {
		failure(w, 404, "Ruta no encontrada")
		return
	}
	id, err := strconv.ParseInt(suffix, 10, 64)
	if err != nil || id <= 0 {
		failure(w, 400, "ID inválido")
		return
	}
	s.byID(w, r, id)
}

func main() {
	path := os.Getenv("DB_PATH")
	if path == "" {
		path = "orders.db"
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )`)
	if err != nil {
		log.Fatal(err)
	}
	service := &http.Server{Addr: ":8002", Handler: server{db: db}, ReadHeaderTimeout: 5 * time.Second}
	log.Print("Orders API en el puerto 8002")
	log.Fatal(service.ListenAndServe())
}
