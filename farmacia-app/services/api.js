// ─────────────────────────────────────────────────────────────────────────────
// API - Farmacia Eben-Ezer
// Base URL: variable de entorno EXPO_PUBLIC_API_URL en Vercel, o dominio prod.
// ─────────────────────────────────────────────────────────────────────────────
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ?? "https://farmacia-ebenezer.com";

const DEFAULT_TIMEOUT = 30000;

async function apiFetch(endpoint, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);

  const url = `${API_BASE_URL}/${endpoint.replace(/^\//, "")}`;

  const hasBody =
    options.method && !["GET", "HEAD"].includes(options.method.toUpperCase());
  const defaultHeaders = hasBody ? { "Content-Type": "application/json" } : {};

  try {
    const res = await fetch(url, {
      ...options,
      headers: { ...defaultHeaders, ...options.headers },
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!res.ok && res.status !== 201) {
      const data = await res.json().catch(() => ({}));
      return {
        success: false,
        message: data.detail || data.message || `Error HTTP ${res.status}`,
      };
    }

    const data = await res.json();
    if (Array.isArray(data)) return { success: true, data };
    return data;
  } catch (e) {
    clearTimeout(timer);
    if (e.name === "AbortError") throw new Error("Tiempo de espera agotado (30s)");
    throw e;
  }
}

// ─── PRODUCTOS PÚBLICOS (sin auth) ───────────────────────────────────────────
export async function getProduct(id) {
  return apiFetch(`api/public/productos/${id}`);
}

export async function getProducts(categoryFilter = null, busqueda = null) {
  const params = new URLSearchParams();
  if (categoryFilter) params.set("categoria_id", categoryFilter);
  if (busqueda) params.set("busqueda", busqueda);
  const query = params.toString() ? `?${params}` : "";
  return apiFetch(`api/public/productos${query}`);
}

// ─── CATEGORÍAS PÚBLICAS ─────────────────────────────────────────────────────
export async function getCategories() {
  return apiFetch("api/public/categorias");
}

// ─── PROMOCIONES (sin backend aún) ───────────────────────────────────────────
export async function getPromos(_position = null) {
  return { success: true, data: [] };
}

// ─── AUTH CLIENTE APP ─────────────────────────────────────────────────────────
export async function loginWithEmail(email, password) {
  return apiFetch("api/app/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function registerUser(name, email, password) {
  return apiFetch("api/app/auth/register", {
    method: "POST",
    body: JSON.stringify({ nombre: name, email, password }),
  });
}

export async function loginWithGoogle({ googleId, name, email, photo }) {
  return apiFetch("api/app/auth/google", {
    method: "POST",
    body: JSON.stringify({ google_id: googleId, name, email, photo }),
  });
}

export async function getMyProfile(token) {
  return apiFetch("api/app/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function forgotPassword(_email) {
  return { success: false, message: "Contacta a la farmacia para recuperar tu contraseña." };
}

export async function resetPassword(_token, _newPassword) {
  return { success: false, message: "Funcionalidad no disponible aún." };
}

// ─── PEDIDOS CLIENTE ──────────────────────────────────────────────────────────
export async function getUserOrders(token) {
  return apiFetch("api/app/pedidos", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createOrder(orderData, token) {
  return apiFetch("api/app/pedidos", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(orderData),
  });
}

export async function getOrderTracking(orderId, token) {
  return apiFetch(`api/app/pedidos/${orderId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function cancelOrder(_orderId, _token) {
  return { success: false, message: "Llama a la farmacia para cancelar tu pedido." };
}

export async function rateOrder(_orderId, _rating, _comment, _token) {
  return { success: true };
}

// ─── SUCURSAL ────────────────────────────────────────────────────────────────
export async function getStores() {
  return {
    success: true,
    data: [
      {
        id: 1,
        name: "Farmacia Eben-Ezer",
        address: "ESFUERZO #47 COL. 13 DE ABRIL",
        phone: "000-000-0000",
        lat: null,
        lng: null,
      },
    ],
  };
}

// ─── ENTREGA / REPARTIDOR ─────────────────────────────────────────────────────
export async function getAvailableOrders(token) {
  return apiFetch("api/app/delivery/available", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getMyDeliveryOrders(token) {
  return apiFetch("api/app/delivery/my-orders", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getDeliveryHistory(token) {
  return apiFetch("api/app/delivery/history", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updateDeliveryLocation(lat, lng, token) {
  return apiFetch("api/app/delivery/location", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ lat, lng }),
  });
}

export async function acceptDeliveryOrder(orderId, token) {
  return apiFetch(`api/app/delivery/orders/${orderId}/accept`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updateDeliveryStatus(orderId, status, token) {
  return apiFetch(`api/app/delivery/orders/${orderId}/status`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status }),
  });
}

// ─── ADMIN ────────────────────────────────────────────────────────────────────
export async function adminGetProducts(token) {
  return apiFetch("api/app/admin/products", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function adminUpdateProduct(productId, data, token) {
  return apiFetch(`api/app/admin/products/${productId}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
}

export async function adminGetUsers(token) {
  return apiFetch("api/app/admin/users", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function adminGetStores(token) {
  return apiFetch("api/app/admin/stores", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function adminUpdateUser(userId, data, token) {
  return apiFetch(`api/app/admin/users/${userId}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
}

export async function registerPushToken(pushToken, token) {
  return apiFetch("api/app/delivery/push-token", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ push_token: pushToken }),
  });
}

export async function registerCustomerPushToken(pushToken, userToken, platform) {
  return apiFetch("api/app/user/push-token", {
    method: "POST",
    headers: { Authorization: `Bearer ${userToken}` },
    body: JSON.stringify({ push_token: pushToken, platform }),
  });
}
