import { Ionicons } from "@expo/vector-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCart } from "../context/CartContext";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useWishlist } from "../context/WishlistContext";
import { MOBILE_HEADER_FIXED } from "./HomeScreen";
import { getCategories, getProducts } from "../services/api";
import LoginPromptSheet from "../components/LoginPromptSheet";
import ProductDetailModal from "../components/ProductDetailModal";

const RED = "#243366";
const YELLOW = "#3c73b9";

const ALL_FILTER = { id: "all", label: "Todo", icon: "grid-outline" };

// Ícono por defecto según nombre de categoría
function iconForCategory(name = "") {
  const n = name.toUpperCase();
  if (n.includes("ANALG") || n.includes("DOLOR"))               return "medkit-outline";
  if (n.includes("ANTIBIO"))                                      return "shield-checkmark-outline";
  if (n.includes("VITAMIN") || n.includes("SUPLEMENTO"))         return "nutrition-outline";
  if (n.includes("DERMA") || n.includes("PIEL"))                 return "body-outline";
  if (n.includes("DIABETES") || n.includes("GLUCOSA"))           return "water-outline";
  if (n.includes("GASTRO") || n.includes("DIGEST"))              return "fitness-outline";
  if (n.includes("RESPIRATO") || n.includes("TOS") || n.includes("GRIPE")) return "cloudy-outline";
  if (n.includes("CARDIACO") || n.includes("PRESION"))           return "heart-outline";
  if (n.includes("INFANTIL") || n.includes("BEBE") || n.includes("BEBÉ")) return "happy-outline";
  if (n.includes("HERIDA") || n.includes("CURACION"))            return "bandage-outline";
  if (n.includes("HIGIENE") || n.includes("PERSONAL"))           return "sparkles-outline";
  if (n.includes("RECETA") || n.includes("CONTROL"))             return "document-text-outline";
  return "flask-outline";
}

// Normaliza productos del FastAPI de Farmacia Eben-Ezer
function normalizeApiProduct(p) {
  const precio = parseFloat(p.precio_venta ?? 0);
  const label  = p.presentacion ? `${p.concentracion ?? ""} ${p.presentacion}`.trim() : "";
  return {
    id:              p.id,
    cat:             p.categoria_nombre ?? null,
    name:            p.nombre,
    nombre_generico: p.nombre_generico ?? null,
    marca:           p.marca ?? null,
    price:           label ? `$${precio.toFixed(2)} / ${label}` : `$${precio.toFixed(2)}`,
    price_numeric:   precio,
    img:             p.imagen_url ?? null,
    promo:           null,
    stock:           p.stock ?? null,
    requiere_receta: p.requiere_receta ?? false,
  };
}

const SORT_OPTIONS = ["Relevancia", "Menor precio", "Mayor precio", "Más nuevo"];

// ─── PRODUCT CARD MÓVIL ───────────────────────────────────────────────────────
function ProductCardMobile({ item, cardWidth, onPress }) {
  const { addToCart, items } = useCart();
  const { toggleWishlist, isWishlisted } = useWishlist();
  const { t } = useTheme();
  const [added, setAdded] = useState(false);
  const [qty, setQty] = useState(1);
  const [limitMsg, setLimitMsg] = useState("");
  const [showLogin, setShowLogin] = useState(false);

  const stockTracked = item.stock !== null && item.stock !== undefined;
  const isUnlimited  = item.stock === -1;
  const inCart    = items.find((i) => i.id === item.id)?.qty ?? 0;
  const available = isUnlimited ? Infinity : (stockTracked ? Math.max(0, item.stock - inCart) : Infinity);
  const agotado   = !isUnlimited && stockTracked && item.stock === 0;
  const atMax     = !isUnlimited && stockTracked && inCart >= item.stock;
  const wishlisted = isWishlisted(item.id);

  // Corregir qty si el carrito se actualizó y ya no hay suficiente disponible
  useEffect(() => {
    if (!isUnlimited && stockTracked && qty > available && available >= 1) setQty(available);
    if (!isUnlimited && stockTracked && available === 0) setQty(1);
  }, [available, stockTracked, isUnlimited]);

  const handleAdd = () => {
    const r = addToCart(item, qty);
    if (r.authRequired) { setShowLogin(true); return; }
    if (!r.ok) { setLimitMsg(r.message); setTimeout(() => setLimitMsg(""), 2500); return; }
    setAdded(true);
    setTimeout(() => { setAdded(false); setQty(1); }, 900);
  };

  return (
    <>
    <TouchableOpacity style={[styles.cardMobile, { width: cardWidth, backgroundColor: t.card }]} onPress={onPress} activeOpacity={0.88}>
      {item.promo && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{item.promo}</Text>
        </View>
      )}
      <TouchableOpacity
        style={styles.heartBtn}
        onPress={(e) => { e.stopPropagation?.(); toggleWishlist(item); }}
        activeOpacity={0.7}
        hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
      >
        <Ionicons name={wishlisted ? "heart" : "heart-outline"} size={15} color={wishlisted ? RED : "#bbb"} />
      </TouchableOpacity>
      <View style={[styles.imgWrap, { backgroundColor: "#fff" }]}>
        <Image source={{ uri: item.img }} style={styles.img} resizeMode="contain" />
      </View>
      <Text style={[styles.catLabel, { color: t.textMuted }]}>{item.cat}</Text>
      <Text style={[styles.cardName, { color: t.text }]} numberOfLines={1}>{item.name}</Text>
      <Text style={styles.cardPrice}>{item.price}</Text>
      {stockTracked && item.stock > 0 && item.stock <= 5 && (
        <Text style={{ fontSize: 9, color: "#e65100", fontWeight: "700", marginTop: 1 }}>
          ¡Solo quedan {item.stock}!
        </Text>
      )}
      {limitMsg ? (
        <Text style={{ fontSize: 9, color: "#e65100", marginTop: 2 }} numberOfLines={2}>{limitMsg}</Text>
      ) : null}
      {/* Footer: qty controls + add button */}
      <View style={styles.mobileCardFooter}>
        <View style={[styles.mobileQtyRow, { backgroundColor: t.iconBg }]}>
          <TouchableOpacity
            style={[styles.mobileQtyBtn, { backgroundColor: t.card }]}
            onPress={(e) => { e.stopPropagation?.(); setQty(q => Math.max(1, q - 1)); }}
            activeOpacity={0.7}
          >
            <Text style={[styles.mobileQtyBtnText, { color: t.text }]}>−</Text>
          </TouchableOpacity>
          <Text style={[styles.mobileQtyText, { color: t.text }]}>{qty}</Text>
          <TouchableOpacity
            style={[styles.mobileQtyBtn, { backgroundColor: t.card }, (atMax || qty >= available) && { opacity: 0.35 }]}
            onPress={(e) => {
              e.stopPropagation?.();
              if (stockTracked && qty >= available) {
                setLimitMsg("Stock máximo alcanzado");
                setTimeout(() => setLimitMsg(""), 2000);
                return;
              }
              setQty(q => q + 1);
            }}
            activeOpacity={0.7}
          >
            <Text style={[styles.mobileQtyBtnText, { color: t.text }]}>+</Text>
          </TouchableOpacity>
        </View>
        <TouchableOpacity
          style={[styles.addBtnMobile, added && styles.addBtnAdded, (agotado || atMax) && { backgroundColor: "#ccc" }]}
          onPress={(e) => { e.stopPropagation?.(); handleAdd(); }}
          disabled={agotado || atMax}
          activeOpacity={0.8}
        >
          <Ionicons name={added ? "checkmark" : agotado || atMax ? "ban-outline" : "cart-outline"} size={14} color="#fff" />
        </TouchableOpacity>
      </View>
    </TouchableOpacity>
    <LoginPromptSheet visible={showLogin} onClose={() => setShowLogin(false)} />
    </>
  );
}

// ─── PRODUCT CARD DESKTOP ─────────────────────────────────────────────────────
function ProductCardDesktop({ item, onPress }) {
  const { addToCart, items } = useCart();
  const { toggleWishlist, isWishlisted } = useWishlist();
  const { t } = useTheme();
  const [added, setAdded]       = useState(false);
  const [qty, setQty]           = useState(1);
  const [limitMsg, setLimitMsg] = useState("");
  const [showLogin, setShowLogin] = useState(false);

  const stockTracked = item.stock !== null && item.stock !== undefined;
  const isUnlimited  = item.stock === -1;
  const inCart    = items.find((i) => i.id === item.id)?.qty ?? 0;
  const available = isUnlimited ? Infinity : (stockTracked ? Math.max(0, item.stock - inCart) : Infinity);
  const agotado   = !isUnlimited && stockTracked && item.stock === 0;
  const atMax     = !isUnlimited && stockTracked && inCart >= item.stock;
  const wishlisted = isWishlisted(item.id);

  useEffect(() => {
    if (!isUnlimited && stockTracked && qty > available && available >= 1) setQty(available);
    if (!isUnlimited && stockTracked && available === 0) setQty(1);
  }, [available, stockTracked, isUnlimited]);

  const handleAdd = () => {
    const r = addToCart(item, qty);
    if (r.authRequired) { setShowLogin(true); return; }
    if (!r.ok) { setLimitMsg(r.message); setTimeout(() => setLimitMsg(""), 2500); return; }
    setAdded(true);
    setTimeout(() => { setAdded(false); setQty(1); }, 1000);
  };

  return (
    <>
    <TouchableOpacity style={[styles.cardDesktop, { backgroundColor: t.card }]} onPress={onPress} activeOpacity={0.9}>
      {item.promo && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{item.promo}</Text>
        </View>
      )}
      <TouchableOpacity
        style={styles.heartBtnDesktop}
        onPress={(e) => { e.stopPropagation?.(); toggleWishlist(item); }}
        activeOpacity={0.7}
      >
        <Ionicons name={wishlisted ? "heart" : "heart-outline"} size={16} color={wishlisted ? RED : "#ccc"} />
      </TouchableOpacity>
      <View style={[styles.imgWrapDesktop, { backgroundColor: "#fff" }]}>
        <Image source={{ uri: item.img }} style={styles.imgDesktop} resizeMode="contain" />
      </View>
      <Text style={[styles.catLabelDesktop, { color: t.textMuted }]}>{item.cat}</Text>
      <Text style={[styles.cardNameDesktop, { color: t.text }]} numberOfLines={2}>{item.name}</Text>
      <Text style={styles.cardPriceDesktop}>{item.price}</Text>
      {stockTracked && item.stock > 0 && item.stock <= 5 && (
        <Text style={{ fontSize: 10, color: "#e65100", fontWeight: "700", marginBottom: 2 }}>
          ¡Solo quedan {item.stock}!
        </Text>
      )}
      {limitMsg ? (
        <Text style={{ fontSize: 10, color: "#e65100", marginBottom: 2 }} numberOfLines={2}>{limitMsg}</Text>
      ) : null}

      {/* Controles cantidad + botón agregar */}
      <View style={styles.cardFooterDesktop}>
        <View style={[styles.qtyRow, { backgroundColor: t.iconBg }]}>
          <TouchableOpacity
            style={styles.qtyBtn}
            onPress={() => setQty(q => Math.max(1, q - 1))}
          >
            <Ionicons name="remove" size={14} color={t.textMuted} />
          </TouchableOpacity>
          <Text style={[styles.qtyText, { color: t.text }]}>{qty}</Text>
          <TouchableOpacity
            style={[styles.qtyBtn, (atMax || qty >= available) && { opacity: 0.35 }]}
            onPress={() => {
              if (stockTracked && qty >= available) {
                setLimitMsg("Stock máximo alcanzado");
                setTimeout(() => setLimitMsg(""), 2000);
                return;
              }
              setQty(q => q + 1);
            }}
          >
            <Ionicons name="add" size={14} color={atMax || qty >= available ? "#aaa" : "#555"} />
          </TouchableOpacity>
        </View>
        <TouchableOpacity
          style={[styles.addBtnDesktop, added && styles.addBtnAdded, (agotado || atMax) && { backgroundColor: "#ccc" }]}
          onPress={handleAdd}
          disabled={agotado || atMax}
          activeOpacity={0.8}
        >
          {added ? (
            <>
              <Ionicons name="checkmark" size={14} color="#fff" />
              <Text style={styles.addBtnText}>Agregado</Text>
            </>
          ) : agotado || atMax ? (
            <>
              <Ionicons name="ban-outline" size={14} color="#fff" />
              <Text style={styles.addBtnText}>Agotado</Text>
            </>
          ) : (
            <>
              <Ionicons name="cart-outline" size={14} color="#fff" />
              <Text style={styles.addBtnText}>Agregar</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </TouchableOpacity>
    <LoginPromptSheet visible={showLogin} onClose={() => setShowLogin(false)} />
    </>
  );
}

// ─── DESKTOP SIDEBAR ──────────────────────────────────────────────────────────
function DesktopSidebar({ activeCategory, setActiveCategory, activeSort, setActiveSort, categories }) {
  const allCats = [ALL_FILTER, ...categories];
  const { t } = useTheme();
  return (
    <View style={[styles.sidebar, { backgroundColor: t.card }]}>
      <Text style={[styles.sidebarTitle, { color: t.textMuted }]}>CATEGORÍAS</Text>
      {allCats.map((cat) => (
        <TouchableOpacity
          key={cat.id}
          style={[styles.sidebarItem, activeCategory === cat.id && styles.sidebarItemActive]}
          onPress={() => setActiveCategory(cat.id)}
          activeOpacity={0.7}
        >
          <Ionicons
            name={cat.icon}
            size={16}
            color={activeCategory === cat.id ? RED : t.textMuted}
          />
          <Text style={[
            styles.sidebarItemText,
            { color: t.textSub },
            activeCategory === cat.id && styles.sidebarItemTextActive
          ]}>
            {cat.label}
          </Text>
          {activeCategory === cat.id && (
            <View style={styles.sidebarActiveDot} />
          )}
        </TouchableOpacity>
      ))}

      <View style={styles.sidebarDivider} />

      <Text style={[styles.sidebarTitle, { color: t.textMuted }]}>ORDENAR</Text>
      {SORT_OPTIONS.map((opt, i) => (
        <TouchableOpacity
          key={i}
          style={[styles.sidebarItem, activeSort === i && styles.sidebarItemActive]}
          onPress={() => setActiveSort(i)}
          activeOpacity={0.7}
        >
          <Ionicons
            name={activeSort === i ? "radio-button-on" : "radio-button-off"}
            size={16}
            color={activeSort === i ? RED : t.textMuted}
          />
          <Text style={[
            styles.sidebarItemText,
            { color: t.textSub },
            activeSort === i && styles.sidebarItemTextActive
          ]}>
            {opt}
          </Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

// ─── HOOK PRODUCTOS DESDE API ─────────────────────────────────────────────────
function useProducts() {
  const [products, setProducts] = useState([]);
  const [apiLoading, setApiLoading] = useState(true);
  const [apiError, setApiError] = useState(null);

  const fetchProducts = useCallback(async () => {
    setApiLoading(true);
    setApiError(null);
    try {
      const result = await getProducts();
      if (result?.success && Array.isArray(result.data)) {
        setProducts(result.data.map(normalizeApiProduct));
      } else {
        setApiError(result?.message || "No se pudieron cargar los productos");
        setProducts([]);
      }
    } catch (e) {
      setApiError(`Error de conexión: ${e?.message || "Sin internet"}`);
      setProducts([]);
    }
    setApiLoading(false);
  }, []);

  useEffect(() => { fetchProducts(); }, [fetchProducts]);

  return { products, apiLoading, apiError, refetch: fetchProducts };
}

// ─── HOOK CATEGORÍAS DESDE API ────────────────────────────────────────────────
function useCategories() {
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    getCategories()
      .then((res) => {
        if (res?.success && Array.isArray(res.data) && res.data.length > 0) {
          setCategories(
            res.data.map((c) => ({
              id:    c.nombre,
              label: c.nombre,
              icon:  iconForCategory(c.nombre),
              img:   null,
            }))
          );
        }
      })
      .catch(() => {});
  }, []);

  return categories;
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
export default function StoreScreen({
  onCartPress,
  onHomePress,
  onOrdersPress,
  onProfilePress,
  activeTab,
  initialCategory = "all",
  filterTrigger = 0,
  refreshTrigger = 0,
}) {
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState(initialCategory);
  const [activeSort, setActiveSort] = useState(0);
  const [showSort, setShowSort] = useState(false);
  const [pendingCategory, setPendingCategory] = useState("all");
  const [pendingSort, setPendingSort] = useState(0);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const { count } = useCart();
  const { t } = useTheme();
  const { width } = useWindowDimensions();
  const { top: safeTop, bottom: safeBottom } = useSafeAreaInsets();
  const { products, apiLoading, apiError, refetch } = useProducts();
  const categories = useCategories();

  useEffect(() => { setActiveCategory(initialCategory); }, [initialCategory]);

  useEffect(() => {
    if (refreshTrigger > 0) {
      refetch();
    }
  }, [refreshTrigger, refetch]);

  const prevFilterTrigger = useRef(filterTrigger);
  useEffect(() => {
    if (filterTrigger > prevFilterTrigger.current) {
      setPendingCategory(activeCategory);
      setPendingSort(activeSort);
      setShowSort(true);
    }
    prevFilterTrigger.current = filterTrigger;
  }, [filterTrigger]);

  const isDesktop = width >= 1024;
  const mobileTopPad = Math.max(safeTop, 20) + MOBILE_HEADER_FIXED + 8;

  // Móvil: 2 columnas
  const PADDING = 16;
  const GAP = 16;
  const mobileCardWidth = (width - PADDING * 2 - GAP) / 2;

  const filtered = products.filter((p) => {
    const matchCat = activeCategory === "all" || p.cat === activeCategory;
    const matchSearch = p.name.toLowerCase().includes(search.toLowerCase());
    return matchCat && matchSearch;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (activeSort === 1) return parseFloat(a.price) - parseFloat(b.price);
    if (activeSort === 2) return parseFloat(b.price) - parseFloat(a.price);
    return 0;
  });

  // ─── DESKTOP LAYOUT ────────────────────────────────────────────────────────
  if (isDesktop) {
    return (
      <View style={[styles.desktopWrapper, { backgroundColor: t.bg }]}>
        {/* DesktopNav is rendered globally in App.js */}

        <View style={styles.desktopBody}>
          {/* Sidebar izquierdo */}
          <View style={styles.sidebarWrap}>
            <DesktopSidebar
              activeCategory={activeCategory}
              setActiveCategory={setActiveCategory}
              activeSort={activeSort}
              setActiveSort={setActiveSort}
              categories={categories}
            />
          </View>

          {/* Contenido principal */}
          <View style={styles.desktopMain}>
            {/* Barra de búsqueda */}
            <View style={styles.desktopSearchBar}>
              <Ionicons name="search" size={18} color="#999" style={{ marginLeft: 14 }} />
              <TextInput
                value={search}
                onChangeText={setSearch}
                placeholder="Buscar productos..."
                style={styles.desktopSearchInput}
                placeholderTextColor="#bbb"
              />
              {search.length > 0 && (
                <TouchableOpacity onPress={() => setSearch("")} style={{ paddingRight: 12 }}>
                  <Ionicons name="close-circle" size={18} color="#ccc" />
                </TouchableOpacity>
              )}
            </View>

            {/* Fila de resultados */}
            <View style={[styles.resultsRow, { marginBottom: 16, backgroundColor: "transparent", borderBottomWidth: 0 }]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={styles.resultsText}>
                  <Text style={{ fontWeight: "900", color: "#111" }}>{sorted.length}</Text>
                  {" "}{sorted.length === 1 ? "producto" : "productos"}
                </Text>
                {apiLoading && <ActivityIndicator size="small" color={RED} />}
                {!apiLoading && (
                  <TouchableOpacity onPress={refetch}>
                    <Ionicons name="refresh-outline" size={14} color="#bbb" />
                  </TouchableOpacity>
                )}
              </View>
              <Text style={[styles.sortLabel, apiError && { color: "#243366" }]}>
                {apiError ? "Sin conexión" : `Orden: ${SORT_OPTIONS[activeSort]}`}
              </Text>
            </View>

            {/* Grid de productos - desktop */}
            <ScrollView
              showsVerticalScrollIndicator={false}
              contentContainerStyle={styles.desktopGrid}
            >
              {apiLoading ? (
                <View style={styles.noResults}>
                  <ActivityIndicator size="large" color={RED} />
                  <Text style={styles.noResultsText}>Cargando productos...</Text>
                </View>
              ) : apiError ? (
                <View style={styles.noResults}>
                  <Ionicons name="wifi-outline" size={48} color="#ddd" />
                  <Text style={styles.noResultsText}>{apiError}</Text>
                  <TouchableOpacity onPress={refetch} style={{ marginTop: 12, backgroundColor: RED, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 10 }}>
                    <Text style={{ color: "#fff", fontWeight: "800" }}>Reintentar</Text>
                  </TouchableOpacity>
                </View>
              ) : sorted.length === 0 ? (
                <View style={styles.noResults}>
                  <Ionicons name="search-outline" size={48} color="#ddd" />
                  <Text style={styles.noResultsText}>Sin resultados para "{search}"</Text>
                </View>
              ) : (
                <View style={styles.desktopGridWrap}>
                  {sorted.map((item) => (
                    <ProductCardDesktop key={item.id} item={item} onPress={() => setSelectedProduct(item)} />
                  ))}
                </View>
              )}
            </ScrollView>
          </View>
        </View>

        <ProductDetailModal
          visible={!!selectedProduct}
          product={selectedProduct}
          onClose={() => setSelectedProduct(null)}
        />
      </View>
    );
  }

  // ─── MOBILE LAYOUT ─────────────────────────────────────────────────────────
  return (
    <View style={[styles.mobileWrapper, { paddingTop: mobileTopPad, backgroundColor: t.bg }]}>
      {/* Header */}
      <View style={[styles.mobileHeader, { backgroundColor: t.header, borderBottomColor: t.border }]}>
        <Text style={[styles.mobileHeaderTitle, { color: t.text }]}>TIENDA</Text>
        {(activeCategory !== "all" || activeSort !== 0) && (
          <TouchableOpacity
            style={styles.activeFilerPill}
            onPress={() => { setPendingCategory(activeCategory); setPendingSort(activeSort); setShowSort(true); }}
          >
            <Ionicons name="funnel" size={12} color="#fff" />
            <Text style={styles.activeFilterPillText}>Filtro activo</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Bottom sheet filtro estilo Rappi */}
      <Modal
        visible={showSort}
        transparent
        animationType="slide"
        onRequestClose={() => setShowSort(false)}
      >
        <View style={{ flex: 1, justifyContent: "flex-end" }}>
          <Pressable style={StyleSheet.absoluteFillObject} onPress={() => setShowSort(false)} />
          <View style={styles.sheetContainer}>
          {/* Handle */}
          <View style={styles.sheetHandle} />

          {/* Título + cerrar */}
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Filtrar y ordenar</Text>
            <TouchableOpacity onPress={() => setShowSort(false)} style={styles.sheetCloseBtn}>
              <Ionicons name="close" size={20} color="#333" />
            </TouchableOpacity>
          </View>

          <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
            {/* Categorías */}
            <Text style={styles.filterSectionTitle}>CATEGORÍA</Text>
            <View style={styles.catChipsWrap}>
              {[ALL_FILTER, ...categories].map((cat) => (
                <TouchableOpacity
                  key={cat.id}
                  style={[styles.sheetCatChip, pendingCategory === cat.id && styles.sheetCatChipActive]}
                  onPress={() => setPendingCategory(cat.id)}
                >
                  <Text style={[styles.sheetCatChipText, pendingCategory === cat.id && styles.sheetCatChipTextActive]}>
                    {cat.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <View style={styles.filterDivider} />

            {/* Ordenar */}
            <Text style={styles.filterSectionTitle}>ORDENAR POR</Text>
            {SORT_OPTIONS.map((opt, i) => (
              <TouchableOpacity
                key={i}
                style={styles.filterOption}
                onPress={() => setPendingSort(i)}
              >
                <View style={[styles.filterRadio, pendingSort === i && styles.filterRadioActive]}>
                  {pendingSort === i && <View style={styles.filterRadioDot} />}
                </View>
                <Text style={[styles.filterOptionText, pendingSort === i && { color: RED, fontWeight: "800" }]}>
                  {opt}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Botón aplicar */}
          <View style={styles.sheetFooter}>
            <TouchableOpacity
              style={styles.sheetResetBtn}
              onPress={() => { setPendingCategory("all"); setPendingSort(0); }}
            >
              <Text style={styles.sheetResetText}>Limpiar</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.sheetApplyBtn}
              onPress={() => {
                setActiveCategory(pendingCategory);
                setActiveSort(pendingSort);
                setShowSort(false);
              }}
            >
              <Text style={styles.sheetApplyText}>Aplicar filtros</Text>
            </TouchableOpacity>
          </View>
        </View>
        </View>
      </Modal>

      {/* Results count */}
      <View style={[styles.resultsRow, { backgroundColor: t.header, borderBottomColor: t.border }]}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Text style={[styles.resultsText, { color: t.textSub }]}>
            {sorted.length} {sorted.length === 1 ? "producto" : "productos"}
          </Text>
          {apiLoading && <ActivityIndicator size="small" color={RED} />}
          {!apiLoading && (
            <TouchableOpacity onPress={refetch}>
              <Ionicons name="refresh-outline" size={14} color="#bbb" />
            </TouchableOpacity>
          )}
        </View>
        <TouchableOpacity onPress={() => { setPendingCategory(activeCategory); setPendingSort(activeSort); setShowSort(true); }} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Text style={[styles.sortLabel, { color: t.textMuted }, apiError && { color: RED }]}>
            {apiError ? "Sin conexión" : (activeCategory !== "all" ? [ALL_FILTER, ...categories].find(c => c.id === activeCategory)?.label : SORT_OPTIONS[activeSort])}
          </Text>
          <Ionicons name="chevron-down" size={12} color={t.textMuted} />
        </TouchableOpacity>
      </View>

      {/* Products Grid */}
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={[styles.mobileGrid, { paddingBottom: safeBottom + 84 }]}
      >
        {apiLoading ? (
          <View style={styles.noResults}>
            <ActivityIndicator size="large" color={RED} />
            <Text style={styles.noResultsText}>Cargando productos...</Text>
          </View>
        ) : apiError ? (
          <View style={styles.noResults}>
            <Ionicons name="wifi-outline" size={48} color="#ddd" />
            <Text style={styles.noResultsText}>{apiError}</Text>
            <TouchableOpacity onPress={refetch} style={{ marginTop: 12, backgroundColor: RED, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 10 }}>
              <Text style={{ color: "#fff", fontWeight: "800" }}>Reintentar</Text>
            </TouchableOpacity>
          </View>
        ) : sorted.length === 0 ? (
          <View style={styles.noResults}>
            <Ionicons name={activeCategory !== "all" ? "filter-outline" : "search-outline"} size={48} color="#ddd" />
            <Text style={styles.noResultsText}>
              {activeCategory !== "all"
                ? `Sin productos en "${[ALL_FILTER, ...categories].find(c => c.id === activeCategory)?.label ?? activeCategory}"`
                : `Sin resultados para "${search}"`}
            </Text>
            {activeCategory !== "all" && (
              <TouchableOpacity
                onPress={() => setActiveCategory("all")}
                style={{ marginTop: 12, paddingHorizontal: 20, paddingVertical: 9, backgroundColor: RED, borderRadius: 20 }}
              >
                <Text style={{ color: "#fff", fontWeight: "800", fontSize: 13 }}>Ver todos</Text>
              </TouchableOpacity>
            )}
          </View>
        ) : (
          <View style={styles.mobileGridWrap}>
            {sorted.map((item) => (
              <ProductCardMobile key={item.id} item={item} cardWidth={mobileCardWidth} onPress={() => setSelectedProduct(item)} />
            ))}
          </View>
        )}
      </ScrollView>

      <ProductDetailModal
        visible={!!selectedProduct}
        product={selectedProduct}
        onClose={() => setSelectedProduct(null)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  // ── DESKTOP WRAPPER ────────────────────────────────────────────────────────
  desktopWrapper: {
    flex: 1,
    backgroundColor: "#f5f5f5",
  },

  // ── DESKTOP NAVBAR (idéntico a HomeScreen) ────────────────────────────────
  desktopNav: {
    backgroundColor: "#fff",
    zIndex: 100,
    borderBottomWidth: 1,
    borderBottomColor: "#eee",
    ...Platform.select({ web: { position: "sticky", top: 0 } }),
  },
  centeredContainer: {
    maxWidth: 1200,
    width: "100%",
    alignSelf: "center",
    paddingHorizontal: 20,
  },
  desktopNavInner: {
    flexDirection: "row",
    alignItems: "center",
    height: 70,
    justifyContent: "space-between",
  },
  navLeft: { flexDirection: "row", alignItems: "center" },
  navLogo: { width: 44, height: 44, marginRight: 20 },
  navLink: { paddingHorizontal: 15 },
  navLinkText: { fontWeight: "700", fontSize: 14, color: "#333" },
  desktopSearch: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f5f5f5",
    borderRadius: 30,
    height: 45,
    marginHorizontal: 30,
    maxWidth: 600,
  },
  desktopSearchInput: { flex: 1, paddingHorizontal: 15, fontSize: 14 },
  desktopSearchBtn: {
    backgroundColor: "#333",
    width: 45,
    height: 45,
    borderRadius: 30,
    justifyContent: "center",
    alignItems: "center",
  },
  navRight: { flexDirection: "row", alignItems: "center", gap: 15 },
  navIconBtn: { padding: 5 },
  navCartBadge: {
    position: "absolute",
    top: -6,
    right: -6,
    backgroundColor: RED,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 3,
  },
  navCartBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff" },
  userNavBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 10, backgroundColor: "#f5f5f5" },
  userNavAvatar: { width: 28, height: 28, borderRadius: 14, backgroundColor: RED, justifyContent: "center", alignItems: "center" },
  userNavAvatarText: { color: "#fff", fontWeight: "900", fontSize: 13 },
  userNavName: { fontSize: 13, fontWeight: "700", color: "#333", maxWidth: 100 },
  loginBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10, borderWidth: 1.5, borderColor: "#eee" },
  loginText: { fontSize: 13, fontWeight: "800", color: RED },

  // ── DESKTOP BODY ───────────────────────────────────────────────────────────
  desktopBody: {
    flex: 1,
    flexDirection: "row",
    maxWidth: 1400,
    alignSelf: "center",
    width: "100%",
    paddingHorizontal: 16,
    paddingTop: 24,
    gap: 24,
  },

  // ── SIDEBAR ────────────────────────────────────────────────────────────────
  sidebarWrap: { width: 220 },
  sidebar: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  sidebarTitle: {
    fontSize: 10,
    fontWeight: "900",
    color: "#bbb",
    letterSpacing: 1,
    marginBottom: 10,
    marginTop: 4,
  },
  sidebarItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 10,
    borderRadius: 10,
    marginBottom: 2,
  },
  sidebarItemActive: { backgroundColor: "#fff5f5" },
  sidebarItemText: { fontSize: 13, color: "#555", fontWeight: "600", flex: 1 },
  sidebarItemTextActive: { color: RED, fontWeight: "800" },
  sidebarActiveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: RED,
  },
  sidebarDivider: { height: 1, backgroundColor: "#f0f0f0", marginVertical: 14 },

  // ── DESKTOP MAIN ───────────────────────────────────────────────────────────
  desktopMain: { flex: 1 },
  desktopSearchBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#fff",
    borderRadius: 14,
    height: 48,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
    marginBottom: 16,
  },
  desktopSearchInput: { flex: 1, paddingHorizontal: 12, fontSize: 14, color: "#333" },

  desktopGrid: { paddingTop: 8, paddingBottom: 40 },
  desktopGridWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 24,
  },

  // ── DESKTOP PRODUCT CARD ──────────────────────────────────────────────────
  cardDesktop: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 18,
    width: 210,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    elevation: 2,
    position: "relative",
  },
  heartBtnDesktop: {
    position: "absolute",
    top: 12,
    right: 12,
    zIndex: 2,
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: "#f8f8f8",
    justifyContent: "center",
    alignItems: "center",
  },
  imgWrapDesktop: {
    backgroundColor: "#f8f8f8",
    borderRadius: 12,
    height: 130,
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 14,
    padding: 10,
  },
  imgDesktop: { width: "100%", height: "100%" },
  catLabelDesktop: { fontSize: 9, color: "#bbb", fontWeight: "700", marginBottom: 2 },
  cardNameDesktop: { fontSize: 13, fontWeight: "800", color: "#111", marginBottom: 6, minHeight: 36 },
  cardPriceDesktop: { fontSize: 16, fontWeight: "900", color: RED, marginBottom: 14 },

  cardFooterDesktop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  qtyRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#f5f5f5",
    borderRadius: 8,
    paddingHorizontal: 4,
    paddingVertical: 4,
  },
  qtyBtn: {
    width: 26,
    height: 26,
    borderRadius: 8,
    backgroundColor: "#fff",
    justifyContent: "center",
    alignItems: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 1,
  },
  qtyText: { fontSize: 13, fontWeight: "800", color: "#111", minWidth: 18, textAlign: "center" },
  addBtnDesktop: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: RED,
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 10,
    justifyContent: "center",
    alignItems: "center",
    gap: 4,
  },
  addBtnText: { color: "#fff", fontSize: 12, fontWeight: "800" },
  addBtnAdded: { backgroundColor: "#22c55e" },

  // ── MOBILE WRAPPER ─────────────────────────────────────────────────────────
  mobileWrapper: {
    flex: 1,
    backgroundColor: "#f5f5f5",
  },
  mobileHeader: {
    backgroundColor: "#fff",
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  mobileHeaderTitle: { fontSize: 18, fontWeight: "900", color: "#111" },
  activeFilerPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: RED, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 20,
  },
  activeFilterPillText: { color: "#fff", fontSize: 11, fontWeight: "800" },
  headerActions: { flexDirection: "row", gap: 8 },
  headerIconBtn: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: "#f5f5f5",
    justifyContent: "center",
    alignItems: "center",
  },
  cartBadge: {
    position: "absolute",
    top: -4,
    right: -4,
    backgroundColor: RED,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 3,
  },
  cartBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff" },

  // ── SEARCH (MÓVIL) ─────────────────────────────────────────────────────────
  searchWrap: {
    backgroundColor: "#fff",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
  },
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f5f5f5",
    borderRadius: 12,
    height: 44,
  },
  searchInput: { flex: 1, paddingHorizontal: 10, fontSize: 14, color: "#333", outlineWidth: 0 },

  // ── BOTTOM SHEET FILTRO ────────────────────────────────────────────────────
  sheetOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  sheetContainer: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    height: "75%",
    paddingBottom: Platform.OS === "ios" ? 34 : 20,
  },
  sheetHandle: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#ddd",
    alignSelf: "center",
    marginTop: 12,
    marginBottom: 4,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
  },
  sheetTitle: { fontSize: 16, fontWeight: "900", color: "#111" },
  sheetCloseBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: "#f5f5f5",
    justifyContent: "center",
    alignItems: "center",
  },
  filterSectionTitle: {
    fontSize: 11,
    fontWeight: "900",
    color: "#aaa",
    letterSpacing: 1,
    marginBottom: 12,
    marginTop: 20,
    paddingHorizontal: 20,
  },
  catChipsWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    paddingHorizontal: 16,
    gap: 8,
  },
  sheetCatChip: {
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderRadius: 20,
    backgroundColor: "#f5f5f5",
    borderWidth: 1.5,
    borderColor: "transparent",
  },
  sheetCatChipActive: {
    backgroundColor: "#fff0f1",
    borderColor: RED,
  },
  sheetCatChipText: { fontSize: 13, fontWeight: "700", color: "#555" },
  sheetCatChipTextActive: { color: RED, fontWeight: "800" },
  filterDivider: {
    height: 1,
    backgroundColor: "#f0f0f0",
    marginTop: 20,
  },
  filterOption: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: "#f8f8f8",
  },
  filterRadio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: "#ddd",
    justifyContent: "center",
    alignItems: "center",
    marginRight: 14,
  },
  filterRadioActive: { borderColor: RED },
  filterRadioDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: RED,
  },
  filterOptionText: { flex: 1, fontSize: 15, color: "#333", fontWeight: "600" },
  sheetFooter: {
    flexDirection: "row",
    gap: 10,
    paddingHorizontal: 20,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: "#f0f0f0",
  },
  sheetResetBtn: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: "#ddd",
    alignItems: "center",
  },
  sheetResetText: { fontSize: 14, fontWeight: "800", color: "#555" },
  sheetApplyBtn: {
    flex: 2,
    paddingVertical: 14,
    borderRadius: 14,
    backgroundColor: RED,
    alignItems: "center",
  },
  sheetApplyText: { fontSize: 14, fontWeight: "900", color: "#fff" },

  // ── CATEGORIES CHIPS ───────────────────────────────────────────────────────
  catScroll: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    alignItems: "center",
    flexDirection: "row",
  },
  catChip: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#e0e0e0",
    marginRight: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  catChipActive: { backgroundColor: RED, borderColor: RED },
  catChipText: { fontSize: 13, fontWeight: "700", color: "#444" },
  catChipTextActive: { color: "#fff" },

  // ── RESULTS ROW ────────────────────────────────────────────────────────────
  resultsRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
    backgroundColor: "#fff",
  },
  resultsText: { fontSize: 13, color: "#555", fontWeight: "700" },
  sortLabel: { fontSize: 13, color: "#555", fontWeight: "600" },

  // ── MOBILE GRID ────────────────────────────────────────────────────────────
  mobileGrid: { paddingHorizontal: 16, paddingTop: 16 },
  mobileGridWrap: { flexDirection: "row", flexWrap: "wrap", gap: 16 },

  // ── MOBILE PRODUCT CARD ────────────────────────────────────────────────────
  cardMobile: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 14,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 6,
    elevation: 2,
    position: "relative",
    minWidth: 150,
    flex: 1,
  },
  badge: {
    position: "absolute",
    top: 12,
    left: 12,
    backgroundColor: RED,
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 6,
    zIndex: 2,
  },
  badgeText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  heartBtn: {
    position: "absolute",
    top: 12,
    right: 12,
    zIndex: 2,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: "#f0f0f0",
    justifyContent: "center",
    alignItems: "center",
  },
  imgWrap: {
    backgroundColor: "#f8f8f8",
    borderRadius: 10,
    height: 100,
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 12,
    padding: 6,
  },
  img: { width: "100%", height: "100%" },
  catLabel: { fontSize: 9, color: "#bbb", fontWeight: "700", marginBottom: 4 },
  cardName: { fontSize: 12, fontWeight: "800", color: "#111", marginBottom: 6 },
  cardPrice: { fontSize: 13, fontWeight: "900", color: RED, marginBottom: 10 },
  mobileCardFooter: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    marginTop: 4,
  },
  mobileQtyRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f5f5f5",
    borderRadius: 8,
    paddingHorizontal: 2,
    paddingVertical: 2,
    gap: 2,
  },
  mobileQtyBtn: {
    width: 26,
    height: 26,
    borderRadius: 7,
    backgroundColor: "#fff",
    justifyContent: "center",
    alignItems: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 1,
  },
  mobileQtyBtnText: { fontSize: 16, fontWeight: "700", color: "#333", lineHeight: 18 },
  mobileQtyText: { fontSize: 13, fontWeight: "800", color: "#111", minWidth: 20, textAlign: "center" },
  addBtnMobile: {
    backgroundColor: RED,
    width: 34,
    height: 34,
    borderRadius: 10,
    justifyContent: "center",
    alignItems: "center",
  },

  // ── NO RESULTS ─────────────────────────────────────────────────────────────
  noResults: { alignItems: "center", paddingTop: 60, gap: 12 },
  noResultsText: { fontSize: 14, color: "#bbb", textAlign: "center" },
});
