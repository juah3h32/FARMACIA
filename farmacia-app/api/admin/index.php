<?php
/**
 * ════════════════════════════════════════════════════════
 * TPN Admin Panel — Enterprise Edition
 * URL: https://todopalnegocio.com.mx/api/admin/
 * ════════════════════════════════════════════════════════
 */
// ─── SECURITY HEADERS ─────────────────────────────────────
header('X-Frame-Options: DENY');
header('X-Content-Type-Options: nosniff');

// Secure session cookie settings
session_set_cookie_params([
    'lifetime' => 0,
    'path'     => '/',
    'secure'   => isset($_SERVER['HTTPS']),
    'httponly' => true,
    'samesite' => 'Strict',
]);
session_start();

// ─── CONFIGURACIÓN ────────────────────────────────────────
// Bcrypt hash of the admin password 'Admin2025!'
// To regenerate: password_hash('YourNewPassword', PASSWORD_BCRYPT, ['cost'=>11])
define('ADMIN_PASSWORD_HASH', '$2b$11$T9RR3apt5DBiYRAjg1.jGeUjW92JwHhoXV7KRsdGUefxklpr6Ju6i');
define('DB_HOST', 'localhost');
define('DB_NAME', 'u992666585_TPN');
define('DB_USER', 'u992666585_TPN_USER');
define('DB_PASS', 'JUANPA9912a');
define('UPLOAD_DIR', __DIR__ . '/uploads/');
define('UPLOAD_URL', '/api/admin/uploads/');
define('OPENAI_API_KEY', getenv('OPENAI_API_KEY') ?: '');
define('CLOUDINARY_CLOUD', 'dcutrbbyw');
define('CLOUDINARY_PRESET', 'tpn_preset');

if (!is_dir(UPLOAD_DIR)) @mkdir(UPLOAD_DIR, 0755, true);

// ─── AUTH ─────────────────────────────────────────────────
if (isset($_POST['admin_password'])) {
    if (password_verify($_POST['admin_password'], ADMIN_PASSWORD_HASH)) {
        session_regenerate_id(true);
        $_SESSION['tpn_admin'] = true;
        $_SESSION['csrf']      = bin2hex(random_bytes(32));
        header('Location: ' . $_SERVER['PHP_SELF']);
        exit;
    } else {
        $loginError = 'Contraseña incorrecta. Intenta de nuevo.';
    }
}
if (isset($_GET['logout'])) {
    session_destroy();
    header('Location: ' . strtok($_SERVER['REQUEST_URI'], '?'));
    exit;
}
$isLogged = !empty($_SESSION['tpn_admin']);
// Ensure CSRF token exists for logged-in sessions
if ($isLogged && empty($_SESSION['csrf'])) {
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
}

// ─── DB ───────────────────────────────────────────────────
$pdo = null; $dbError = null;
if ($isLogged) {
    try {
        $pdo = new PDO(
            "mysql:host=".DB_HOST.";dbname=".DB_NAME.";charset=utf8mb4",
            DB_USER, DB_PASS,
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]
        );
    } catch (PDOException $e) { $dbError = $e->getMessage(); }
}

// ─── HELPER: SVG ICONS ────────────────────────────────────
function icon(string $name, int $size = 16, string $class = ''): string {
    $s = $size;
    $c = $class ? " class=\"$class\"" : '';
    $icons = [
        'package'       => '<path stroke-linecap="round" stroke-linejoin="round" d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9"/>',
        'tag'           => '<path stroke-linecap="round" stroke-linejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z"/><path stroke-linecap="round" stroke-linejoin="round" d="M6 6h.008v.008H6V6z"/>',
        'image'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z"/>',
        'building'      => '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 6.75h.75m-.75 3h.75m-.75 3h.75m3-6h.75m-.75 3h.75m-.75 3h.75M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21m-3.75 3.75h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008z"/>',
        'upload'        => '<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/>',
        'users'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/>',
        'cart'          => '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z"/>',
        'truck'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 18.75a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 01-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 00-3.213-9.193 2.056 2.056 0 00-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.048-.987-1.106a48.554 48.554 0 00-10.026 0 1.106 1.106 0 00-.987 1.106v7.635m12-6.677v6.677m0 4.5v-4.5m0 0h-12"/>',
        'settings'      => '<path stroke-linecap="round" stroke-linejoin="round" d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.397.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>',
        'database'      => '<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625v8.625m-16.5-2.625v8.625"/>',
        'plus'          => '<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15"/>',
        'pencil'        => '<path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10"/>',
        'trash'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/>',
        'toggle'        => '<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21"/>',
        'search'        => '<path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/>',
        'logout'        => '<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9"/>',
        'x'             => '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>',
        'user'          => '<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"/>',
        'chart'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>',
        'box'           => '<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/>',
        'check'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/>',
        'download'      => '<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"/>',
        'photo'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z"/><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z"/>',
        'filter'        => '<path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z"/>',
        'alert'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>',
        'info'          => '<path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"/>',
        'google'        => '<path d="M12.545 10.239v3.821h5.445c-.712 2.315-2.647 3.972-5.445 3.972a6.033 6.033 0 110-12.064c1.498 0 2.866.549 3.921 1.453l2.814-2.814A9.969 9.969 0 0012.545 3C7.021 3 2.543 7.477 2.543 12s4.478 9 10.002 9c8.396 0 10.249-7.85 9.426-11.748l-9.426-.013z" fill="currentColor"/>',
        'email'         => '<path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75"/>',
    ];
    $path = $icons[$name] ?? '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.5"/>';
    return "<svg{$c} xmlns=\"http://www.w3.org/2000/svg\" width=\"{$s}\" height=\"{$s}\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\">{$path}</svg>";
}

// ─── AJAX ACTIONS ─────────────────────────────────────────
if ($isLogged && $pdo && isset($_GET['action'])) {
    header('Content-Type: application/json; charset=utf-8');
    $action = $_GET['action'];
    $input  = json_decode(file_get_contents('php://input'), true) ?? [];

    // ── CSRF check for all state-mutating (POST) actions ──
    $mutatingActions = [
        'create_product','update_product','delete_product','toggle_product','update_stock','import_csv',
        'upload_image','upload_promo_image','create_promo','update_promo','delete_promo',
        'toggle_promo','save_cat','del_cat','toggle_cat','save_store',
        'delete_store','toggle_store','set_user_role','set_user_store','create_delivery',
        'delete_user','update_order_status','bulk_delete_products','manual_assign_driver',
    ];
    if (in_array($action, $mutatingActions)) {
        $csrfHeader   = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '';
        $csrfInput    = $input['_csrf'] ?? '';
        $csrfFormPost = $_POST['_csrf'] ?? '';
        $csrfToken    = $_SESSION['csrf'] ?? '';
        $csrfOk = $csrfToken && (
            hash_equals($csrfToken, $csrfHeader)  ||
            hash_equals($csrfToken, $csrfInput)   ||
            hash_equals($csrfToken, $csrfFormPost)
        );
        if (!$csrfOk) {
            echo json_encode(['error' => 'Token CSRF inválido. Recarga la página.']);
            exit;
        }
    }

    switch ($action) {
        case 'list_products':
            $q = '%'.($_GET['q'] ?? '').'%'; $cat = $_GET['cat'] ?? '';
            $stockFilter = $_GET['stock_filter'] ?? '';
            $sql = "SELECT * FROM products WHERE name LIKE ?"; $params = [$q];
            if ($cat) { $sql .= " AND category = ?"; $params[] = $cat; }
            if ($stockFilter === 'none')  $sql .= " AND stock = 0";
            if ($stockFilter === 'low')   $sql .= " AND stock > 0 AND stock < 10";
            if ($stockFilter === 'ok')    $sql .= " AND stock >= 10";
            $sql .= " ORDER BY stock ASC, category, name";
            $stmt = $pdo->prepare($sql); $stmt->execute($params);
            echo json_encode(['data' => $stmt->fetchAll()]); exit;

        case 'update_stock':
            $id    = (int)($input['id'] ?? 0);
            $sv    = (int)($input['stock'] ?? 0);
            // -1 = ilimitado; otros negativos → 0
            $stock = $sv === -1 ? -1 : max(0, $sv);
            if (!$id) { echo json_encode(['error' => 'ID requerido']); exit; }
            // Si se repone stock (o ilimitado), reactivar el producto automáticamente
            $pdo->prepare("UPDATE products SET stock=?, active=IF(?=0,0,1), updated_at=NOW() WHERE id=?")
                ->execute([$stock, $stock, $id]);
            echo json_encode(['ok' => true]); exit;

        case 'create_product':
            $trimStr = fn($v) => is_string($v) ? trim($v) : $v;
            $n = array_map($trimStr, $input);
            if (empty($n['name']) || empty($n['category']) || empty($n['price'])) {
                echo json_encode(['error' => 'Nombre, categoría y precio son requeridos']); exit;
            }
            $extraImgs = (!empty($input['extra_images']) && is_array($input['extra_images']))
                ? json_encode(array_values(array_filter($input['extra_images']))) : null;
            $skuVal = !empty($n['sku']) ? strtoupper($n['sku']) : null;
            try {
                $pdo->prepare("INSERT INTO products (sku,name,category,price,unit,image_url,extra_images,promo,description,stock,active) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
                    ->execute([$skuVal, strtoupper($n['name']), strtoupper($n['category']), (float)$n['price'],
                        strtoupper($n['unit'] ?? 'KG'), $n['image_url'] ?? '', $extraImgs,
                        $n['promo'] ?? null, $n['description'] ?? null, (int)($n['stock'] ?? 0), (int)($n['active'] ?? 1)]);
                echo json_encode(['ok' => true, 'id' => $pdo->lastInsertId()]);
            } catch (PDOException $e) {
                echo json_encode(['error' => str_contains($e->getMessage(),'sku') ? 'El SKU ya existe' : $e->getMessage()]);
            }
            exit;

        case 'update_product':
            $id = (int)($input['id'] ?? 0);
            if (!$id) { echo json_encode(['error' => 'ID requerido']); exit; }
            $extraImgs = (!empty($input['extra_images']) && is_array($input['extra_images']))
                ? json_encode(array_values(array_filter($input['extra_images']))) : null;
            $skuVal = !empty(trim($input['sku'] ?? '')) ? strtoupper(trim($input['sku'])) : null;
            $stockV = (int)($input['stock'] ?? 0);
            $stockV = $stockV === -1 ? -1 : max(0, $stockV);
            try {
                $pdo->prepare("UPDATE products SET sku=?,name=?,category=?,price=?,unit=?,image_url=?,extra_images=?,promo=?,description=?,stock=?,active=? WHERE id=?")
                    ->execute([$skuVal, strtoupper(trim($input['name'])), strtoupper(trim($input['category'])),
                        (float)$input['price'], strtoupper(trim($input['unit'] ?? 'KG')), trim($input['image_url'] ?? ''),
                        $extraImgs, $input['promo'] ?: null, $input['description'] ?? null,
                        $stockV, (int)($input['active'] ?? 1), $id]);
                echo json_encode(['ok' => true]);
            } catch (PDOException $e) {
                echo json_encode(['error' => str_contains($e->getMessage(),'sku') ? 'El SKU ya existe' : $e->getMessage()]);
            }
            exit;

        case 'delete_product':
            $id = (int)($input['id'] ?? 0);
            if (!$id) { echo json_encode(['error' => 'ID requerido']); exit; }
            $pdo->prepare("DELETE FROM products WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'toggle_product':
            $id = (int)($input['id'] ?? 0);
            $pdo->prepare("UPDATE products SET active = 1-active WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'import_csv':
            if (empty($_FILES['csv'])) { echo json_encode(['error' => 'No se recibió archivo']); exit; }
            $handle = fopen($_FILES['csv']['tmp_name'], 'r');
            if (!$handle) { echo json_encode(['error' => 'No se pudo leer el archivo']); exit; }
            $header = array_map('strtolower', array_map('trim', fgetcsv($handle)));
            $map = array_flip($header);
            $inserted = 0; $errors = [];
            $stmt = $pdo->prepare("INSERT INTO products (name,category,price,unit,image_url,promo,description,active) VALUES (?,?,?,?,?,?,?,1) ON DUPLICATE KEY UPDATE price=VALUES(price),image_url=VALUES(image_url),promo=VALUES(promo)");
            while (($row = fgetcsv($handle)) !== false) {
                try {
                    $get = fn($k) => isset($map[$k]) ? trim($row[$map[$k]] ?? '') : '';
                    $name  = strtoupper($get('name') ?: $get('nombre'));
                    $cat   = strtoupper($get('category') ?: $get('categoria'));
                    $price = (float) str_replace(['$',','], '', $get('price') ?: $get('precio'));
                    $unit  = strtoupper($get('unit') ?: $get('unidad') ?: 'KG');
                    $img   = $get('image_url') ?: $get('imagen') ?: $get('img');
                    $promo = $get('promo') ?: null;
                    $desc  = $get('description') ?: $get('descripcion') ?: null;
                    if (!$name || !$cat || $price <= 0) { $errors[] = "Fila inválida: ".implode(',',$row); continue; }
                    $stmt->execute([$name,$cat,$price,$unit,$img,$promo?:null,$desc]);
                    $inserted++;
                } catch (Exception $ex) { $errors[] = $ex->getMessage(); }
            }
            fclose($handle);
            echo json_encode(['ok' => true, 'inserted' => $inserted, 'errors' => $errors]); exit;

        case 'upload_image':
        case 'upload_promo_image':
            if (empty($_FILES['image'])) { echo json_encode(['error' => 'No se recibió imagen']); exit; }
            $file = $_FILES['image'];
            $cloudName = 'dcutrbbyw';
            $uploadPreset = 'tpn_preset';
            $folder = ($action === 'upload_promo_image') ? 'tpn_promos' : 'tpn_products';

            $ch = curl_init("https://api.cloudinary.com/v1_1/$cloudName/image/upload");
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, [
                'file' => new CURLFile($file['tmp_name'], $file['type'], $file['name']),
                'upload_preset' => $uploadPreset,
                'folder' => $folder
            ]);
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            $response = curl_exec($ch);
            curl_close($ch);

            $data = json_decode($response, true);
            if (isset($data['secure_url'])) {
                echo json_encode(['ok' => true, 'url' => $data['secure_url']]);
            } else {
                echo json_encode(['error' => 'Error en Cloudinary: ' . ($data['error']['message'] ?? 'Desconocido')]);
            }
            exit;

        case 'generate_description':
            $name     = trim($input['name'] ?? '');
            $category = trim($input['category'] ?? '');
            if (!$name) { echo json_encode(['error' => 'Se requiere el nombre del producto']); exit; }
            $context = $category ?: 'abarrotes';
            $payload = json_encode([
                'model'       => 'gpt-4o-mini',
                'max_tokens'  => 160,
                'temperature' => 0.7,
                'messages'    => [[
                    'role'    => 'user',
                    'content' => "Eres redactor de fichas de producto para una tienda de abarrotes en México. " .
                                 "Escribe una descripción del producto '{$name}' (categoría: {$context}) " .
                                 "siguiendo exactamente este estilo y extensión: " .
                                 "\"La Charola Naturalizable 855 está diseñada para negocios que buscan calidad premium sin impactar al medio ambiente. " .
                                 "Fabricada con materiales de origen natural (fécula de maíz o caña de azúcar), esta charola ofrece la misma resistencia " .
                                 "que una térmica tradicional, pero con la ventaja de ser 100% biodegradable y compostable.\" " .
                                 "2-3 oraciones, tono profesional, menciona usos, beneficios o características del producto. " .
                                 "Solo la descripción, sin comillas ni texto adicional.",
                ]],
            ]);
            $ch = curl_init('https://api.openai.com/v1/chat/completions');
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_POST           => true,
                CURLOPT_POSTFIELDS     => $payload,
                CURLOPT_HTTPHEADER     => ['Content-Type: application/json', 'Authorization: Bearer ' . OPENAI_API_KEY],
            ]);
            $data = json_decode(curl_exec($ch), true);
            curl_close($ch);
            if (!empty($data['error'])) { echo json_encode(['error' => $data['error']['message']]); exit; }
            $description = mb_substr(trim($data['choices'][0]['message']['content'] ?? ''), 0, 400);
            echo json_encode(['description' => $description]); exit;

        case 'stats':
            echo json_encode([
                'products'       => $pdo->query("SELECT COUNT(*) FROM products WHERE active=1")->fetchColumn(),
                'products_total' => $pdo->query("SELECT COUNT(*) FROM products")->fetchColumn(),
                'no_stock'       => $pdo->query("SELECT COUNT(*) FROM products WHERE stock=0 AND active=1")->fetchColumn(),
                'low_stock'      => $pdo->query("SELECT COUNT(*) FROM products WHERE stock>0 AND stock<10 AND active=1")->fetchColumn(),
                'users'          => $pdo->query("SELECT COUNT(*) FROM users")->fetchColumn(),
                'orders'         => $pdo->query("SELECT COUNT(*) FROM orders")->fetchColumn(),
                'revenue'        => $pdo->query("SELECT COALESCE(SUM(total),0) FROM orders WHERE status!='cancelled'")->fetchColumn(),
            ]); exit;

        case 'list_users':
            try {
                $stmt = $pdo->query(
                    "SELECT u.id, u.name, u.email,
                            COALESCE(u.role,'customer') AS role,
                            u.store_id,
                            s.name AS store_name,
                            COALESCE(u.phone,'') AS phone,
                            google_id IS NOT NULL AS is_google,
                            u.email_verified, u.created_at,
                            (u.push_token IS NOT NULL AND u.push_token != '') AS has_push_token
                     FROM users u
                     LEFT JOIN stores s ON s.id = u.store_id
                     ORDER BY u.created_at DESC LIMIT 300"
                );
            } catch (PDOException $e) {
                $stmt = $pdo->query("SELECT id,name,email,'customer' AS role, NULL AS store_id, NULL AS store_name, '' AS phone, google_id IS NOT NULL AS is_google,email_verified,created_at, 0 AS has_push_token FROM users ORDER BY created_at DESC LIMIT 300");
            }
            echo json_encode(['data' => $stmt->fetchAll()]); exit;

        case 'set_user_store':
            $id = (int)($input['id'] ?? 0);
            $storeId = !empty($input['store_id']) ? (int)$input['store_id'] : null;
            if (!$id) { echo json_encode(['error' => 'ID requerido']); exit; }
            try { $pdo->prepare("UPDATE users SET store_id=? WHERE id=?")->execute([$storeId, $id]); echo json_encode(['ok' => true]); }
            catch (PDOException $e) { echo json_encode(['error' => $e->getMessage()]); }
            exit;

        case 'create_delivery':
            $name  = trim($input['name'] ?? '');
            $email = trim($input['email'] ?? '');
            $pass  = $input['password'] ?? '';
            $phone = trim($input['phone'] ?? '') ?: null;
            $storeId = !empty($input['store_id']) ? (int)$input['store_id'] : null;
            if (!$name || !$email || !$pass) { echo json_encode(['error' => 'Nombre, correo y contraseña son obligatorios']); exit; }
            $exists = $pdo->prepare("SELECT id FROM users WHERE email=? LIMIT 1");
            $exists->execute([$email]);
            if ($exists->fetch()) { echo json_encode(['error' => 'Ya existe un usuario con ese correo']); exit; }
            try {
                $hash = password_hash($pass, PASSWORD_BCRYPT);
                $pdo->prepare("INSERT INTO users (name,email,password_hash,phone,role,store_id,email_verified,active) VALUES (?,?,?,?,'delivery',?,1,1)")
                    ->execute([$name, $email, $hash, $phone, $storeId]);
                echo json_encode(['ok' => true, 'id' => $pdo->lastInsertId()]);
            } catch (PDOException $e) { echo json_encode(['error' => $e->getMessage()]); }
            exit;

        case 'delete_user':
            $id = (int)($input['id'] ?? 0);
            if ($id) {
                // Solo permite eliminar repartidores, nunca admins ni clientes
                $pdo->prepare("DELETE FROM users WHERE id=? AND role='delivery'")->execute([$id]);
            }
            echo json_encode(['ok' => true]); exit;

        case 'list_cats':
            $stmt = $pdo->query("SELECT * FROM categories ORDER BY sort_order,name");
            echo json_encode(['data' => $stmt->fetchAll()]); exit;

        case 'save_cat':
            $id = (int)($input['id'] ?? 0);
            if (empty($input['name']) || empty($input['label'])) { echo json_encode(['error' => 'Nombre y etiqueta requeridos']); exit; }
            if ($id) {
                $pdo->prepare("UPDATE categories SET name=?,label=?,icon=?,img_url=?,sort_order=?,active=? WHERE id=?")
                    ->execute([strtoupper(trim($input['name'])), trim($input['label']), trim($input['icon'] ?? 'grid-outline'),
                        trim($input['img_url'] ?? ''), (int)($input['sort_order'] ?? 0), (int)($input['active'] ?? 1), $id]);
            } else {
                $pdo->prepare("INSERT INTO categories (name,label,icon,img_url,sort_order,active) VALUES (?,?,?,?,?,?)")
                    ->execute([strtoupper(trim($input['name'])), trim($input['label']), trim($input['icon'] ?? 'grid-outline'),
                        trim($input['img_url'] ?? ''), (int)($input['sort_order'] ?? 0), (int)($input['active'] ?? 1)]);
            }
            echo json_encode(['ok' => true]); exit;

        case 'del_cat':
            $id = (int)($input['id'] ?? 0);
            if ($id) $pdo->prepare("DELETE FROM categories WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'toggle_cat':
            $id = (int)($input['id'] ?? 0);
            $pdo->prepare("UPDATE categories SET active=1-active WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'list_promos':
            $stmt = $pdo->query("SELECT * FROM promos ORDER BY position,sort_order,id");
            echo json_encode(['data' => $stmt->fetchAll()]); exit;

        case 'create_promo':
            $n = array_map('trim', $input);
            if (empty($n['title']) || empty($n['image_url'])) { echo json_encode(['error' => 'Título e imagen requeridos']); exit; }
            $pdo->prepare("INSERT INTO promos (title,image_url,link_url,position,sort_order,active) VALUES (?,?,?,?,?,?)")
                ->execute([$n['title'], $n['image_url'], $n['link_url'] ?? '', $n['position'] ?? 'both', (int)($n['sort_order'] ?? 0), (int)($n['active'] ?? 1)]);
            echo json_encode(['ok' => true, 'id' => $pdo->lastInsertId()]); exit;

        case 'update_promo':
            $id = (int)($input['id'] ?? 0);
            if (!$id) { echo json_encode(['error' => 'ID requerido']); exit; }
            $pdo->prepare("UPDATE promos SET title=?,image_url=?,link_url=?,position=?,sort_order=?,active=? WHERE id=?")
                ->execute([trim($input['title']), trim($input['image_url']), trim($input['link_url'] ?? ''),
                    $input['position'] ?? 'both', (int)($input['sort_order'] ?? 0), (int)($input['active'] ?? 1), $id]);
            echo json_encode(['ok' => true]); exit;

        case 'delete_promo':
            $id = (int)($input['id'] ?? 0);
            if (!$id) { echo json_encode(['error' => 'ID requerido']); exit; }
            $pdo->prepare("DELETE FROM promos WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'toggle_promo':
            $id = (int)($input['id'] ?? 0);
            $pdo->prepare("UPDATE promos SET active=1-active WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'list_stores':
            try { $stmt = $pdo->query("SELECT * FROM stores ORDER BY sort_order,name"); echo json_encode(['data' => $stmt->fetchAll()]); }
            catch (PDOException $e) { echo json_encode(['data' => [], 'error' => 'Tabla stores no encontrada']); }
            exit;

        // ── OPERACIONES: pedidos sin repartidor asignado ───────────────────
        case 'ops_pending_orders':
            try {
                $stmt = $pdo->query(
                    "SELECT o.id, o.status, o.total, o.address, o.created_at, o.store_id,
                            u.name AS customer_name,
                            s.name AS store_name,
                            (SELECT COUNT(*) FROM order_items WHERE order_id=o.id) AS items_count
                     FROM orders o
                     LEFT JOIN users u  ON u.id = o.user_id
                     LEFT JOIN stores s ON s.id = o.store_id
                     WHERE o.status = 'pending' AND o.delivery_user_id IS NULL
                     ORDER BY o.created_at ASC
                     LIMIT 50"
                );
                echo json_encode(['data' => $stmt->fetchAll()]);
            } catch (PDOException $e) { echo json_encode(['data' => [], 'error' => $e->getMessage()]); }
            exit;

        // ── OPERACIONES: carga actual de cada repartidor ───────────────────
        case 'ops_driver_workload':
            try {
                // Repartidores con sus pedidos activos
                $stmt = $pdo->query(
                    "SELECT u.id, u.name, u.email,
                            COALESCE(u.store_id,0) AS store_id,
                            s.name AS store_name,
                            (u.push_token IS NOT NULL AND u.push_token != '') AS has_push,
                            COUNT(o.id) AS active_orders
                     FROM users u
                     LEFT JOIN stores s  ON s.id = u.store_id
                     LEFT JOIN orders o  ON o.delivery_user_id = u.id
                                       AND o.status IN ('accepted','preparing','picked_up','on_the_way')
                     WHERE u.role = 'delivery' AND u.active = 1
                     GROUP BY u.id
                     ORDER BY active_orders ASC, u.name ASC"
                );
                $drivers = $stmt->fetchAll();

                // Para cada driver: detalle de pedidos activos
                foreach ($drivers as &$d) {
                    $os = $pdo->prepare(
                        "SELECT o.id, o.status, o.address, o.total, o.created_at
                         FROM orders o
                         WHERE o.delivery_user_id = ?
                           AND o.status IN ('accepted','preparing','picked_up','on_the_way')
                         ORDER BY o.created_at DESC"
                    );
                    $os->execute([$d['id']]);
                    $d['orders'] = $os->fetchAll();
                }
                echo json_encode(['data' => $drivers]);
            } catch (PDOException $e) { echo json_encode(['data' => [], 'error' => $e->getMessage()]); }
            exit;

        // ── OPERACIONES: asignación manual de repartidor a pedido ─────────
        case 'manual_assign_driver':
            $orderId  = (int)($input['order_id']  ?? 0);
            $driverId = (int)($input['driver_id'] ?? 0);
            if (!$orderId || !$driverId) { echo json_encode(['error' => 'Datos incompletos']); exit; }
            try {
                $pdo->prepare(
                    "UPDATE orders SET delivery_user_id=?, status='accepted', updated_at=NOW()
                     WHERE id=? AND (delivery_user_id IS NULL OR delivery_user_id != ?)"
                )->execute([$driverId, $orderId, $driverId]);

                // Notificar al repartidor si tiene push token
                $dRow = $pdo->prepare("SELECT name FROM users WHERE id=?");
                $dRow->execute([$driverId]);
                $dData = $dRow->fetch();

                $oRow = $pdo->prepare("SELECT address, user_id FROM orders WHERE id=?");
                $oRow->execute([$orderId]);
                $oData = $oRow->fetch();

                if ($oData) {
                    // Push al repartidor
                    $tRow = $pdo->prepare("SELECT push_token FROM users WHERE id=? AND push_token IS NOT NULL AND push_token!=''");
                    $tRow->execute([$driverId]);
                    $tData = $tRow->fetch();
                    if ($tData) {
                        // Usar la misma función sendExpoPush del index.php principal no está disponible aquí;
                        // guardamos un flag para que la app lo pille en el siguiente poll (10s)
                    }
                    // Notificar al cliente
                    $custRow = $pdo->prepare("SELECT push_token FROM users WHERE id=?");
                    $custRow->execute([$oData['user_id']]);
                }

                echo json_encode(['ok' => true, 'driver' => $dData['name'] ?? 'Repartidor']);
            } catch (PDOException $e) { echo json_encode(['error' => $e->getMessage()]); }
            exit;

        case 'save_store':
            $id = (int)($input['id'] ?? 0); $n = array_map('trim', $input);
            if (empty($n['name']) || empty($n['address']) || empty($n['lat']) || empty($n['lng'])) {
                echo json_encode(['error' => 'Nombre, dirección, lat y lng requeridos']); exit;
            }
            try {
                if ($id) {
                    $pdo->prepare("UPDATE stores SET name=?,city=?,address=?,lat=?,lng=?,phone=?,sort_order=?,active=? WHERE id=?")
                        ->execute([$n['name'], $n['city'] ?? '', $n['address'], (float)$n['lat'], (float)$n['lng'],
                            $n['phone'] ?? null, (int)($n['sort_order'] ?? 0), (int)($n['active'] ?? 1), $id]);
                } else {
                    $pdo->prepare("INSERT INTO stores (name,city,address,lat,lng,phone,sort_order,active) VALUES (?,?,?,?,?,?,?,?)")
                        ->execute([$n['name'], $n['city'] ?? '', $n['address'], (float)$n['lat'], (float)$n['lng'],
                            $n['phone'] ?? null, (int)($n['sort_order'] ?? 0), 1]);
                }
                echo json_encode(['ok' => true, 'id' => $id ?: $pdo->lastInsertId()]);
            } catch (PDOException $e) { echo json_encode(['error' => $e->getMessage()]); }
            exit;

        case 'delete_store':
            $id = (int)($input['id'] ?? 0);
            if ($id) $pdo->prepare("DELETE FROM stores WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'toggle_store':
            $id = (int)($input['id'] ?? 0);
            $pdo->prepare("UPDATE stores SET active=1-active WHERE id=?")->execute([$id]);
            echo json_encode(['ok' => true]); exit;

        case 'set_user_role':
            $id = (int)($input['id'] ?? 0); $role = $input['role'] ?? '';
            if (!$id || !in_array($role, ['customer','delivery','admin'])) { echo json_encode(['error' => 'ID o rol inválido']); exit; }
            try { $pdo->prepare("UPDATE users SET role=? WHERE id=?")->execute([$role, $id]); echo json_encode(['ok' => true]); }
            catch (PDOException $e) { echo json_encode(['error' => 'Columna role no encontrada']); }
            exit;

        case 'list_orders':
            $status = $_GET['status'] ?? '';
            try {
                $sql = "SELECT o.*,
                               u.name AS user_name, u.email AS user_email,
                               d.name AS delivery_name,
                               s.lat AS store_lat, s.lng AS store_lng, s.name AS store_name
                        FROM orders o
                        LEFT JOIN users u  ON u.id = o.user_id
                        LEFT JOIN users d  ON d.id = o.delivery_user_id
                        LEFT JOIN stores s ON s.id = o.store_id";
                $params = [];
                if ($status) { $sql .= " WHERE o.status=?"; $params[] = $status; }
                $sql .= " ORDER BY o.created_at DESC LIMIT 300";
                $stmt = $pdo->prepare($sql); $stmt->execute($params);
                echo json_encode(['data' => $stmt->fetchAll()]);
            } catch (PDOException $e) { echo json_encode(['data' => [], 'error' => $e->getMessage()]); }
            exit;

        case 'update_order_status':
            $id = (int)($input['id'] ?? 0); $status = $input['status'] ?? '';
            $allowed = ['pending','accepted','picked_up','on_the_way','delivered','cancelled'];
            if (!$id || !in_array($status, $allowed)) { echo json_encode(['error' => 'ID o estado inválido']); exit; }
            try { $pdo->prepare("UPDATE orders SET status=? WHERE id=?")->execute([$status, $id]); echo json_encode(['ok' => true]); }
            catch (PDOException $e) { echo json_encode(['error' => $e->getMessage()]); }
            exit;

        case 'bulk_delete_products':
            $ids = array_filter(array_map('intval', $input['ids'] ?? []));
            if (empty($ids)) { echo json_encode(['error' => 'Sin IDs']); exit; }
            try {
                $in = implode(',', array_fill(0, count($ids), '?'));
                $pdo->prepare("DELETE FROM order_items WHERE product_id IN ($in)")->execute(array_values($ids));
                $pdo->prepare("DELETE FROM products WHERE id IN ($in)")->execute(array_values($ids));
                echo json_encode(['ok' => true, 'deleted' => count($ids)]); exit;
            } catch (PDOException $e) {
                echo json_encode(['error' => $e->getMessage()]); exit;
            }

        default: echo json_encode(['error' => 'Acción no encontrada']); exit;
    }
}

$categories = ['VEGETALES','LÁCTEOS','ACEITES','CEREALES','BEBIDAS','LIMPIEZA','CARNES','FRUTAS','OTROS'];
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TPN — Panel de Administración</title>
<link rel="stylesheet" href="admin-style.css">
<link href="https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css" rel="stylesheet">
<script src="https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.js"></script>
<style>
  /* map overrides already handled in admin-style.css */
</style>
</head>
<body>

<?php if (!$isLogged): ?>
<!-- ═══════════════════════ LOGIN ═══════════════════════ -->
<div class="login-wrap">
  <div class="login-card">
    <div class="login-logo">
      <div class="login-logo-mark">T</div>
      <div class="login-logo-text">
        <h1>TPN Admin</h1>
        <p>Todo Pal Negocio</p>
      </div>
    </div>
    <h2 class="login-heading">Bienvenido de nuevo</h2>
    <p class="login-sub">Ingresa tu contraseña para acceder al panel.</p>

    <?php if (!empty($loginError)): ?>
    <div class="login-error">
      <?= icon('alert', 14) ?>
      <?= htmlspecialchars($loginError) ?>
    </div>
    <?php endif ?>

    <form method="POST">
      <label class="login-field-label">Contraseña de acceso</label>
      <input type="password" name="admin_password" class="login-input" placeholder="••••••••••" autofocus>
      <button type="submit" class="login-btn">Acceder al panel</button>
    </form>
  </div>
</div>

<?php else: ?>
<!-- ═══════════════════════ NAVBAR ═══════════════════════ -->
<nav class="navbar">
  <div class="navbar-brand">
    <div class="navbar-logo">T</div>
    <span class="navbar-name">TPN Admin</span>
  </div>
  <div class="navbar-divider"></div>
  <?php if ($dbError): ?>
    <div class="db-badge err">
      <span class="db-badge-dot"></span>Sin conexión
    </div>
  <?php else: ?>
    <div class="db-badge ok">
      <span class="db-badge-dot"></span>Base de datos activa
    </div>
  <?php endif ?>
  <div class="navbar-spacer"></div>
  <div class="navbar-user-info">
    <div class="navbar-avatar"><?= icon('user', 14) ?></div>
    <span class="navbar-user">Administrador</span>
  </div>
  <div class="navbar-divider"></div>
  <a href="?logout=1" class="navbar-logout">
    <?= icon('logout', 14) ?>
    Salir
  </a>
</nav>

<div class="admin-layout">
  <div class="admin-content">

<?php if ($dbError): ?>
  <div class="db-error-card">
    <h3>Error de conexión a la base de datos</h3>
    <code><?= htmlspecialchars($dbError) ?></code>
    <p>Verifica DB_NAME, DB_USER y DB_PASS en la parte superior del archivo index.php.</p>
  </div>
<?php else: ?>

    <!-- Stats -->
    <div id="stats-row" class="stats-grid"></div>

    <!-- Tabs -->
    <div class="tab-bar" id="tab-bar">
      <button class="tab-btn active" onclick="showTab('products',this)">
        <?= icon('package', 14) ?> Productos
      </button>
      <button class="tab-btn" onclick="showTab('categories',this)">
        <?= icon('tag', 14) ?> Categorías
      </button>
      <button class="tab-btn" onclick="showTab('promos',this)">
        <?= icon('image', 14) ?> Promociones
      </button>
      <button class="tab-btn" onclick="showTab('stores',this)">
        <?= icon('building', 14) ?> Sucursales
      </button>
      <button class="tab-btn" onclick="showTab('import',this)">
        <?= icon('upload', 14) ?> Importar CSV
      </button>
      <button class="tab-btn" onclick="showTab('users',this)">
        <?= icon('users', 14) ?> Usuarios
      </button>
      <button class="tab-btn" onclick="showTab('orders',this)">
        <?= icon('cart', 14) ?> Pedidos
      </button>
      <button class="tab-btn" onclick="showTab('delivery',this)">
        <?= icon('truck', 14) ?> Repartidores
      </button>
      <button class="tab-btn" onclick="showTab('config',this)">
        <?= icon('settings', 14) ?> Configuración
      </button>
    </div>

    <!-- ════════ TAB: PRODUCTOS ════════ -->
    <div id="tab-products" class="tab-panel active">
      <div class="tab-panel-inner">
        <div class="toolbar">
          <div class="toolbar-field" style="max-width:260px">
            <?= icon('search', 15) ?>
            <input id="search-q" type="text" placeholder="Buscar producto…" oninput="loadProducts()">
          </div>
          <div class="toolbar-field" style="max-width:200px">
            <?= icon('filter', 15) ?>
            <select id="filter-cat" onchange="loadProducts()">
              <option value="">Todas las categorías</option>
              <?php foreach ($categories as $c): ?>
              <option value="<?= $c ?>"><?= $c ?></option>
              <?php endforeach ?>
            </select>
          </div>
          <div class="toolbar-field" style="max-width:180px">
            <?= icon('database', 15) ?>
            <select id="filter-stock" onchange="loadProducts()">
              <option value="">Todo el stock</option>
              <option value="none">⛔ Sin stock (0)</option>
              <option value="low">⚠️ Stock bajo (&lt;10)</option>
              <option value="ok">✅ Stock OK (≥10)</option>
            </select>
          </div>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-primary" onclick="openModal('create')">
            <?= icon('plus', 14) ?>
            Nuevo producto
          </button>
        </div>
        <div class="bulk-bar" id="bulk-bar">
          <span id="bulk-count">0 seleccionados</span>
          <button class="btn btn-danger btn-sm" onclick="bulkDeleteProds()">🗑 Eliminar seleccionados</button>
          <button class="btn btn-ghost btn-sm" onclick="clearSelection()">Cancelar</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th style="width:36px"><input type="checkbox" class="row-check" id="check-all" onchange="toggleSelectAllProds(this)"></th>
              <th>Imagen</th><th>Producto</th><th>Categoría</th><th>Precio</th>
              <th>Unidad</th><th>Stock</th><th>Promo</th><th>Activo</th><th>Acciones</th>
            </tr></thead>
            <tbody id="products-tbody">
              <tr><td colspan="10"><div class="empty-state">
                <div class="empty-icon"><?= icon('package', 20) ?></div>
                <div class="empty-label">Cargando productos…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ════════ TAB: CATEGORÍAS ════════ -->
    <div id="tab-categories" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar">
          <div>
            <div class="toolbar-section-title">Categorías</div>
            <div class="toolbar-section-sub">Controla qué categorías aparecen en la app</div>
          </div>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-primary" onclick="openCatModal()">
            <?= icon('plus', 14) ?> Nueva categoría
          </button>
        </div>
        <div class="notice notice-warning mb-2" style="margin:0 18px 12px">
          <strong>Importante:</strong> El campo <strong>Nombre</strong> debe coincidir exactamente con
          <code>category</code> en productos (mayúsculas). Ej: <code>VEGETALES</code>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Imagen</th><th>Nombre en BD</th><th>Etiqueta App</th><th>Ícono</th><th>Orden</th><th>Activo</th><th>Acciones</th>
            </tr></thead>
            <tbody id="cats-tbody">
              <tr><td colspan="7"><div class="empty-state">
                <div class="empty-icon"><?= icon('tag', 20) ?></div>
                <div class="empty-label">Cargando…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>
        <div class="notice notice-info mt-2" style="margin:12px 18px 18px">
          <strong>Íconos disponibles (Ionicons):</strong>
          leaf-outline · nutrition-outline · flask-outline · restaurant-outline · wine-outline · sparkles-outline · fish-outline · pricetag-outline · grid-outline · cart-outline
        </div>
      </div>
    </div>

    <!-- ════════ TAB: PROMOCIONES ════════ -->
    <div id="tab-promos" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar">
          <div class="toolbar-section-title">Banners y Promociones</div>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-primary" onclick="openPromoModal('create')">
            <?= icon('plus', 14) ?> Nueva promoción
          </button>
        </div>
        <div class="notice notice-info mb-3" style="margin:0 18px 12px">
          <strong>Dimensiones recomendadas de imágenes:</strong>
          <div class="dimension-cards">
            <div class="dimension-card">
              <div class="dim-icon"><?= icon('info', 15) ?></div>
              <div class="dim-type">Móvil</div>
              <div class="dim-size">800 × 300 px</div>
              <div class="dim-ratio">Relación 8:3</div>
              <div class="dim-pos">home_mobile</div>
            </div>
            <div class="dimension-card">
              <div class="dim-icon"><?= icon('info', 15) ?></div>
              <div class="dim-type">Escritorio</div>
              <div class="dim-size">1200 × 380 px</div>
              <div class="dim-ratio">Relación ~3:1</div>
              <div class="dim-pos">home_desktop</div>
            </div>
            <div class="dimension-card">
              <div class="dim-icon"><?= icon('info', 15) ?></div>
              <div class="dim-type">Ambos</div>
              <div class="dim-size">1200 × 400 px</div>
              <div class="dim-ratio">Relación 3:1</div>
              <div class="dim-pos">both</div>
            </div>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Imagen</th><th>Título</th><th>Posición</th><th>Orden</th><th>Enlace</th><th>Activo</th><th>Acciones</th>
            </tr></thead>
            <tbody id="promos-tbody">
              <tr><td colspan="7"><div class="empty-state">
                <div class="empty-icon"><?= icon('image', 20) ?></div>
                <div class="empty-label">Cargando…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ════════ TAB: SUCURSALES ════════ -->
    <div id="tab-stores" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar">
          <div class="toolbar-section-title">Sucursales</div>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-primary" onclick="openStoreForm(null)">
            <?= icon('plus', 14) ?> Nueva sucursal
          </button>
        </div>

        <div id="storeForm" class="store-form">
          <div class="toolbar-section-title mb-2" id="storeFormTitle">Nueva sucursal</div>
          <input type="hidden" id="storeId">
          <div class="field-row mb-2">
            <div class="field">
              <label class="field-label">Nombre <span>*</span></label>
              <input id="storeName" type="text" placeholder="TPN Centro">
            </div>
            <div class="field">
              <label class="field-label">Ciudad</label>
              <input id="storeCity" type="text" placeholder="Morelia">
            </div>
          </div>
          <div class="field mb-2">
            <label class="field-label">Dirección <span>*</span></label>
            <input id="storeAddress" type="text" placeholder="Calle 20 de Noviembre #825">
          </div>
          <!-- Mapa picker de coordenadas -->
          <div class="field mb-2">
            <label class="field-label">Ubicación en mapa <span>— clic para fijar pin</span></label>
            <div class="map-pin-hint">
              <?= icon('info', 13) ?> Haz clic en el mapa para establecer las coordenadas, o escríbelas manualmente abajo.
            </div>
            <div id="map-picker" class="map-picker"></div>
          </div>
          <div class="field-row-4 mb-2">
            <div class="field">
              <label class="field-label">Latitud <span>*</span></label>
              <input id="storeLat" type="number" step="0.0000001" placeholder="19.7061" oninput="movePickerPin()">
            </div>
            <div class="field">
              <label class="field-label">Longitud <span>*</span></label>
              <input id="storeLng" type="number" step="0.0000001" placeholder="-101.1950" oninput="movePickerPin()">
            </div>
            <div class="field">
              <label class="field-label">Teléfono</label>
              <input id="storePhone" type="text" placeholder="443-123-4567">
            </div>
            <div class="field">
              <label class="field-label">Orden</label>
              <input id="storeSortOrder" type="number" value="0">
            </div>
          </div>
          <!-- espacio intencional -->
          <div class="flex gap-2">
            <button class="btn btn-primary" onclick="saveStore()"><?= icon('check', 14) ?> Guardar sucursal</button>
            <button class="btn btn-outline" onclick="document.getElementById('storeForm').classList.remove('open')">Cancelar</button>
          </div>
          <p id="storeFormError" class="text-brand text-sm mt-1 hidden"></p>
        </div>

        <!-- Mapa resumen de sucursales -->
        <div id="map-stores" class="map-stores" style="margin:0 18px 0"></div>

        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Nombre</th><th>Ciudad</th><th>Dirección</th><th>Coordenadas</th><th>Teléfono</th><th>Estado</th><th>Acciones</th>
            </tr></thead>
            <tbody id="storesTbody">
              <tr><td colspan="7"><div class="empty-state">
                <div class="empty-icon"><?= icon('building', 20) ?></div>
                <div class="empty-label">Cargando…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ════════ TAB: IMPORTAR CSV ════════ -->
    <div id="tab-import" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar">
          <div class="toolbar-section-title">Importar productos desde CSV</div>
        </div>
        <div class="panel-body">
        <div class="notice notice-info mb-3">
          <strong>Formato de columnas:</strong> <code>name, category, price, unit, image_url, promo, description</code><br>
          También en español: <code>nombre, categoria, precio, unidad, imagen, descripcion</code><br>
          Si el producto ya existe, se actualiza precio e imagen.
        </div>
        <a href="data:text/csv;charset=utf-8,name,category,price,unit,image_url,promo,description%0AJITOMATE,VEGETALES,7.90,KG,https://url-imagen.com/foto.jpg,-10%25,Jitomate fresco"
           download="plantilla_productos.csv"
           class="btn btn-secondary mb-3">
          <?= icon('download', 14) ?> Descargar plantilla CSV
        </a>

        <div class="drop-zone" id="drop-zone"
             onclick="document.getElementById('csv-file').click()"
             ondragover="event.preventDefault();this.classList.add('drag-over')"
             ondragleave="this.classList.remove('drag-over')"
             ondrop="handleDrop(event)">
          <div class="drop-zone-icon"><?= icon('upload', 22) ?></div>
          <div class="drop-zone-title">Arrastra tu archivo CSV aquí</div>
          <div class="drop-zone-sub">o haz clic para seleccionar desde tu dispositivo</div>
          <input type="file" id="csv-file" accept=".csv" class="hidden" onchange="previewCSV(this)" onclick="event.stopPropagation()">
          <button class="btn btn-primary" onclick="event.stopPropagation();document.getElementById('csv-file').click()">
            Seleccionar archivo
          </button>
        </div>

        <div id="csv-preview" class="hidden mt-3">
          <div class="flex items-center gap-2 mb-2">
            <span class="font-semi" id="csv-filename"></span>
            <div class="toolbar-spacer"></div>
            <button class="btn btn-primary" onclick="importCSV()">
              <?= icon('check', 14) ?> Importar productos
            </button>
          </div>
          <div class="table-wrap" style="max-height:220px;overflow-y:auto">
            <table id="csv-table">
              <thead id="csv-head"></thead>
              <tbody id="csv-body"></tbody>
            </table>
          </div>
          <p id="csv-count" class="text-faint text-sm mt-1"></p>
        </div>
        <div id="import-result" class="hidden mt-3"></div>
        </div><!-- end panel-body -->
      </div>
    </div>

    <!-- ════════ TAB: USUARIOS ════════ -->
    <div id="tab-users" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar mb-3">
          <div>
            <div class="toolbar-section-title">Usuarios registrados</div>
            <div class="toolbar-section-sub">Gestiona roles y accesos</div>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>#</th><th>Nombre</th><th>Email</th><th>Rol</th>
              <th>Login</th><th>Verificado</th><th>Registro</th><th></th>
            </tr></thead>
            <tbody id="users-tbody">
              <tr><td colspan="8"><div class="empty-state">
                <div class="empty-icon"><?= icon('users', 20) ?></div>
                <div class="empty-label">Cargando usuarios…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ════════ TAB: PEDIDOS ════════ -->
    <div id="tab-orders" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar mb-3">
          <div>
            <div class="toolbar-section-title">Todos los pedidos</div>
          </div>
          <div class="toolbar-spacer"></div>
          <select id="orders-filter-status" style="max-width:200px" onchange="loadOrders()">
            <option value="">Todos los estados</option>
            <option value="pending">Pendiente</option>
            <option value="accepted">Aceptado</option>
            <option value="picked_up">Recogido</option>
            <option value="on_the_way">En camino</option>
            <option value="delivered">Entregado</option>
            <option value="cancelled">Cancelado</option>
          </select>
        </div>
        <!-- Mapa de seguimiento del pedido seleccionado -->
        <div id="order-map-wrap" style="display:none;margin-bottom:20px;padding:0 18px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
            <span style="font-size:12px;font-weight:700;color:var(--text-400);text-transform:uppercase;letter-spacing:.5px" id="order-map-label">Seguimiento del pedido</span>
            <button class="btn btn-ghost btn-xs" onclick="closeOrderMap()"><?= icon('x',12) ?> Cerrar mapa</button>
          </div>
          <div id="map-order" class="map-order"></div>
        </div>

        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>ID</th><th>Cliente</th><th>Total</th><th>Estado</th>
              <th>Pago</th><th>Repartidor</th><th>Fecha</th><th>Mapa</th><th>Acción</th>
            </tr></thead>
            <tbody id="orders-tbody">
              <tr><td colspan="9"><div class="empty-state">
                <div class="empty-icon"><?= icon('cart', 20) ?></div>
                <div class="empty-label">Cargando pedidos…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ════════ TAB: REPARTIDORES ════════ -->
    <div id="tab-delivery" class="tab-panel">
      <div class="tab-panel-inner">

        <!-- Header toolbar -->
        <div class="toolbar mb-2">
          <div>
            <div class="toolbar-section-title">Centro de Operaciones</div>
            <div class="toolbar-section-sub">Control total de repartidores, pedidos y asignaciones</div>
          </div>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-outline btn-sm" onclick="loadDeliveryTab()" style="margin-right:8px">
            <?= icon('refresh', 13) ?> Actualizar
          </button>
          <button class="btn btn-primary" onclick="openDeliveryModal()">
            <?= icon('plus', 14) ?> Nuevo repartidor
          </button>
        </div>

        <!-- Stat chips -->
        <div id="delivery-stats" style="display:flex;gap:10px;margin:0 18px 18px;flex-wrap:wrap;"></div>

        <!-- ── PEDIDOS SIN ASIGNAR ───────────────────────────────────────── -->
        <div class="section-title mb-2" style="padding:0 18px;display:flex;align-items:center;gap:10px">
          🚨 Pedidos sin repartidor
          <span id="ops-pending-count" class="badge badge-red" style="display:none"></span>
        </div>
        <div class="table-wrap mb-4">
          <table>
            <thead><tr>
              <th>#Pedido</th>
              <th>Cliente</th>
              <th>Dirección</th>
              <th>Sucursal</th>
              <th>Productos</th>
              <th>Total</th>
              <th>Hora</th>
              <th>Asignar a</th>
            </tr></thead>
            <tbody id="ops-pending-tbody">
              <tr><td colspan="8"><div class="empty-state" style="padding:20px 0">
                <div class="empty-label" style="color:#aaa">Cargando pedidos…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>

        <!-- ── CARGA ACTUAL POR REPARTIDOR ──────────────────────────────── -->
        <div class="section-title mb-2" style="padding:0 18px">🏍 Estado en vivo — repartidores</div>
        <div id="ops-workload-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;padding:0 18px 18px"></div>

        <hr style="border:none;border-top:1px solid #f0f0f0;margin:0 0 18px">

        <!-- ── GESTIÓN DE REPARTIDORES ──────────────────────────────────── -->
        <div class="section-title mb-2" style="padding:0 18px">⚙️ Gestión de repartidores</div>
        <div class="table-wrap mb-3">
          <table>
            <thead><tr>
              <th>Repartidor</th>
              <th>Teléfono</th>
              <th>Sucursal asignada</th>
              <th>Notificaciones</th>
              <th>Login</th>
              <th>Acciones</th>
            </tr></thead>
            <tbody id="delivery-tbody">
              <tr><td colspan="6"><div class="empty-state">
                <div class="empty-icon"><?= icon('truck', 20) ?></div>
                <div class="empty-label">Cargando…</div>
              </div></td></tr>
            </tbody>
          </table>
        </div>

        <!-- ── ASIGNAR ROLES ─────────────────────────────────────────────── -->
        <div class="section-title mb-2" style="padding:0 18px">👥 Todos los usuarios — asignar rol</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Usuario</th><th>Correo</th><th>Rol actual</th><th>Cambiar rol</th></tr></thead>
            <tbody id="all-users-role-tbody">
              <tr><td colspan="4"><div class="empty-state">Cargando…</div></td></tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>

    <!-- ════════ TAB: CONFIG ════════ -->
    <div id="tab-config" class="tab-panel">
      <div class="tab-panel-inner">
        <div class="toolbar">
          <div class="toolbar-section-title">Configuración del sistema</div>
        </div>
        <div class="config-grid">
          <div class="config-card">
            <div class="config-card-title"><?= icon('database', 14) ?> Base de datos</div>
            <div class="config-row"><span class="config-key">Host</span><code class="config-val"><?= DB_HOST ?></code></div>
            <div class="config-row"><span class="config-key">Base de datos</span><code class="config-val"><?= DB_NAME ?></code></div>
            <div class="config-row"><span class="config-key">Usuario</span><code class="config-val"><?= DB_USER ?></code></div>
            <div class="config-row">
              <span class="config-key">Estado</span>
              <span class="badge <?= $dbError ? 'badge-red' : 'badge-green' ?>">
                <?= $dbError ? 'Error de conexión' : 'Conectada' ?>
              </span>
            </div>
          </div>
          <div class="config-card">
            <div class="config-card-title"><?= icon('settings', 14) ?> URL de la API</div>
            <div class="config-row" style="flex-direction:column;align-items:flex-start;gap:4px">
              <span class="config-key">API Base URL</span>
              <code class="config-val" style="word-break:break-all">https://<?= $_SERVER['HTTP_HOST'] ?>/api</code>
            </div>
            <div class="config-row"><span class="config-key">GET /api/products</span></div>
            <div class="config-row"><span class="config-key">POST /api/auth/login</span></div>
            <div class="config-row"><span class="config-key">POST /api/auth/register</span></div>
          </div>
          <div class="config-card">
            <div class="config-card-title"><?= icon('info', 14) ?> Google OAuth</div>
            <div style="font-size:12.5px;color:var(--text-3);line-height:1.8">
              <p>1. <a href="https://console.cloud.google.com" target="_blank" style="color:var(--brand);font-weight:600">console.cloud.google.com</a></p>
              <p>2. APIs → Credentials → Authorized origins:</p>
              <code class="config-val">https://<?= $_SERVER['HTTP_HOST'] ?></code>
              <p>3. Redirect URIs:</p>
              <code class="config-val">https://<?= $_SERVER['HTTP_HOST'] ?>/auth</code>
            </div>
          </div>
          <div class="config-card">
            <div class="config-card-title"><?= icon('alert', 14) ?> Seguridad</div>
            <div class="notice notice-warning" style="font-size:12px;margin:0">
              Cambia <code>ADMIN_PASSWORD</code> en la sección CONFIG del archivo PHP.<br>
              Cambia <code>SECRET_KEY</code> en <code>../index.php</code>
            </div>
          </div>
        </div>
      </div>
    </div>

<?php endif ?>
  </div>
</div>
<?php endif ?>


<!-- ═══════════════ MODAL: NUEVO REPARTIDOR ═══════════ -->
<div id="delivery-modal" class="modal-overlay" onclick="if(event.target===this)closeDeliveryModal()">
  <div class="modal">
    <div class="modal-header">
      <h2 class="modal-title"><?= icon('truck', 16) ?> Nuevo repartidor</h2>
      <button class="modal-close" onclick="closeDeliveryModal()"><?= icon('x', 14) ?></button>
    </div>
    <div class="modal-body">
      <p id="delivery-modal-err" class="notice notice-error hidden" style="margin-bottom:14px"></p>
      <div class="field-row mb-2">
        <div class="field">
          <label class="field-label">Nombre completo *</label>
          <input id="dnew-name" placeholder="Juan Pérez" required>
        </div>
        <div class="field">
          <label class="field-label">Teléfono</label>
          <input id="dnew-phone" type="tel" placeholder="443 123 4567">
        </div>
      </div>
      <div class="field mb-2">
        <label class="field-label">Correo electrónico *</label>
        <input id="dnew-email" type="email" placeholder="juan@ejemplo.com" required>
        <div class="field-hint">Será su usuario para entrar a la app de repartidor</div>
      </div>
      <div class="field mb-2">
        <label class="field-label">Contraseña temporal *</label>
        <input id="dnew-pass" type="password" placeholder="Mínimo 6 caracteres" minlength="6" required>
        <div class="field-hint">El repartidor podrá cambiarla desde su perfil</div>
      </div>
      <div class="field mb-3">
        <label class="field-label">Sucursal asignada</label>
        <select id="dnew-store">
          <option value="">— Sin asignar por ahora —</option>
        </select>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-outline" onclick="closeDeliveryModal()">Cancelar</button>
        <button class="btn btn-primary" onclick="saveNewDelivery()"><?= icon('check', 14) ?> Crear repartidor</button>
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════ MODAL: PRODUCTO ════════════════════ -->
<div id="product-modal" class="modal-overlay">
  <div class="modal modal-lg">
    <div class="modal-header">
      <h2 id="modal-title" class="modal-title">Nuevo producto</h2>
      <button class="modal-close" onclick="closeModal()"><?= icon('x', 14) ?></button>
    </div>
    <div class="modal-body">
      <form id="product-form" onsubmit="saveProduct(event)">
        <input type="hidden" id="prod-id">
        <div class="field-row mb-2">
          <div class="field">
            <label class="field-label">Nombre <span>*</span></label>
            <input id="prod-name" required placeholder="JITOMATE">
          </div>
          <div class="field">
            <label class="field-label">SKU / Código <span>(opcional)</span></label>
            <input id="prod-sku" placeholder="TPN-001">
          </div>
        </div>
        <div class="field-row mb-2">
          <div class="field">
            <label class="field-label">Categoría <span>*</span></label>
            <select id="prod-cat" required>
              <option value="">Selecciona una categoría…</option>
              <?php foreach ($categories as $c): ?><option value="<?= $c ?>"><?= $c ?></option><?php endforeach ?>
            </select>
          </div>
          <div class="field">
            <label class="field-label">Unidad</label>
            <select id="prod-unit">
              <option value="KG">KG — Kilogramo</option>
              <option value="PZA">PZA — Pieza</option>
              <option value="L">L — Litro</option>
              <option value="G">G — Gramos</option>
              <option value="PAQUETE">PAQUETE</option>
              <option value="CAJA">CAJA</option>
            </select>
          </div>
        </div>
        <div class="field-row-4 mb-2">
          <div class="field">
            <label class="field-label">Precio <span>*</span></label>
            <input id="prod-price" type="number" step="0.01" required placeholder="7.90">
          </div>
          <div class="field">
            <label class="field-label">Stock <small style="color:#aaa">(-1 = ∞)</small></label>
            <input id="prod-stock" type="number" min="-1" placeholder="0">
          </div>
          <div class="field">
            <label class="field-label">Promo</label>
            <input id="prod-promo" placeholder="-10%">
          </div>
          <div class="field">
            <label class="field-label">Estado</label>
            <select id="prod-active">
              <option value="1">Activo</option>
              <option value="0">Inactivo</option>
            </select>
          </div>
        </div>

        <div class="field mb-2">
          <label class="field-label">Imagen principal</label>
          <div class="field-group">
            <input id="prod-img" placeholder="https://… o sube una imagen">
            <button type="button" class="btn btn-secondary btn-sm" onclick="triggerUpload('img-upload','prod-img','img-preview')">
              <?= icon('photo', 13) ?> Subir
            </button>
            <input type="file" id="img-upload" accept="image/*" class="hidden" onchange="uploadImageTo(this,'prod-img','img-preview')">
          </div>
          <img id="img-preview" class="img-preview mt-1">
        </div>

        <div class="field mb-2 extra-imgs-panel">
          <div class="flex items-center gap-2 mb-2">
            <label class="field-label" style="margin:0">Imágenes adicionales</label>
            <div class="toolbar-spacer"></div>
            <button type="button" class="btn btn-outline btn-xs" onclick="addExtraImg()">
              <?= icon('plus', 11) ?> Agregar
            </button>
          </div>
          <div id="extra-imgs-list" class="extra-imgs-list"></div>
          <div class="field-hint">Máximo 6 imágenes. Aparecen en la galería del producto.</div>
        </div>

        <div class="field mb-3">
          <div class="flex items-center gap-2 mb-1">
            <label class="field-label" style="margin:0">Descripción</label>
            <div class="toolbar-spacer"></div>
            <button type="button" id="ai-desc-btn" class="btn btn-outline btn-xs" onclick="generateDescription()" title="Genera la descripción automáticamente con IA usando el nombre del producto">
              ✨ Generar con IA
            </button>
          </div>
          <textarea id="prod-desc" rows="5" maxlength="400" placeholder="Descripción del producto para los clientes…" oninput="updateDescCount()"></textarea>
          <div class="field-hint" style="text-align:right"><span id="desc-count">0</span>/400 caracteres</div>
        </div>

        <div class="flex gap-2">
          <button type="button" class="btn btn-outline" style="flex:1" onclick="closeModal()">Cancelar</button>
          <button type="submit" id="save-btn" class="btn btn-primary" style="flex:1">Guardar producto</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- ═══════════════ MODAL: CATEGORÍA ════════════════════ -->
<div id="cat-modal" class="modal-overlay">
  <div class="modal">
    <div class="modal-header">
      <h2 id="cat-modal-title" class="modal-title">Nueva categoría</h2>
      <button class="modal-close" onclick="closeCatModal()"><?= icon('x', 14) ?></button>
    </div>
    <div class="modal-body">
      <form id="cat-form" onsubmit="saveCat(event)">
        <input type="hidden" id="cat-id">
        <div class="field-row mb-2">
          <div class="field">
            <label class="field-label">Nombre en BD <span>* (MAYÚSCULAS)</span></label>
            <input id="cat-name" required placeholder="VEGETALES">
          </div>
          <div class="field">
            <label class="field-label">Etiqueta en App <span>*</span></label>
            <input id="cat-label" required placeholder="Vegetales">
          </div>
          <div class="field">
            <label class="field-label">Ícono (Ionicons)</label>
            <input id="cat-icon" placeholder="leaf-outline">
          </div>
          <div class="field">
            <label class="field-label">Orden</label>
            <input id="cat-order" type="number" value="0" min="0">
          </div>
        </div>
        <div class="field mb-2">
          <label class="field-label">URL de imagen</label>
          <div class="field-group">
            <input id="cat-img" placeholder="https://…">
            <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('cat-img-upload').click()">
              <?= icon('photo', 13) ?>
            </button>
            <input type="file" id="cat-img-upload" accept="image/*" class="hidden" onchange="uploadCatImage(this)">
          </div>
          <img id="cat-img-preview" class="img-preview mt-1">
        </div>
        <div class="field mb-3">
          <label class="field-label">Estado</label>
          <select id="cat-active">
            <option value="1">Activo — visible en app</option>
            <option value="0">Inactivo — oculto</option>
          </select>
        </div>
        <div class="flex gap-2">
          <button type="button" class="btn btn-outline" style="flex:1" onclick="closeCatModal()">Cancelar</button>
          <button type="submit" id="cat-save-btn" class="btn btn-primary" style="flex:1">Guardar categoría</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- ═══════════════ MODAL: PROMOCIÓN ════════════════════ -->
<div id="promo-modal" class="modal-overlay">
  <div class="modal">
    <div class="modal-header">
      <h2 id="promo-modal-title" class="modal-title">Nueva promoción</h2>
      <button class="modal-close" onclick="closePromoModal()"><?= icon('x', 14) ?></button>
    </div>
    <div class="modal-body">
      <form id="promo-form" onsubmit="savePromo(event)">
        <input type="hidden" id="promo-id">
        <div class="field mb-2">
          <label class="field-label">Título <span>*</span></label>
          <input id="promo-title" required placeholder="Oferta de temporada">
        </div>
        <div class="field-row mb-2">
          <div class="field">
            <label class="field-label">Posición <span>*</span></label>
            <select id="promo-position">
              <option value="both">Ambos dispositivos (1200×400)</option>
              <option value="home_mobile">Solo móvil (800×300)</option>
              <option value="home_desktop">Solo escritorio (1200×380)</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label">Orden</label>
            <input id="promo-order" type="number" value="0" min="0">
          </div>
        </div>
        <div class="field mb-2">
          <label class="field-label">Imagen <span>*</span></label>
          <div class="field-group">
            <input id="promo-img" required placeholder="https://… o sube una imagen">
            <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('promo-img-upload').click()">
              <?= icon('photo', 13) ?> Subir
            </button>
            <input type="file" id="promo-img-upload" accept="image/*" class="hidden" onchange="uploadPromoImage(this)">
          </div>
          <img id="promo-img-preview" class="img-preview mt-1" style="height:90px;width:100%">
        </div>
        <div class="field mb-2">
          <label class="field-label">Enlace <span>(opcional)</span></label>
          <input id="promo-link" placeholder="https://…">
        </div>
        <div class="field mb-3">
          <label class="field-label">Estado</label>
          <select id="promo-active">
            <option value="1">Activo</option>
            <option value="0">Inactivo</option>
          </select>
        </div>
        <div class="flex gap-2">
          <button type="button" class="btn btn-outline" style="flex:1" onclick="closePromoModal()">Cancelar</button>
          <button type="submit" id="promo-save-btn" class="btn btn-primary" style="flex:1">Guardar promoción</button>
        </div>
      </form>
    </div>
  </div>
</div>


<!-- ═══════════════ SCRIPTS ═══════════════════════════════ -->
<script>
let csvData = [];
const PRODS = {}, PROMOS = {}, CATS = {}, STORES = {};

// ── Tabs ───────────────────────────────────────────────
function showTab(tab, btnEl) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  if (btnEl) btnEl.classList.add('active');
  if (tab === 'products')   loadProducts();
  if (tab === 'categories') loadCats();
  if (tab === 'promos')     loadPromos();
  if (tab === 'stores')     loadStores();
  if (tab === 'users')      loadUsers();
  if (tab === 'orders')     loadOrders();
  if (tab === 'delivery')   { loadDeliveryTab(); startOpsAutoRefresh(); }
  else                      stopOpsAutoRefresh();
}

let _opsRefreshTimer = null;
function startOpsAutoRefresh() {
  stopOpsAutoRefresh();
  _opsRefreshTimer = setInterval(() => {
    if (document.getElementById('tab-delivery')?.classList.contains('active')) loadDeliveryTab();
    else stopOpsAutoRefresh();
  }, 30000); // refresca cada 30s mientras el tab esté abierto
}
function stopOpsAutoRefresh() {
  if (_opsRefreshTimer) { clearInterval(_opsRefreshTimer); _opsRefreshTimer = null; }
}

// ── Stats ──────────────────────────────────────────────
async function loadStats() {
  const s = await api('stats');
  const cards = [
    { label: 'Productos activos', val: s.products,       color: 'green',
      icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/>' },
    { label: 'Sin stock',         val: s.no_stock,       color: 'red',
      icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>',
      onclick: "showTab('products',document.querySelector('.tab-btn'));document.getElementById('filter-stock').value='none';loadProducts();" },
    { label: 'Stock bajo (<10)',  val: s.low_stock,      color: 'orange',
      icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"/>',
      onclick: "showTab('products',document.querySelector('.tab-btn'));document.getElementById('filter-stock').value='low';loadProducts();" },
    { label: 'Usuarios',          val: s.users,          color: 'purple',
      icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/>' },
    { label: 'Pedidos totales',   val: s.orders,         color: 'blue',
      icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z"/>' },
    { label: 'Ingresos totales',  val: '$' + Number(s.revenue).toLocaleString('es-MX', {minimumFractionDigits:2}), color: 'green',
      icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>' },
  ];
  document.getElementById('stats-row').innerHTML = cards.map(c => `
    <div class="stat-card${c.onclick ? ' stat-card-link' : ''}" ${c.onclick ? `onclick="${c.onclick}" style="cursor:pointer"` : ''}>
      <div class="stat-icon ${c.color}">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">${c.icon}</svg>
      </div>
      <div>
        <div class="stat-value">${c.val}</div>
        <div class="stat-label">${c.label}</div>
      </div>
    </div>`).join('');
}

// ── Bulk selection ─────────────────────────────────────
let selectedProds = new Set();

function toggleSelectProd(id, checked) {
  checked ? selectedProds.add(id) : selectedProds.delete(id);
  updateBulkBar();
  document.getElementById(`prod-row-${id}`)?.classList.toggle('selected-row', checked);
}
function toggleSelectAllProds(el) {
  document.querySelectorAll('.prod-check').forEach(cb => {
    cb.checked = el.checked;
    toggleSelectProd(parseInt(cb.dataset.id), el.checked);
  });
}
function updateBulkBar() {
  const bar = document.getElementById('bulk-bar');
  const n = selectedProds.size;
  bar.classList.toggle('visible', n > 0);
  document.getElementById('bulk-count').textContent = `${n} seleccionado${n !== 1 ? 's' : ''}`;
}
function clearSelection() {
  selectedProds.clear();
  document.querySelectorAll('.prod-check, #check-all').forEach(cb => cb.checked = false);
  document.querySelectorAll('.selected-row').forEach(r => r.classList.remove('selected-row'));
  updateBulkBar();
}
async function bulkDeleteProds() {
  const ids = [...selectedProds];
  if (!ids.length) return;
  if (!confirm(`¿Eliminar ${ids.length} producto(s)? Esta acción no se puede deshacer.`)) return;
  try {
    const res = await api('bulk_delete_products', 'POST', { ids });
    if (res.error) { alert('Error: ' + res.error); return; }
    selectedProds.clear();
    loadProducts(); loadStats();
  } catch(e) {
    alert('Error al eliminar: ' + (e.message || 'Respuesta inesperada del servidor'));
  }
}

// ── Productos ──────────────────────────────────────────
async function loadProducts() {
  const q   = document.getElementById('search-q').value;
  const cat = document.getElementById('filter-cat').value;
  const sf  = document.getElementById('filter-stock').value;
  const res = await api(`list_products&q=${encodeURIComponent(q)}&cat=${encodeURIComponent(cat)}&stock_filter=${sf}`);
  const tbody = document.getElementById('products-tbody');
  if (!res.data?.length) {
    tbody.innerHTML = `<tr><td colspan="10"><div class="empty-state"><div class="empty-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/></svg></div><div class="empty-label">Sin productos que mostrar</div></div></td></tr>`;
    return;
  }
  res.data.forEach(p => PRODS[p.id] = p);
  tbody.innerHTML = res.data.map(p => {
    const stock = parseInt(p.stock ?? 0);
    const isUnlimited = stock === -1;
    const stockColor = isUnlimited ? 'green' : stock === 0 ? 'red' : stock < 10 ? 'yellow' : 'green';
    const stockLabel = isUnlimited ? '∞ Ilimitado' : stock === 0 ? 'Agotado' : stock < 10 ? `${stock} bajo` : stock;
    return `<tr id="prod-row-${p.id}">
      <td><input type="checkbox" class="row-check prod-check" data-id="${p.id}" onchange="toggleSelectProd(${p.id}, this.checked)" ${selectedProds.has(p.id) ? 'checked' : ''}></td>
      <td class="td-img"><img src="${p.image_url || 'https://placehold.co/40x40/f1f3f7/94a3b8?text=N/A'}" alt="${p.name}"></td>
      <td>
        <div class="td-name">${p.name}</div>
        ${p.sku ? `<div class="td-sub">${p.sku}</div>` : ''}
      </td>
      <td><span class="badge badge-gray">${p.category}</span></td>
      <td class="td-price">$${Number(p.price).toFixed(2)}</td>
      <td class="td-muted">${p.unit}</td>
      <td>
        <div class="stock-edit-wrap" id="se-${p.id}">
          <span class="badge badge-${stockColor}" id="se-badge-${p.id}">
            <span class="status-dot ${stockColor}"></span>${stockLabel}
          </span>
          <div class="stock-inline" id="se-form-${p.id}" style="display:none">
            <input type="number" min="-1" id="se-input-${p.id}" value="${isUnlimited ? -1 : stock}" style="width:64px;padding:3px 6px;border:1px solid var(--border);border-radius:6px;font-size:12px">
            <button class="btn btn-primary btn-xs" onclick="saveQuickStock(${p.id})">OK</button>
            <button class="btn btn-ghost btn-xs" style="font-size:11px" onclick="setUnlimitedStock(${p.id})" title="Stock ilimitado">∞</button>
            <button class="btn btn-ghost btn-xs" onclick="cancelQuickStock(${p.id})">✕</button>
          </div>
          <button class="btn btn-ghost btn-xs" id="se-edit-btn-${p.id}" onclick="openQuickStock(${p.id})" title="Editar stock" style="padding:2px 5px">✏️</button>
        </div>
      </td>
      <td>${p.promo ? `<span class="badge badge-red">${p.promo}</span>` : '<span class="text-faint">—</span>'}</td>
      <td>
        <label class="toggle">
          <input type="checkbox" ${p.active ? 'checked' : ''} onchange="toggleProduct(${p.id})">
          <span class="toggle-track"></span>
        </label>
      </td>
      <td>
        <div class="td-actions">
          <button class="btn btn-outline btn-xs" onclick="editProd(${p.id})">Editar</button>
          <button class="btn btn-danger btn-xs" onclick="deleteProd(${p.id})">Eliminar</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

function openQuickStock(id) {
  document.getElementById(`se-badge-${id}`).style.display = 'none';
  document.getElementById(`se-edit-btn-${id}`).style.display = 'none';
  document.getElementById(`se-form-${id}`).style.display = 'flex';
  document.getElementById(`se-input-${id}`).focus();
}
function cancelQuickStock(id) {
  document.getElementById(`se-badge-${id}`).style.display = '';
  document.getElementById(`se-edit-btn-${id}`).style.display = '';
  document.getElementById(`se-form-${id}`).style.display = 'none';
}
async function saveQuickStock(id) {
  const val = parseInt(document.getElementById(`se-input-${id}`).value);
  const newStock = isNaN(val) ? 0 : val;
  const res = await api('update_stock', 'POST', { id, stock: newStock });
  if (res.error) { alert(res.error); return; }
  loadProducts(); loadStats();
}
async function setUnlimitedStock(id) {
  const res = await api('update_stock', 'POST', { id, stock: -1 });
  if (res.error) { alert(res.error); return; }
  loadProducts(); loadStats();
}

async function toggleProduct(id) { await api('toggle_product', 'POST', { id }); loadProducts(); loadStats(); }
function editProd(id) { const p = PRODS[id]; if (p) editProduct(p); }

async function deleteProd(id) {
  const p = PRODS[id]; if (!p) return;
  if (!confirm(`¿Eliminar "${p.name}"?\n\nEsta acción no se puede deshacer.`)) return;
  await api('delete_product', 'POST', { id }); loadProducts(); loadStats();
}

function openModal(mode) {
  document.getElementById('modal-title').textContent = mode === 'create' ? 'Nuevo producto' : 'Editar producto';
  document.getElementById('product-form').reset();
  document.getElementById('prod-id').value = '';
  document.getElementById('prod-stock').value = '0';
  document.getElementById('img-preview').classList.remove('visible');
  document.getElementById('extra-imgs-list').innerHTML = '';
  document.getElementById('product-modal').classList.add('open');
  updateDescCount();
}

function editProduct(p) {
  openModal('edit');
  document.getElementById('prod-id').value    = p.id;
  document.getElementById('prod-sku').value   = p.sku || '';
  document.getElementById('prod-name').value  = p.name;
  document.getElementById('prod-cat').value   = p.category;
  document.getElementById('prod-price').value = p.price;
  document.getElementById('prod-unit').value  = p.unit;
  document.getElementById('prod-stock').value = p.stock ?? 0;
  document.getElementById('prod-promo').value = p.promo || '';
  document.getElementById('prod-img').value   = p.image_url || '';
  document.getElementById('prod-desc').value  = p.description || '';
  document.getElementById('prod-active').value= p.active;
  updateDescCount();
  if (p.image_url) { const img = document.getElementById('img-preview'); img.src = p.image_url; img.classList.add('visible'); }
  document.getElementById('extra-imgs-list').innerHTML = '';
  try { (p.extra_images ? JSON.parse(p.extra_images) : []).forEach(url => addExtraImg(url)); } catch(e) {}
}

function closeModal() { document.getElementById('product-modal').classList.remove('open'); }

// ── Extra imgs ─────────────────────────────────────────
let extraImgCount = 0;
function addExtraImg(url = '') {
  const list = document.getElementById('extra-imgs-list');
  if (list.children.length >= 6) { alert('Máximo 6 imágenes adicionales'); return; }
  const idx = extraImgCount++;
  const div = document.createElement('div');
  div.className = 'extra-img-row';
  div.innerHTML = `
    <input type="text" id="extra-inp-${idx}" class="extra-img-url" placeholder="https://…" value="${url}">
    <button type="button" onclick="triggerUpload('extra-upload-${idx}','extra-inp-${idx}','extra-prev-${idx}')" class="btn btn-outline btn-xs">Subir</button>
    <input type="file" id="extra-upload-${idx}" accept="image/*" class="hidden" onchange="uploadImageTo(this,'extra-inp-${idx}','extra-prev-${idx}','tpn_products')">
    <img id="extra-prev-${idx}" class="extra-img-thumb ${url ? 'visible' : ''}" src="${url}">
    <button type="button" onclick="this.parentElement.remove()" class="btn btn-danger btn-xs">✕</button>`;
  div.querySelector('.extra-img-url').addEventListener('input', function() {
    const prev = document.getElementById(`extra-prev-${idx}`);
    prev.src = this.value; prev.classList.toggle('visible', !!this.value);
  });
  list.appendChild(div);
}

function triggerUpload(fileId, textId, prevId) {
  const fi = document.getElementById(fileId);
  fi._textId = textId; fi._prevId = prevId; fi.click();
}

async function uploadImageTo(fileInput, textInputId, previewId, folder = 'tpn_products') {
  const file = fileInput.files[0]; if (!file) return;
  const CLOUD_NAME = 'dcutrbbyw';
  const UPLOAD_PRESET = 'tpn_preset';

  const fd = new FormData();
  fd.append('file', file);
  fd.append('upload_preset', UPLOAD_PRESET);
  fd.append('folder', folder);

  try {
    const res = await fetch(`https://api.cloudinary.com/v1_1/${CLOUD_NAME}/image/upload`, {
      method: 'POST',
      body: fd
    });
    const data = await res.json();
    if (data.secure_url) {
      document.getElementById(textInputId).value = data.secure_url;
      const prev = document.getElementById(previewId);
      if (prev) {
        prev.src = data.secure_url;
        prev.classList.add('visible');
      }
    } else {
      alert('Error de Cloudinary: ' + (data.error?.message || 'desconocido'));
    }
  } catch (err) {
    alert('Error de conexión con Cloudinary');
  }
}

function updateDescCount() {
  const len = document.getElementById('prod-desc').value.length;
  const el = document.getElementById('desc-count');
  if (!el) return;
  el.textContent = len;
  el.style.color = len >= 380 ? '#e53e3e' : len >= 320 ? '#dd6b20' : '#888';
}

async function generateDescription() {
  const name = document.getElementById('prod-name').value.trim();
  if (!name) { alert('Escribe primero el nombre del producto para generar la descripción.'); return; }
  const category = document.getElementById('prod-cat').value;
  const btn = document.getElementById('ai-desc-btn');
  btn.innerHTML = '⏳ Generando…'; btn.disabled = true;
  try {
    const res = await api('generate_description', 'POST', { name, category });
    if (res.error) { alert('Error IA: ' + res.error); }
    else { document.getElementById('prod-desc').value = res.description; updateDescCount(); }
  } catch(e) {
    alert('Error de conexión con la IA');
  }
  btn.innerHTML = '✨ Generar con IA'; btn.disabled = false;
}

async function saveProduct(e) {
  e.preventDefault();
  const id = document.getElementById('prod-id').value;
  const extraImgs = [...document.querySelectorAll('.extra-img-url')].map(i => i.value.trim()).filter(Boolean);
  const data = {
    id: id ? parseInt(id) : null,
    sku: document.getElementById('prod-sku').value.trim() || null,
    name: document.getElementById('prod-name').value,
    category: document.getElementById('prod-cat').value,
    price: document.getElementById('prod-price').value,
    unit: document.getElementById('prod-unit').value,
    stock: parseInt(document.getElementById('prod-stock').value) || 0,
    promo: document.getElementById('prod-promo').value || null,
    image_url: document.getElementById('prod-img').value,
    extra_images: extraImgs,
    description: document.getElementById('prod-desc').value || null,
    active: document.getElementById('prod-active').value,
  };
  const btn = document.getElementById('save-btn');
  btn.textContent = 'Guardando…'; btn.disabled = true;
  const res = await api(id ? 'update_product' : 'create_product', 'POST', data);
  btn.textContent = 'Guardar producto'; btn.disabled = false;
  if (res.error) { alert('Error: ' + res.error); return; }
  closeModal(); loadProducts(); loadStats();
}

// ── Categorías ─────────────────────────────────────────
async function loadCats() {
  const res = await api('list_cats');
  const tbody = document.getElementById('cats-tbody');
  if (!res.data?.length) { tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-label">Sin categorías</div></div></td></tr>`; return; }
  res.data.forEach(c => CATS[c.id] = c);
  tbody.innerHTML = res.data.map(c => `<tr>
    <td class="td-img">${c.img_url ? `<img src="${c.img_url}" alt="${c.label}">` : '<span class="text-faint td-muted">—</span>'}</td>
    <td><code class="font-mono">${c.name}</code></td>
    <td class="td-name">${c.label}</td>
    <td class="td-muted">${c.icon || '—'}</td>
    <td class="td-muted" style="text-align:center">${c.sort_order}</td>
    <td><label class="toggle"><input type="checkbox" ${c.active ? 'checked' : ''} onchange="toggleCat(${c.id})"><span class="toggle-track"></span></label></td>
    <td><div class="td-actions">
      <button class="btn btn-outline btn-xs" onclick="editCatById(${c.id})">Editar</button>
      <button class="btn btn-danger btn-xs" onclick="deleteCatById(${c.id})">Eliminar</button>
    </div></td>
  </tr>`).join('');
}

async function toggleCat(id) { await api('toggle_cat', 'POST', { id }); loadCats(); }

function editCatById(id) {
  const c = CATS[id]; if (!c) return;
  document.getElementById('cat-modal-title').textContent = 'Editar categoría';
  document.getElementById('cat-id').value    = c.id;
  document.getElementById('cat-name').value  = c.name;
  document.getElementById('cat-label').value = c.label;
  document.getElementById('cat-icon').value  = c.icon || '';
  document.getElementById('cat-order').value = c.sort_order;
  document.getElementById('cat-img').value   = c.img_url || '';
  document.getElementById('cat-active').value= c.active;
  const prev = document.getElementById('cat-img-preview');
  prev.src = c.img_url || ''; prev.classList.toggle('visible', !!c.img_url);
  document.getElementById('cat-modal').classList.add('open');
}

async function deleteCatById(id) {
  const c = CATS[id]; if (!c) return;
  if (!confirm(`¿Eliminar categoría "${c.label}"?`)) return;
  await api('del_cat', 'POST', { id }); loadCats();
}

function openCatModal() {
  document.getElementById('cat-modal-title').textContent = 'Nueva categoría';
  document.getElementById('cat-form').reset();
  document.getElementById('cat-id').value = '';
  document.getElementById('cat-img-preview').classList.remove('visible');
  document.getElementById('cat-modal').classList.add('open');
}
function closeCatModal() { document.getElementById('cat-modal').classList.remove('open'); }

async function saveCat(e) {
  e.preventDefault();
  const id = document.getElementById('cat-id').value;
  const data = {
    id: id ? parseInt(id) : null,
    name: document.getElementById('cat-name').value.toUpperCase().trim(),
    label: document.getElementById('cat-label').value,
    icon: document.getElementById('cat-icon').value || 'grid-outline',
    sort_order: parseInt(document.getElementById('cat-order').value) || 0,
    img_url: document.getElementById('cat-img').value,
    active: document.getElementById('cat-active').value,
  };
  const btn = document.getElementById('cat-save-btn');
  btn.textContent = 'Guardando…'; btn.disabled = true;
  const res = await api('save_cat', 'POST', data);
  btn.textContent = 'Guardar categoría'; btn.disabled = false;
  if (res.error) { alert('Error: ' + res.error); return; }
  closeCatModal(); loadCats();
}

async function uploadCatImage(input) {
  await uploadImageTo(input, 'cat-img', 'cat-img-preview', 'tpn_categories');
}

// ── Promos ─────────────────────────────────────────────
const posLabel = { home_mobile: 'Solo móvil', home_desktop: 'Solo escritorio', both: 'Ambos' };
const posBadge = { home_mobile: 'badge-blue', home_desktop: 'badge-purple', both: 'badge-green' };

async function loadPromos() {
  const res = await api('list_promos');
  const tbody = document.getElementById('promos-tbody');
  if (!res.data?.length) { tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-label">Sin promociones</div></div></td></tr>`; return; }
  res.data.forEach(p => PROMOS[p.id] = p);
  tbody.innerHTML = res.data.map(p => `<tr>
    <td class="td-img"><img src="${p.image_url}" alt="${p.title}" style="width:72px;height:40px;object-fit:cover;border-radius:6px"></td>
    <td class="td-name">${p.title}</td>
    <td><span class="badge ${posBadge[p.position]||'badge-gray'}">${posLabel[p.position] || p.position}</span></td>
    <td class="td-muted" style="text-align:center">${p.sort_order}</td>
    <td class="td-muted truncate">${p.link_url || '—'}</td>
    <td><label class="toggle"><input type="checkbox" ${p.active ? 'checked' : ''} onchange="togglePromo(${p.id})"><span class="toggle-track"></span></label></td>
    <td><div class="td-actions">
      <button class="btn btn-outline btn-xs" onclick="editPromoById(${p.id})">Editar</button>
      <button class="btn btn-danger btn-xs" onclick="deletePromoById(${p.id})">Eliminar</button>
    </div></td>
  </tr>`).join('');
}

async function togglePromo(id) { await api('toggle_promo', 'POST', { id }); loadPromos(); }

function editPromoById(id) {
  const p = PROMOS[id]; if (!p) return;
  openPromoModal('edit');
  document.getElementById('promo-id').value       = p.id;
  document.getElementById('promo-title').value    = p.title;
  document.getElementById('promo-position').value = p.position;
  document.getElementById('promo-order').value    = p.sort_order;
  document.getElementById('promo-img').value      = p.image_url;
  document.getElementById('promo-link').value     = p.link_url || '';
  document.getElementById('promo-active').value   = p.active;
  const prev = document.getElementById('promo-img-preview');
  if (p.image_url) { prev.src = p.image_url; prev.classList.add('visible'); }
}

async function deletePromoById(id) {
  const p = PROMOS[id]; if (!p) return;
  if (!confirm(`¿Eliminar "${p.title}"?`)) return;
  await api('delete_promo', 'POST', { id }); loadPromos();
}

function openPromoModal(mode) {
  document.getElementById('promo-modal-title').textContent = mode === 'create' ? 'Nueva promoción' : 'Editar promoción';
  document.getElementById('promo-form').reset();
  document.getElementById('promo-id').value = '';
  document.getElementById('promo-img-preview').classList.remove('visible');
  document.getElementById('promo-modal').classList.add('open');
}
function closePromoModal() { document.getElementById('promo-modal').classList.remove('open'); }

async function savePromo(e) {
  e.preventDefault();
  const id = document.getElementById('promo-id').value;
  const data = {
    id: id ? parseInt(id) : null,
    title: document.getElementById('promo-title').value,
    position: document.getElementById('promo-position').value,
    sort_order: parseInt(document.getElementById('promo-order').value) || 0,
    image_url: document.getElementById('promo-img').value,
    link_url: document.getElementById('promo-link').value || '',
    active: document.getElementById('promo-active').value,
  };
  const btn = document.getElementById('promo-save-btn');
  btn.textContent = 'Guardando…'; btn.disabled = true;
  const res = await api(id ? 'update_promo' : 'create_promo', 'POST', data);
  btn.textContent = 'Guardar promoción'; btn.disabled = false;
  if (res.error) { alert('Error: ' + res.error); return; }
  closePromoModal(); loadPromos();
}

async function uploadPromoImage(input) {
  await uploadImageTo(input, 'promo-img', 'promo-img-preview', 'tpn_promos');
}

// ── CSV ────────────────────────────────────────────────
function handleDrop(e) {
  e.preventDefault(); document.getElementById('drop-zone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) { document.getElementById('csv-file').files = e.dataTransfer.files; previewCSV({files:[file]}); }
}

function previewCSV(input) {
  const file = input.files ? input.files[0] : input; if (!file) return;
  document.getElementById('csv-filename').textContent = file.name;
  const reader = new FileReader();
  reader.onload = e => {
    const lines = e.target.result.split(/\r?\n/).filter(l => l.trim());
    csvData = lines.map(l => l.split(',').map(v => v.trim().replace(/^"|"$/g, '')));
    const head = csvData[0];
    document.getElementById('csv-head').innerHTML = '<tr>' + head.map(h => `<th>${h}</th>`).join('') + '</tr>';
    document.getElementById('csv-body').innerHTML = csvData.slice(1, 6).map(row =>
      '<tr>' + row.map(v => `<td style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:12px">${v}</td>`).join('') + '</tr>'
    ).join('');
    document.getElementById('csv-count').textContent = `${csvData.length - 1} productos detectados (mostrando primeras 5 filas)`;
    document.getElementById('csv-preview').classList.remove('hidden');
    document.getElementById('import-result').classList.add('hidden');
  };
  reader.readAsText(file);
}

async function importCSV() {
  const fileInput = document.getElementById('csv-file');
  if (!fileInput.files[0]) { alert('Selecciona un archivo CSV'); return; }
  const fd = new FormData(); fd.append('csv', fileInput.files[0]); fd.append('_csrf', CSRF_TOKEN);
  const res = await fetch('?action=import_csv', { method: 'POST', body: fd });
  const data = await res.json();
  const resultDiv = document.getElementById('import-result');
  resultDiv.classList.remove('hidden');
  resultDiv.innerHTML = data.ok
    ? `<div class="notice notice-success"><strong>Importación completada:</strong> ${data.inserted} productos importados / actualizados.${data.errors?.length ? `<br>${data.errors.length} errores: ${data.errors.slice(0,3).join(', ')}` : ''}</div>`
    : `<div class="notice notice-error">${data.error}</div>`;
  if (data.ok) { loadProducts(); loadStats(); }
}

// ── Usuarios ───────────────────────────────────────────
const ROLE_LABELS = { customer: 'Cliente', delivery: 'Repartidor', admin: 'Admin' };
const ROLE_COLORS = { customer: 'badge-gray', delivery: 'badge-orange', admin: 'badge-red' };

async function loadUsers() {
  const res = await api('list_users');
  const tbody = document.getElementById('users-tbody');
  if (!res.data?.length) { tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="empty-label">Sin usuarios</div></div></td></tr>`; return; }
  tbody.innerHTML = res.data.map(u => {
    const role = u.role || 'customer';
    return `<tr>
      <td class="td-mono">#${u.id}</td>
      <td class="td-name">${u.name}</td>
      <td class="td-muted">${u.email}</td>
      <td>
        <select class="role-select" onchange="setUserRole(${u.id},this.value,this)">
          <option value="customer"  ${role==='customer'  ? 'selected':''}>Cliente</option>
          <option value="delivery"  ${role==='delivery'  ? 'selected':''}>Repartidor</option>
          <option value="admin"     ${role==='admin'     ? 'selected':''}>Admin</option>
        </select>
      </td>
      <td>${u.is_google
        ? '<span class="badge badge-blue">Google</span>'
        : '<span class="badge badge-gray">Email</span>'}</td>
      <td>${u.email_verified ? '<span class="badge badge-green">Verificado</span>' : '<span class="badge badge-yellow">Pendiente</span>'}</td>
      <td class="td-muted">${u.created_at?.substring(0,10)}</td>
      <td><button class="btn btn-danger btn-xs" onclick="deleteUser(${u.id},'${u.email.replace(/'/g,"\\'")}')">Eliminar</button></td>
    </tr>`;
  }).join('');
}

async function deleteUser(id, email) {
  if (!confirm(`¿Eliminar usuario ${email}?`)) return;
  await api('delete_user', 'POST', { id }); loadUsers(); loadStats();
}

async function setUserRole(id, role, selectEl) {
  const r = await api('set_user_role', 'POST', { id, role });
  if (r.error) { alert('Error: ' + r.error); loadUsers(); return; }
  const td = selectEl?.closest('td');
  if (td) td.classList.add('flash-confirm');
  if (document.getElementById('tab-delivery')?.classList.contains('active')) loadDeliveryTab();
}

// ── Pedidos ────────────────────────────────────────────
const ORDER_STATUS = {
  pending:    { label: 'Pendiente',  color: 'badge-yellow' },
  accepted:   { label: 'Aceptado',   color: 'badge-admin'   },
  picked_up:  { label: 'Recogido',   color: 'badge-admin'   },
  on_the_way: { label: 'En camino',  color: 'badge-purple' },
  delivered:  { label: 'Entregado',  color: 'badge-green'  },
  cancelled:  { label: 'Cancelado',  color: 'badge-red'    },
};

// Orders cache for map lookups
const ORDERS_MAP_DATA = {};

async function loadOrders() {
  const status = document.getElementById('orders-filter-status')?.value || '';
  const res = await api('list_orders' + (status ? `&status=${status}` : ''));
  const tbody = document.getElementById('orders-tbody');
  if (res.error) { tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="empty-label">${res.error}</div></div></td></tr>`; return; }
  if (!res.data?.length) { tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="empty-label">No hay pedidos</div></div></td></tr>`; return; }
  res.data.forEach(o => { ORDERS_MAP_DATA[o.id] = o; });
  tbody.innerHTML = res.data.map(o => {
    const st = ORDER_STATUS[o.status] || { label: o.status, color: 'badge-gray' };
    const hasCoords = o.dest_lat || o.store_lat;
    return `<tr>
      <td class="td-mono">#${o.id}</td>
      <td>
        <div class="td-name">${o.customer_name || o.user_name || `#${o.user_id}`}</div>
        <div class="td-sub">${o.customer_email || o.user_email || ''}</div>
      </td>
      <td class="td-price">$${parseFloat(o.total||0).toFixed(2)}</td>
      <td><span class="badge ${st.color}">${st.label}</span></td>
      <td>${o.payment_status === 'paid'
        ? '<span class="badge badge-green">Pagado</span>'
        : '<span class="badge badge-yellow">Pendiente</span>'}</td>
      <td class="td-muted">${o.delivery_name || '—'}</td>
      <td class="td-muted">${o.created_at?.substring(0,16) || ''}</td>
      <td>
        <button class="btn btn-outline btn-xs" onclick="openOrderMap(ORDERS_MAP_DATA[${o.id}])" title="Ver ruta en mapa">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z"/></svg>
          Mapa
        </button>
      </td>
      <td>
        <select class="status-select" onchange="updateOrderStatus(${o.id},this.value,this)">
          <option value="">Cambiar estado…</option>
          <option value="pending">Pendiente</option>
          <option value="accepted">Aceptado</option>
          <option value="picked_up">Recogido</option>
          <option value="on_the_way">En camino</option>
          <option value="delivered">Entregado</option>
          <option value="cancelled">Cancelado</option>
        </select>
      </td>
    </tr>`;
  }).join('');
}

async function updateOrderStatus(id, status, selectEl) {
  if (!status) return;
  const r = await api('update_order_status', 'POST', { id, status });
  if (r.error) { alert('Error: ' + r.error); return; }
  const td = selectEl?.closest('td'); if (td) td.classList.add('flash-confirm');
  loadOrders();
}

// ── Repartidores / Centro de Operaciones ───────────────
async function loadDeliveryTab() {
  const [usersRes, storesRes, pendingRes, workloadRes] = await Promise.all([
    api('list_users'),
    api('list_stores'),
    api('ops_pending_orders'),
    api('ops_driver_workload'),
  ]);
  if (!usersRes.data) return;
  const stores   = storesRes.data   || [];
  const delivery = usersRes.data.filter(u => u.role === 'delivery');
  const pending  = pendingRes.data  || [];
  const drivers  = workloadRes.data || [];
  const sinSucursal = delivery.filter(u => !u.store_id).length;

  // ── Stat chips ──────────────────────────────────────
  document.getElementById('delivery-stats').innerHTML = [
    ['badge-blue',   '🏍', `${delivery.length} repartidores`],
    [sinSucursal > 0 ? 'badge-yellow' : 'badge-green', '🏪', sinSucursal > 0 ? `${sinSucursal} sin sucursal` : 'Todos asignados'],
    [pending.length > 0 ? 'badge-red' : 'badge-green', '📦', pending.length > 0 ? `${pending.length} sin asignar` : 'Sin pendientes'],
    ['badge-gray', '👥', `${usersRes.data.length} usuarios totales`],
  ].map(([cls,ico,label]) => `<span class="badge ${cls}" style="padding:7px 14px;font-size:12px">${ico} ${label}</span>`).join('');

  // ── Poblar select del modal ──────────────────────────
  const sel = document.getElementById('dnew-store');
  if (sel.options.length <= 1) {
    stores.forEach(s => { const o=document.createElement('option'); o.value=s.id; o.textContent=`${s.name} — ${s.city}`; sel.appendChild(o); });
  }

  // ── Pedidos sin asignar ──────────────────────────────
  const driverOpts = `<option value="">— Elegir repartidor —</option>` +
    drivers.map(d => `<option value="${d.id}">${d.name} (${d.active_orders} activos)${d.store_name ? ' · '+d.store_name : ''}</option>`).join('');
  const pendBadge = document.getElementById('ops-pending-count');
  if (pending.length > 0) {
    pendBadge.textContent = pending.length;
    pendBadge.style.display = '';
  } else {
    pendBadge.style.display = 'none';
  }
  const ptbody = document.getElementById('ops-pending-tbody');
  ptbody.innerHTML = pending.length
    ? pending.map(o => {
        const ago = (() => {
          const diff = Math.floor((Date.now() - new Date(o.created_at).getTime()) / 60000);
          return diff < 1 ? 'ahora' : `hace ${diff} min`;
        })();
        return `<tr>
          <td class="td-mono" style="font-weight:800">#${String(o.id).padStart(6,'0')}</td>
          <td class="td-name">${o.customer_name || 'Cliente'}</td>
          <td class="td-muted" style="max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${o.address||''}">${o.address || '—'}</td>
          <td>${o.store_name ? `<span class="badge badge-blue">${o.store_name}</span>` : '<span class="td-muted">—</span>'}</td>
          <td class="td-muted">${o.items_count} prod.</td>
          <td class="td-price">$${parseFloat(o.total||0).toFixed(2)}</td>
          <td class="td-muted" style="white-space:nowrap">${ago}</td>
          <td>
            <div style="display:flex;gap:6px;align-items:center">
              <select id="assign-sel-${o.id}" style="font-size:12px;padding:4px 8px;border:1px solid #e0e0e0;border-radius:6px;min-width:160px">
                ${driverOpts}
              </select>
              <button class="btn btn-primary btn-xs" onclick="manualAssign(${o.id})">Asignar</button>
            </div>
          </td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="8"><div class="empty-state" style="padding:20px 0">
        <div class="empty-label" style="color:#22c55e">✅ Todos los pedidos tienen repartidor asignado</div>
      </div></td></tr>`;

  // ── Carga actual por repartidor ──────────────────────
  const grid = document.getElementById('ops-workload-grid');
  const STATUS_LABELS = { accepted:'Aceptado', preparing:'Preparando', picked_up:'Recogido', on_the_way:'En camino' };
  const STATUS_COLORS = { accepted:'#e6192e', preparing:'#f59e0b', picked_up:'#e6192e', on_the_way:'#e6192e' };
  grid.innerHTML = drivers.length
    ? drivers.map(d => {
        const pushIcon = d.has_push ? '🔔' : '⚠️';
        const pushTitle = d.has_push ? 'Notificaciones activas' : 'Sin token push — debe abrir la app';
        const orderCards = d.orders.length
          ? d.orders.map(o => `
              <div style="background:#f8faff;border:1px solid #e0e9ff;border-radius:8px;padding:8px 10px;margin-bottom:6px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span style="font-weight:800;font-size:12px">#${String(o.id).padStart(6,'0')}</span>
                  <span style="font-size:11px;font-weight:700;color:${STATUS_COLORS[o.status]||'#666'}">${STATUS_LABELS[o.status]||o.status}</span>
                </div>
                <div style="font-size:11px;color:#888;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${o.address||'—'}</div>
              </div>`).join('')
          : `<div style="font-size:12px;color:#aaa;text-align:center;padding:10px 0">Sin pedidos activos</div>`;
        return `
          <div style="background:#fff;border:1px solid #f0f0f0;border-radius:14px;padding:14px;box-shadow:0 1px 6px rgba(0,0,0,0.04)">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
              <div style="width:38px;height:38px;border-radius:50%;background:#e6192e;display:flex;align-items:center;justify-content:center;color:#fff;font-size:16px;font-weight:900;flex-shrink:0">
                ${d.name[0]?.toUpperCase() || '?'}
              </div>
              <div style="flex:1;min-width:0">
                <div style="font-weight:800;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${d.name}</div>
                <div style="font-size:11px;color:#888">${d.store_name || 'Sin sucursal'}</div>
              </div>
              <span title="${pushTitle}" style="font-size:16px;cursor:default">${pushIcon}</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
              <span style="background:${d.active_orders > 0 ? '#eff6ff' : '#f0fdf4'};color:${d.active_orders > 0 ? '#3b82f6' : '#22c55e'};font-size:11px;font-weight:800;padding:2px 8px;border-radius:20px">
                ${d.active_orders} pedido${d.active_orders !== 1 ? 's' : ''} activo${d.active_orders !== 1 ? 's' : ''}
              </span>
            </div>
            ${orderCards}
          </div>`;
      }).join('')
    : `<div style="padding:20px;color:#aaa;font-size:13px">No hay repartidores registrados.</div>`;

  // ── Tabla gestión de repartidores ────────────────────
  const storeOpts = `<option value="">Sin asignar</option>` + stores.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
  const dTbody = document.getElementById('delivery-tbody');
  dTbody.innerHTML = delivery.length
    ? delivery.map(u => {
        const opts = storeOpts.replace(`value="${u.store_id}"`, `value="${u.store_id}" selected`);
        const pushBadge = u.has_push_token
          ? `<span class="badge badge-green">🔔 Activo</span>`
          : `<span class="badge badge-yellow" title="El repartidor debe abrir la app">⚠️ Sin token</span>`;
        return `<tr>
          <td><div class="td-name">${u.name}</div><div class="td-sub">${u.email}</div></td>
          <td class="td-muted">${u.phone || '—'}</td>
          <td>
            <select class="role-select" style="width:auto;min-width:160px" onchange="assignStore(${u.id},this.value,this)">
              ${opts}
            </select>
          </td>
          <td>${pushBadge}</td>
          <td>${u.is_google ? '<span class="badge badge-blue">Google</span>' : '<span class="badge badge-gray">Email</span>'}</td>
          <td class="td-actions">
            <button class="btn btn-outline btn-xs" onclick="setUserRoleAndRefreshDelivery(${u.id},'customer')">Quitar rol</button>
          </td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="6"><div class="empty-state">
        <div class="empty-icon"><?= icon('truck', 22) ?></div>
        <div class="empty-label">No hay repartidores aún</div>
        <div class="empty-sub">Usa "Nuevo repartidor" o asigna el rol desde la tabla de abajo.</div>
      </div></td></tr>`;

  // ── Tabla todos los usuarios ─────────────────────────
  const allTbody = document.getElementById('all-users-role-tbody');
  allTbody.innerHTML = usersRes.data.map(u => {
    const role = u.role || 'customer';
    return `<tr>
      <td class="td-name">${u.name}</td>
      <td class="td-muted">${u.email}</td>
      <td><span class="badge ${ROLE_COLORS[role] || 'badge-gray'}">${ROLE_LABELS[role] || role}</span></td>
      <td><div class="td-actions">
        ${role!=='customer'  ? `<button class="btn btn-secondary btn-xs" onclick="setUserRoleAndRefreshDelivery(${u.id},'customer')">Cliente</button>` : ''}
        ${role!=='delivery'  ? `<button class="btn btn-outline btn-xs" onclick="setUserRoleAndRefreshDelivery(${u.id},'delivery')">🏍 Repartidor</button>` : ''}
        ${role!=='admin'     ? `<button class="btn btn-danger btn-xs" onclick="setUserRoleAndRefreshDelivery(${u.id},'admin')">Admin</button>` : '<span class="text-faint td-muted">—</span>'}
      </div></td>
    </tr>`;
  }).join('');
}

async function manualAssign(orderId) {
  const sel = document.getElementById(`assign-sel-${orderId}`);
  const driverId = sel?.value;
  if (!driverId) { alert('Elige un repartidor primero.'); return; }
  const r = await api('manual_assign_driver', 'POST', { order_id: orderId, driver_id: parseInt(driverId) });
  if (r.error) { alert('Error: ' + r.error); return; }
  const row = sel.closest('tr');
  if (row) { row.style.background='#f0fdf4'; setTimeout(()=>{ row.style.background=''; loadDeliveryTab(); },800); }
  else loadDeliveryTab();
}

async function assignStore(userId, storeId, selectEl) {
  const r = await api('set_user_store', 'POST', { id: userId, store_id: storeId || null });
  if (r.error) { alert('Error: ' + r.error); return; }
  const td = selectEl?.closest('td'); if (td) td.classList.add('flash-confirm');
}

async function setUserRoleAndRefreshDelivery(id, role) {
  const r = await api('set_user_role', 'POST', { id, role });
  if (r.error) { alert('Error: ' + r.error); return; }
  loadDeliveryTab(); loadUsers();
}

function openDeliveryModal() {
  document.getElementById('delivery-modal').classList.add('open');
  document.getElementById('dnew-name').focus();
  document.getElementById('delivery-modal-err').classList.add('hidden');
}
function closeDeliveryModal() {
  document.getElementById('delivery-modal').classList.remove('open');
  ['dnew-name','dnew-phone','dnew-email','dnew-pass'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('dnew-store').selectedIndex = 0;
}
async function saveNewDelivery() {
  const name    = document.getElementById('dnew-name').value.trim();
  const email   = document.getElementById('dnew-email').value.trim();
  const pass    = document.getElementById('dnew-pass').value;
  const phone   = document.getElementById('dnew-phone').value.trim();
  const storeId = document.getElementById('dnew-store').value;
  const errEl   = document.getElementById('delivery-modal-err');
  if (!name || !email || !pass) { errEl.textContent = 'Nombre, correo y contraseña son obligatorios.'; errEl.classList.remove('hidden'); return; }
  const r = await api('create_delivery', 'POST', { name, email, password: pass, phone, store_id: storeId || null });
  if (r.error) { errEl.textContent = r.error; errEl.classList.remove('hidden'); return; }
  closeDeliveryModal();
  loadDeliveryTab(); loadStats();
}

// ── Sucursales ─────────────────────────────────────────
async function loadStores() {
  const r = await api('list_stores');
  if (r.error) {
    document.getElementById('storesTbody').innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-label">${r.error}</div></div></td></tr>`;
    return;
  }
  const rows = r.data || [];
  rows.forEach(s => STORES[s.id] = s);
  // Render overview map after table is ready
  initMapStores(rows);
  document.getElementById('storesTbody').innerHTML = rows.length
    ? rows.map(s => `<tr>
        <td class="td-name">${s.name}</td>
        <td class="td-muted">${s.city || '—'}</td>
        <td class="td-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.address}</td>
        <td class="td-mono">${parseFloat(s.lat).toFixed(5)}, ${parseFloat(s.lng).toFixed(5)}</td>
        <td class="td-muted">${s.phone || '—'}</td>
        <td>
          <button onclick="toggleStore(${s.id})" class="badge ${s.active==1 ? 'badge-green' : 'badge-gray'}" style="cursor:pointer;border:none">
            <span class="status-dot ${s.active==1?'green':'gray'}"></span>
            ${s.active==1 ? 'Activa' : 'Inactiva'}
          </button>
        </td>
        <td><div class="td-actions">
          <button class="btn btn-outline btn-xs" onclick="openStoreForm(${s.id})">Editar</button>
          <button class="btn btn-danger btn-xs" onclick="deleteStore(${s.id},'${s.name.replace(/'/g,"\\'")}')">Eliminar</button>
        </div></td>
      </tr>`).join('')
    : `<tr><td colspan="7"><div class="empty-state"><div class="empty-label">No hay sucursales registradas.</div></div></td></tr>`;
}

function openStoreForm(id) {
  const form = document.getElementById('storeForm');
  form.classList.add('open');
  if (id && STORES[id]) {
    const s = STORES[id];
    document.getElementById('storeFormTitle').textContent = 'Editar sucursal';
    document.getElementById('storeId').value    = id;
    document.getElementById('storeName').value  = s.name;
    document.getElementById('storeCity').value  = s.city || '';
    document.getElementById('storeAddress').value = s.address;
    document.getElementById('storeLat').value   = s.lat;
    document.getElementById('storeLng').value   = s.lng;
    document.getElementById('storePhone').value = s.phone || '';
    document.getElementById('storeSortOrder').value = s.sort_order || 0;
  } else {
    document.getElementById('storeFormTitle').textContent = 'Nueva sucursal';
    document.getElementById('storeId').value = '';
    ['storeName','storeCity','storeAddress','storeLat','storeLng','storePhone'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('storeSortOrder').value = 0;
  }
  document.getElementById('storeFormError').classList.add('hidden');
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  // Init map picker after a short delay so the form is fully visible
  setTimeout(initMapPicker, 300);
}

async function saveStore() {
  const errEl = document.getElementById('storeFormError');
  const payload = {
    id: document.getElementById('storeId').value || 0,
    name: document.getElementById('storeName').value.trim(),
    city: document.getElementById('storeCity').value.trim(),
    address: document.getElementById('storeAddress').value.trim(),
    lat: document.getElementById('storeLat').value,
    lng: document.getElementById('storeLng').value,
    phone: document.getElementById('storePhone').value.trim(),
    sort_order: document.getElementById('storeSortOrder').value,
    active: 1,
  };
  if (!payload.name || !payload.address || !payload.lat || !payload.lng) {
    errEl.textContent = 'Nombre, dirección, latitud y longitud son requeridos.';
    errEl.classList.remove('hidden'); return;
  }
  const r = await api('save_store', 'POST', payload);
  if (r.error) { errEl.textContent = r.error; errEl.classList.remove('hidden'); return; }
  document.getElementById('storeForm').classList.remove('open'); loadStores();
}

async function deleteStore(id, name) {
  if (!confirm(`¿Eliminar la sucursal "${name}"?`)) return;
  await api('delete_store', 'POST', { id }); loadStores();
}

async function toggleStore(id) { await api('toggle_store', 'POST', { id }); loadStores(); }

// ── CSRF token (injected from PHP session) ─────────────
const CSRF_TOKEN = '<?= htmlspecialchars($_SESSION['csrf'] ?? '', ENT_QUOTES) ?>';

// ── API helper ─────────────────────────────────────────
async function api(action, method = 'GET', body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.headers['X-CSRF-Token'] = CSRF_TOKEN;
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`?action=${action}`, opts);
  return res.json();
}

// ── Init ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadProducts();

  ['product-modal','cat-modal','promo-modal'].forEach(id => {
    document.getElementById(id)?.addEventListener('click', e => {
      if (e.target === e.currentTarget) {
        if (id === 'product-modal') closeModal();
        if (id === 'cat-modal')     closeCatModal();
        if (id === 'promo-modal')   closePromoModal();
      }
    });
  });

  document.getElementById('prod-img')?.addEventListener('input', function() {
    const img = document.getElementById('img-preview');
    img.src = this.value; img.classList.toggle('visible', !!this.value);
  });
  document.getElementById('cat-img')?.addEventListener('input', function() {
    const prev = document.getElementById('cat-img-preview');
    prev.src = this.value; prev.classList.toggle('visible', !!this.value);
  });
  document.getElementById('promo-img')?.addEventListener('input', function() {
    const prev = document.getElementById('promo-img-preview');
    prev.src = this.value; prev.classList.toggle('visible', !!this.value);
  });
});

// ═══════════════════════════════════════════════════════
// MAPBOX — Delivery route map + store picker
// ═══════════════════════════════════════════════════════
mapboxgl.accessToken = '';
let mapPicker = null, pickerMarker = null;
let mapStores = null, storeMarkers = [];
let mapOrder = null, orderMapMarkers = [];

// ── a) initMapPicker — coordinate picker inside store form ──────────────
function initMapPicker() {
  const latEl = document.getElementById('storeLat');
  const lngEl = document.getElementById('storeLng');
  const existLat = parseFloat(latEl?.value);
  const existLng = parseFloat(lngEl?.value);
  const hasCoords = !isNaN(existLat) && !isNaN(existLng);
  const center = hasCoords ? [existLng, existLat] : [-101.1950, 19.7061];

  // Destroy previous instance if tab was opened before
  if (mapPicker) { mapPicker.remove(); mapPicker = null; pickerMarker = null; }

  const el = document.getElementById('map-picker');
  if (!el) return;

  mapPicker = new mapboxgl.Map({
    container: 'map-picker',
    style: 'mapbox://styles/mapbox/streets-v12',
    center: center,
    zoom: hasCoords ? 15 : 13,
  });
  mapPicker.addControl(new mapboxgl.NavigationControl(), 'top-right');

  pickerMarker = new mapboxgl.Marker({ draggable: true, color: '#e6192e' })
    .setLngLat(center)
    .addTo(mapPicker);

  if (hasCoords) {
    latEl.value = existLat.toFixed(7);
    lngEl.value = existLng.toFixed(7);
  }

  const updateInputs = (lngLat) => {
    if (latEl) latEl.value = lngLat.lat.toFixed(7);
    if (lngEl) lngEl.value = lngLat.lng.toFixed(7);
  };

  mapPicker.on('click', (e) => {
    pickerMarker.setLngLat(e.lngLat);
    updateInputs(e.lngLat);
  });

  pickerMarker.on('dragend', () => {
    updateInputs(pickerMarker.getLngLat());
  });
}

// ── b) movePickerPin — sync map pin when lat/lng inputs change ──────────
function movePickerPin() {
  if (!mapPicker || !pickerMarker) return;
  const lat = parseFloat(document.getElementById('storeLat')?.value);
  const lng = parseFloat(document.getElementById('storeLng')?.value);
  if (isNaN(lat) || isNaN(lng)) return;
  pickerMarker.setLngLat([lng, lat]);
  mapPicker.flyTo({ center: [lng, lat], zoom: 15 });
}

// ── c) initMapStores — overview map of all active stores ────────────────
function initMapStores(stores) {
  const el = document.getElementById('map-stores');
  if (!el) return;

  if (mapStores) { mapStores.remove(); mapStores = null; }
  storeMarkers.forEach(m => m.remove());
  storeMarkers = [];

  mapStores = new mapboxgl.Map({
    container: 'map-stores',
    style: 'mapbox://styles/mapbox/streets-v12',
    center: [-101.1950, 19.7061],
    zoom: 7,
  });
  mapStores.addControl(new mapboxgl.NavigationControl(), 'top-right');

  const activeStores = (stores || []).filter(s => s.active == 1);
  if (!activeStores.length) return;

  const bounds = new mapboxgl.LngLatBounds();
  const colors = ['#e6192e','#3b82f6','#22c55e','#f59e0b','#8b5cf6','#ec4899'];

  activeStores.forEach((s, i) => {
    const lat = parseFloat(s.lat), lng = parseFloat(s.lng);
    if (isNaN(lat) || isNaN(lng)) return;
    const marker = new mapboxgl.Marker({ color: colors[i % colors.length] })
      .setLngLat([lng, lat])
      .setPopup(new mapboxgl.Popup({ offset: 25 }).setHTML(
        `<strong>${s.name}</strong><small>${s.city || ''}</small>`
      ))
      .addTo(mapStores);
    storeMarkers.push(marker);
    bounds.extend([lng, lat]);
  });

  if (!bounds.isEmpty()) {
    mapStores.fitBounds(bounds, { padding: 60, maxZoom: 14 });
  }
}

// ── d) openOrderMap — delivery route map for a specific order ───────────
function openOrderMap(order) {
  const wrap = document.getElementById('order-map-wrap');
  const label = document.getElementById('order-map-label');
  if (!wrap) return;
  wrap.style.display = 'block';
  if (label) label.textContent = `Seguimiento — Pedido #${String(order.id || '').padStart(6,'0')}`;

  // Clear previous markers
  orderMapMarkers.forEach(m => m.remove());
  orderMapMarkers = [];

  // Remove previous route layer/source if they exist
  if (mapOrder) {
    if (mapOrder.getLayer('route-line'))   mapOrder.removeLayer('route-line');
    if (mapOrder.getSource('route'))       mapOrder.removeSource('route');
  }

  if (!mapOrder) {
    mapOrder = new mapboxgl.Map({
      container: 'map-order',
      style: 'mapbox://styles/mapbox/streets-v12',
      center: [-101.1950, 19.7061],
      zoom: 12,
    });
    mapOrder.addControl(new mapboxgl.NavigationControl(), 'top-right');
  }

  const bounds = new mapboxgl.LngLatBounds();
  const coords = [];

  // Store marker (blue)
  const storeLat = parseFloat(order.store_lat), storeLng = parseFloat(order.store_lng);
  if (!isNaN(storeLat) && !isNaN(storeLng)) {
    const m = new mapboxgl.Marker({ color: '#3b82f6' })
      .setLngLat([storeLng, storeLat])
      .setPopup(new mapboxgl.Popup({ offset: 25 }).setHTML(`<strong>Tienda: ${order.store_name || '—'}</strong>`))
      .addTo(mapOrder);
    orderMapMarkers.push(m);
    bounds.extend([storeLng, storeLat]);
    coords.push([storeLng, storeLat]);
  }

  // Delivery driver marker (green)
  const dLat = parseFloat(order.delivery_lat), dLng = parseFloat(order.delivery_lng);
  if (!isNaN(dLat) && !isNaN(dLng)) {
    const m = new mapboxgl.Marker({ color: '#22c55e' })
      .setLngLat([dLng, dLat])
      .setPopup(new mapboxgl.Popup({ offset: 25 }).setHTML(`<strong>Repartidor: ${order.delivery_name || '—'}</strong>`))
      .addTo(mapOrder);
    orderMapMarkers.push(m);
    bounds.extend([dLng, dLat]);
    coords.push([dLng, dLat]);
  }

  // Destination marker (red)
  const destLat = parseFloat(order.dest_lat), destLng = parseFloat(order.dest_lng);
  if (!isNaN(destLat) && !isNaN(destLng)) {
    const m = new mapboxgl.Marker({ color: '#e6192e' })
      .setLngLat([destLng, destLat])
      .setPopup(new mapboxgl.Popup({ offset: 25 }).setHTML(`<strong>Destino:</strong><small>${order.address || '—'}</small>`))
      .addTo(mapOrder);
    orderMapMarkers.push(m);
    bounds.extend([destLng, destLat]);
    coords.push([destLng, destLat]);
  }

  // Fit bounds to all markers
  if (!bounds.isEmpty()) {
    mapOrder.fitBounds(bounds, { padding: 60, maxZoom: 15 });
  }

  // Draw dashed LineString route: store → delivery (if exists) → destination
  if (coords.length >= 2) {
    mapOrder.once('idle', () => {
      if (mapOrder.getLayer('route-line')) mapOrder.removeLayer('route-line');
      if (mapOrder.getSource('route'))     mapOrder.removeSource('route');
      mapOrder.addSource('route', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'LineString', coordinates: coords } }
      });
      mapOrder.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        paint: {
          'line-color': '#e6192e',
          'line-width': 3,
          'line-dasharray': [2, 2],
          'line-opacity': 0.75,
        }
      });
    });
  }
}

// ── e) closeOrderMap ────────────────────────────────────────────────────
function closeOrderMap() {
  const wrap = document.getElementById('order-map-wrap');
  if (wrap) wrap.style.display = 'none';
  if (mapOrder) {
    if (mapOrder.getLayer('route-line')) mapOrder.removeLayer('route-line');
    if (mapOrder.getSource('route'))     mapOrder.removeSource('route');
  }
  orderMapMarkers.forEach(m => m.remove());
  orderMapMarkers = [];
}
</script>
</body>
</html>