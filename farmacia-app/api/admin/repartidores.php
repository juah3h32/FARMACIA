<?php
// ─── CONFIGURACIÓN BD ────────────────────────────────────────────────────────
$DB_HOST = 'localhost';
$DB_NAME = 'u992666585_TPN';
$DB_USER = 'u992666585_TPN_USER';
$DB_PASS = 'JUANPA9912a';

// Hash bcrypt de 'tpnadmin2024' — cámbialo con: password_hash('tupass', PASSWORD_BCRYPT)
define('ADMIN_PASS_HASH', '$2y$11$wVZ7ZNTY2c/ej.4OWZCiC.lbCuimCFvBRoBgPuELbD1hEnlS0VNp.');

session_start();

// ─── LOGIN SIMPLE ────────────────────────────────────────────────────────────
if (isset($_POST['pass'])) {
    if (password_verify($_POST['pass'], ADMIN_PASS_HASH)) {
        session_regenerate_id(true);
        $_SESSION['tpn_admin'] = true;
    } else {
        $loginError = 'Contraseña incorrecta';
    }
}
if (isset($_GET['logout'])) {
    session_destroy();
    header('Location: repartidores.php');
    exit;
}
if (!isset($_SESSION['tpn_admin'])) {
    showLogin(isset($loginError) ? $loginError : null);
    exit;
}

// ─── CONEXIÓN BD ─────────────────────────────────────────────────────────────
try {
    $pdo = new PDO("mysql:host=$DB_HOST;dbname=$DB_NAME;charset=utf8mb4", $DB_USER, $DB_PASS);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
} catch (Exception $e) {
    die('<p style="color:red;padding:20px">Error BD: ' . $e->getMessage() . '</p>');
}

// ─── ACCIONES POST ────────────────────────────────────────────────────────────
$msg = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action'])) {

    if ($_POST['action'] === 'create_repartidor') {
        $name    = trim($_POST['name'] ?? '');
        $email   = trim($_POST['email'] ?? '');
        $pass    = $_POST['password'] ?? '';
        $phone   = trim($_POST['phone'] ?? '') ?: null;
        $storeId = !empty($_POST['store_id']) ? (int)$_POST['store_id'] : null;

        if (!$name || !$email || !$pass) {
            $msg = 'error:Nombre, correo y contraseña son obligatorios';
        } else {
            $exists = $pdo->prepare("SELECT id FROM users WHERE email=? LIMIT 1");
            $exists->execute([$email]);
            if ($exists->fetch()) {
                $msg = 'error:Ya existe un usuario con ese correo';
            } else {
                $hash = password_hash($pass, PASSWORD_BCRYPT);
                $pdo->prepare(
                    "INSERT INTO users (name, email, password_hash, phone, role, store_id, email_verified, active)
                     VALUES (?, ?, ?, ?, 'delivery', ?, 1, 1)"
                )->execute([$name, $email, $hash, $phone, $storeId]);
                $msg = 'success:Repartidor "' . htmlspecialchars($name) . '" creado correctamente';
            }
        }
    }

    if ($_POST['action'] === 'update_user') {
        $uid     = (int)$_POST['user_id'];
        $role    = in_array($_POST['role'], ['customer','delivery','admin']) ? $_POST['role'] : 'customer';
        $storeId = !empty($_POST['store_id']) ? (int)$_POST['store_id'] : null;
        $phone   = trim($_POST['phone'] ?? '') ?: null;
        $pdo->prepare("UPDATE users SET role=?, store_id=?, phone=? WHERE id=?")
            ->execute([$role, $storeId, $phone, $uid]);
        $msg = 'success:Usuario actualizado correctamente';
    }

    if ($_POST['action'] === 'delete_user') {
        $uid = (int)$_POST['user_id'];
        $pdo->prepare("DELETE FROM users WHERE id=? AND role='delivery'")->execute([$uid]);
        $msg = 'success:Repartidor eliminado';
    }

    if ($_POST['action'] === 'bulk_assign') {
        $storeId = !empty($_POST['store_id']) ? (int)$_POST['store_id'] : null;
        $uids    = isset($_POST['uids']) ? array_map('intval', $_POST['uids']) : [];
        foreach ($uids as $uid) {
            $pdo->prepare("UPDATE users SET role='delivery', store_id=? WHERE id=?")
                ->execute([$storeId, $uid]);
        }
        $msg = 'success:' . count($uids) . ' repartidores asignados';
    }
}

// ─── DATOS ────────────────────────────────────────────────────────────────────
$stores = $pdo->query("SELECT id, name, address FROM stores WHERE active=1 ORDER BY name")->fetchAll();
$users  = $pdo->query(
    "SELECT u.id, u.name, u.email, u.photo_url,
            COALESCE(u.role,'customer') AS role,
            u.store_id, s.name AS store_name,
            COALESCE(u.phone,'') AS phone, u.created_at
     FROM users u
     LEFT JOIN stores s ON s.id = u.store_id
     ORDER BY u.role DESC, u.name ASC"
)->fetchAll();

$msgType = '';
$msgText = '';
if ($msg) {
    [$msgType, $msgText] = explode(':', $msg, 2);
}

// ─── HTML ─────────────────────────────────────────────────────────────────────
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Repartidores — TPN Admin</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f4f7;color:#222;}
  a{color:#e6192e;text-decoration:none;}

  /* Nav */
  .nav{background:#fff;padding:0 24px;height:58px;display:flex;align-items:center;justify-content:space-between;
       box-shadow:0 1px 6px rgba(0,0,0,.08);position:sticky;top:0;z-index:100;}
  .nav-brand{display:flex;align-items:center;gap:10px;}
  .nav-logo{width:36px;height:36px;background:#e6192e;border-radius:10px;display:flex;align-items:center;justify-content:center;
            color:#fff;font-weight:900;font-size:14px;}
  .nav-title{font-size:16px;font-weight:800;color:#111;}
  .nav-sub{font-size:11px;color:#aaa;}
  .btn-logout{background:#fff1f2;color:#e6192e;border:1px solid #fecdd3;padding:7px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;}

  /* Layout */
  .container{max-width:1100px;margin:0 auto;padding:24px 16px;}

  /* Alert */
  .alert{padding:12px 16px;border-radius:10px;margin-bottom:20px;font-size:13px;font-weight:600;}
  .alert-success{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;}
  .alert-error{background:#fff1f2;color:#e6192e;border:1px solid #fecdd3;}

  /* Stats */
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;}
  .stat{background:#fff;border-radius:14px;padding:16px 20px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.05);}
  .stat-num{font-size:28px;font-weight:900;line-height:1;}
  .stat-label{font-size:11px;color:#aaa;font-weight:600;margin-top:4px;text-transform:uppercase;letter-spacing:.4px;}

  /* Card */
  .card{background:#fff;border-radius:16px;box-shadow:0 1px 6px rgba(0,0,0,.06);margin-bottom:24px;overflow:hidden;}
  .card-header{padding:16px 20px;border-bottom:1px solid #f0f0f0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;}
  .card-title{font-size:14px;font-weight:800;color:#111;}

  /* Bulk assign */
  .bulk-form{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
  .bulk-form select,.bulk-form button{height:36px;border-radius:8px;font-size:13px;font-weight:600;}
  .bulk-form select{border:1px solid #e5e7eb;padding:0 10px;min-width:180px;}
  .bulk-form button{background:#e6192e;color:#fff;border:none;padding:0 16px;cursor:pointer;}

  /* Filtros */
  .filters{display:flex;gap:8px;padding:14px 20px;border-bottom:1px solid #f5f5f5;flex-wrap:wrap;}
  .filter-btn{padding:6px 14px;border-radius:20px;font-size:12px;font-weight:700;border:1.5px solid #eee;background:#fafafa;color:#666;cursor:pointer;text-decoration:none;}
  .filter-btn.active{background:#e6192e;border-color:#e6192e;color:#fff;}

  /* Tabla */
  table{width:100%;border-collapse:collapse;}
  thead th{padding:10px 16px;font-size:11px;font-weight:800;color:#aaa;text-transform:uppercase;letter-spacing:.5px;text-align:left;background:#fafafa;}
  tbody tr{border-top:1px solid #f5f5f5;transition:background .15s;}
  tbody tr:hover{background:#fafef9;}
  td{padding:12px 16px;font-size:13px;vertical-align:middle;}

  /* Avatar */
  .avatar{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:15px;flex-shrink:0;}
  .user-cell{display:flex;align-items:center;gap:10px;}
  .user-name{font-weight:700;color:#111;}
  .user-email{font-size:11px;color:#aaa;margin-top:1px;}

  /* Badges */
  .badge{display:inline-flex;align-items:center;gap:4px;padding:4px 9px;border-radius:8px;font-size:11px;font-weight:700;}
  .badge-delivery{background:#fff1f2;color:#e6192e;}
  .badge-admin{background:#fff1f2;color:#e6192e;}
  .badge-customer{background:#f3f4f6;color:#6b7280;}
  .badge-store{background:#fff0f1;color:#e6192e;font-size:10px;}

  /* Edit form inline */
  .edit-row{background:#f9fafb!important;}
  .edit-form{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
  .edit-form select{height:34px;border-radius:8px;border:1px solid #e5e7eb;padding:0 10px;font-size:13px;}
  .btn-save{background:#e6192e;color:#fff;border:none;padding:7px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;}
  .btn-edit{background:#f3f4f6;color:#374151;border:none;padding:6px 12px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;}
  .btn-cancel{background:#f3f4f6;color:#374151;border:none;padding:7px 12px;border-radius:8px;font-size:12px;cursor:pointer;}

  .checkbox-col{width:36px;}
  input[type=checkbox]{width:16px;height:16px;cursor:pointer;accent-color:#e6192e;}

  /* Botón nuevo */
  .btn-primary{background:#e6192e;color:#fff;border:none;padding:9px 18px;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:6px;}
  .btn-danger{background:#fff1f2;color:#e6192e;border:1px solid #fecdd3;padding:6px 12px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;}

  /* Modal overlay */
  .modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:200;align-items:center;justify-content:center;}
  .modal-overlay.open{display:flex;}
  .modal{background:#fff;border-radius:20px;width:100%;max-width:460px;margin:16px;box-shadow:0 20px 60px rgba(0,0,0,.2);overflow:hidden;}
  .modal-head{padding:20px 24px 0;display:flex;align-items:center;justify-content:space-between;}
  .modal-head h2{font-size:16px;font-weight:900;color:#111;}
  .btn-close{background:none;border:none;font-size:22px;color:#aaa;cursor:pointer;line-height:1;}
  .modal-body{padding:20px 24px 24px;}
  .field{margin-bottom:14px;}
  .field label{font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:5px;}
  .field input,.field select{width:100%;padding:10px 13px;border:1.5px solid #e5e7eb;border-radius:10px;font-size:14px;outline:none;}
  .field input:focus,.field select:focus{border-color:#e6192e;}
  .field .hint{font-size:11px;color:#aaa;margin-top:3px;}
  .field-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
  .modal-footer{display:flex;gap:8px;justify-content:flex-end;padding-top:8px;}

  @media(max-width:640px){
    .stats{grid-template-columns:repeat(2,1fr);}
    table thead{display:none;}
    tbody tr{display:block;padding:12px;border:1px solid #f0f0f0;border-radius:12px;margin-bottom:8px;}
    td{display:block;padding:4px 0;}
    td::before{content:attr(data-label);font-size:10px;color:#aaa;font-weight:700;display:block;}
    .field-row{grid-template-columns:1fr;}
  }
</style>
</head>
<body>

<!-- Nav -->
<nav class="nav">
  <div class="nav-brand">
    <div class="nav-logo">TPN</div>
    <div>
      <div class="nav-title">Panel Admin</div>
      <div class="nav-sub">Gestión de repartidores</div>
    </div>
  </div>
  <a href="?logout=1" class="btn-logout">Cerrar sesión</a>
</nav>

<div class="container">

<?php if ($msgText): ?>
  <div class="alert alert-<?= $msgType ?>"><?= htmlspecialchars($msgText) ?></div>
<?php endif; ?>

<!-- Stats -->
<?php
$total      = count($users);
$delivery   = count(array_filter($users, fn($u) => $u['role']==='delivery'));
$admins     = count(array_filter($users, fn($u) => $u['role']==='admin'));
$customers  = $total - $delivery - $admins;
$sinAsignar = count(array_filter($users, fn($u) => $u['role']==='delivery' && !$u['store_id']));
?>
<div class="stats">
  <div class="stat"><div class="stat-num"><?= $total ?></div><div class="stat-label">Usuarios</div></div>
  <div class="stat"><div class="stat-num" style="color:#3b82f6"><?= $delivery ?></div><div class="stat-label">Repartidores</div></div>
  <div class="stat"><div class="stat-num" style="color:#22c55e"><?= $customers ?></div><div class="stat-label">Clientes</div></div>
  <div class="stat"><div class="stat-num" style="color:<?= $sinAsignar>0?'#f59e0b':'#22c55e' ?>"><?= $sinAsignar ?></div><div class="stat-label">Sin sucursal</div></div>
</div>

<!-- Tabla usuarios -->
<div class="card">
  <div class="card-header">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      <span class="card-title">USUARIOS (<?= $total ?>)</span>
      <button class="btn-primary" onclick="openModal()">＋ Nuevo repartidor</button>
    </div>
    <!-- Asignación masiva -->
    <form method="POST" class="bulk-form" id="bulkForm">
      <input type="hidden" name="action" value="bulk_assign">
      <select name="store_id" required>
        <option value="">Asignar sucursal a seleccionados...</option>
        <?php foreach ($stores as $st): ?>
          <option value="<?= $st['id'] ?>"><?= htmlspecialchars($st['name']) ?></option>
        <?php endforeach; ?>
      </select>
      <button type="submit" onclick="return collectChecked()">Asignar repartidores</button>
    </form>
  </div>

  <!-- Filtros -->
  <?php $f = $_GET['filter'] ?? 'all'; ?>
  <div class="filters">
    <a href="?filter=all"      class="filter-btn <?= $f==='all'?'active':'' ?>">Todos (<?= $total ?>)</a>
    <a href="?filter=delivery" class="filter-btn <?= $f==='delivery'?'active':'' ?>">Repartidores (<?= $delivery ?>)</a>
    <a href="?filter=customer" class="filter-btn <?= $f==='customer'?'active':'' ?>">Clientes (<?= $customers ?>)</a>
    <a href="?filter=admin"    class="filter-btn <?= $f==='admin'?'active':'' ?>">Admins (<?= $admins ?>)</a>
    <a href="?filter=unassigned" class="filter-btn <?= $f==='unassigned'?'active':'' ?>">Sin sucursal (<?= $sinAsignar ?>)</a>
  </div>

  <table>
    <thead>
      <tr>
        <th class="checkbox-col"><input type="checkbox" id="selectAll" onclick="toggleAll(this)"></th>
        <th>Usuario</th>
        <th>Rol</th>
        <th>Sucursal asignada</th>
        <th>Registro</th>
        <th>Editar</th>
      </tr>
    </thead>
    <tbody>
    <?php foreach ($users as $u):
        if ($f === 'delivery'   && $u['role'] !== 'delivery')  continue;
        if ($f === 'customer'   && $u['role'] !== 'customer')  continue;
        if ($f === 'admin'      && $u['role'] !== 'admin')     continue;
        if ($f === 'unassigned' && !($u['role']==='delivery' && !$u['store_id'])) continue;

        $colors = ['delivery'=>['#eff6ff','#3b82f6'],'admin'=>['#fff1f2','#e6192e'],'customer'=>['#f3f4f6','#6b7280']];
        [$bg, $fg] = $colors[$u['role']] ?? $colors['customer'];
        $initial = strtoupper(substr($u['name'],0,1));
    ?>
      <tr id="row-<?= $u['id'] ?>">
        <td><input type="checkbox" class="user-check" value="<?= $u['id'] ?>"></td>
        <td data-label="Usuario">
          <div class="user-cell">
            <div class="avatar" style="background:<?= $bg ?>;color:<?= $fg ?>"><?= $initial ?></div>
            <div>
              <div class="user-name"><?= htmlspecialchars($u['name']) ?></div>
              <div class="user-email"><?= htmlspecialchars($u['email']) ?></div>
            </div>
          </div>
        </td>
        <td data-label="Rol">
          <span class="badge badge-<?= $u['role'] ?>"><?= $u['role'] === 'delivery' ? '🏍 Repartidor' : ($u['role'] === 'admin' ? '🛡 Admin' : '👤 Cliente') ?></span>
        </td>
        <td data-label="Sucursal">
          <?php if ($u['store_name']): ?>
            <span class="badge badge-store">🏪 <?= htmlspecialchars($u['store_name']) ?></span>
          <?php else: ?>
            <span style="color:#ccc;font-size:12px;">— Sin asignar</span>
          <?php endif; ?>
        </td>
        <td data-label="Registro" style="color:#aaa;font-size:12px;">
          <?= date('d/m/Y', strtotime($u['created_at'])) ?>
        </td>
        <td>
          <div style="display:flex;gap:6px;">
            <button class="btn-edit" onclick="showEdit(<?= $u['id'] ?>, '<?= $u['role'] ?>', '<?= $u['store_id'] ?>')">Editar</button>
            <?php if ($u['role'] === 'delivery'): ?>
            <form method="POST" style="display:inline" onsubmit="return confirm('¿Eliminar a <?= htmlspecialchars(addslashes($u['name'])) ?>?')">
              <input type="hidden" name="action" value="delete_user">
              <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
              <button type="submit" class="btn-danger">✕</button>
            </form>
            <?php endif; ?>
          </div>
        </td>
      </tr>
      <!-- Fila edit inline -->
      <tr id="edit-<?= $u['id'] ?>" style="display:none;" class="edit-row">
        <td colspan="6">
          <form method="POST" class="edit-form">
            <input type="hidden" name="action" value="update_user">
            <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
            <strong style="font-size:13px;color:#555"><?= htmlspecialchars($u['name']) ?></strong>
            <select name="role" id="role-<?= $u['id'] ?>" onchange="toggleStore(<?= $u['id'] ?>)">
              <option value="customer" <?= $u['role']==='customer'?'selected':'' ?>>👤 Cliente</option>
              <option value="delivery" <?= $u['role']==='delivery'?'selected':'' ?>>🏍 Repartidor</option>
              <option value="admin"    <?= $u['role']==='admin'?'selected':'' ?>>🛡 Admin</option>
            </select>
            <select name="store_id" id="store-<?= $u['id'] ?>">
              <option value="">Sin sucursal</option>
              <?php foreach ($stores as $st): ?>
                <option value="<?= $st['id'] ?>" <?= $u['store_id']==$st['id']?'selected':'' ?>>
                  <?= htmlspecialchars($st['name']) ?>
                </option>
              <?php endforeach; ?>
            </select>
            <input type="text" name="phone" placeholder="Teléfono" value="<?= htmlspecialchars($u['phone']) ?>" style="width:130px;height:34px;border-radius:8px;border:1px solid #e5e7eb;padding:0 10px;font-size:13px;">
            <button type="submit" class="btn-save">Guardar</button>
            <button type="button" class="btn-cancel" onclick="hideEdit(<?= $u['id'] ?>)">Cancelar</button>
          </form>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table>
</div>

</div><!-- /container -->

<!-- ══ MODAL NUEVO REPARTIDOR ══════════════════════════════════════════════ -->
<div class="modal-overlay" id="modalOverlay" onclick="closeOnOverlay(event)">
  <div class="modal">
    <div class="modal-head">
      <h2>🏍 Nuevo repartidor</h2>
      <button class="btn-close" onclick="closeModal()">×</button>
    </div>
    <div class="modal-body">
      <form method="POST" id="createForm">
        <input type="hidden" name="action" value="create_repartidor">
        <div class="field-row">
          <div class="field">
            <label>Nombre completo *</label>
            <input type="text" name="name" placeholder="Juan Pérez" required>
          </div>
          <div class="field">
            <label>Teléfono</label>
            <input type="tel" name="phone" placeholder="443 123 4567">
          </div>
        </div>
        <div class="field">
          <label>Correo electrónico *</label>
          <input type="email" name="email" placeholder="juan@ejemplo.com" required>
          <div class="hint">Este será su usuario para entrar a la app</div>
        </div>
        <div class="field">
          <label>Contraseña temporal *</label>
          <input type="password" name="password" placeholder="Mínimo 6 caracteres" minlength="6" required>
          <div class="hint">El repartidor podrá cambiarla desde la app</div>
        </div>
        <div class="field">
          <label>Sucursal asignada</label>
          <select name="store_id">
            <option value="">— Sin asignar por ahora —</option>
            <?php foreach ($stores as $st): ?>
              <option value="<?= $st['id'] ?>"><?= htmlspecialchars($st['name']) ?> — <?= htmlspecialchars($st['address']) ?></option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn-cancel" onclick="closeModal()">Cancelar</button>
          <button type="submit" class="btn-primary">Crear repartidor</button>
        </div>
      </form>
    </div>
  </div>
</div>

<script>
function showEdit(id, role, storeId) {
  document.getElementById('edit-'+id).style.display = 'table-row';
  document.getElementById('row-'+id).style.background = '#f9fafb';
  toggleStore(id);
}
function hideEdit(id) {
  document.getElementById('edit-'+id).style.display = 'none';
  document.getElementById('row-'+id).style.background = '';
}
function toggleStore(id) {
  var role  = document.getElementById('role-'+id).value;
  var store = document.getElementById('store-'+id);
  store.disabled = (role !== 'delivery');
  store.style.opacity = role === 'delivery' ? '1' : '0.4';
}
function toggleAll(cb) {
  document.querySelectorAll('.user-check').forEach(function(c){ c.checked = cb.checked; });
}
function collectChecked() {
  var checks = document.querySelectorAll('.user-check:checked');
  if (!checks.length) { alert('Selecciona al menos un usuario'); return false; }
  var form = document.getElementById('bulkForm');
  document.querySelectorAll('.hidden-uid').forEach(function(e){ e.remove(); });
  checks.forEach(function(c) {
    var inp = document.createElement('input');
    inp.type = 'hidden'; inp.name = 'uids[]'; inp.value = c.value;
    inp.className = 'hidden-uid';
    form.appendChild(inp);
  });
  return true;
}
// Modal
function openModal() {
  document.getElementById('modalOverlay').classList.add('open');
  document.querySelector('#createForm input[name=name]').focus();
}
function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
}
function closeOnOverlay(e) {
  if (e.target === document.getElementById('modalOverlay')) closeModal();
}
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeModal(); });
</script>
</body>
</html>
<?php

// ─── PANTALLA LOGIN ───────────────────────────────────────────────────────────
function showLogin($error = null) { ?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin TPN — Acceso</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f4f4f7;display:flex;align-items:center;justify-content:center;min-height:100vh;}
  .card{background:#fff;padding:40px 32px;border-radius:20px;width:340px;box-shadow:0 8px 32px rgba(0,0,0,.10);}
  .logo{width:56px;height:56px;background:#e6192e;border-radius:16px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:22px;margin:0 auto 20px;}
  h1{text-align:center;font-size:20px;font-weight:900;margin-bottom:6px;}
  p{text-align:center;color:#aaa;font-size:13px;margin-bottom:24px;}
  label{font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:6px;}
  input{width:100%;padding:11px 14px;border:1.5px solid #e5e7eb;border-radius:10px;font-size:14px;outline:none;}
  input:focus{border-color:#e6192e;}
  button{width:100%;margin-top:16px;padding:13px;background:#e6192e;color:#fff;border:none;border-radius:12px;font-size:14px;font-weight:800;cursor:pointer;}
  .error{background:#fff1f2;color:#e6192e;padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:16px;text-align:center;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">TPN</div>
  <h1>Panel Admin</h1>
  <p>Gestión de repartidores y sucursales</p>
  <?php if ($error): ?>
    <div class="error"><?= htmlspecialchars($error) ?></div>
  <?php endif; ?>
  <form method="POST">
    <label>Contraseña de acceso</label>
    <input type="password" name="pass" placeholder="••••••••" autofocus>
    <button type="submit">Entrar</button>
  </form>
</div>
</body>
</html>
<?php }
