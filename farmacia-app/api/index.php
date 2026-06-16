<?php
/**
 * ════════════════════════════════════════════════════════════════════════════
 * TPN - Todo Pal Negocio - API REST
 * Versión: 1.0.0
 *
 * INSTALACIÓN EN HOSTINGER:
 * 1. Sube esta carpeta "api/" a tu public_html (quedaría public_html/api/index.php)
 * 2. Ejecuta schema.sql en phpMyAdmin
 * 3. Configura los valores de DB_* y las constantes de abajo
 * 4. Configura APP_URL en services/api.js de la app con tu dominio
 * ════════════════════════════════════════════════════════════════════════════
 */

// ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
// !! CAMBIA ESTOS VALORES con los datos de tu base de datos de Hostinger !!
define('DB_HOST', 'localhost');
define('DB_NAME', 'u992666585_TPN');        // ← Tu nombre de BD en Hostinger
define('DB_USER', 'u992666585_TPN_USER');    // ← Tu usuario de BD
define('DB_PASS', 'JUANPA9912a'); // ← Tu contraseña de BD

// Email de la tienda (para enviar correos de reset de contraseña)
define('MAIL_FROM',    'noreply@tudominio.com');
define('MAIL_FROMNAME','Todo Pal Negocio');
define('APP_NAME',     'Todo Pal Negocio');
define('APP_URL',      'https://todopalnegocio.com.mx/'); // URL de tu app web

// Llave secreta para firmar tokens (cambia por una cadena aleatoria larga)
define('SECRET_KEY', 'cambia_esto_por_una_llave_muy_secreta_2024_TPN');

// Duración de sesión: 30 días
define('SESSION_DAYS', 30);

// ─── CORS + HEADERS ───────────────────────────────────────────────────────────
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');
header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// ─── CONEXIÓN A BASE DE DATOS ─────────────────────────────────────────────────
try {
    $pdo = new PDO(
        "mysql:host=" . DB_HOST . ";dbname=" . DB_NAME . ";charset=utf8mb4",
        DB_USER,
        DB_PASS,
        [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]
    );
    // Sincronizar zona horaria con la BD (México Centro)
    $pdo->exec("SET time_zone = '-06:00'");
} catch (PDOException $e) {
    respond(500, false, 'Error de base de datos. Verifica la configuración.');
}

// ─── PUSH NOTIFICATIONS VÍA EXPO ─────────────────────────────────────────────
// Genera un JWT firmado con la clave privada de la cuenta de servicio de Firebase
function fcmGetAccessToken($sa) {
    $now    = time();
    $header  = rtrim(strtr(base64_encode(json_encode(array('alg'=>'RS256','typ'=>'JWT'))), '+/', '-_'), '=');
    $payload = rtrim(strtr(base64_encode(json_encode(array(
        'iss'   => $sa['client_email'],
        'scope' => 'https://www.googleapis.com/auth/firebase.messaging',
        'aud'   => 'https://oauth2.googleapis.com/token',
        'iat'   => $now,
        'exp'   => $now + 3600,
    ))), '+/', '-_'), '=');
    $unsigned = $header . '.' . $payload;
    openssl_sign($unsigned, $sig, $sa['private_key'], 'SHA256');
    $jwt = $unsigned . '.' . rtrim(strtr(base64_encode($sig), '+/', '-_'), '=');
    $ch = curl_init('https://oauth2.googleapis.com/token');
    curl_setopt_array($ch, array(
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => http_build_query(array('grant_type'=>'urn:ietf:params:oauth:grant-type:jwt-bearer','assertion'=>$jwt)),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_SSL_VERIFYPEER => false,
    ));
    $res = curl_exec($ch); curl_close($ch);
    $tok = json_decode($res, true);
    return isset($tok['access_token']) ? $tok['access_token'] : null;
}

function sendExpoPush($pdo, $userIds, $title, $body, $data = array()) {
    if (empty($userIds)) return;
    try {
        // Asegurar que la columna existe (silencioso si ya existe)
        try { $pdo->exec("ALTER TABLE users ADD COLUMN push_token VARCHAR(255) DEFAULT NULL"); }
        catch (PDOException $e) {}

        $in   = implode(',', array_fill(0, count($userIds), '?'));
        $rows = $pdo->prepare(
            "SELECT push_token FROM users WHERE id IN ($in) AND push_token IS NOT NULL AND push_token != ''"
        );
        $rows->execute($userIds);
        $tokens = array_column($rows->fetchAll(PDO::FETCH_ASSOC), 'push_token');
        if (empty($tokens)) return;

        // ── FCM v1 (cuenta de servicio) ───────────────────────────────────────
        $saPath = __DIR__ . '/firebase-service-account.json';
        if (!file_exists($saPath) || !function_exists('curl_init')) return;
        $sa        = json_decode(file_get_contents($saPath), true);
        $projectId = $sa['project_id'];
        $accessToken = fcmGetAccessToken($sa);
        if (!$accessToken) return;

        // FCM v1 requiere que los valores de data sean strings
        $strData = array();
        foreach ($data as $k => $v) { $strData[$k] = (string)$v; }

        foreach ($tokens as $token) {
            $msg = array('message' => array(
                'token'        => $token,
                'notification' => array('title' => $title, 'body' => $body),
                'android'      => array(
                    'priority'     => 'high',
                    'notification' => array(
                        'channel_id'        => 'pedidos',
                        'sound'             => 'default',
                        'notification_priority' => 'PRIORITY_MAX',
                        'visibility'        => 'PUBLIC',
                    ),
                ),
                'data' => $strData,
            ));
            $ch = curl_init("https://fcm.googleapis.com/v1/projects/{$projectId}/messages:send");
            curl_setopt_array($ch, array(
                CURLOPT_POST           => true,
                CURLOPT_POSTFIELDS     => json_encode($msg),
                CURLOPT_HTTPHEADER     => array(
                    'Authorization: Bearer ' . $accessToken,
                    'Content-Type: application/json',
                ),
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_TIMEOUT        => 5,
                CURLOPT_SSL_VERIFYPEER => false,
            ));
            curl_exec($ch); curl_close($ch);
        }
    } catch (Exception $e) {}
}

// ─── ROUTER ───────────────────────────────────────────────────────────────────
// Soporta 3 estilos de URL:
//   1. /api/products                (con .htaccess rewrite)
//   2. /api/index.php/products      (PATH_INFO directo)
//   3. /api/index.php?resource=products&action=login  (query params, fallback)

$method = $_SERVER['REQUEST_METHOD'];
$body   = json_decode(file_get_contents('php://input'), true) ?? [];

// --- Intentar PATH_INFO primero (funciona con /index.php/resource/action) ---
$pathInfo = trim($_SERVER['PATH_INFO'] ?? '', '/');

// --- Si PATH_INFO está vacío, parsear REQUEST_URI ---
if (empty($pathInfo)) {
    $uri   = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $parts = array_values(array_filter(explode('/', trim($uri, '/'))));
    // Eliminar segmentos que no son datos: 'api', 'index.php'
    $parts = array_values(array_filter($parts, fn($s) => $s !== 'api' && $s !== 'index.php'));
    $pathInfo = implode('/', $parts);
}

// --- Fallback a query params (?resource=products&action=login) ---
$segments = array_values(array_filter(explode('/', $pathInfo)));
if (empty($segments)) {
    $r = $_GET['resource'] ?? $_POST['resource'] ?? '';
    $a = $_GET['action']   ?? $_POST['action']   ?? '';
    $segments = array_filter([$r, $a]);
    $segments = array_values($segments);
}

$resource = $segments[0] ?? '';
$action   = $segments[1] ?? '';

// ─── DISPATCH ─────────────────────────────────────────────────────────────────
switch ($resource) {

    // ── PRODUCTOS ──────────────────────────────────────────────────────────────
    case 'products':
        if ($method === 'GET') {

            // GET /api/products/123 → detalle de un producto
            if (!empty($action) && is_numeric($action)) {
                $stmt = $pdo->prepare(
                    "SELECT id, name, category, price, unit, image_url, extra_images, promo, description, stock,
                            CASE
                                WHEN stock = -1 THEN -1
                                ELSE GREATEST(0, stock - COALESCE((
                                    SELECT SUM(oi.qty)
                                    FROM order_items oi
                                    JOIN orders o ON o.id = oi.order_id
                                    WHERE oi.product_id = products.id
                                      AND (
                                        o.status IN ('accepted','preparing','picked_up','on_the_way','arrived')
                                        OR (o.status = 'pending' AND o.created_at > DATE_SUB(NOW(), INTERVAL 30 MINUTE))
                                      )
                                ), 0))
                            END AS available
                     FROM products WHERE id = ? AND active = 1"
                );
                $stmt->execute([(int)$action]);
                $p = $stmt->fetch();
                if (!$p) respond(404, false, 'Producto no encontrado');

                $p['stock']         = (int)$p['available'];
                $p['price']         = (float)$p['price'];
                $p['price_display'] = '$' . number_format($p['price'], 2) . ' / ' . $p['unit'];
                $p['extra_images'] = $p['extra_images'] ? json_decode($p['extra_images'], true) : [];
                respond(200, true, 'OK', $p);
            }

            $cat = $_GET['category'] ?? null;
            $q   = $_GET['q'] ?? null;

            $sql = "SELECT id, sku, name, category, price, unit, image_url, extra_images, promo, description, stock,
                           CASE
                                WHEN stock = -1 THEN -1
                                ELSE GREATEST(0, stock - COALESCE((
                                    SELECT SUM(oi.qty)
                                    FROM order_items oi
                                    JOIN orders o ON o.id = oi.order_id
                                    WHERE oi.product_id = p.id
                                      AND (
                                        o.status IN ('accepted','preparing','picked_up','on_the_way','arrived')
                                        OR (o.status = 'pending' AND o.created_at > DATE_SUB(NOW(), INTERVAL 30 MINUTE))
                                      )
                                ), 0))
                           END AS real_available
                    FROM products p WHERE active = 1";
            $params = [];

            if ($cat && $cat !== 'all') {
                $sql .= " AND category = ?";
                $params[] = strtoupper($cat);
            }
            if ($q) {
                $sql .= " AND name LIKE ?";
                $params[] = "%$q%";
            }
            
            $sql .= " ORDER BY category, name";

            $stmt = $pdo->prepare($sql);
            $stmt->execute($params);
            $products = $stmt->fetchAll();

            foreach ($products as &$p) {
                $p['price_display'] = "$" . number_format($p['price'], 2) . " / " . $p['unit'];
                $p['price']         = (float) $p['price'];
                $p['stock']         = (int) $p['real_available']; 
                $p['in_stock']      = $p['stock'] > 0 || (int)$p['stock'] === -1;
                $p['extra_images']  = $p['extra_images'] ? json_decode($p['extra_images'], true) : [];
            }

            respond(200, true, 'OK', $products);
        }

        if ($method === 'POST') {
            // Crear/actualizar producto (requiere autenticación de admin en futuro)
            $required = ['name', 'category', 'price', 'unit', 'image_url'];
            foreach ($required as $field) {
                if (empty($body[$field])) {
                    respond(400, false, "Campo requerido: $field");
                }
            }

            $stmt = $pdo->prepare(
                "INSERT INTO products (name, category, price, unit, image_url, promo, description)
                 VALUES (?, ?, ?, ?, ?, ?, ?)"
            );
            $stmt->execute([
                strtoupper(trim($body['name'])),
                strtoupper(trim($body['category'])),
                (float) $body['price'],
                strtoupper(trim($body['unit'])),
                trim($body['image_url']),
                $body['promo'] ?? null,
                $body['description'] ?? null,
            ]);

            respond(201, true, 'Producto creado', ['id' => $pdo->lastInsertId()]);
        }

        respond(405, false, 'Método no permitido');
        break;

    // ── AUTENTICACIÓN ──────────────────────────────────────────────────────────
    case 'auth':
        switch ($action) {

            // ── REGISTRO ────────────────────────────────────────────────────────
            case 'register':
                if ($method !== 'POST') respond(405, false, 'Método no permitido');

                $name     = trim($body['name'] ?? '');
                $email    = strtolower(trim($body['email'] ?? ''));
                $password = $body['password'] ?? '';

                if (!$name || !$email || !$password) {
                    respond(400, false, 'Nombre, email y contraseña son requeridos');
                }
                if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
                    respond(400, false, 'Email inválido');
                }
                if (strlen($password) < 6) {
                    respond(400, false, 'La contraseña debe tener al menos 6 caracteres');
                }

                // Verificar si ya existe
                $check = $pdo->prepare("SELECT id FROM users WHERE email = ?");
                $check->execute([$email]);
                if ($check->fetch()) {
                    respond(409, false, 'Ya existe una cuenta con ese email');
                }

                $hash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 11]);
                $stmt = $pdo->prepare(
                    "INSERT INTO users (name, email, password_hash, email_verified) VALUES (?, ?, ?, 1)"
                );
                $stmt->execute([$name, $email, $hash]);
                $userId = $pdo->lastInsertId();

                $token  = createSession($pdo, $userId);
                $user   = getUserById($pdo, $userId);

                respond(201, true, '¡Bienvenido!', [
                    'user'  => $user,
                    'token' => $token,
                ]);
                break;

            // ── LOGIN ────────────────────────────────────────────────────────────
            // TODO: add rate limiting at nginx/server level
            case 'login':
                if ($method !== 'POST') respond(405, false, 'Método no permitido');

                $email    = strtolower(trim($body['email'] ?? ''));
                $password = $body['password'] ?? '';

                if (!$email || !$password) {
                    respond(400, false, 'Email y contraseña requeridos');
                }

                $stmt = $pdo->prepare("SELECT * FROM users WHERE email = ? AND active = 1");
                $stmt->execute([$email]);
                $row = $stmt->fetch();

                // Use password_verify for timing-safe comparison; return generic message
                // to prevent user enumeration (same message whether email or password is wrong)
                if (!$row || !$row['password_hash'] || !password_verify($password, $row['password_hash'])) {
                    respond(401, false, 'Credenciales inválidas');
                }

                $token = createSession($pdo, $row['id']);
                $user  = getUserById($pdo, $row['id']);

                respond(200, true, '¡Bienvenido!', [
                    'user'  => $user,
                    'token' => $token,
                ]);
                break;

            // ── GOOGLE LOGIN ─────────────────────────────────────────────────────
            case 'google':
                if ($method !== 'POST') respond(405, false, 'Método no permitido');

                $googleId = trim($body['google_id'] ?? '');
                $name     = trim($body['name'] ?? '');
                $email    = strtolower(trim($body['email'] ?? ''));
                $photo    = trim($body['photo'] ?? '');

                if (!$googleId || !$email) {
                    respond(400, false, 'Datos de Google incompletos');
                }

                // Buscar por google_id o email
                $stmt = $pdo->prepare(
                    "SELECT * FROM users WHERE google_id = ? OR email = ? LIMIT 1"
                );
                $stmt->execute([$googleId, $email]);
                $row = $stmt->fetch();

                if ($row) {
                    // Actualizar datos de Google
                    $pdo->prepare("UPDATE users SET google_id=?, name=?, photo_url=?, email_verified=1 WHERE id=?")
                        ->execute([$googleId, $name, $photo, $row['id']]);
                    $userId = $row['id'];
                } else {
                    // Crear usuario nuevo
                    $pdo->prepare(
                        "INSERT INTO users (name, email, google_id, photo_url, email_verified) VALUES (?,?,?,?,1)"
                    )->execute([$name, $email, $googleId, $photo]);
                    $userId = $pdo->lastInsertId();
                }

                $token = createSession($pdo, $userId);
                $user  = getUserById($pdo, $userId);

                respond(200, true, '¡Bienvenido!', [
                    'user'  => $user,
                    'token' => $token,
                ]);
                break;

            // ── OLVIDÉ CONTRASEÑA ────────────────────────────────────────────────
            case 'forgot-password':
                if ($method !== 'POST') respond(405, false, 'Método no permitido');

                $email = strtolower(trim($body['email'] ?? ''));
                if (!$email || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
                    respond(400, false, 'Email inválido');
                }

                $stmt = $pdo->prepare("SELECT id, name FROM users WHERE email = ? AND active = 1");
                $stmt->execute([$email]);
                $user = $stmt->fetch();

                // Siempre responder OK por seguridad (no revelar si existe)
                if (!$user) {
                    respond(200, true, 'Si el email existe, recibirás un enlace de recuperación.');
                }

                // Crear token de reset
                $token  = bin2hex(random_bytes(32));
                $expiry = date('Y-m-d H:i:s', strtotime('+1 hour'));

                // Eliminar tokens anteriores
                $pdo->prepare("DELETE FROM password_resets WHERE user_id = ?")->execute([$user['id']]);
                $pdo->prepare(
                    "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)"
                )->execute([$user['id'], $token, $expiry]);

                // Enviar email
                $resetLink = APP_URL . "/reset-password?token=" . $token;
                $subject   = APP_NAME . " - Recupera tu contraseña";
                $body_mail  = "Hola " . htmlspecialchars($user['name']) . ",\n\n"
                    . "Recibimos una solicitud para restablecer tu contraseña.\n\n"
                    . "Haz clic en el siguiente enlace (válido por 1 hora):\n"
                    . $resetLink . "\n\n"
                    . "Si no solicitaste esto, ignora este mensaje.\n\n"
                    . "— " . APP_NAME;

                $headers  = "From: " . MAIL_FROMNAME . " <" . MAIL_FROM . ">\r\n";
                $headers .= "Reply-To: " . MAIL_FROM . "\r\n";
                $headers .= "Content-Type: text/plain; charset=UTF-8\r\n";

                mail($email, $subject, $body_mail, $headers);

                respond(200, true, 'Si el email existe, recibirás un enlace de recuperación.');
                break;

            // ── VERIFICAR TOKEN DE RESET ─────────────────────────────────────────
            case 'verify-reset':
                $token = $_GET['token'] ?? $body['token'] ?? '';
                if (!$token) respond(400, false, 'Token requerido');

                $stmt = $pdo->prepare(
                    "SELECT pr.*, u.email FROM password_resets pr
                     JOIN users u ON u.id = pr.user_id
                     WHERE pr.token = ? AND pr.used = 0 AND pr.expires_at > NOW()"
                );
                $stmt->execute([$token]);
                $row = $stmt->fetch();

                if (!$row) {
                    respond(400, false, 'Token inválido o expirado');
                }

                respond(200, true, 'Token válido', ['email' => $row['email']]);
                break;

            // ── CONFIRMAR NUEVA CONTRASEÑA ───────────────────────────────────────
            case 'reset-password':
                if ($method !== 'POST') respond(405, false, 'Método no permitido');

                $token    = $body['token'] ?? '';
                $password = $body['password'] ?? '';

                if (!$token || !$password) {
                    respond(400, false, 'Token y nueva contraseña requeridos');
                }
                if (strlen($password) < 6) {
                    respond(400, false, 'La contraseña debe tener al menos 6 caracteres');
                }

                $stmt = $pdo->prepare(
                    "SELECT * FROM password_resets WHERE token = ? AND used = 0 AND expires_at > NOW()"
                );
                $stmt->execute([$token]);
                $reset = $stmt->fetch();

                if (!$reset) {
                    respond(400, false, 'Token inválido o expirado');
                }

                $hash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 11]);
                $pdo->prepare("UPDATE users SET password_hash = ? WHERE id = ?")->execute([$hash, $reset['user_id']]);
                $pdo->prepare("UPDATE password_resets SET used = 1 WHERE id = ?")->execute([$reset['id']]);

                // Invalidar todas las sesiones del usuario
                $pdo->prepare("DELETE FROM sessions WHERE user_id = ?")->execute([$reset['user_id']]);

                respond(200, true, 'Contraseña actualizada correctamente');
                break;

            // ── ME (perfil actual con rol actualizado) ───────────────────────────
            case 'me':
                if ($method !== 'GET') respond(405, false, 'Método no permitido');
                $uid  = requireAuth($pdo);
                $user = getUserById($pdo, $uid);
                if (!$user) respond(404, false, 'Usuario no encontrado');
                respond(200, true, 'OK', $user);
                break;

            // ── LOGOUT ───────────────────────────────────────────────────────────
            case 'logout':
                $token = getBearerToken();
                if ($token) {
                    $pdo->prepare("DELETE FROM sessions WHERE token = ?")->execute([$token]);
                }
                respond(200, true, 'Sesión cerrada');
                break;

            default:
                respond(404, false, 'Endpoint no encontrado');
        }
        break;

    // ── CATEGORÍAS ────────────────────────────────────────────────────────────
    case 'categories':
        if ($method === 'GET') {
            // Si existe la tabla categories, usar esa; si no, derivar de productos
            try {
                $stmt = $pdo->query(
                    "SELECT id, name, label, icon, img_url, sort_order
                     FROM categories WHERE active = 1 ORDER BY sort_order, name"
                );
                $cats = $stmt->fetchAll();
            } catch (PDOException $e) {
                // Tabla no existe todavía: derivar de productos activos
                $stmt = $pdo->query(
                    "SELECT DISTINCT category AS name FROM products WHERE active = 1 ORDER BY category"
                );
                $cats = array_map(fn($r) => [
                    'id'         => null,
                    'name'       => $r['name'],
                    'label'      => ucfirst(strtolower($r['name'])),
                    'icon'       => 'grid-outline',
                    'img_url'    => null,
                    'sort_order' => 0,
                ], $stmt->fetchAll());
            }
            respond(200, true, 'OK', $cats);
        }
        respond(405, false, 'Método no permitido');
        break;

    // ── PROMOCIONES / BANNERS ──────────────────────────────────────────────────
    case 'promos':
        if ($method === 'GET') {
            $pos  = $_GET['position'] ?? null;
            $sql  = "SELECT * FROM promos WHERE active = 1";
            $params = [];
            if ($pos) {
                $sql .= " AND (position = ? OR position = 'both')";
                $params[] = $pos;
            }
            $sql .= " ORDER BY sort_order ASC, id DESC";
            $stmt = $pdo->prepare($sql);
            $stmt->execute($params);
            respond(200, true, 'OK', $stmt->fetchAll());
        }
        respond(405, false, 'Método no permitido');
        break;

    // ── PEDIDOS ────────────────────────────────────────────────────────────────
    case 'orders':
        $userId = requireAuth($pdo);

        // GET /api/orders — Listar mis pedidos
        if ($method === 'GET' && (empty($action) || is_numeric($action))) {
            $stmt = $pdo->prepare("SELECT o.*, (SELECT COUNT(*) FROM order_items WHERE order_id=o.id) AS items_count FROM orders o WHERE o.user_id=? ORDER BY o.created_at DESC LIMIT 50");
            $stmt->execute([$userId]);
            $orders = $stmt->fetchAll();
            foreach ($orders as &$order) {
                $it = $pdo->prepare("SELECT * FROM order_items WHERE order_id=?");
                $it->execute([$order['id']]);
                $order['items'] = $it->fetchAll();
            }
            respond(200, true, 'OK', $orders);
        }

        // POST /api/orders/{id}/cancel
        if ($method === 'POST' && is_numeric($action) && ($segments[2] ?? '') === 'cancel') {
            $orderId = (int)$action;
            $stmt = $pdo->prepare("SELECT id, status, delivery_user_id FROM orders WHERE id=? AND user_id=?");
            $stmt->execute([$orderId, $userId]);
            $order = $stmt->fetch();
            if (!$order) respond(404, false, 'Pedido no encontrado');
            if (!in_array($order['status'], ['pending','accepted','preparing'])) respond(400, false, 'No se puede cancelar ahora');
            $pdo->prepare("UPDATE orders SET status='cancelled', updated_at=NOW() WHERE id=?")->execute([$orderId]);
            // Reactivar productos con stock físico > 0 que quedaron inactivos
            $oi = $pdo->prepare("SELECT product_id FROM order_items WHERE order_id = ?");
            $oi->execute([$orderId]);
            foreach ($oi->fetchAll() as $item) {
                $pdo->prepare(
                    "UPDATE products SET active = 1 WHERE id = ? AND stock > 0 AND stock != -1 AND active = 0"
                )->execute([$item['product_id']]);
            }
            if ($order['delivery_user_id']) {
                sendExpoPush($pdo, [(int)$order['delivery_user_id']], '❌ Pedido cancelado', "Pedido #$orderId cancelado", ['tab' => 'available']);
            }
            respond(200, true, 'Pedido cancelado');
        }

        // POST /api/orders/{id}/rate
        if ($method === 'POST' && is_numeric($action) && ($segments[2] ?? '') === 'rate') {
            $orderId = (int)$action;
            $rating  = (int)($body['rating'] ?? 0);
            $comment = trim($body['comment'] ?? '');
            if ($rating < 1 || $rating > 5) respond(400, false, 'Rating inválido');
            $stmt = $pdo->prepare("UPDATE orders SET rating=?, rating_comment=? WHERE id=? AND user_id=? AND status='delivered'");
            $stmt->execute([$rating, $comment, $orderId, $userId]);
            if ($stmt->rowCount() > 0) respond(200, true, '¡Gracias!');
            else respond(400, false, 'No se puede calificar este pedido');
        }

        // POST /api/orders — Crear pedido nuevo
        if ($method === 'POST' && empty($action)) {
            // Migraciones automáticas (Rating y Proximidad)
            try { $pdo->exec("ALTER TABLE orders ADD COLUMN payment_method VARCHAR(60) NULL, ADD COLUMN payment_status VARCHAR(20) NOT NULL DEFAULT 'pending', ADD COLUMN notified_nearby TINYINT(1) DEFAULT 0, ADD COLUMN notified_arrived TINYINT(1) DEFAULT 0, ADD COLUMN rating TINYINT NULL, ADD COLUMN rating_comment TEXT NULL"); } catch (Exception $e) {}
            
            $items = $body['items'] ?? [];
            if (empty($items)) respond(400, false, 'Carrito vacío');
            
            $address = trim($body['address'] ?? '');
            $destLat = isset($body['dest_lat']) ? (float)$body['dest_lat'] : null;
            $destLng = isset($body['dest_lng']) ? (float)$body['dest_lng'] : null;
            $storeId = isset($body['store_id']) ? (int)$body['store_id'] : null;

            // ── AUTO-SELECCIÓN DE SUCURSAL MÁS CERCANA ────────────────────────
            // Si el cliente envió coordenadas, calcular la tienda más cercana
            // y usarla siempre (ignora cualquier store_id que haya enviado la app)
            $nearestStoreId   = null;
            $assignedDelivery = null;

            if ($destLat !== null && $destLng !== null) {
                try {
                    $stores = $pdo->query(
                        "SELECT id, lat, lng FROM stores WHERE active = 1"
                    )->fetchAll();

                    $minDist = PHP_FLOAT_MAX;
                    foreach ($stores as $store) {
                        // Haversine distance (km)
                        $dLat  = deg2rad((float)$store['lat'] - $destLat);
                        $dLng  = deg2rad((float)$store['lng'] - $destLng);
                        $a     = sin($dLat/2)**2
                               + cos(deg2rad($destLat)) * cos(deg2rad((float)$store['lat']))
                               * sin($dLng/2)**2;
                        $dist  = 6371 * 2 * asin(sqrt($a));
                        if ($dist < $minDist) {
                            $minDist        = $dist;
                            $nearestStoreId = (int)$store['id'];
                        }
                    }
                } catch (PDOException $e) {
                    // Si falla, usar el store_id enviado por la app
                    $nearestStoreId = $storeId;
                }
            }

            // Usar la tienda más cercana calculada, o la que mandó la app como respaldo
            $resolvedStoreId = $nearestStoreId ?? $storeId ?? null;

            // ── AUTO-MIGRACIÓN DE COLUMNAS DE REPARTIDOR ─────────────────────
            // Usar ADD COLUMN sin IF NOT EXISTS (compatible MySQL 5.7 y 8)
            try { $pdo->exec("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'customer'"); }
            catch (PDOException $e) {}
            try { $pdo->exec("ALTER TABLE users ADD COLUMN store_id INT UNSIGNED NULL"); }
            catch (PDOException $e) {}

            // ── AUTO-ASIGNACIÓN DE REPARTIDOR ─────────────────────────────────
            // 1ª pasada: repartidor con menos pedidos activos de la misma sucursal
            if ($resolvedStoreId) {
                try {
                    $s1 = $pdo->prepare(
                        "SELECT u.id, COUNT(o.id) AS active_orders
                         FROM users u
                         LEFT JOIN orders o
                           ON o.delivery_user_id = u.id
                          AND o.status IN ('accepted','preparing','picked_up','on_the_way')
                         WHERE u.role = 'delivery'
                           AND u.active = 1
                           AND u.store_id = ?
                         GROUP BY u.id
                         ORDER BY active_orders ASC, u.id ASC
                         LIMIT 1"
                    );
                    $s1->execute([$resolvedStoreId]);
                    $driver = $s1->fetch();
                    if ($driver) $assignedDelivery = (int)$driver['id'];
                } catch (PDOException $e) {}
            }

            // 2ª pasada (fallback): cualquier repartidor activo sin importar sucursal
            if (!$assignedDelivery) {
                try {
                    $s2 = $pdo->prepare(
                        "SELECT u.id, COUNT(o.id) AS active_orders
                         FROM users u
                         LEFT JOIN orders o
                           ON o.delivery_user_id = u.id
                          AND o.status IN ('accepted','preparing','picked_up','on_the_way')
                         WHERE u.role = 'delivery'
                           AND u.active = 1
                         GROUP BY u.id
                         ORDER BY active_orders ASC, u.id ASC
                         LIMIT 1"
                    );
                    $s2->execute();
                    $driver = $s2->fetch();
                    if ($driver) $assignedDelivery = (int)$driver['id'];
                } catch (PDOException $e) {}
            }

            // ── CAMPOS DEL CUERPO ─────────────────────────────────────────────
            $notes         = trim($body['notes'] ?? '');
            $paymentMethod = trim($body['payment_method'] ?? '');
            $paymentStatus = trim($body['payment_status'] ?? 'pending');
            $customerName  = trim($body['customer_name'] ?? '');
            $customerEmail = trim($body['customer_email'] ?? '');

            // ── TOTALES ───────────────────────────────────────────────────────
            $subtotal = 0;
            foreach ($items as $item) {
                $price     = (float)($item['price_numeric'] ?? $item['price'] ?? 0);
                $subtotal += $price * (int)($item['qty'] ?? 1);
            }
            if ($subtotal == 0 && isset($body['total']) && (float)$body['total'] > 0) {
                $total    = (float)$body['total'];
                $shipping = (float)($body['shipping'] ?? 49);
            } else {
                $shipping = $subtotal >= 500 ? 0 : 49;
                $total    = $subtotal + $shipping;
            }

            // ── VALIDAR STOCK DISPONIBLE (descontando pedidos activos) ────────
            foreach ($items as $item) {
                $pid = (int)($item['product_id'] ?? $item['id'] ?? 0);
                $qty = (int)($item['qty'] ?? 1);
                if ($pid <= 0) continue;
                $stockRow = $pdo->prepare(
                    "SELECT p.name, p.stock,
                            CASE
                                WHEN p.stock = -1 THEN -1
                                ELSE p.stock - COALESCE((
                                    SELECT SUM(oi.qty)
                                    FROM order_items oi
                                    JOIN orders o ON o.id = oi.order_id
                                    WHERE oi.product_id = p.id
                                      AND (
                                        o.status IN ('accepted','preparing','picked_up','on_the_way','arrived')
                                        OR (o.status = 'pending' AND o.created_at > DATE_SUB(NOW(), INTERVAL 30 MINUTE))
                                      )
                                ), 0)
                            END AS available
                     FROM products p
                     WHERE p.id = ? AND p.active = 1"
                );
                $stockRow->execute([$pid]);
                $prod = $stockRow->fetch();
                if (!$prod) respond(400, false, 'Producto no encontrado o sin stock');
                // stock = -1 significa ilimitado (sin control de inventario)
                if ((int)$prod['stock'] !== -1 && (int)$prod['available'] < $qty) {
                    respond(400, false, 'Sin stock suficiente: ' . $prod['name'] .
                        ' (disponible: ' . max(0, (int)$prod['available']) . ')');
                }
            }

            // ── INSERTAR PEDIDO ───────────────────────────────────────────────
            $pdo->beginTransaction();
            try {
                // Si hay repartidor asignado, el estado pasa directo a 'accepted'
                $initialStatus = $assignedDelivery ? 'accepted' : 'pending';

                $pdo->prepare(
                    "INSERT INTO orders
                     (user_id, delivery_user_id, total, shipping, address,
                      dest_lat, dest_lng, notes, payment_method, payment_status,
                      customer_name, customer_email, store_id, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )->execute([
                    $userId,
                    $assignedDelivery,
                    $total, $shipping, $address,
                    $destLat, $destLng, $notes,
                    $paymentMethod ?: null,
                    $paymentStatus,
                    $customerName ?: null,
                    $customerEmail ?: null,
                    $resolvedStoreId,
                    $initialStatus,
                ]);
                $orderId = $pdo->lastInsertId();

                $insItem = $pdo->prepare(
                    "INSERT INTO order_items (order_id, product_id, product_name, price, qty)
                     VALUES (?,?,?,?,?)"
                );
                foreach ($items as $item) {
                    $price = (float)($item['price_numeric'] ?? $item['price'] ?? 0);
                    $pid   = (int)($item['product_id'] ?? $item['id'] ?? 0);
                    $qty   = (int)($item['qty'] ?? 1);
                    $insItem->execute([
                        $orderId,
                        $pid,
                        $item['product_name'] ?? $item['name'] ?? '',
                        $price,
                        $qty,
                    ]);
                    // Stock se descuenta solo al marcar el pedido como 'delivered'
                }

                $pdo->commit();

                // ── PUSH NOTIFICATIONS ────────────────────────────────────────
                $orderNum = str_pad($orderId, 6, '0', STR_PAD_LEFT);
                if ($assignedDelivery) {
                    // Notificar al repartidor asignado
                    sendExpoPush($pdo, [$assignedDelivery],
                        '🛵 ¡Nuevo pedido asignado!',
                        "Pedido #$orderNum — $address",
                        ['tab' => 'active', 'type' => 'new_order', 'order_id' => (string)$orderId]
                    );
                } else {
                    // Pedido en cola: notificar a todos los repartidores disponibles.
                    $ids = [];
                    try {
                        if ($resolvedStoreId) {
                            $storeDrivers = $pdo->prepare(
                                "SELECT id FROM users WHERE role='delivery' AND store_id=? AND active=1"
                            );
                            $storeDrivers->execute([$resolvedStoreId]);
                            $ids = array_column($storeDrivers->fetchAll(), 'id');
                        }
                        if (empty($ids)) {
                            $allDrivers = $pdo->query(
                                "SELECT id FROM users WHERE role='delivery' AND active=1"
                            );
                            $ids = array_column($allDrivers->fetchAll(), 'id');
                        }
                    } catch (PDOException $e) {}
                    if (!empty($ids)) {
                        sendExpoPush($pdo, $ids,
                            '🛵 ¡Nuevo pedido disponible!',
                            "Pedido #$orderNum — $address",
                            ['tab' => 'available', 'type' => 'new_order', 'order_id' => (string)$orderId]
                        );
                    }
                }

                respond(201, true, 'Pedido creado', [
                    'order_id'         => $orderId,
                    'id'               => $orderId,
                    'store_id'         => $resolvedStoreId,
                    'delivery_user_id' => $assignedDelivery,
                    'status'           => $initialStatus,
                ]);
            } catch (Exception $e) {
                $pdo->rollBack();
                respond(500, false, 'Error al crear el pedido: ' . $e->getMessage());
            }
        }

        respond(405, false, 'Método no permitido');
        break;

    // ── SUCURSALES ────────────────────────────────────────────────────────────
    case 'stores':
        if ($method === 'GET') {
            try {
                $stmt = $pdo->query(
                    "SELECT id, name, city, address, lat, lng
                     FROM stores WHERE active = 1 ORDER BY sort_order ASC, name ASC"
                );
                respond(200, true, 'OK', $stmt->fetchAll());
            } catch (PDOException $e) {
                respond(500, false, 'Error al obtener sucursales');
            }
        }
        respond(405, false, 'Método no permitido');
        break;

    // ── DELIVERY (repartidor) ─────────────────────────────────────────────────
    case 'delivery':
        // Garantizar que las columnas role/store_id/push_token existen
        // ANTES del role-check para evitar PDOException si el schema no fue aplicado
        try { $pdo->exec("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'customer'"); } catch (PDOException $e) {}
        try { $pdo->exec("ALTER TABLE users ADD COLUMN store_id INT UNSIGNED NULL"); } catch (PDOException $e) {}
        try { $pdo->exec("ALTER TABLE users ADD COLUMN push_token VARCHAR(255) DEFAULT NULL"); } catch (PDOException $e) {}

        $deliveryUserId = requireAuth($pdo);

        // Verificar que el usuario sea repartidor o admin
        $roleRow = $pdo->prepare("SELECT COALESCE(role,'customer') AS role FROM users WHERE id=?");
        $roleRow->execute([$deliveryUserId]);
        $roleCheck = $roleRow->fetch();
        if (!$roleCheck || !in_array($roleCheck['role'], ['delivery','admin'])) {
            respond(403, false, 'Acceso denegado');
        }

        // GET /delivery/available — pedidos disponibles para tomar (sin repartidor asignado)
        if ($method === 'GET' && $action === 'available') {
            try {
                // Obtener store_id del repartidor actual
                $driverStmt = $pdo->prepare("SELECT store_id FROM users WHERE id = ?");
                $driverStmt->execute([$deliveryUserId]);
                $driverRow = $driverStmt->fetch();
                $driverStoreId = $driverRow ? $driverRow['store_id'] : null;

                // Si tiene sucursal asignada, solo ver pedidos de esa sucursal
                if ($driverStoreId) {
                    $stmt = $pdo->prepare(
                        "SELECT o.*, u.name AS customer_name, u.email AS customer_email,
                                s.name AS store_name, s.lat AS store_lat, s.lng AS store_lng
                         FROM orders o
                         LEFT JOIN users u ON u.id = o.user_id
                         LEFT JOIN stores s ON s.id = o.store_id
                         WHERE o.delivery_user_id IS NULL
                           AND o.status = 'pending'
                           AND (o.store_id = ? OR o.store_id IS NULL)
                         ORDER BY o.created_at DESC LIMIT 50"
                    );
                    $stmt->execute([$driverStoreId]);
                } else {
                    $stmt = $pdo->query(
                        "SELECT o.*, u.name AS customer_name, u.email AS customer_email,
                                s.name AS store_name, s.lat AS store_lat, s.lng AS store_lng
                         FROM orders o
                         LEFT JOIN users u ON u.id = o.user_id
                         LEFT JOIN stores s ON s.id = o.store_id
                         WHERE o.delivery_user_id IS NULL
                           AND o.status = 'pending'
                         ORDER BY o.created_at DESC LIMIT 50"
                    );
                }
                $orders = $stmt->fetchAll();
                foreach ($orders as &$order) {
                    $items = $pdo->prepare("SELECT * FROM order_items WHERE order_id = ?");
                    $items->execute([$order['id']]);
                    $order['items'] = $items->fetchAll();
                }
                respond(200, true, 'OK', $orders);
            } catch (PDOException $e) {
                respond(500, false, 'Error al obtener pedidos');
            }
        }

        // GET /delivery/my-orders — pedidos asignados al repartidor actual (activos)
        if ($method === 'GET' && $action === 'my-orders') {
            try {
                $stmt = $pdo->prepare(
                    "SELECT o.*, u.name AS customer_name, u.email AS customer_email,
                            s.name AS store_name, s.lat AS store_lat, s.lng AS store_lng,
                            s.address AS store_address, s.phone AS store_phone, s.city AS store_city,
                            d.name AS delivery_user_name
                     FROM orders o
                     LEFT JOIN users u ON u.id = o.user_id
                     LEFT JOIN stores s ON s.id = o.store_id
                     LEFT JOIN users d ON d.id = o.delivery_user_id
                     WHERE o.delivery_user_id = ?
                       AND o.status IN ('accepted','preparing','picked_up','on_the_way','arrived')
                     ORDER BY o.created_at DESC"
                );
                $stmt->execute([$deliveryUserId]);
                $orders = $stmt->fetchAll();
                foreach ($orders as &$order) {
                    $items = $pdo->prepare("SELECT * FROM order_items WHERE order_id = ?");
                    $items->execute([$order['id']]);
                    $order['items'] = $items->fetchAll();
                }
                respond(200, true, 'OK', $orders);
            } catch (PDOException $e) {
                respond(500, false, 'Error al obtener tus pedidos');
            }
        }

        // GET /delivery/history — pedidos terminados por el repartidor
        if ($method === 'GET' && $action === 'history') {
            try {
                $stmt = $pdo->prepare(
                    "SELECT o.*, u.name AS customer_name, u.email AS customer_email,
                            s.name AS store_name, d.name AS delivery_user_name
                     FROM orders o
                     LEFT JOIN users u ON u.id = o.user_id
                     LEFT JOIN stores s ON s.id = o.store_id
                     LEFT JOIN users d ON d.id = o.delivery_user_id
                     WHERE o.delivery_user_id = ?
                       AND o.status IN ('delivered','cancelled')
                     ORDER BY o.updated_at DESC LIMIT 50"
                );
                $stmt->execute([$deliveryUserId]);
                $orders = $stmt->fetchAll();
                respond(200, true, 'OK', $orders);
            } catch (PDOException $e) {
                respond(500, false, 'Error al obtener historial');
            }
        }

        // POST /delivery/push-token — guardar token de notificaciones del dispositivo
        if ($method === 'POST' && $action === 'push-token') {
            $pushToken = trim($body['push_token'] ?? '');
            if (!$pushToken) respond(400, false, 'Token requerido');
            try {
                try { $pdo->exec("ALTER TABLE users ADD COLUMN push_token VARCHAR(255) DEFAULT NULL"); }
                catch (PDOException $e) {}
                $pdo->prepare("UPDATE users SET push_token = ? WHERE id = ?")->execute([$pushToken, $deliveryUserId]);
                respond(200, true, 'Token registrado');
            } catch (PDOException $e) {
                respond(500, false, 'Error al guardar token');
            }
        }

        // POST /delivery/location — actualizar mi ubicación actual para el rastreo
        if ($method === 'POST' && $action === 'location') {
            $lat = $body['lat'] ?? null;
            $lng = $body['lng'] ?? null;
            if (!$lat || !$lng) respond(400, false, 'Coordenadas requeridas');

            try {
                // Actualizar ubicación en todos los pedidos activos del repartidor
                $stmt = $pdo->prepare(
                    "UPDATE orders SET delivery_lat = ?, delivery_lng = ?, updated_at = NOW()
                     WHERE delivery_user_id = ?
                       AND status IN ('accepted','preparing','picked_up','on_the_way')"
                );
                $stmt->execute([$lat, $lng, $deliveryUserId]);

                // ── Detección de proximidad: notificar al cliente cuando el repartidor está a ≤ 600 m o ≤ 80 m
                try {
                    try { $pdo->exec("ALTER TABLE orders ADD COLUMN notified_nearby TINYINT(1) DEFAULT 0"); } catch (PDOException $e) {}
                    try { $pdo->exec("ALTER TABLE orders ADD COLUMN notified_arrived TINYINT(1) DEFAULT 0"); } catch (PDOException $e) {}

                    $nearbyOrders = $pdo->prepare(
                        "SELECT id, user_id, dest_lat, dest_lng, notified_nearby, notified_arrived
                         FROM orders
                         WHERE delivery_user_id = ?
                           AND status IN ('on_the_way','picked_up','arrived')
                           AND dest_lat IS NOT NULL AND dest_lng IS NOT NULL"
                    );
                    $nearbyOrders->execute([$deliveryUserId]);
                    foreach ($nearbyOrders->fetchAll() as $ord) {
                        $dLat = deg2rad((float)$lat   - (float)$ord['dest_lat']);
                        $dLng = deg2rad((float)$lng   - (float)$ord['dest_lng']);
                        $a    = sin($dLat/2)**2
                              + cos(deg2rad((float)$ord['dest_lat']))
                              * cos(deg2rad((float)$lat))
                              * sin($dLng/2)**2;
                        $dist = 6371000 * 2 * asin(sqrt($a)); // metros

                        $orderNum = str_pad($ord['id'], 6, '0', STR_PAD_LEFT);

                        // Caso 1: Muy cerca / Afuera (≤ 80 metros)
                        if ($dist <= 80 && !$ord['notified_arrived']) {
                            $pdo->prepare("UPDATE orders SET notified_arrived = 1, status = 'arrived' WHERE id = ?")
                                ->execute([$ord['id']]);
                            sendExpoPush($pdo, [(int)$ord['user_id']],
                                '🏠 ¡Tu repartidor llegó!',
                                "Tu pedido #$orderNum está afuera. ¡Sal a recibirlo!",
                                ['order_id' => (string)$ord['id'], 'type' => 'arrived']
                            );
                        }
                        // Caso 2: Cerca (≤ 600 metros)
                        elseif ($dist <= 600 && !$ord['notified_nearby'] && !$ord['notified_arrived']) {
                            $pdo->prepare("UPDATE orders SET notified_nearby = 1 WHERE id = ?")
                                ->execute([$ord['id']]);
                            sendExpoPush($pdo, [(int)$ord['user_id']],
                                '📍 Tu pedido está muy cerca',
                                "El repartidor con el pedido #$orderNum llegará en un par de minutos",
                                ['order_id' => (string)$ord['id'], 'type' => 'nearby']
                            );
                        }
                    }
                } catch (Exception $e) {}

                respond(200, true, 'Ubicación actualizada');
            } catch (PDOException $e) {
                respond(500, false, 'Error al actualizar ubicación');
            }
        }

        // POST /delivery/orders/{id}/accept — aceptar pedido
        if ($method === 'POST' && $segments[1] === 'orders') {
            $orderId = (int)($segments[2] ?? 0); // delivery/orders/{id}/accept
            if (!$orderId) respond(400, false, 'ID de pedido requerido');

            try {
                // Solo si el pedido no tiene repartidor y está pendiente
                $stmt = $pdo->prepare(
                    "UPDATE orders SET status='accepted', delivery_user_id=?, updated_at=NOW()
                     WHERE id=? AND delivery_user_id IS NULL AND status='pending'"
                );
                $stmt->execute([$deliveryUserId, $orderId]);
                if ($stmt->rowCount() === 0) respond(400, false, 'El pedido ya no está disponible');

                // Notificar al cliente que le asignaron un repartidor
                try {
                    $orderRow = $pdo->prepare("SELECT user_id FROM orders WHERE id = ?");
                    $orderRow->execute([$orderId]);
                    $ord = $orderRow->fetch();
                    if ($ord) {
                        sendExpoPush($pdo, [(int)$ord['user_id']],
                            '🛵 Repartidor asignado',
                            'Tu pedido #' . str_pad($orderId, 6, '0', STR_PAD_LEFT)
                                . ' tiene un repartidor en camino a la tienda',
                            ['order_id' => (string)$orderId, 'type' => 'accepted']
                        );
                    }
                } catch (Exception $e) {}

                respond(200, true, 'Pedido aceptado');
            } catch (PDOException $e) {
                respond(500, false, 'Error al aceptar pedido');
            }
        }

        // PUT /delivery/orders/{id}/status — actualizar estado
        if ($method === 'PUT' && $segments[1] === 'orders') {
            $orderId = (int)($segments[2] ?? 0);
            $status  = $body['status'] ?? '';
            $allowed = ['preparing','picked_up','on_the_way','arrived','delivered','cancelled'];
            if (!$orderId || !in_array($status, $allowed)) {
                respond(400, false, 'ID o estado inválido');
            }
            try {
                $pdo->beginTransaction();

                $pdo->prepare(
                    "UPDATE orders SET status=?, updated_at=NOW() WHERE id=? AND delivery_user_id=?"
                )->execute([$status, $orderId, $deliveryUserId]);

                // Si se marca manualmente como llegado o entregado, marcar flags de proximidad para no repetir
                if ($status === 'arrived' || $status === 'delivered') {
                    $pdo->prepare("UPDATE orders SET notified_nearby=1, notified_arrived=1 WHERE id=?")->execute([$orderId]);
                }

                // Al cancelar: reactivar productos con stock físico que quedaron inactivos
                if ($status === 'cancelled') {
                    $oi2 = $pdo->prepare("SELECT product_id FROM order_items WHERE order_id = ?");
                    $oi2->execute([$orderId]);
                    foreach ($oi2->fetchAll() as $item) {
                        $pdo->prepare(
                            "UPDATE products SET active = 1 WHERE id = ? AND stock > 0 AND stock != -1 AND active = 0"
                        )->execute([$item['product_id']]);
                    }
                }

                // Al entregar: descontar stock real y desactivar productos sin existencia
                if ($status === 'delivered') {
                    $orderItems = $pdo->prepare(
                        "SELECT product_id, qty FROM order_items WHERE order_id = ?"
                    );
                    $orderItems->execute([$orderId]);
                    foreach ($orderItems->fetchAll() as $oi) {
                        // stock = -1 significa ilimitado; no descontar ni desactivar
                        $pdo->prepare(
                            "UPDATE products SET stock = GREATEST(0, stock - ?) WHERE id = ? AND stock != -1"
                        )->execute([$oi['qty'], $oi['product_id']]);
                        $pdo->prepare(
                            "UPDATE products SET active = 0 WHERE id = ? AND stock <= 0 AND stock != -1"
                        )->execute([$oi['product_id']]);
                    }
                }

                $pdo->commit();

                // ── Notificar al cliente según el nuevo estado ────────────────
                try {
                    $orderRow = $pdo->prepare("SELECT user_id FROM orders WHERE id = ?");
                    $orderRow->execute([$orderId]);
                    $ord = $orderRow->fetch();
                    if ($ord) {
                        $orderNum = str_pad($orderId, 6, '0', STR_PAD_LEFT);
                        $msgs = [
                            'preparing'  => ['🏪 Preparando tu pedido',
                                             "Tu pedido #$orderNum se está preparando en la tienda"],
                            'picked_up'  => ['📦 ¡Pedido recogido!',
                                             "El repartidor ya recogió tu pedido #$orderNum"],
                            'on_the_way' => ['🛵 ¡En camino!',
                                             "Tu repartidor está en camino a tu dirección"],
                            'arrived'    => ['🏠 ¡Tu repartidor llegó!',
                                             "Tu pedido #$orderNum está afuera. ¡Sal a recibirlo!"],
                            'delivered'  => ['✅ ¡Pedido entregado!',
                                             "Tu pedido #$orderNum fue entregado. ¡Buen provecho!"],
                            'cancelled'  => ['❌ Pedido cancelado',
                                             "Tu pedido #$orderNum fue cancelado"],
                        ];
                        if (isset($msgs[$status])) {
                            [$title, $msgBody] = $msgs[$status];
                            sendExpoPush($pdo, [(int)$ord['user_id']],
                                $title, $msgBody,
                                ['order_id' => (string)$orderId, 'type' => $status, 'refresh' => true]
                            );
                        }
                    }
                } catch (Exception $e) {}

                respond(200, true, 'Estado actualizado');
            } catch (PDOException $e) {
                $pdo->rollBack();
                respond(500, false, 'Error al actualizar estado');
            }
        }

        respond(405, false, 'Método no permitido');
        break;

    // ── RASTREO (público para el cliente dueño del pedido) ───────────────────
    case 'tracking':
        $userId = requireAuth($pdo);
        $orderId = (int)$action;
        if (!$orderId) respond(400, false, 'ID de pedido requerido');

        $stmt = $pdo->prepare(
            "SELECT o.id, o.status, o.delivery_lat, o.delivery_lng, o.dest_lat, o.dest_lng,
                    COALESCE(s.lat,     ns.lat)     as store_lat,
                    COALESCE(s.lng,     ns.lng)     as store_lng,
                    COALESCE(s.name,    ns.name)    as store_name,
                    COALESCE(s.address, ns.address) as store_address,
                    COALESCE(s.phone,   ns.phone)   as store_phone,
                    COALESCE(s.city,    ns.city)    as store_city,
                    d.name AS driver_name,
                    d.photo_url AS driver_photo
             FROM orders o
             LEFT JOIN stores s ON s.id = o.store_id
             LEFT JOIN stores ns ON ns.id = (
               SELECT id FROM stores WHERE active = 1
               ORDER BY (
                 POW(lat - COALESCE(o.dest_lat, 19.7044), 2) +
                 POW(lng - COALESCE(o.dest_lng, -101.2262), 2)
               ) ASC LIMIT 1
             )
             LEFT JOIN users d ON d.id = o.delivery_user_id
             WHERE o.id = ? AND o.user_id = ?"
        );
        $stmt->execute([$orderId, $userId]);
        $order = $stmt->fetch();
        if (!$order) respond(404, false, 'Pedido no encontrado');

        respond(200, true, 'OK', $order);
        break;

    // ── TOKEN PUSH DEL CLIENTE ────────────────────────────────────────────────
    case 'user':
        $userId = requireAuth($pdo);

        if ($method === 'POST' && $action === 'push-token') {
            $pushToken = trim($body['push_token'] ?? '');
            if (!$pushToken) respond(400, false, 'Token requerido');
            try {
                try { $pdo->exec("ALTER TABLE users ADD COLUMN push_token VARCHAR(255) DEFAULT NULL"); }
                catch (PDOException $e) {}
                $pdo->prepare("UPDATE users SET push_token = ? WHERE id = ?")->execute([$pushToken, $userId]);
                respond(200, true, 'Token registrado');
            } catch (PDOException $e) {
                respond(500, false, 'Error al guardar token');
            }
        }

        respond(404, false, 'Endpoint no encontrado');
        break;

    // ── ADMIN ──────────────────────────────────────────────────────────────────
    case 'admin':
        $userId = requireAuth($pdo);
        // Verificar que sea admin
        $roleCheck = $pdo->prepare("SELECT COALESCE(role,'customer') AS role FROM users WHERE id=?");
        $roleCheck->execute([$userId]);
        $roleRow = $roleCheck->fetch();
        if (!$roleRow || $roleRow['role'] !== 'admin') {
            respond(403, false, 'Acceso restringido a administradores');
        }

        // GET /admin/users — lista todos los usuarios
        if ($method === 'GET' && $action === 'users') {
            $stmt = $pdo->query(
                "SELECT u.id, u.name, u.email, u.photo_url, u.active,
                        COALESCE(u.role,'customer') AS role,
                        u.store_id, s.name AS store_name,
                        u.created_at
                 FROM users u
                 LEFT JOIN stores s ON s.id = u.store_id
                 ORDER BY u.created_at DESC"
            );
            respond(200, true, 'OK', $stmt->fetchAll());
        }

        // GET /admin/stores — lista todas las sucursales activas
        if ($method === 'GET' && $action === 'stores') {
            $stmt = $pdo->query("SELECT id, name, address FROM stores WHERE active=1 ORDER BY name");
            respond(200, true, 'OK', $stmt->fetchAll());
        }

        // GET /admin/products — lista todos los productos con stock
        if ($method === 'GET' && $action === 'products') {
            $stmt = $pdo->query(
                "SELECT p.id, p.sku, p.name, p.category, p.price, p.unit, p.stock, p.active, p.image_url, p.promo,
                        CASE WHEN p.stock = -1 THEN -1
                             ELSE GREATEST(0, p.stock - COALESCE((
                                SELECT SUM(oi.qty) FROM order_items oi
                                JOIN orders o ON o.id = oi.order_id
                                WHERE oi.product_id = p.id
                                  AND (
                                    o.status IN ('accepted','preparing','picked_up','on_the_way','arrived')
                                    OR (o.status = 'pending' AND o.created_at > DATE_SUB(NOW(), INTERVAL 30 MINUTE))
                                  )
                             ), 0))
                        END AS real_available
                 FROM products p ORDER BY p.category, p.name"
            );
            $rows = $stmt->fetchAll();
            foreach ($rows as &$r) {
                $r['stock']          = (int)$r['stock'];
                $r['real_available'] = (int)$r['real_available'];
                $r['reserved']       = $r['stock'] === -1 ? 0 : max(0, $r['stock'] - $r['real_available']);
                $r['active']         = (int)$r['active'];
                $r['price']          = (float)$r['price'];
            }
            respond(200, true, 'OK', $rows);
        }

        // PUT /admin/products/{id} — actualizar stock y/o datos del producto
        if ($method === 'PUT' && strpos($action, 'products/') === 0) {
            $pid  = (int)substr($action, strlen('products/'));
            $sets = []; $params = [];
            // stock = -1 significa ilimitado; permitir -1, pero no otros negativos
            if (array_key_exists('stock', $body)) {
                $v = (int)$body['stock'];
                $v = $v === -1 ? -1 : max(0, $v);
                $sets[] = 'stock=?'; $params[] = $v;
                // Reactivar automáticamente si se agrega stock
                if ($v > 0 || $v === -1) { $sets[] = 'active=1'; }
            }
            if (array_key_exists('price', $body))  { $sets[] = 'price=?';  $params[] = (float)$body['price']; }
            if (array_key_exists('active', $body)) { $sets[] = 'active=?'; $params[] = $body['active'] ? 1 : 0; }
            if (array_key_exists('name', $body))   { $sets[] = 'name=?';   $params[] = trim($body['name']); }
            if (empty($sets)) respond(400, false, 'Nada que actualizar');
            $params[] = $pid;
            $pdo->prepare("UPDATE products SET ".implode(',',$sets)." WHERE id=?")->execute($params);
            respond(200, true, 'Producto actualizado');
        }

        // PUT /admin/users/{id} — actualizar role y/o store_id
        if ($method === 'PUT' && is_numeric($action)) {
            $targetId = (int)$action;
            $role     = $body['role'] ?? null;
            $storeId  = array_key_exists('store_id', $body) ? ($body['store_id'] ? (int)$body['store_id'] : null) : false;

            $allowed = ['customer','delivery','admin'];
            if ($role && !in_array($role, $allowed)) respond(400, false, 'Rol inválido');

            $sets = [];
            $params = [];
            if ($role) { $sets[] = 'role=?'; $params[] = $role; }
            if ($storeId !== false) { $sets[] = 'store_id=?'; $params[] = $storeId; }

            if (empty($sets)) respond(400, false, 'Nada que actualizar');

            $params[] = $targetId;
            $pdo->prepare("UPDATE users SET ".implode(',',$sets)." WHERE id=?")->execute($params);
            respond(200, true, 'Usuario actualizado');
        }

        respond(404, false, 'Endpoint admin no encontrado');
        break;

    // ── ROUTE PROXY ────────────────────────────────────────────────────────────
    // GET /route?origin_lat=X&origin_lng=Y&dest_lat=X&dest_lng=Y
    // Prueba Google Directions y luego OSRM, ambos server-side
    case 'route':
        if ($method !== 'GET') { respond(405, false, 'Método no permitido'); }

        $oLat = floatval($_GET['origin_lat'] ?? 0);
        $oLng = floatval($_GET['origin_lng'] ?? 0);
        $dLat = floatval($_GET['dest_lat']   ?? 0);
        $dLng = floatval($_GET['dest_lng']   ?? 0);

        if (!$oLat || !$oLng || !$dLat || !$dLng) {
            respond(400, false, 'Coordenadas requeridas: origin_lat, origin_lng, dest_lat, dest_lng');
        }

        // Helper: fetch con curl (más fiable) o file_get_contents como fallback
        $fetchUrl = function(string $url): ?string {
            if (function_exists('curl_init')) {
                $ch = curl_init($url);
                curl_setopt_array($ch, [
                    CURLOPT_RETURNTRANSFER => true,
                    CURLOPT_TIMEOUT        => 8,
                    CURLOPT_FOLLOWLOCATION => true,
                    CURLOPT_SSL_VERIFYPEER => false,
                    CURLOPT_USERAGENT      => 'TPN-App/1.0',
                ]);
                $body = curl_exec($ch);
                curl_close($ch);
                return $body ?: null;
            }
            $ctx = stream_context_create(['http' => ['timeout' => 8, 'ignore_errors' => true]]);
            $body = @file_get_contents($url, false, $ctx);
            return $body ?: null;
        };

        // ── Hora local de Ciudad de México (independiente de la zona del servidor) ──
        $dtMX   = new DateTime('now', new DateTimeZone('America/Mexico_City'));
        $hourMX = (int)$dtMX->format('G');
        // Multiplicador de tráfico por hora local
        $trafficMul = 1.0;
        if (($hourMX >= 7 && $hourMX < 9) || ($hourMX >= 17 && $hourMX < 19))  $trafficMul = 1.40;
        elseif (($hourMX >= 9 && $hourMX < 12) || ($hourMX >= 19 && $hourMX < 21)) $trafficMul = 1.15;

        // ── Intento 1: Google Directions API ─────────────────────────────────
        $apiKey  = 'AIzaSyCcPbr92rZz26wyw1hB4XLuBMfMxtDHE9o';
        $gUrl    = "https://maps.googleapis.com/maps/api/directions/json"
                 . "?origin={$oLat},{$oLng}&destination={$dLat},{$dLng}"
                 . "&key={$apiKey}&language=es&mode=driving&departure_time=now";
        $gBody   = $fetchUrl($gUrl);
        $gJson   = $gBody ? json_decode($gBody, true) : null;
        $gRoute  = $gJson['routes'][0] ?? null;

        if ($gRoute && ($gJson['status'] ?? '') === 'OK') {
            $legs       = $gRoute['legs'] ?? [];
            $durNormal  = (int)array_sum(array_map(fn($l) => $l['duration']['value'] ?? 0, $legs));
            $durTraffic = (int)array_sum(array_map(
                fn($l) => $l['duration_in_traffic']['value'] ?? $l['duration']['value'] ?? 0, $legs
            ));
            $tRatio = $durNormal > 0 ? round($durTraffic / $durNormal, 2) : 1.0;
            respond(200, true, 'OK', [
                'polyline'             => $gRoute['overview_polyline']['points'] ?? '',
                'duration_sec'         => $durNormal,
                'duration_traffic_sec' => $durTraffic,
                'traffic_ratio'        => $tRatio,
                'distance_m'           => (int)array_sum(array_map(fn($l) => $l['distance']['value'] ?? 0, $legs)),
                'source'               => 'google',
            ]);
        }

        // ── Intento 2: OSRM server-side (funciona bien desde PHP) ────────────
        $osrmUrl  = "https://router.project-osrm.org/route/v1/driving/{$oLng},{$oLat};{$dLng},{$dLat}?overview=full&geometries=geojson";
        $osrmBody = $fetchUrl($osrmUrl);
        $osrmJson = $osrmBody ? json_decode($osrmBody, true) : null;
        $osrmR    = $osrmJson['routes'][0] ?? null;

        if (($osrmJson['code'] ?? '') === 'Ok' && $osrmR) {
            // GeoJSON: [lng, lat] → convertir a [{latitude, longitude}]
            $coords = array_map(
                fn($c) => ['latitude' => (float)$c[1], 'longitude' => (float)$c[0]],
                $osrmR['geometry']['coordinates'] ?? []
            );
            $durNormal = (int)($osrmR['duration'] ?? 0);
            respond(200, true, 'OK', [
                'coordinates'          => $coords,
                'duration_sec'         => $durNormal,
                'duration_traffic_sec' => (int)round($durNormal * $trafficMul),
                'traffic_ratio'        => round($trafficMul, 2),
                'distance_m'           => (int)($osrmR['distance'] ?? 0),
                'source'               => 'osrm',
            ]);
        }

        // ── Intento 3: Valhalla server-side ──────────────────────────────────
        $valBody = json_encode([
            'locations' => [
                ['lon' => $oLng, 'lat' => $oLat],
                ['lon' => $dLng, 'lat' => $dLat],
            ],
            'costing' => 'auto',
        ]);
        if (function_exists('curl_init')) {
            $ch = curl_init('https://valhalla1.openstreetmap.de/route');
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_TIMEOUT        => 10,
                CURLOPT_POST           => true,
                CURLOPT_POSTFIELDS     => $valBody,
                CURLOPT_HTTPHEADER     => ['Content-Type: application/json', 'Accept: application/json'],
                CURLOPT_SSL_VERIFYPEER => false,
            ]);
            $valRaw = curl_exec($ch);
            curl_close($ch);
            $valJson = $valRaw ? json_decode($valRaw, true) : null;
            $valLegs = $valJson['trip']['legs'] ?? null;
            if ($valLegs) {
                $shape     = $valLegs[0]['shape'] ?? '';
                $summaries = array_filter(array_column($valLegs, 'summary'));
                $totalSec  = (int)array_sum(array_column($summaries, 'time'));
                $totalKm   = (float)array_sum(array_column($summaries, 'length'));
                if ($shape) {
                    respond(200, true, 'OK', [
                        'polyline'             => $shape,
                        'polyline6'            => true,
                        'duration_sec'         => $totalSec,
                        'duration_traffic_sec' => (int)round($totalSec * $trafficMul),
                        'traffic_ratio'        => round($trafficMul, 2),
                        'distance_m'           => (int)($totalKm * 1000),
                        'source'               => 'valhalla',
                    ]);
                }
            }
        }

        respond(200, false, 'Sin ruta disponible (' . ($gJson['status'] ?? 'sin respuesta') . ')');
        break;

    // ── TTS: Google Cloud Text-to-Speech (voz navegación) ────────────────────
    case 'tts':
        $text = trim($_GET['text'] ?? '');
        if (!$text || mb_strlen($text) > 400) respond(400, false, 'Texto inválido');
        if (!function_exists('curl_init')) respond(503, false, 'cURL no disponible');

        $ttsApiKey = 'AIzaSyCcPbr92rZz26wyw1hB4XLuBMfMxtDHE9o';
        $ttsBody   = json_encode([
            'input'       => ['text' => $text],
            'voice'       => ['languageCode' => 'es-US', 'name' => 'es-US-Neural2-B', 'ssmlGender' => 'FEMALE'],
            'audioConfig' => ['audioEncoding' => 'MP3', 'speakingRate' => 0.92, 'pitch' => 0.0],
        ]);

        $ch2 = curl_init("https://texttospeech.googleapis.com/v1/text:synthesize?key={$ttsApiKey}");
        curl_setopt_array($ch2, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 8,
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => $ttsBody,
            CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
            CURLOPT_SSL_VERIFYPEER => false,
        ]);
        $ttsRaw  = curl_exec($ch2);
        curl_close($ch2);
        $ttsData = $ttsRaw ? json_decode($ttsRaw, true) : null;

        if (!empty($ttsData['audioContent'])) {
            $mp3 = base64_decode($ttsData['audioContent']);
            // Override the global JSON Content-Type with audio/mpeg
            header_remove('Content-Type');
            header('Content-Type: audio/mpeg');
            header('Content-Length: ' . strlen($mp3));
            header('Cache-Control: no-store');
            echo $mp3;
            exit;
        }
        $ttsErr = (is_array($ttsData) && isset($ttsData['error']['message']))
            ? $ttsData['error']['message']
            : 'TTS no disponible — activa Cloud Text-to-Speech API';
        respond(503, false, $ttsErr);
        break;

    default:
        respond(404, false, 'Recurso no encontrado');
}

// ═══════════════════════════════════════════════════════════════════════════════
// FUNCIONES AUXILIARES
// ═══════════════════════════════════════════════════════════════════════════════

function respond(int $code, bool $success, string $message, $data = null): void
{
    http_response_code($code);
    $out = ['success' => $success, 'message' => $message];
    if ($data !== null) $out['data'] = $data;
    echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function createSession(PDO $pdo, int $userId): string
{
    $token   = bin2hex(random_bytes(32));
    $expires = date('Y-m-d H:i:s', strtotime('+' . SESSION_DAYS . ' days'));

    // Limpiar sesiones expiradas del usuario
    $pdo->prepare("DELETE FROM sessions WHERE user_id = ? AND expires_at < NOW()")->execute([$userId]);

    $pdo->prepare("INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)")
        ->execute([$userId, $token, $expires]);

    return $token;
}

function getUserById(PDO $pdo, int $userId): array
{
    $stmt = $pdo->prepare(
        "SELECT u.id, u.name, u.email, u.photo_url, u.google_id, u.email_verified, u.created_at,
                COALESCE(u.role, 'customer') AS role,
                u.store_id,
                s.name AS store_name,
                s.address AS store_address,
                (SELECT AVG(rating) FROM orders WHERE delivery_user_id = u.id AND rating IS NOT NULL) AS avg_rating,
                (SELECT COUNT(rating) FROM orders WHERE delivery_user_id = u.id AND rating IS NOT NULL) AS total_ratings
         FROM users u
         LEFT JOIN stores s ON s.id = u.store_id
         WHERE u.id = ?"
    );
    $stmt->execute([$userId]);
    $user = $stmt->fetch() ?: [];
    if ($user) {
        $user['avg_rating'] = $user['avg_rating'] ? round((float)$user['avg_rating'], 1) : null;
        $user['total_ratings'] = (int)($user['total_ratings'] ?? 0);
    }
    return $user;
}

function getBearerToken(): ?string
{
    $auth = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (preg_match('/Bearer\s+(.+)/i', $auth, $m)) return $m[1];
    return null;
}

function requireAuth(PDO $pdo): int
{
    $token = getBearerToken();
    if (!$token) respond(401, false, 'Autenticación requerida');

    $stmt = $pdo->prepare(
        "SELECT user_id FROM sessions WHERE token = ? AND expires_at > NOW()"
    );
    $stmt->execute([$token]);
    $row = $stmt->fetch();

    if (!$row) respond(401, false, 'Sesión expirada o inválida');
    return (int)$row['user_id'];
}
