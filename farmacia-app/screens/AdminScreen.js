import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import {
  adminGetUsers,
  adminGetStores,
  adminUpdateUser,
  adminGetProducts,
  adminUpdateProduct,
} from "../services/api";

const RED    = "#e6192e";
const GREEN  = "#22c55e";
const BLUE   = RED; // Redirigir azul a rojo
const ORANGE = "#f59e0b";

const ROLE_CONFIG = {
  customer: { label: "Cliente",      color: "#6b7280", bg: "#f3f4f6", icon: "person-outline", darkBg: "#2c2c2e" },
  delivery: { label: "Repartidor",   color: RED,       bg: "#fff5f5", icon: "bicycle-outline", darkBg: "#3a1515" },
  admin:    { label: "Admin",        color: RED,       bg: "#fff1f2", icon: "shield-checkmark-outline", darkBg: "#3a1515" },
};

// ─── MODAL EDITAR USUARIO ─────────────────────────────────────────────────────
function EditUserModal({ user, stores, onClose, onSave }) {
  const { t, isDark } = useTheme();
  const [role, setRole]       = useState(user.role || "customer");
  const [storeId, setStoreId] = useState(user.store_id ? String(user.store_id) : "");
  const [saving, setSaving]   = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await onSave(user.id, { role, store_id: storeId ? parseInt(storeId) : null });
    setSaving(false);
    onClose();
  };

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={s.modalBackdrop}>
        <View style={[s.modalCard, { backgroundColor: t.card }]}>
          <View style={s.modalHeader}>
            <View style={[s.modalAvatar, { backgroundColor: t.iconBg }]}>
              <Text style={[s.modalAvatarText, { color: t.text }]}>{(user.name || "?")[0].toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[s.modalName, { color: t.text }]}>{user.name}</Text>
              <Text style={[s.modalEmail, { color: t.textMuted }]}>{user.email}</Text>
            </View>
            <TouchableOpacity onPress={onClose} style={[s.closeBtn, { backgroundColor: t.iconBg }]}>
              <Ionicons name="close" size={20} color={t.textMuted} />
            </TouchableOpacity>
          </View>

          <Text style={s.sectionLabel}>ROL</Text>
          <View style={s.roleRow}>
            {["customer", "delivery", "admin"].map((r) => {
              const cfg = ROLE_CONFIG[r];
              const bg = isDark ? cfg.darkBg : cfg.bg;
              return (
                <TouchableOpacity
                  key={r}
                  style={[
                    s.roleChip,
                    { backgroundColor: t.cardAlt, borderColor: t.border },
                    role === r && { backgroundColor: bg, borderColor: cfg.color }
                  ]}
                  onPress={() => { setRole(r); if (r !== "delivery") setStoreId(""); }}
                >
                  <Ionicons name={cfg.icon} size={14} color={role === r ? cfg.color : t.textMuted} />
                  <Text style={[s.roleChipText, { color: t.textMuted }, role === r && { color: cfg.color, fontWeight: "800" }]}>
                    {cfg.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {role === "delivery" && (
            <>
              <Text style={s.sectionLabel}>SUCURSAL ASIGNADA</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 16 }}>
                <View style={s.storeRow}>
                  <TouchableOpacity
                    style={[s.storeChip, { backgroundColor: t.cardAlt, borderColor: t.border }, storeId === "" && s.storeChipActive]}
                    onPress={() => setStoreId("")}
                  >
                    <Text style={[s.storeChipText, { color: t.textMuted }, storeId === "" && s.storeChipTextActive]}>Sin asignar</Text>
                  </TouchableOpacity>
                  {stores.map((st) => (
                    <TouchableOpacity
                      key={st.id}
                      style={[s.storeChip, { backgroundColor: t.cardAlt, borderColor: t.border }, storeId === String(st.id) && s.storeChipActive]}
                      onPress={() => setStoreId(String(st.id))}
                    >
                      <Ionicons name="storefront-outline" size={12} color={storeId === String(st.id) ? "#fff" : t.textMuted} />
                      <Text style={[s.storeChipText, { color: t.textMuted }, storeId === String(st.id) && s.storeChipTextActive]}>
                        {st.name}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            </>
          )}

          <TouchableOpacity style={s.saveBtn} onPress={handleSave} disabled={saving}>
            {saving
              ? <ActivityIndicator color="#fff" size="small" />
              : <><Ionicons name="checkmark-circle" size={18} color="#fff" /><Text style={s.saveBtnText}>GUARDAR CAMBIOS</Text></>
            }
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

// ─── MODAL EDITAR STOCK ───────────────────────────────────────────────────────
function EditStockModal({ product, onClose, onSave }) {
  const { t } = useTheme();
  const [stock, setStock]   = useState(String(product.stock));
  const [active, setActive] = useState(!!product.active);
  const [saving, setSaving] = useState(false);
  const reserved = product.reserved ?? 0;

  const handleSave = async () => {
    const val = parseInt(stock);
    if (isNaN(val) || val < 0) return;
    setSaving(true);
    // Si el stock es > 0 siempre activar; si es 0 respetar el toggle
    const payload = { stock: val, active: val > 0 ? true : active };
    await onSave(product.id, payload);
    setSaving(false);
    onClose();
  };

  const stockNum = parseInt(stock) || 0;
  const stockColor = stockNum === 0 ? RED : stockNum <= 5 ? ORANGE : GREEN;

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={s.modalBackdrop}>
        <View style={[s.modalCard, { backgroundColor: t.card }]}>
          <View style={s.modalHeader}>
            <View style={[s.modalAvatar, { backgroundColor: t.iconBg }]}>
              <Ionicons name="cube-outline" size={22} color={t.textMuted} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[s.modalName, { color: t.text }]}>{product.name}</Text>
              <Text style={[s.modalEmail, { color: t.textMuted }]}>{product.category} · ${product.price} / {product.unit}</Text>
            </View>
            <TouchableOpacity onPress={onClose} style={[s.closeBtn, { backgroundColor: t.iconBg }]}>
              <Ionicons name="close" size={20} color={t.textMuted} />
            </TouchableOpacity>
          </View>

          {/* Visible en tienda */}
          <View style={[s.activeRow, { backgroundColor: t.cardAlt }]}>
            <View style={{ flex: 1 }}>
              <Text style={[s.sectionLabel, { marginBottom: 2 }]}>VISIBLE EN TIENDA</Text>
              <Text style={{ fontSize: 11, color: t.textMuted }}>
                {active ? "Los clientes pueden ver y comprar este producto" : "Oculto — no aparece en la tienda"}
              </Text>
            </View>
            <Switch
              value={active}
              onValueChange={setActive}
              trackColor={{ false: "#ddd", true: GREEN + "88" }}
              thumbColor={active ? GREEN : "#bbb"}
            />
          </View>

          <Text style={[s.sectionLabel, { marginTop: 16 }]}>STOCK EN BODEGA</Text>
          <View style={s.stockInputRow}>
            <TouchableOpacity
              style={[s.stockStepBtn, { backgroundColor: t.iconBg }]}
              onPress={() => setStock(String(Math.max(0, stockNum - 1)))}
            >
              <Ionicons name="remove" size={20} color={RED} />
            </TouchableOpacity>
            <TextInput
              style={[s.stockInput, { borderColor: stockColor, color: t.text, backgroundColor: t.input }]}
              value={stock}
              onChangeText={setStock}
              keyboardType="number-pad"
              selectTextOnFocus
            />
            <TouchableOpacity
              style={[s.stockStepBtn, { backgroundColor: t.iconBg }]}
              onPress={() => setStock(String(stockNum + 1))}
            >
              <Ionicons name="add" size={20} color={GREEN} />
            </TouchableOpacity>
          </View>

          <View style={[s.stockBadge, { backgroundColor: stockColor + "18", borderColor: stockColor + "44" }]}>
            <Ionicons
              name={stockNum === 0 ? "close-circle" : stockNum <= 5 ? "warning" : "checkmark-circle"}
              size={14} color={stockColor}
            />
            <Text style={[s.stockBadgeText, { color: stockColor }]}>
              {stockNum === 0 ? "Sin stock — se desactivará en tienda"
                : stockNum <= 5 ? `Pocas unidades (${stockNum} total en bodega)`
                : `${stockNum} unidades en bodega`}
            </Text>
          </View>
          {reserved > 0 && (
            <View style={[s.stockBadge, { backgroundColor: ORANGE + "18", borderColor: ORANGE + "44", marginTop: 8 }]}>
              <Ionicons name="time-outline" size={14} color={ORANGE} />
              <Text style={[s.stockBadgeText, { color: ORANGE }]}>
                {reserved} en pedidos activos (en proceso de entrega)
              </Text>
            </View>
          )}

          <TouchableOpacity style={s.saveBtn} onPress={handleSave} disabled={saving}>
            {saving
              ? <ActivityIndicator color="#fff" size="small" />
              : <><Ionicons name="checkmark-circle" size={18} color="#fff" /><Text style={s.saveBtnText}>GUARDAR</Text></>
            }
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

// ─── TARJETA USUARIO ──────────────────────────────────────────────────────────
function UserCard({ user, onEdit }) {
  const { t, isDark } = useTheme();
  const cfg = ROLE_CONFIG[user.role] || ROLE_CONFIG.customer;
  const bg = isDark ? cfg.darkBg : cfg.bg;

  return (
    <TouchableOpacity style={[s.userCard, { backgroundColor: t.card }]} onPress={() => onEdit(user)} activeOpacity={0.82}>
      <View style={s.userCardLeft}>
        <View style={[s.avatar, { backgroundColor: bg }]}>
          <Text style={[s.avatarText, { color: cfg.color }]}>{(user.name || "?")[0].toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[s.userName, { color: t.text }]}>{user.name}</Text>
          <Text style={[s.userEmail, { color: t.textMuted }]} numberOfLines={1}>{user.email}</Text>
          {user.store_name && user.role === "delivery" && (
            <View style={s.storePill}>
              <Ionicons name="storefront-outline" size={10} color={RED} />
              <Text style={s.storePillText}>{user.store_name}</Text>
            </View>
          )}
        </View>
      </View>
      <View style={{ alignItems: "flex-end", gap: 6 }}>
        <View style={[s.roleBadge, { backgroundColor: bg }]}>
          <Ionicons name={cfg.icon} size={11} color={cfg.color} />
          <Text style={[s.roleBadgeText, { color: cfg.color }]}>{cfg.label}</Text>
        </View>
        <Ionicons name="chevron-forward" size={14} color={t.border} />
      </View>
    </TouchableOpacity>
  );
}

// ─── TARJETA PRODUCTO / STOCK ─────────────────────────────────────────────────
function ProductCard({ product, onEdit }) {
  const { t } = useTheme();
  const isInactive = !product.active;
  const avail = product.real_available ?? product.stock;
  const reserved = product.reserved ?? 0;
  const stockColor = isInactive ? "#9e9e9e" : avail === 0 ? RED : avail <= 5 ? ORANGE : GREEN;
  const stockLabel = isInactive ? "INACTIVO" : avail === 0 ? "AGOTADO" : avail <= 5 ? "POCAS" : "OK";
  return (
    <TouchableOpacity style={[s.userCard, { backgroundColor: t.card, opacity: isInactive ? 0.6 : 1 }]} onPress={() => onEdit(product)} activeOpacity={0.82}>
      <View style={s.userCardLeft}>
        <View style={[s.avatar, { backgroundColor: stockColor + "18" }]}>
          <Ionicons name={isInactive ? "cube" : "cube-outline"} size={20} color={stockColor} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[s.userName, { color: t.text }]}>{product.name}</Text>
          <Text style={[s.userEmail, { color: t.textMuted }]}>{product.category} · ${product.price} / {product.unit}</Text>
          {reserved > 0 && (
            <Text style={{ fontSize: 10, color: ORANGE, marginTop: 2 }}>
              {reserved} en pedidos activos · total en BD: {product.stock}
            </Text>
          )}
          {isInactive && (
            <Text style={{ fontSize: 10, color: "#9e9e9e", marginTop: 2 }}>
              Oculto en tienda — agrega stock para reactivar
            </Text>
          )}
        </View>
      </View>
      <View style={{ alignItems: "flex-end", gap: 6 }}>
        <View style={[s.roleBadge, { backgroundColor: stockColor + "18" }]}>
          <Text style={[s.roleBadgeText, { color: stockColor, fontSize: 11 }]}>
            {isInactive ? "INACTIVO" : `${avail} disp · ${stockLabel}`}
          </Text>
        </View>
        <Ionicons name="create-outline" size={16} color={t.textMuted} />
      </View>
    </TouchableOpacity>
  );
}

// ─── PANTALLA ADMIN ───────────────────────────────────────────────────────────
export default function AdminScreen() {
  const { user, signOut } = useAuth();
  const { t } = useTheme();
  const [tab, setTab]               = useState("users"); // users | inventory
  const [users, setUsers]           = useState([]);
  const [stores, setStores]         = useState([]);
  const [products, setProducts]     = useState([]);
  const [loading, setLoading]       = useState(true);
  const [filter, setFilter]         = useState("all");
  const [searchStock, setSearch]    = useState("");
  const [editingUser, setEditingUser]     = useState(null);
  const [editingProduct, setEditingProduct] = useState(null);

  const load = async () => {
    setLoading(true);
    const [resU, resS, resP] = await Promise.all([
      adminGetUsers(user.token),
      adminGetStores(user.token),
      adminGetProducts(user.token),
    ]);
    if (resU?.success) setUsers(resU.data || []);
    if (resS?.success) setStores(resS.data || []);
    if (resP?.success) setProducts(resP.data || []);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleSaveUser = async (userId, data) => {
    await adminUpdateUser(userId, data, user.token);
    await load();
  };

  const handleSaveProduct = async (productId, data) => {
    await adminUpdateProduct(productId, data, user.token);
    setProducts((prev) => prev.map((p) => p.id === productId ? { ...p, ...data } : p));
  };

  const filtered = filter === "all" ? users : users.filter((u) => u.role === filter);
  const counts = {
    all:      users.length,
    delivery: users.filter((u) => u.role === "delivery").length,
    customer: users.filter((u) => u.role === "customer" || !u.role).length,
    admin:    users.filter((u) => u.role === "admin").length,
  };

  const filteredProducts = searchStock.trim()
    ? products.filter((p) => p.name.toLowerCase().includes(searchStock.toLowerCase()) || p.category.toLowerCase().includes(searchStock.toLowerCase()))
    : products;

  const stockCounts = {
    total:   products.length,
    agotado: products.filter((p) => p.stock === 0).length,
    poco:    products.filter((p) => p.stock > 0 && p.stock <= 5).length,
    ok:      products.filter((p) => p.stock > 6).length,
  };

  return (
    <View style={[s.wrapper, { backgroundColor: t.bg }]}>
      {/* Header */}
      <View style={[s.header, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <View style={s.headerLeft}>
          <View style={s.headerIcon}>
            <Ionicons name="shield-checkmark" size={20} color="#fff" />
          </View>
          <View>
            <Text style={[s.headerTitle, { color: t.text }]}>PANEL ADMIN</Text>
            <Text style={[s.headerSub, { color: t.textMuted }]}>{user?.name}</Text>
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TouchableOpacity style={[s.iconBtn, { backgroundColor: t.iconBg }]} onPress={load}>
            <Ionicons name="refresh-outline" size={18} color={t.textMuted} />
          </TouchableOpacity>
          <TouchableOpacity style={[s.iconBtn, { backgroundColor: t.iconBgRed }]} onPress={signOut}>
            <Ionicons name="log-out-outline" size={18} color={RED} />
          </TouchableOpacity>
        </View>
      </View>

      {/* Tabs */}
      <View style={[s.tabBar, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <TouchableOpacity style={[s.tabBtn, tab === "users" && s.tabBtnActive]} onPress={() => setTab("users")}>
          <Ionicons name="people-outline" size={16} color={tab === "users" ? RED : t.textMuted} />
          <Text style={[s.tabBtnText, { color: t.textMuted }, tab === "users" && s.tabBtnTextActive]}>Usuarios</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[s.tabBtn, tab === "inventory" && s.tabBtnActive]} onPress={() => setTab("inventory")}>
          <Ionicons name="cube-outline" size={16} color={tab === "inventory" ? RED : t.textMuted} />
          <Text style={[s.tabBtnText, { color: t.textMuted }, tab === "inventory" && s.tabBtnTextActive]}>Inventario</Text>
          {stockCounts.agotado > 0 && (
            <View style={s.alertDot}><Text style={s.alertDotText}>{stockCounts.agotado}</Text></View>
          )}
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={s.loadingWrap}>
          <ActivityIndicator size="large" color={RED} />
          <Text style={[s.loadingText, { color: t.textMuted }]}>Cargando...</Text>
        </View>
      ) : tab === "users" ? (
        <>
          {/* Stats usuarios */}
          <View style={s.statsRow}>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: t.border }]}>
              <Text style={[s.statNum, { color: t.text }]}>{counts.all}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Total</Text>
            </View>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: BLUE + "44" }]}>
              <Text style={[s.statNum, { color: BLUE }]}>{counts.delivery}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Repartidores</Text>
            </View>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: GREEN + "44" }]}>
              <Text style={[s.statNum, { color: GREEN }]}>{counts.customer}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Clientes</Text>
            </View>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: RED + "44" }]}>
              <Text style={[s.statNum, { color: RED }]}>{counts.admin}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Admins</Text>
            </View>
          </View>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filters}>
            {[
              { key: "all",      label: "Todos",       icon: "people-outline" },
              { key: "delivery", label: "Repartidores", icon: "bicycle-outline" },
              { key: "customer", label: "Clientes",     icon: "person-outline" },
              { key: "admin",    label: "Admins",       icon: "shield-outline" },
            ].map((f) => (
              <TouchableOpacity
                key={f.key}
                style={[s.filterChip, { backgroundColor: t.card, borderColor: t.border }, filter === f.key && s.filterChipActive]}
                onPress={() => setFilter(f.key)}
              >
                <Ionicons name={f.icon} size={13} color={filter === f.key ? "#fff" : t.textMuted} />
                <Text style={[s.filterChipText, { color: t.textMuted }, filter === f.key && s.filterChipTextActive]}>
                  {f.label} ({counts[f.key]})
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.listContent}>
            {filtered.length === 0 ? (
              <View style={s.emptyWrap}>
                <Ionicons name="people-outline" size={48} color={t.border} />
                <Text style={[s.emptyText, { color: t.textMuted }]}>Sin usuarios en esta categoría</Text>
              </View>
            ) : filtered.map((u) => (
              <UserCard key={u.id} user={u} onEdit={setEditingUser} />
            ))}
            <View style={{ height: 40 }} />
          </ScrollView>
        </>
      ) : (
        <>
          {/* Stats inventario */}
          <View style={s.statsRow}>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: t.border }]}>
              <Text style={[s.statNum, { color: t.text }]}>{stockCounts.total}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Productos</Text>
            </View>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: RED + "44" }]}>
              <Text style={[s.statNum, { color: RED }]}>{stockCounts.agotado}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Agotados</Text>
            </View>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: ORANGE + "44" }]}>
              <Text style={[s.statNum, { color: ORANGE }]}>{stockCounts.poco}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Pocas uds</Text>
            </View>
            <View style={[s.statCard, { backgroundColor: t.card, borderColor: GREEN + "44" }]}>
              <Text style={[s.statNum, { color: GREEN }]}>{stockCounts.ok}</Text>
              <Text style={[s.statLabel, { color: t.textMuted }]}>Con stock</Text>
            </View>
          </View>

          {/* Buscador */}
          <View style={[s.searchRow, { backgroundColor: t.card, borderColor: t.border }]}>
            <Ionicons name="search-outline" size={16} color={t.textMuted} />
            <TextInput
              style={[s.searchInput, { color: t.text }]}
              placeholder="Buscar producto..."
              value={searchStock}
              onChangeText={setSearch}
              placeholderTextColor={t.placeholder}
            />
            {searchStock.length > 0 && (
              <TouchableOpacity onPress={() => setSearch("")}>
                <Ionicons name="close-circle" size={16} color={t.textMuted} />
              </TouchableOpacity>
            )}
          </View>

          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.listContent}>
            {filteredProducts.length === 0 ? (
              <View style={s.emptyWrap}>
                <Ionicons name="cube-outline" size={48} color={t.border} />
                <Text style={[s.emptyText, { color: t.textMuted }]}>Sin productos</Text>
              </View>
            ) : filteredProducts.map((p) => (
              <ProductCard key={p.id} product={p} onEdit={setEditingProduct} />
            ))}
            <View style={{ height: 40 }} />
          </ScrollView>
        </>
      )}

      {editingUser && (
        <EditUserModal
          user={editingUser}
          stores={stores}
          onClose={() => setEditingUser(null)}
          onSave={handleSaveUser}
        />
      )}
      {editingProduct && (
        <EditStockModal
          product={editingProduct}
          onClose={() => setEditingProduct(null)}
          onSave={handleSaveProduct}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  wrapper: { flex: 1, backgroundColor: "#f5f5f5", paddingTop: Platform.OS === "ios" ? 54 : 44 },

  header: {
    backgroundColor: "#fff", paddingHorizontal: 16, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  headerIcon: {
    width: 40, height: 40, borderRadius: 12,
    backgroundColor: RED, justifyContent: "center", alignItems: "center",
  },
  headerTitle: { fontSize: 16, fontWeight: "900", color: "#111" },
  headerSub: { fontSize: 11, color: "#aaa", marginTop: 1 },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center",
  },

  tabBar: {
    flexDirection: "row", backgroundColor: "#fff",
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  tabBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 12,
  },
  tabBtnActive: { borderBottomWidth: 2, borderBottomColor: RED },
  tabBtnText: { fontSize: 13, fontWeight: "700", color: "#aaa" },
  tabBtnTextActive: { color: RED },
  alertDot: {
    backgroundColor: RED, borderRadius: 8, minWidth: 16, height: 16,
    alignItems: "center", justifyContent: "center", paddingHorizontal: 4,
  },
  alertDotText: { color: "#fff", fontSize: 9, fontWeight: "900" },

  statsRow: { flexDirection: "row", gap: 10, padding: 16, paddingBottom: 8 },
  statCard: {
    flex: 1, backgroundColor: "#fff", borderRadius: 12, padding: 12,
    alignItems: "center", borderWidth: 1.5,
  },
  statNum: { fontSize: 22, fontWeight: "900", color: "#111" },
  statLabel: { fontSize: 10, color: "#aaa", fontWeight: "600", marginTop: 2 },

  filters: { paddingHorizontal: 16, paddingBottom: 12, gap: 8 },
  filterChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20,
    backgroundColor: "#fff", borderWidth: 1, borderColor: "#eee",
  },
  filterChipActive: { backgroundColor: RED, borderColor: RED },
  filterChipText: { fontSize: 12, fontWeight: "700", color: "#666" },
  filterChipTextActive: { color: "#fff" },

  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: 16, marginBottom: 8, marginTop: 4,
    backgroundColor: "#fff", borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10,
    borderWidth: 1, borderColor: "#eee",
  },
  searchInput: { flex: 1, fontSize: 13, color: "#111" },

  listContent: { paddingHorizontal: 16, paddingTop: 4 },
  loadingWrap: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  loadingText: { color: "#aaa", fontSize: 13 },
  emptyWrap: { flex: 1, alignItems: "center", paddingTop: 60, gap: 12 },
  emptyText: { color: "#bbb", fontSize: 14 },

  userCard: {
    backgroundColor: "#fff", borderRadius: 14, padding: 14, marginBottom: 10,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04, shadowRadius: 6, elevation: 2,
  },
  userCardLeft: { flexDirection: "row", alignItems: "center", gap: 12, flex: 1 },
  avatar: { width: 44, height: 44, borderRadius: 22, justifyContent: "center", alignItems: "center" },
  avatarText: { fontSize: 18, fontWeight: "900" },
  userName: { fontSize: 14, fontWeight: "800", color: "#111" },
  userEmail: { fontSize: 11, color: "#aaa", marginTop: 1, maxWidth: 180 },
  storePill: { flexDirection: "row", alignItems: "center", gap: 3, marginTop: 3 },
  storePillText: { fontSize: 10, fontWeight: "700", color: RED },
  roleBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8,
  },
  roleBadgeText: { fontSize: 10, fontWeight: "700" },

  // Modal compartido
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center", alignItems: "center", padding: 24,
  },
  modalCard: { backgroundColor: "#fff", borderRadius: 20, padding: 20, width: "100%", maxWidth: 420 },
  modalHeader: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 20 },
  modalAvatar: {
    width: 48, height: 48, borderRadius: 24,
    backgroundColor: "#f3f4f6", justifyContent: "center", alignItems: "center",
  },
  modalAvatarText: { fontSize: 20, fontWeight: "900", color: "#555" },
  modalName: { fontSize: 15, fontWeight: "900", color: "#111" },
  modalEmail: { fontSize: 12, color: "#aaa", marginTop: 2 },
  closeBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center",
  },
  sectionLabel: { fontSize: 10, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 10 },
  roleRow: { flexDirection: "row", gap: 8, marginBottom: 20 },
  roleChip: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5,
    paddingVertical: 10, borderRadius: 12, borderWidth: 1.5, borderColor: "#eee", backgroundColor: "#fafafa",
  },
  roleChipText: { fontSize: 12, fontWeight: "600", color: "#aaa" },
  storeRow: { flexDirection: "row", gap: 8 },
  storeChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 20,
    borderWidth: 1.5, borderColor: "#eee", backgroundColor: "#fafafa",
  },
  storeChipActive: { backgroundColor: RED, borderColor: RED },
  storeChipText: { fontSize: 12, fontWeight: "700", color: "#666" },
  storeChipTextActive: { color: "#fff" },
  saveBtn: {
    backgroundColor: RED, borderRadius: 14, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 4,
  },
  saveBtnText: { color: "#fff", fontWeight: "900", fontSize: 14 },

  // Stock modal
  stockInputRow: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 16 },
  stockStepBtn: {
    width: 44, height: 44, borderRadius: 12,
    backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center",
  },
  stockInput: {
    flex: 1, fontSize: 32, fontWeight: "900", color: "#111", textAlign: "center",
    borderWidth: 2, borderRadius: 14, paddingVertical: 10,
  },
  stockBadge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: 12,
    borderWidth: 1, marginBottom: 16,
  },
  stockBadgeText: { fontSize: 12, fontWeight: "700", flex: 1 },
  activeRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, marginBottom: 4,
  },
});

