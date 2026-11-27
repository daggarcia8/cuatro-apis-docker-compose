import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonParseException;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Map;
import java.util.concurrent.Executors;

public class AuthServer {
    private static final Gson JSON = new Gson();
    private static final String DB_URL = "jdbc:sqlite:" +
            System.getenv().getOrDefault("DB_PATH", "auth.db");
    private static final int MAX_BODY = 65536;

    private static Connection connect() throws SQLException {
        return DriverManager.getConnection(DB_URL);
    }

    private static byte[] hash(String password, byte[] salt) throws GeneralSecurityException {
        PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, 600_000, 256);
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                    .generateSecret(spec).getEncoded();
        } finally {
            spec.clearPassword();
        }
    }

    private static void initialize() throws SQLException, GeneralSecurityException {
        try (Connection db = connect(); Statement schema = db.createStatement()) {
            schema.executeUpdate("CREATE TABLE IF NOT EXISTS accounts (" +
                    "id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT NOT NULL UNIQUE, " +
                    "salt BLOB NOT NULL, password_hash BLOB NOT NULL)");
            schema.executeUpdate("CREATE TABLE IF NOT EXISTS login_attempts (" +
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, " +
                    "valid INTEGER NOT NULL CHECK (valid IN (0, 1)), " +
                    "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)");
            try (ResultSet account = schema.executeQuery("SELECT id FROM accounts WHERE id = 1")) {
                if (account.next()) {
                    return;
                }
            }
            String username = System.getenv().getOrDefault("AUTH_USERNAME", "demo");
            String password = System.getenv().getOrDefault("AUTH_PASSWORD", "demo-password");
            if (username.isBlank() || password.isBlank()) {
                throw new IllegalArgumentException("La cuenta inicial requiere usuario y contraseña");
            }
            byte[] salt = new byte[16];
            new SecureRandom().nextBytes(salt);
            try (PreparedStatement insert = db.prepareStatement(
                    "INSERT OR IGNORE INTO accounts (id, username, salt, password_hash) VALUES (1, ?, ?, ?)")) {
                insert.setString(1, username);
                insert.setBytes(2, salt);
                insert.setBytes(3, hash(password, salt));
                insert.executeUpdate();
            }
        }
    }

    private static boolean authenticate(String username, String password)
            throws SQLException, GeneralSecurityException {
        try (Connection db = connect()) {
            boolean valid;
            try (Statement lookup = db.createStatement();
                 ResultSet account = lookup.executeQuery("SELECT username, salt, password_hash FROM accounts WHERE id = 1")) {
                if (!account.next()) {
                    throw new SQLException("Falta la cuenta inicial");
                }
                byte[] candidate = hash(password, account.getBytes("salt"));
                valid = MessageDigest.isEqual(account.getBytes("password_hash"), candidate)
                        && username.equals(account.getString("username"));
            }
            try (PreparedStatement attempt = db.prepareStatement(
                    "INSERT INTO login_attempts (username, valid) VALUES (?, ?)")) {
                attempt.setString(1, username);
                attempt.setInt(2, valid ? 1 : 0);
                attempt.executeUpdate();
            }
            return valid;
        }
    }

    private static void send(HttpExchange exchange, int status, Object value) throws IOException {
        byte[] body = JSON.toJson(value).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, body.length);
        exchange.getResponseBody().write(body);
    }

    private static String requiredText(JsonObject body, String key) {
        JsonElement value = body.get(key);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()
                || value.getAsString().isBlank()) {
            throw new IllegalArgumentException("username y password deben ser textos no vacíos");
        }
        return value.getAsString();
    }

    private static void login(HttpExchange exchange)
            throws IOException, SQLException, GeneralSecurityException {
        byte[] input = exchange.getRequestBody().readNBytes(MAX_BODY + 1);
        if (input.length > MAX_BODY) {
            send(exchange, 413, Map.of("error", "El cuerpo es demasiado grande"));
            return;
        }
        JsonElement element = JsonParser.parseString(new String(input, StandardCharsets.UTF_8));
        if (!element.isJsonObject()) {
            throw new IllegalArgumentException("Envía un objeto JSON");
        }
        JsonObject body = element.getAsJsonObject();
        boolean valid = authenticate(requiredText(body, "username"), requiredText(body, "password"));
        send(exchange, valid ? 200 : 401, Map.of("valid", valid));
    }

    private static void handle(HttpExchange exchange) throws IOException {
        try {
            String path = exchange.getRequestURI().getPath();
            if (!path.equals("/login") && !path.equals("/health")) {
                send(exchange, 404, Map.of("error", "Ruta no encontrada"));
                return;
            }
            String allowed = path.equals("/login") ? "POST" : "GET";
            if (!allowed.equals(exchange.getRequestMethod())) {
                exchange.getResponseHeaders().set("Allow", allowed);
                send(exchange, 405, Map.of("error", "Método no permitido"));
                return;
            }
            if (path.equals("/login")) {
                login(exchange);
                return;
            }
            try (Connection db = connect(); Statement statement = db.createStatement();
                 ResultSet result = statement.executeQuery("SELECT 1 FROM accounts WHERE id = 1")) {
                boolean ready = result.next();
                send(exchange, ready ? 200 : 503, Map.of("status", ready ? "ok" : "unavailable"));
            }
        } catch (JsonParseException | IllegalArgumentException error) {
            send(exchange, 400, Map.of("error", "JSON inválido o faltan username y password"));
        } catch (SQLException | GeneralSecurityException error) {
            error.printStackTrace();
            if (exchange.getRequestURI().getPath().equals("/health")) {
                send(exchange, 503, Map.of("status", "unavailable"));
            } else {
                send(exchange, 500, Map.of("error", "Error interno"));
            }
        } finally {
            exchange.close();
        }
    }

    public static void main(String[] args) throws Exception {
        initialize();
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", 8001), 0);
        server.createContext("/", AuthServer::handle);
        server.setExecutor(Executors.newFixedThreadPool(4));
        server.start();
        System.out.println("Auth API en el puerto 8001");
    }
}
