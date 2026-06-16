import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { useTheme } from "../context/ThemeContext";
import { useWishlist } from "../context/WishlistContext";
import { useLocation } from "../context/LocationContext";

// Altura fija del MobileHeader por debajo del safe area:
// paddingBottom(10) + locationRow(~36) + marginBottom(10) + searchRow(42) + border(1) = 99
export const MOBILE_HEADER_FIXED = 99;
import { getCategories, getProducts, getPromos } from "../services/api";
import LocationPickerModal from "../components/LocationPickerModal";
import LoginPromptSheet from "../components/LoginPromptSheet";
import ProductDetailModal from "../components/ProductDetailModal";

// ─── CONSTANTES ──────────────────────────────────────────────────────────────
const RED = "#243366";
const YELLOW = "#3c73b9";

// ─── DATA ────────────────────────────────────────────────────────────────────
// Las categorías se cargan desde la API (ver useHomeData)

// Marcas: reemplaza estas URLs con tus links reales de Cloudinary
const BRANDS = [
  {
    name: "Marca 1",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496685/QyW4qf4bS-uuEyqMcrlOS_xxupzg.webp",
  },
  {
    name: "Marca 2",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496686/8raVd8Ge171ERwyz9Nekf_i6qeim.webp",
  },
  {
    name: "Marca 3",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496686/aarfs_ilybpd.png",
  },
  {
    name: "Marca 4",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496685/vYWD8lIqjt3GIeKFTZaav_iuipju.webp",
  },
  {
    name: "Marca 5",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496685/coAP5yJmDus_5jMyJftPO_v1wlfj.webp",
  },
  {
    name: "Marca 6",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496685/EtMNQTFHzDJ_hvyuV7zkb_ndvqj4.webp",
  },
  {
    name: "Marca 7",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496684/ReymaLogoOficial_glqfgk.png",
  },
  {
    name: "Marca 8",
    img: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775496684/images_lxabhm.png",
  },
];

// ─── HOOK DATOS INICIO DESDE API ─────────────────────────────────────────────
function useHomeData() {
  const [categories, setCategories] = useState([]);
  const [allProducts, setAllProducts] = useState([]);
  const [featuredProducts, setFeaturedProducts] = useState([]);
  const [promos, setPromos] = useState([]);
  const [productsLoading, setProductsLoading] = useState(true);
  const [productsError, setProductsError] = useState(null);

  const load = useCallback(async () => {
    setProductsLoading(true);
    setProductsError(null);

    // Categorías
    getCategories()
      .then((res) => {
        if (res?.success && Array.isArray(res.data) && res.data.length > 0) {
          setCategories(res.data.map((c) => ({
            label: c.nombre,
            img:   null,
            name:  c.nombre,
          })));
        }
      })
      .catch(() => {});

    // Productos (todos para búsqueda, primeros 12 para destacados)
    try {
      const res = await getProducts();
      if (res?.success && Array.isArray(res.data) && res.data.length > 0) {
        const mapped = res.data.map((p) => {
          const precio = parseFloat(p.precio_venta ?? 0);
          const label  = p.presentacion ? `${p.concentracion ?? ""} ${p.presentacion}`.trim() : "";
          return {
            id:              p.id,
            cat:             p.categoria_nombre ?? null,
            name:            p.nombre,
            nombre_generico: p.nombre_generico ?? null,
            price:           label ? `$${precio.toFixed(2)} / ${label}` : `$${precio.toFixed(2)}`,
            price_numeric:   precio,
            img:             p.imagen_url ?? null,
            promo:           null,
            stock:           p.stock ?? null,
          };
        });
        setAllProducts(mapped);
        setFeaturedProducts(mapped.slice(0, 12));
      } else {
        setProductsError(res?.message || "No se pudieron cargar los productos");
      }
    } catch (e) {
      setProductsError(`Error de conexión: ${e?.message || "Sin internet"}`);
    } finally {
      setProductsLoading(false);
    }

    // Promos / banners
    getPromos()
      .then((res) => {
        if (res?.success && Array.isArray(res.data) && res.data.length > 0) {
          setPromos(res.data);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  return { categories, allProducts, featuredProducts, promos, productsLoading, productsError, reload: load };
}

// ─── PRODUCT CARD ─────────────────────────────────────────────────────────────
function ProductCard({ item, isDesktop, cardWidth, onPress }) {
  const [qty, setQty] = useState(1);
  const [added, setAdded] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const { addToCart, items } = useCart();
  const { toggleWishlist, isWishlisted } = useWishlist();
  const { t } = useTheme();
  const wishlisted = isWishlisted(item.id);

  const stockTracked = item.stock !== null && item.stock !== undefined;
  const isUnlimited  = item.stock === -1;
  const inCart    = items.find((i) => i.id === item.id)?.qty ?? 0;
  const available = isUnlimited ? Infinity : (stockTracked ? Math.max(0, item.stock - inCart) : Infinity);
  const agotado   = !isUnlimited && stockTracked && item.stock === 0;
  const atMax     = !isUnlimited && stockTracked && inCart >= item.stock;

  useEffect(() => {
    if (stockTracked && qty > available && available >= 1) setQty(available);
    if (stockTracked && available === 0) setQty(1);
  }, [available, stockTracked]);

  const handleAdd = (qtyToAdd = 1) => {
    if (agotado || atMax) return;
    const r = addToCart(item, qtyToAdd);
    if (r.authRequired) { setShowLogin(true); return; }
    if (r.ok) { setAdded(true); setTimeout(() => { setAdded(false); setQty(1); }, 900); }
  };

  if (!isDesktop) {
    return (
      <>
        <TouchableOpacity
          style={[styles.cardMobile, { width: cardWidth, backgroundColor: t.card }]}
          onPress={onPress}
          activeOpacity={0.85}
        >
          {item.promo && (
            <View style={styles.cardBadgeMobile}>
              <Text style={styles.badgeText}>{item.promo}</Text>
            </View>
          )}
          <TouchableOpacity
            style={styles.heartBtnMobile}
            onPress={(e) => { e.stopPropagation?.(); toggleWishlist(item); }}
            activeOpacity={0.7}
            hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
          >
            <Ionicons name={wishlisted ? "heart" : "heart-outline"} size={14} color={wishlisted ? RED : "#bbb"} />
          </TouchableOpacity>
          <View style={[styles.cardImgBgMobile, { backgroundColor: "#fff" }]}>
            <Image source={{ uri: item.img }} style={styles.cardImgMobile} resizeMode="contain" />
          </View>
          <View style={styles.cardInfoMobile}>
            <Text style={[styles.cardCatMobile, { color: t.textMuted }]}>{item.cat}</Text>
            <Text style={[styles.prodNameMobile, { color: t.text }]} numberOfLines={1}>{item.name}</Text>
            <Text style={styles.priceMobile}>{item.price}</Text>
            {stockTracked && item.stock > 0 && item.stock <= 5 && (
              <Text style={{ fontSize: 9, color: "#e65100", fontWeight: "700", marginTop: 1 }}>
                ¡Solo quedan {item.stock}!
              </Text>
            )}
            <View style={styles.cardFooterMobile}>
              <View style={[styles.mobileQtyRowHome, { backgroundColor: t.iconBg }]}>
                <TouchableOpacity
                  style={[styles.mobileQtyBtnHome, { backgroundColor: t.card }]}
                  onPress={(e) => { e.stopPropagation?.(); setQty(q => Math.max(1, q - 1)); }}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.mobileQtyBtnTextHome, { color: t.text }]}>−</Text>
                </TouchableOpacity>
                <Text style={[styles.mobileQtyTextHome, { color: t.text }]}>{qty}</Text>
                <TouchableOpacity
                  style={[styles.mobileQtyBtnHome, { backgroundColor: t.card }, (atMax || qty >= available) && { opacity: 0.35 }]}
                  onPress={(e) => {
                    e.stopPropagation?.();
                    if (stockTracked && qty >= available) return;
                    setQty(q => q + 1);
                  }}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.mobileQtyBtnTextHome, { color: t.text }]}>+</Text>
                </TouchableOpacity>
              </View>
              <TouchableOpacity
                style={[styles.addBtnMobile, added && { backgroundColor: "#4caf50" }, (agotado || atMax) && { backgroundColor: "#ccc" }]}
                onPress={(e) => { e.stopPropagation?.(); handleAdd(qty); }}
                disabled={agotado || atMax}
              >
                <Ionicons name={added ? "checkmark" : agotado || atMax ? "ban-outline" : "cart-outline"} size={14} color="white" />
              </TouchableOpacity>
            </View>
          </View>
        </TouchableOpacity>
        <LoginPromptSheet visible={showLogin} onClose={() => setShowLogin(false)} />
      </>
    );
  }

  return (
    <>
      <TouchableOpacity style={[styles.cardDesktop, { width: cardWidth, backgroundColor: t.card, borderColor: t.border }]} onPress={onPress} activeOpacity={0.9}>
        {item.promo && (
          <View style={styles.cardBadge}>
            <Text style={styles.badgeText}>{item.promo}</Text>
          </View>
        )}
        <TouchableOpacity
          style={styles.heartBtn}
          onPress={(e) => { e.stopPropagation?.(); toggleWishlist(item); }}
          activeOpacity={0.7}
        >
          <Ionicons name={wishlisted ? "heart" : "heart-outline"} size={18} color={wishlisted ? RED : "#999"} />
        </TouchableOpacity>
        <Image source={{ uri: item.img }} style={styles.cardImgDesktop} resizeMode="contain" />
        <Text style={[styles.cardCatDesktop, { color: t.textMuted }]}>{item.cat}</Text>
        <Text style={[styles.prodNameDesktop, { color: t.text }]}>{item.name}</Text>
        <Text style={styles.priceDesktop}>{item.price}</Text>
        {stockTracked && item.stock > 0 && item.stock <= 5 && (
          <Text style={{ fontSize: 10, color: "#e65100", fontWeight: "700", marginBottom: 2 }}>
            ¡Solo quedan {item.stock}!
          </Text>
        )}
        <View style={styles.cardFooterDesktop}>
          <View style={[styles.qtyControl, { backgroundColor: t.iconBg }]}>
            <TouchableOpacity onPress={(e) => { e.stopPropagation?.(); setQty(q => Math.max(1, q - 1)); }}>
              <Text style={styles.qtyBtn}>−</Text>
            </TouchableOpacity>
            <Text style={[styles.qtyText, { color: t.text }]}>{qty}</Text>
            <TouchableOpacity
              onPress={(e) => {
                e.stopPropagation?.();
                if (stockTracked && qty >= available) return;
                setQty(q => q + 1);
              }}
              style={(stockTracked && qty >= available) ? { opacity: 0.3 } : {}}
            >
              <Text style={styles.qtyBtn}>+</Text>
            </TouchableOpacity>
          </View>
          <TouchableOpacity
            style={[styles.addBtnDesktop, (agotado || atMax) && { backgroundColor: "#ccc" }]}
            onPress={(e) => { e.stopPropagation?.(); handleAdd(qty); }}
            disabled={agotado || atMax}
          >
            <Ionicons name={added ? "checkmark" : agotado || atMax ? "ban-outline" : "add"} size={18} color="white" />
          </TouchableOpacity>
        </View>
      </TouchableOpacity>
      <LoginPromptSheet visible={showLogin} onClose={() => setShowLogin(false)} />
    </>
  );
}

// ─── SEARCH BAR WITH AUTOCOMPLETE ────────────────────────────────────────────
function SearchBar({ products = [], onSelect, isDesktop }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [focused, setFocused] = useState(false);
  const { t } = useTheme();

  const handleChange = (text) => {
    setQuery(text);
    if (text.trim().length < 2) {
      setResults([]);
      return;
    }
    const q = text.toLowerCase();
    const filtered = products
      .filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.cat && p.cat.toLowerCase().includes(q))
      )
      .slice(0, 6);
    setResults(filtered);
  };

  const handleSelect = (item) => {
    setQuery("");
    setResults([]);
    setFocused(false);
    onSelect?.(item);
  };

  const showDropdown = focused && results.length > 0;

  const dropdown = showDropdown ? (
    <View style={[isDesktop ? searchStyles.desktopDropdown : searchStyles.mobileDropdown, { backgroundColor: t.card, borderColor: t.border }]}>
      {results.map((item) => (
        <TouchableOpacity
          key={item.id}
          style={[searchStyles.resultItem, { borderBottomColor: t.divider }]}
          onPress={() => handleSelect(item)}
        >
          {item.img ? (
            <Image
              source={{ uri: item.img }}
              style={[searchStyles.resultImg, { backgroundColor: "#fff" }]}
              resizeMode="contain"
            />
          ) : (
            <View style={[searchStyles.resultImg, { backgroundColor: t.input }]} />
          )}
          <View style={{ flex: 1 }}>
            <Text style={[searchStyles.resultName, { color: t.text }]} numberOfLines={1}>
              {item.name}
            </Text>
            <Text style={[searchStyles.resultCat, { color: t.textMuted }]}>{item.cat}</Text>
          </View>
          <Text style={searchStyles.resultPrice}>{item.price}</Text>
        </TouchableOpacity>
      ))}
    </View>
  ) : null;

  if (isDesktop) {
    return (
      <View style={[styles.desktopSearch, { zIndex: 200, backgroundColor: t.input }]}>
        <Ionicons name="search" size={18} color={t.textMuted} style={{ marginLeft: 16 }} />
        <TextInput
          value={query}
          onChangeText={handleChange}
          placeholder="Escribe lo que necesitas..."
          placeholderTextColor={t.placeholder}
          style={[styles.desktopSearchInput, { color: t.text }]}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 200)}
        />
        {query.length > 0 && (
          <TouchableOpacity
            onPress={() => { setQuery(""); setResults([]); }}
            style={{ paddingRight: 8 }}
          >
            <Ionicons name="close-circle" size={17} color="#bbb" />
          </TouchableOpacity>
        )}
        <TouchableOpacity style={styles.desktopSearchBtn}>
          <Ionicons name="search" size={18} color="#fff" />
        </TouchableOpacity>
        {dropdown}
      </View>
    );
  }

  return (
    <View style={{ flex: 1, zIndex: 200 }}>
      <View style={[styles.mobileSearch, { backgroundColor: t.input }]}>
        <Ionicons name="search" size={18} color={t.textMuted} style={{ marginLeft: 12 }} />
        <TextInput
          value={query}
          onChangeText={handleChange}
          placeholder="Escribe lo que necesitas..."
          style={[styles.mobileSearchInput, { color: t.text }]}
          placeholderTextColor={t.placeholder}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 200)}
        />
        {query.length > 0 && (
          <TouchableOpacity
            onPress={() => { setQuery(""); setResults([]); }}
            style={{ paddingRight: 10 }}
          >
            <Ionicons name="close-circle" size={17} color="#bbb" />
          </TouchableOpacity>
        )}
      </View>
      {dropdown}
    </View>
  );
}

const searchStyles = StyleSheet.create({
  desktopDropdown: {
    position: "absolute",
    top: 50,
    left: 0,
    right: 0,
    backgroundColor: "#fff",
    borderRadius: 12,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.13,
    shadowRadius: 20,
    elevation: 20,
    zIndex: 9999,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#f0f0f0",
  },
  mobileDropdown: {
    position: "absolute",
    top: 46,
    left: 0,
    right: 0,
    backgroundColor: "#fff",
    borderRadius: 12,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.13,
    shadowRadius: 20,
    elevation: 20,
    zIndex: 9999,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#f0f0f0",
  },
  resultItem: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#f5f5f5",
    gap: 12,
  },
  resultImg: {
    width: 42,
    height: 42,
    borderRadius: 8,
    backgroundColor: "#f9f9f9",
  },
  resultName: { fontSize: 13, fontWeight: "700", color: "#222" },
  resultCat: { fontSize: 10, color: "#aaa", fontWeight: "600", marginTop: 2 },
  resultPrice: { fontSize: 13, fontWeight: "800", color: "#243366" },
});

// ─── DESKTOP NAVBAR (STICKY) ──────────────────────────────────────────────────
export function DesktopNav({ onHomePress, onCartPress, onStorePress, onOrdersPress, onProfilePress, products, onProductSelect, onSettingsPress, activeTabIndex = 0, onNotifPress, unreadCount = 0, onFavPress }) {
  const { count } = useCart();
  const { wishlist } = useWishlist();
  const { user, signOut, signInWithGoogle } = useAuth();
  const { t } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);

  const firstName = user?.givenName || user?.name?.split(" ")[0] || user?.email?.split("@")[0] || "Mi cuenta";
  const favCount = wishlist?.length || 0;

  return (
    <View style={[styles.desktopNav, { zIndex: 200, backgroundColor: t.header, borderBottomColor: t.border }]}>
      <View style={[styles.desktopNavInner, styles.centeredContainer]}>
        <View style={styles.navLeft}>
          <Image source={require("../assets/images/logo.png")} style={styles.navLogo} resizeMode="contain" />
          <TouchableOpacity style={styles.navLink} onPress={onHomePress}>
            <Text style={[styles.navLinkText, { color: t.text }, activeTabIndex === 0 && { color: RED }]}>INICIO</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.navLink} onPress={onStorePress}>
            <Text style={[styles.navLinkText, { color: t.text }, activeTabIndex === 1 && { color: RED }]}>TIENDA</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.navLink} onPress={onOrdersPress}>
            <Text style={[styles.navLinkText, { color: t.text }, activeTabIndex === 2 && { color: RED }]}>PEDIDOS</Text>
          </TouchableOpacity>
        </View>

        <View style={{ flex: 1, marginHorizontal: 30, maxWidth: 600, zIndex: 200 }}>
          <SearchBar products={products} onSelect={onProductSelect} isDesktop={true} />
        </View>

        <View style={styles.navRight}>
          {/* Favoritos */}
          <TouchableOpacity style={styles.navIconBtn} onPress={onFavPress}>
            <View style={{ position: "relative" }}>
              <Ionicons name="heart" size={24} color={favCount > 0 ? RED : t.text} />
              {favCount > 0 && (
                <View style={styles.navCartBadge}>
                  <Text style={styles.navCartBadgeText}>{favCount}</Text>
                </View>
              )}
            </View>
          </TouchableOpacity>

          {/* Campana de notificaciones */}
          <TouchableOpacity style={styles.navIconBtn} onPress={onNotifPress}>
            <View style={{ position: "relative" }}>
              <Ionicons name="notifications" size={24} color={t.text} />
              {unreadCount > 0 && (
                <View style={styles.navCartBadge}>
                  <Text style={styles.navCartBadgeText}>{unreadCount > 9 ? "9+" : unreadCount}</Text>
                </View>
              )}
            </View>
          </TouchableOpacity>

          <TouchableOpacity style={styles.navIconBtn} onPress={onCartPress}>
            <View style={{ position: "relative" }}>
              <Ionicons name="cart-sharp" size={24} color={t.text} />
              {count > 0 && (
                <View style={styles.navCartBadge}>
                  <Text style={styles.navCartBadgeText}>{count > 9 ? "9+" : count}</Text>
                </View>
              )}
            </View>
          </TouchableOpacity>

          {user ? (
            <View style={{ position: "relative", zIndex: 300 }}>
              {/* Botón perfil — abre dropdown */}
              <TouchableOpacity
                style={[styles.userNavBtn, { backgroundColor: t.iconBg }, menuOpen && { backgroundColor: t.cardAlt }]}
                onPress={() => setMenuOpen((v) => !v)}
                activeOpacity={0.85}
              >
                <View style={styles.userNavAvatar}>
                  <Text style={styles.userNavAvatarText}>
                    {(user.givenName || user.name || "U")[0].toUpperCase()}
                  </Text>
                </View>
                <Text style={[styles.userNavName, { color: t.text }]} numberOfLines={1}>{firstName}</Text>
                <Ionicons
                  name={menuOpen ? "chevron-up" : "chevron-down"}
                  size={13}
                  color="#888"
                  style={{ marginLeft: 2 }}
                />
              </TouchableOpacity>

              {/* Dropdown */}
              {menuOpen && (
                <>
                  {/* Backdrop invisible */}
                  <TouchableOpacity
                    onPress={() => setMenuOpen(false)}
                    style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 298 }}
                  />
                  <View style={navDropdown.container}>
                    {/* Cabecera usuario */}
                    <View style={navDropdown.userRow}>
                      {user.photo ? (
                        <Image source={{ uri: user.photo }} style={navDropdown.avatarImg} />
                      ) : (
                        <View style={[navDropdown.avatarImg, { backgroundColor: RED, justifyContent: "center", alignItems: "center" }]}>
                          <Text style={{ color: "#fff", fontSize: 16, fontWeight: "900" }}>
                            {(user.givenName || user.name || "U")[0].toUpperCase()}
                          </Text>
                        </View>
                      )}
                      <View style={{ flex: 1 }}>
                        <Text style={navDropdown.userName} numberOfLines={1}>{user.name || firstName}</Text>
                        <Text style={navDropdown.userEmail} numberOfLines={1}>{user.email}</Text>
                      </View>
                    </View>

                    <View style={navDropdown.divider} />

                    {/* Configuración */}
                    <TouchableOpacity
                      style={navDropdown.item}
                      onPress={() => { setMenuOpen(false); onSettingsPress?.(); }}
                      activeOpacity={0.7}
                    >
                      <View style={navDropdown.itemIcon}>
                        <Ionicons name="settings-outline" size={17} color="#555" />
                      </View>
                      <Text style={navDropdown.itemText}>Configuración</Text>
                      <Ionicons name="chevron-forward" size={13} color="#ccc" />
                    </TouchableOpacity>

                    <View style={navDropdown.divider} />

                    {/* Cerrar sesión */}
                    <TouchableOpacity
                      style={navDropdown.item}
                      onPress={() => { setMenuOpen(false); signOut(); }}
                      activeOpacity={0.7}
                    >
                      <View style={[navDropdown.itemIcon, { backgroundColor: "#fff5f5" }]}>
                        <Ionicons name="log-out-outline" size={17} color={RED} />
                      </View>
                      <Text style={[navDropdown.itemText, { color: RED }]}>Cerrar sesión</Text>
                    </TouchableOpacity>
                  </View>
                </>
              )}
            </View>
          ) : (
            <TouchableOpacity style={styles.loginBtn} onPress={signInWithGoogle}>
              <Ionicons name="logo-google" size={16} color={RED} />
              <Text style={styles.loginText}>INICIAR SESIÓN</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    </View>
  );
}

const navDropdown = StyleSheet.create({
  container: {
    position: "absolute",
    top: 48,
    right: 0,
    width: 260,
    backgroundColor: "#fff",
    borderRadius: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.14,
    shadowRadius: 24,
    elevation: 24,
    zIndex: 999,
    borderWidth: 1,
    borderColor: "#f0f0f0",
    overflow: "hidden",
  },
  userRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    backgroundColor: "#fafafa",
  },
  avatarImg: {
    width: 40,
    height: 40,
    borderRadius: 20,
  },
  userName: { fontSize: 14, fontWeight: "800", color: "#111" },
  userEmail: { fontSize: 11, color: "#999", marginTop: 1 },
  divider: { height: 1, backgroundColor: "#f0f0f0" },
  item: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 13,
  },
  itemIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: "#f5f5f5",
    justifyContent: "center",
    alignItems: "center",
  },
  itemText: { flex: 1, fontSize: 14, fontWeight: "600", color: "#222" },
});

// ─── MOBILE FIXED HEADER ──────────────────────────────────────────────────────
export function MobileHeader({ onFavPress, onCartPress, cartCount = 0, products, onProductSelect, onFilterPress, onNotifPress, unreadCount = 0 }) {
  const { top: safeTop } = useSafeAreaInsets();
  const { wishlist } = useWishlist();
  const { address, coords, deliveryAddress, setDeliveryAddress, setDeliveryCoords, loading: locLoading, requestLocation } = useLocation();
  const { user } = useAuth();
  const { t } = useTheme();
  const [pickerVisible, setPickerVisible] = useState(false);

  const displayAddress = deliveryAddress || address;
  const favCount = wishlist?.length || 0;

  return (
    <View style={[styles.mobileHeaderFixed, { paddingTop: Math.max(safeTop, 20), backgroundColor: t.header, borderBottomColor: t.border }]}>
      {/* Fila superior: ubicación + íconos */}
      <View style={styles.mobileHeaderTop}>
        <TouchableOpacity
          style={styles.mobileLocation}
          onPress={() => setPickerVisible(true)}
          activeOpacity={0.7}
        >
          <Ionicons name="location-sharp" size={22} color={RED} />
          <View style={{ flex: 1, paddingHorizontal: 8 }}>
            <Text style={[styles.mobileWelcome, { color: t.text }]}>
              {user ? `HOLA, ${(user.givenName || user.name || user.email?.split('@')[0] || "USUARIO").toUpperCase()}` : "ENTREGAR EN"}
            </Text>
            <Text style={[styles.mobileAddress, { color: t.textMuted }]} numberOfLines={1}>
              {locLoading ? "Detectando ubicación..." : (displayAddress || "Selecciona tu dirección ›")}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={RED} />
        </TouchableOpacity>

        <View style={styles.mobileHeaderIcons}>
          <TouchableOpacity style={styles.headerIconBtn} onPress={onFavPress}>
            <Ionicons name="heart" size={24} color={favCount > 0 ? RED : t.text} />
            {favCount > 0 && (
              <View style={styles.cartBadge}>
                <Text style={styles.cartBadgeText}>{favCount > 9 ? "9+" : favCount}</Text>
              </View>
            )}
          </TouchableOpacity>
          <TouchableOpacity style={styles.headerIconBtn} onPress={onCartPress}>
            <Ionicons name="cart" size={24} color={t.text} />
            {cartCount > 0 && (
              <View style={styles.cartBadge}>
                <Text style={styles.cartBadgeText}>{cartCount > 9 ? "9+" : cartCount}</Text>
              </View>
            )}
          </TouchableOpacity>
          <TouchableOpacity style={styles.headerIconBtn} onPress={onNotifPress}>
            <Ionicons name="notifications" size={24} color={t.text} />
            {unreadCount > 0 && (
              <View style={styles.bellBadge}>
                <Text style={styles.bellBadgeText}>{unreadCount > 9 ? "9+" : unreadCount}</Text>
              </View>
            )}
          </TouchableOpacity>
        </View>
      </View>

      {/* Fila de búsqueda */}
      <View style={[styles.mobileSearchRow, { zIndex: 200 }]}>
        <SearchBar products={products} onSelect={onProductSelect} isDesktop={false} />
        <TouchableOpacity
          style={[styles.filterBtn, !onFilterPress && { opacity: 0.45 }]}
          onPress={onFilterPress || undefined}
          activeOpacity={0.8}
        >
          <Ionicons name="options" size={20} color="#fff" />
        </TouchableOpacity>
      </View>

      {/* Modal selector de ubicación */}
      <LocationPickerModal
        visible={pickerVisible}
        onClose={() => setPickerVisible(false)}
        onConfirm={(addr, pickedCoords) => { setDeliveryAddress(addr); setDeliveryCoords(pickedCoords); }}
        currentCoords={coords}
      />
    </View>
  );
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
export default function RappiStore({ onCartPress, onStorePress, onOrdersPress, onProfilePress, onSettingsPress, onCategoryPress }) {
  const { width } = useWindowDimensions();
  const { top: safeTop, bottom: safeBottom } = useSafeAreaInsets();
  const { t } = useTheme();
  const isDesktop = width >= 1024;
  const { categories, allProducts, featuredProducts, promos, productsLoading, productsError, reload } = useHomeData();
  const { address, coords, deliveryAddress, setDeliveryAddress, setDeliveryCoords, requestLocation, resetDeliveryAddress } = useLocation();
  const [locationPickerVisible, setLocationPickerVisible] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [activePromoIdx, setActivePromoIdx] = useState(0);
  const promoScrollRef = React.useRef(null);

  // Derivadas del carrusel — deben declararse ANTES de los useEffects que las usan
  const desktopCardWidth = 210;
  const gap = 16;
  const mobileCardWidth = (width - 16 * 2 - gap) / 2;
  const carouselW = Math.min(width, 1200);
  // 44px flecha × 2 + 8px margen × 2 + 16px gap entre banners = 120
  const desktopBannerW = Math.round((carouselW - 120) / 2);
  const desktopBannerH = Math.min(300, Math.round(desktopBannerW * 0.52));
  const desktopScrollStep = desktopBannerW + 16;

  // Auto-play carrusel
  React.useEffect(() => {
    if (isDesktop && promos.length > 1) {
      const interval = setInterval(() => {
        setActivePromoIdx((prev) => (prev + 1) % promos.length);
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [isDesktop, promos.length]);

  // Desplazamiento suave al cambiar slide
  React.useEffect(() => {
    if (isDesktop && promoScrollRef.current && promos.length > 0) {
      promoScrollRef.current.scrollTo({
        x: activePromoIdx * desktopScrollStep,
        animated: true,
      });
    }
  }, [activePromoIdx, isDesktop, promos.length, desktopScrollStep]);

  return (
    <View style={[styles.mainWrapper, { backgroundColor: t.bg }]}>
      {/* Navbar fija PC */}
      {/* DesktopNav is rendered globally in App.js */}

      {/* Header fijo móvil — renderizado globalmente desde App.js */}

      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingTop: isDesktop ? 0 : Math.max(safeTop, 20) + MOBILE_HEADER_FIXED + 8,
          paddingBottom: isDesktop ? 40 : safeBottom + 84,
        }}
      >
        {/* ── BANNER PRINCIPAL ── */}
        <View style={[styles.banner, isDesktop && styles.bannerDesktop]}>
          <View
            style={[
              styles.bannerInner,
              isDesktop && styles.centeredContainer,
              isDesktop && { paddingVertical: 50 },
            ]}
          >
            <View style={styles.bannerTextWrap}>
              <Text style={styles.bannerLine1}>TODO LO QUE TU</Text>
              <Text style={styles.bannerLine2}>NEGOCIO</Text>
              <Text style={styles.bannerLine3}>NECESITA</Text>

              {isDesktop ? (
                <View style={{ position: "relative", zIndex: 999 }}>
                  {/* Input de dirección — abre picker al tocar */}
                  <TouchableOpacity
                    style={styles.bannerLocationRow}
                    onPress={() => setLocationPickerVisible(!locationPickerVisible)}
                    activeOpacity={0.85}
                  >
                    <Ionicons
                      name="location-sharp"
                      size={20}
                      color="#666"
                      style={{ marginLeft: 15 }}
                    />
                    <Text
                      style={[styles.bannerLocationInput, { lineHeight: 20 }]}
                      numberOfLines={1}
                    >
                      {deliveryAddress && deliveryAddress !== "Mi ubicación actual"
                        ? deliveryAddress
                        : (address && address !== "Mi ubicación actual" && address !== "Detectando ubicación..."
                          ? address
                          : "¿Dónde quieres recibir tu compra?")}
                    </Text>
                    <View style={styles.ordenarBtnDesktop}>
                      <Text style={styles.ordenarBtnTextDesktop}>CAMBIAR</Text>
                    </View>
                  </TouchableOpacity>
                  <View style={styles.cambiarUbicacionRow}>
                    <TouchableOpacity style={styles.cambiarUbicacion} onPress={requestLocation}>
                      <Ionicons name="navigate" size={13} color="#fff" />
                      <Text style={styles.cambiarUbicacionText}>Usar mi ubicación GPS</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.cambiarUbicacion} onPress={() => setLocationPickerVisible(!locationPickerVisible)}>
                      <Ionicons name="map-outline" size={13} color="#fff" />
                      <Text style={styles.cambiarUbicacionText}>Elegir en el mapa</Text>
                    </TouchableOpacity>
                  </View>

                  {/* Popup picker PC — aparece debajo del botón */}
                  <LocationPickerModal
                    popup
                    visible={locationPickerVisible}
                    onClose={() => setLocationPickerVisible(false)}
                    onConfirm={(addr, pickedCoords) => { setDeliveryAddress(addr); setDeliveryCoords(pickedCoords); setLocationPickerVisible(false); }}
                    currentCoords={coords}
                  />
                </View>
              ) : (
                <TouchableOpacity style={styles.ordenarBtnMobile} onPress={onStorePress}>
                  <Text style={styles.ordenarBtnTextMobile}>ORDENAR AHORA</Text>
                </TouchableOpacity>
              )}
            </View>

            <Image
              source={{
                uri: "https://res.cloudinary.com/dfuzfdrat/image/upload/q_auto/f_auto/v1775497342/Sin_t_%CC%B8tulo-2_Recuperado_fpjpzz.png",
              }}
              style={[styles.bannerImg, isDesktop && styles.bannerImgDesktop]}
              resizeMode="contain"
            />
          </View>
        </View>

        {!isDesktop && (
          <View style={styles.dotsContainer}>
            <View style={[styles.dot, styles.dotActive]} />
            <View style={styles.dot} />
            <View style={styles.dot} />
          </View>
        )}

        {/* ── CATEGORÍAS ── */}
        {isDesktop ? (
          <View style={[styles.sectionDesktopWrap, styles.centeredContainer]}>
            <View style={styles.catHeader}>
              <Text style={[styles.sectionTitleDesktop, { color: t.text }]}>TODO POR CATEGORÍA</Text>
              <TouchableOpacity
                style={styles.todasBtnDesktop}
                onPress={() => onCategoryPress?.("all")}
              >
                <Text style={styles.todasBtnTextDesktop}>TODAS &gt;</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.catRowDesktop}>
              {categories.slice(0, 7).map((cat, i) => (
                <TouchableOpacity
                  key={i}
                  style={[styles.catItemDesktop, { backgroundColor: "#fff", borderColor: t.border }]}
                  onPress={() => onCategoryPress?.(cat.name)}
                  activeOpacity={0.8}
                >
                  <Image
                    source={{ uri: cat.img }}
                    style={styles.catImgDesktop}
                    resizeMode="contain"
                  />
                  <Text style={[styles.catLabelDesktop, { color: t.text }]}>
                    {cat.label.toUpperCase()}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ) : (
          <View style={styles.sectionMobileWrap}>
            <Text style={[styles.sectionTitleMobile, { marginBottom: 12, color: t.text }]}>CATEGORÍAS</Text>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              style={{ marginHorizontal: -16 }}
              contentContainerStyle={styles.catScrollMobile}
            >
              {categories.map((cat, i) => (
                <TouchableOpacity
                  key={i}
                  style={[styles.catPillChip, { backgroundColor: t.card, borderColor: t.border }]}
                  onPress={() => onCategoryPress?.(cat.name)}
                  activeOpacity={0.75}
                >
                  <Text style={[styles.catPillChipText, { color: t.text }]}>{cat.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        )}

        {/* ── LO MÁS COMPRADO ── */}
        <View
          style={[
            { marginTop: isDesktop ? 40 : 20 },
            isDesktop && styles.centeredContainer,
          ]}
        >
          <Text
            style={[
              isDesktop
                ? styles.sectionTitleDesktop
                : styles.sectionTitleMobile,
              { marginBottom: 16, paddingHorizontal: isDesktop ? 0 : 16, color: t.text },
            ]}
          >
            {isDesktop ? "LO MÁS COMPRADO" : "LO MÁS PEDIDO"}
          </Text>

          {isDesktop ? (
            // PC: scroll horizontal
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ gap: 16, paddingBottom: 10 }}
            >
              {featuredProducts.map((item) => (
                <ProductCard
                  key={item.id}
                  item={item}
                  isDesktop={true}
                  cardWidth={desktopCardWidth}
                  onPress={() => setSelectedProduct(item)}
                />
              ))}
            </ScrollView>
          ) : (
            // Móvil: grid 2 columnas con wrap
            <View>
              {productsLoading ? (
                <View style={{ alignItems: "center", paddingVertical: 32 }}>
                  <ActivityIndicator size="large" color={RED} />
                  <Text style={{ color: t.textMuted, marginTop: 10, fontSize: 13 }}>Cargando productos...</Text>
                </View>
              ) : productsError ? (
                <View style={styles.errorState}>
                  <View style={styles.errorIconCircle}>
                    <Ionicons name="storefront-outline" size={38} color={RED} />
                  </View>
                  <Text style={[styles.errorTitle, { color: t.text }]}>No pudimos cargar los productos</Text>
                  <Text style={[styles.errorSubtitle, { color: t.textMuted }]}>Revisa tu conexión e intenta de nuevo</Text>
                  <TouchableOpacity onPress={reload} style={styles.retryBtn} activeOpacity={0.85}>
                    <Ionicons name="refresh-outline" size={16} color="#fff" />
                    <Text style={styles.retryBtnText}>Reintentar</Text>
                  </TouchableOpacity>
                </View>
              ) : (
                <>
                  <View style={styles.mobileProductsGrid}>
                    {featuredProducts.slice(0, 8).map((item) => (
                      <ProductCard
                        key={item.id}
                        item={item}
                        isDesktop={false}
                        onPress={() => setSelectedProduct(item)}
                        cardWidth={mobileCardWidth}
                      />
                    ))}
                  </View>
                  {featuredProducts.length > 0 && (
                    <TouchableOpacity
                      style={{
                        marginHorizontal: 16, marginTop: 12, backgroundColor: RED,
                        borderRadius: 14, paddingVertical: 14,
                        alignItems: "center", flexDirection: "row",
                        justifyContent: "center", gap: 8,
                      }}
                      onPress={onStorePress}
                      activeOpacity={0.85}
                    >
                      <Ionicons name="grid-outline" size={18} color="#fff" />
                      <Text style={{ color: "#fff", fontWeight: "900", fontSize: 14, letterSpacing: 1 }}>
                        VER TODOS LOS PRODUCTOS
                      </Text>
                    </TouchableOpacity>
                  )}
                </>
              )}
            </View>
          )}
        </View>

        {/* ── CARRUSEL BANNERS PROMOCIONES ── */}
        {promos.length > 0 && (
          <View style={styles.promoCarouselContainer}>
            {isDesktop ? (
              <View style={{ width: carouselW, alignSelf: "center" }}>
                {/* Fila: [← flecha] [banners] [flecha →] */}
                <View style={{ flexDirection: "row", alignItems: "center" }}>
                  <TouchableOpacity
                    style={[styles.carouselNavBtn, { marginRight: 8, opacity: promos.length > 1 ? 1 : 0 }]}
                    onPress={() => setActivePromoIdx(prev => (prev - 1 + promos.length) % promos.length)}
                    disabled={promos.length <= 1}
                    activeOpacity={0.8}
                  >
                    <Ionicons name="chevron-back" size={22} color="#fff" />
                  </TouchableOpacity>

                  <ScrollView
                    ref={promoScrollRef}
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    scrollEnabled={false}
                    style={{ flex: 1, height: desktopBannerH }}
                    contentContainerStyle={{ gap: 16 }}
                  >
                    {promos.map((p, idx) => (
                      <Image
                        key={`${p.id}-${idx}`}
                        source={{ uri: p.image_url }}
                        style={{ width: desktopBannerW, height: desktopBannerH, borderRadius: 16 }}
                        resizeMode="cover"
                      />
                    ))}
                  </ScrollView>

                  <TouchableOpacity
                    style={[styles.carouselNavBtn, { marginLeft: 8, opacity: promos.length > 1 ? 1 : 0 }]}
                    onPress={() => setActivePromoIdx(prev => (prev + 1) % promos.length)}
                    disabled={promos.length <= 1}
                    activeOpacity={0.8}
                  >
                    <Ionicons name="chevron-forward" size={22} color="#fff" />
                  </TouchableOpacity>
                </View>

                {/* Dots debajo */}
                <View style={styles.promoDotsRow}>
                  {promos.map((_, i) => (
                    <TouchableOpacity
                      key={i}
                      onPress={() => setActivePromoIdx(i)}
                      style={[styles.promoDot, activePromoIdx === i && styles.promoDotActive]}
                    />
                  ))}
                </View>
              </View>
            ) : (
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.promoBannersScrollMobile}
              >
                {promos.map((p, idx) => (
                  <TouchableOpacity key={`${p.id}-${idx}`} activeOpacity={0.92}>
                    <Image
                      source={{ uri: p.image_url }}
                      style={styles.promoImgMobile}
                      resizeMode="cover"
                    />
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}
          </View>
        )}


        {/* ── SOLO PC: MARCAS DESTACADAS (carga desde Cloudinary) ── */}
        {isDesktop && (
          <View style={[styles.brandsSection, styles.centeredContainer]}>
            <Text style={[styles.sectionTitleDesktop, { color: t.text }]}>MARCAS DESTACADAS</Text>
            <View style={styles.brandsCarouselWrap}>
              <TouchableOpacity
                style={[styles.carouselArrow, { backgroundColor: RED }]}
              >
                <Ionicons name="chevron-back" size={20} color="#fff" />
              </TouchableOpacity>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.brandsScroll}
              >
                {BRANDS.map((brand, index) => (
                  <View key={index} style={[styles.brandLogoWrap, { backgroundColor: t.card, borderColor: t.border }]}>
                    <Image
                      source={{ uri: brand.img }}
                      style={styles.brandLogo}
                      resizeMode="contain"
                      // Cloudinary entrega imágenes optimizadas automáticamente
                    />
                  </View>
                ))}
              </ScrollView>
              <TouchableOpacity
                style={[styles.carouselArrow, { backgroundColor: RED }]}
              >
                <Ionicons name="chevron-forward" size={20} color="#fff" />
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* ── SOLO PC: BANNERS APP + DOMICILIO ── */}
        {isDesktop && (
          <View style={[styles.appPromoSection, styles.centeredContainer]}>
            <Image
              source={{
                uri: "https://res.cloudinary.com/TU_CLOUD/image/upload/banner-app.jpg",
              }}
              style={styles.appPromoBannerImg}
              resizeMode="cover"
            />
            <Image
              source={{
                uri: "https://res.cloudinary.com/TU_CLOUD/image/upload/banner-domicilio.jpg",
              }}
              style={styles.appPromoBannerImg}
              resizeMode="cover"
            />
          </View>
        )}

        {/* ── SOLO PC: FOOTER ── */}
        {isDesktop && (
          <View style={styles.footerContainer}>
            <View style={[styles.footerInner, styles.centeredContainer]}>
              {/* Columna 1: Logo + descripción + pagos */}
              <View style={styles.footerCol}>
                <View style={styles.footerLogoWrap}>
                  <Image source={require("../assets/images/logo.png")} style={styles.footerLogoImg} resizeMode="contain" />
                </View>
                <Text style={styles.footerDesc}>
                  Somos una distribuidora líder de productos esenciales,
                  destinada a satisfacer las necesidades de todo tipo de
                  negocios.
                </Text>
                <Text style={styles.footerSubtitle}>MÉTODOS DE PAGO</Text>
                <View style={styles.paymentMethodsRow}>
                  {["VISA", "MC", "AMEX"].map((p) => (
                    <View key={p} style={styles.payBadge}>
                      <Text style={styles.payBadgeText}>{p}</Text>
                    </View>
                  ))}
                </View>
              </View>

              {/* Columna 2: Políticas + newsletter */}
              <View style={styles.footerCol}>
                <Text style={styles.footerTitle}>POLÍTICAS DE LA TIENDA</Text>
                {[
                  "Políticas de entrega",
                  "Términos y Condiciones",
                  "Aviso de Privacidad",
                  "Devoluciones",
                ].map((l) => (
                  <Text key={l} style={styles.footerLink}>
                    {l}
                  </Text>
                ))}
                <Text style={[styles.footerTitle, { marginTop: 20 }]}>
                  Recibe ofertas exclusivas
                </Text>
                <View style={styles.newsletterRow}>
                  <TextInput
                    placeholder="Ingresa tu correo"
                    style={styles.newsletterInput}
                  />
                  <TouchableOpacity style={styles.newsletterBtn}>
                    <Text style={styles.newsletterBtnText}>Enviar</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* Columna 3: Links */}
              <View style={styles.footerCol}>
                <Text style={styles.footerTitle}>TODO PAL NEGOCIO</Text>
                {[
                  "Inicio",
                  "Productos",
                  "Ofertas",
                  "Cómo comprar",
                  "Quiénes somos",
                ].map((l) => (
                  <Text key={l} style={styles.footerLink}>
                    {l}
                  </Text>
                ))}
                <Text style={[styles.footerTitle, { marginTop: 20 }]}>
                  AYUDA
                </Text>
                <Text style={styles.footerLink}>Mi cuenta</Text>
              </View>

              {/* Columna 4: Contacto + redes */}
              <View style={styles.footerCol}>
                <Text style={styles.footerTitle}>CONTÁCTANOS</Text>
                <Text style={styles.footerLink}>Sucursales</Text>
                <Text style={[styles.footerLink, { fontWeight: "700" }]}>
                  atencionaclientes@todopalnegocio.com.mx
                </Text>
                <Text style={[styles.footerTitle, { marginTop: 20 }]}>
                  SÍGUENOS EN NUESTRAS REDES
                </Text>
                <View style={styles.socialRow}>
                  <Ionicons name="logo-facebook" size={24} color="#000" />
                  <Ionicons name="logo-tiktok" size={24} color="#000" />
                  <Ionicons name="logo-instagram" size={24} color="#000" />
                  <Ionicons name="logo-linkedin" size={24} color="#000" />
                </View>
              </View>
            </View>

            <View style={styles.footerBottomBar}>
              <Text style={styles.footerCopyright}>
                Copyright © TODO PAL NEGOCIO. Todos los derechos reservados.
              </Text>
            </View>
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

// ─── STYLES ──────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  mainWrapper: {
    flex: 1,
    backgroundColor: "#fff",
  },

  centeredContainer: {
    maxWidth: 1200,
    width: "100%",
    alignSelf: "center",
    paddingHorizontal: 20,
  },

  // ── PC NAVBAR (sticky) ──────────────────────────────────────────────────────
  desktopNav: {
    backgroundColor: "#fff",
    zIndex: 200,
    borderBottomWidth: 1,
    borderBottomColor: "#eee",
    ...Platform.select({ web: { position: "sticky", top: 0 } }),
  },
  desktopNavInner: {
    flexDirection: "row",
    alignItems: "center",
    height: 70,
    justifyContent: "space-between",
  },
  navLeft: { flexDirection: "row", alignItems: "center" },
  navLogo: {
    width: 44,
    height: 44,
    marginRight: 20,
  },
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
  desktopSearchInput: { flex: 1, paddingHorizontal: 15, fontSize: 14, outlineWidth: 0 },
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
  navLocationWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    backgroundColor: "#f8f8f8",
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 10,
    maxWidth: 200,
  },
  navLocationText: { fontSize: 11, color: "#555", flex: 1 },
  loginBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10, borderWidth: 1.5, borderColor: "#eee" },
  loginText: { fontSize: 13, fontWeight: "800", color: RED },
  userNavBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 10, backgroundColor: "#f5f5f5" },
  userNavAvatar: { width: 28, height: 28, borderRadius: 14, backgroundColor: RED, justifyContent: "center", alignItems: "center" },
  userNavAvatarText: { color: "#fff", fontWeight: "900", fontSize: 13 },
  userNavName: { fontSize: 13, fontWeight: "700", color: "#333", maxWidth: 100 },

  // ── MÓVIL HEADER FIJO ────────────────────────────────────────────────────────
  mobileHeaderFixed: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 200,
    backgroundColor: "#fff",
    paddingHorizontal: 16,
    paddingBottom: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 6,
    elevation: 4,
  },
  mobileHeaderTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
  },
  mobileLocation: {
    flexDirection: "row",
    alignItems: "center",
    flex: 1,
    paddingRight: 10,
  },
  mobileWelcome: { fontSize: 12, fontWeight: "900", color: "#000" },
  mobileAddress: { fontSize: 10, color: "#666", fontWeight: "500" },
  mobileHeaderIcons: { flexDirection: "row", gap: 12 },
  headerIconBtn: { position: "relative" },
  bellBadge: {
    position: "absolute",
    top: -2,
    right: -4,
    backgroundColor: RED,
    width: 14,
    height: 14,
    borderRadius: 7,
    justifyContent: "center",
    alignItems: "center",
    zIndex: 1,
  },
  bellBadgeText: { color: "#fff", fontSize: 9, fontWeight: "bold" },
  cartBadge: {
    position: "absolute",
    top: -4,
    right: -6,
    backgroundColor: RED,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 3,
    zIndex: 1,
    borderWidth: 1.5,
    borderColor: "#fff",
  },
  cartBadgeText: { color: "#fff", fontSize: 9, fontWeight: "800" },
  mobileSearchRow: { flexDirection: "row", gap: 10 },
  mobileSearch: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f5f5f5",
    borderRadius: 10,
    height: 42,
  },
  mobileSearchInput: {
    flex: 1,
    paddingHorizontal: 10,
    fontSize: 13,
    color: "#333",
    outlineWidth: 0,
  },
  filterBtn: {
    backgroundColor: RED,
    width: 42,
    height: 42,
    borderRadius: 10,
    justifyContent: "center",
    alignItems: "center",
  },

  // ── BANNER ────────────────────────────────────────────────────────────────────
  banner: {
    backgroundColor: RED,
    marginHorizontal: 16,
    borderRadius: 20,
    overflow: "hidden",
  },
  bannerDesktop: {
    marginHorizontal: 0,
    borderRadius: 0,
    minHeight: 360,
    justifyContent: "center",
  },
  bannerInner: { flexDirection: "row", alignItems: "center", padding: 24 },
  bannerTextWrap: { flex: 1, zIndex: 2 },
  bannerLine1: { color: "#fff", fontSize: 16, fontWeight: "800" },
  bannerLine2: {
    color: "#fff",
    fontSize: 34,
    fontWeight: "900",
    lineHeight: 36,
  },
  bannerLine3: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "800",
    marginBottom: 18,
  },
  ordenarBtnMobile: {
    backgroundColor: "#fff",
    alignSelf: "flex-start",
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 25,
  },
  ordenarBtnTextMobile: { color: RED, fontWeight: "900", fontSize: 13 },
  bannerImg: {
    width: 140,
    height: 110,
    position: "absolute",
    right: 8,
    bottom: 0,
  },
  bannerImgDesktop: {
    width: "42%",
    height: 360,
    position: "relative",
    right: 0,
  },
  bannerLocationRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#fff",
    borderRadius: 30,
    maxWidth: 460,
    height: 50,
  },
  bannerLocationInput: {
    flex: 1,
    paddingHorizontal: 10,
    fontSize: 14,
    color: "#333",
  },
  ordenarBtnDesktop: {
    backgroundColor: "#000",
    height: 50,
    paddingHorizontal: 28,
    borderTopRightRadius: 30,
    borderBottomRightRadius: 30,
    justifyContent: "center",
  },
  ordenarBtnTextDesktop: { color: "#fff", fontWeight: "800", fontSize: 14 },
  cambiarUbicacionRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 10,
    marginLeft: 15,
    gap: 16,
  },
  cambiarUbicacion: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
  },
  cambiarUbicacionClear: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  cambiarUbicacionText: { color: "#fff", fontSize: 12, fontWeight: "600" },

  // ── DOTS ─────────────────────────────────────────────────────────────────────
  dotsContainer: {
    flexDirection: "row",
    justifyContent: "center",
    marginVertical: 14,
    gap: 8,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: RED,
    opacity: 0.4,
  },
  dotActive: { opacity: 1 },

  // ── SECCIONES ─────────────────────────────────────────────────────────────────
  sectionDesktopWrap: { marginTop: 36 },
  sectionMobileWrap: { paddingHorizontal: 16, marginTop: 4 },
  catHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  sectionTitleDesktop: {
    fontSize: 20,
    fontWeight: "900",
    color: "#222",
    textAlign: "center",
    flex: 1,
  },
  sectionTitleMobile: { fontSize: 15, fontWeight: "900", color: "#000" },
  todasBtnDesktop: {
    position: "absolute",
    right: 0,
    backgroundColor: RED,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  todasBtnTextDesktop: { color: "#fff", fontWeight: "800", fontSize: 12 },
  verTodoBtnMobile: {
    backgroundColor: RED,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  verTodoTextMobile: { color: "#fff", fontWeight: "800", fontSize: 11 },

  // ── CATEGORÍAS ────────────────────────────────────────────────────────────────
  catScrollMobile: {
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 4,
  },
  catPillChip: {
    backgroundColor: "#fff",
    borderWidth: 1.5,
    borderColor: "#e8e8e8",
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 9,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },
  catPillChipText: { fontSize: 13, fontWeight: "700", color: "#222" },
  catRowDesktop: {
    flexDirection: "row",
    paddingVertical: 10,
    marginHorizontal: -6,
  },
  catCarouselWrap: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
  },
  carouselArrow: {
    width: 30,
    height: 30,
    borderRadius: 15,
    justifyContent: "center",
    alignItems: "center",
    marginHorizontal: 8,
  },
  catScrollDesktop: { gap: 16, paddingVertical: 10 },
  catItemDesktop: {
    flex: 1,
    minWidth: 0,
    height: 160,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#eaeaea",
    borderRadius: 16,
    justifyContent: "center",
    alignItems: "center",
    padding: 10,
    marginHorizontal: 6,
    elevation: 2,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
  },
  catImgDesktop: { width: 72, height: 72, marginBottom: 10 },
  catLabelDesktop: {
    color: "#333",
    fontSize: 12,
    fontWeight: "800",
    textAlign: "center",
  },

  // ── ERROR STATE ───────────────────────────────────────────────────────────────
  errorState: {
    alignItems: "center",
    paddingVertical: 40,
    paddingHorizontal: 32,
  },
  errorIconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: "#fff5f5",
    borderWidth: 2,
    borderColor: "#ffd0d4",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 18,
  },
  errorTitle: {
    fontSize: 16,
    fontWeight: "800",
    color: "#222",
    textAlign: "center",
    marginBottom: 6,
  },
  errorSubtitle: {
    fontSize: 13,
    color: "#999",
    textAlign: "center",
    marginBottom: 22,
    lineHeight: 19,
  },
  retryBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: RED,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 24,
  },
  retryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },

  // ── PRODUCTOS GRID MÓVIL ──────────────────────────────────────────────────────
  mobileProductsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    gap: 16,
  },

  // ── PRODUCT CARD ──────────────────────────────────────────────────────────────
  cardMobile: {
    backgroundColor: "#f6f6f6",
    borderRadius: 14,
    padding: 12,
    marginBottom: 0,
    position: "relative",
  },
  cardBadgeMobile: {
    position: "absolute",
    top: 10,
    left: 10,
    backgroundColor: RED,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    zIndex: 1,
  },
  heartBtnMobile: {
    position: "absolute",
    top: 10,
    right: 10,
    zIndex: 2,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: "rgba(255,255,255,0.9)",
    justifyContent: "center",
    alignItems: "center",
  },
  cardImgBgMobile: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 8,
    marginBottom: 10,
  },
  cardImgMobile: { width: "100%", height: 90 },
  cardInfoMobile: {},
  cardCatMobile: {
    fontSize: 9,
    color: "#aaa",
    fontWeight: "700",
    marginBottom: 4,
  },
  prodNameMobile: {
    fontSize: 12,
    fontWeight: "900",
    color: "#000",
    marginBottom: 2,
  },
  cardFooterMobile: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 6,
  },
  priceMobile: { fontSize: 13, fontWeight: "900", color: RED, marginTop: 4 },
  mobileQtyRowHome: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 8,
    overflow: "hidden",
  },
  mobileQtyBtnHome: {
    width: 24,
    height: 24,
    justifyContent: "center",
    alignItems: "center",
  },
  mobileQtyBtnTextHome: { fontSize: 14, fontWeight: "700" },
  mobileQtyTextHome: { width: 20, textAlign: "center", fontSize: 12, fontWeight: "700" },
  addBtnMobile: {
    backgroundColor: RED,
    width: 30,
    height: 30,
    borderRadius: 15,
    justifyContent: "center",
    alignItems: "center",
  },

  cardDesktop: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#eaeaea",
    borderRadius: 14,
    padding: 15,
    position: "relative",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 6,
    elevation: 2,
  },
  cardBadge: {
    position: "absolute",
    top: 10,
    left: 10,
    backgroundColor: RED,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    zIndex: 1,
  },
  badgeText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  heartBtn: { position: "absolute", top: 10, right: 10, zIndex: 1 },
  cardImgDesktop: { width: "100%", height: 110, marginBottom: 10 },
  cardCatDesktop: {
    fontSize: 10,
    color: "#bbb",
    fontWeight: "700",
    marginBottom: 2,
  },
  prodNameDesktop: {
    fontSize: 13,
    fontWeight: "800",
    color: "#222",
    marginBottom: 6,
  },
  priceDesktop: {
    fontSize: 13,
    fontWeight: "800",
    color: RED,
    marginBottom: 10,
  },
  cardFooterDesktop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  qtyControl: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f5f5f5",
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 3,
  },
  qtyBtn: { fontSize: 16, color: RED, fontWeight: "900", paddingHorizontal: 5 },
  qtyText: { fontSize: 13, fontWeight: "700", marginHorizontal: 6 },
  addBtnDesktop: {
    backgroundColor: RED,
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: "center",
    alignItems: "center",
  },

  // ── PROMOS ────────────────────────────────────────────────────────────────────
  promoCarouselContainer: { marginTop: 24, marginBottom: 30 },
  promoBannersScrollMobile: { paddingHorizontal: 16, gap: 14 },
  promoImgMobile: {
    width: 320,
    height: 160,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#f0f0f0",
  },
  promoDotsRow: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 10,
    marginTop: 14,
  },
  promoDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#ddd",
  },
  promoDotActive: {
    width: 28,
    backgroundColor: RED,
  },
  carouselNavBtn: {
    backgroundColor: RED,
    width: 44,
    height: 44,
    borderRadius: 22,
    justifyContent: "center",
    alignItems: "center",
    flexShrink: 0,
  },

  // ── MARCAS (con Cloudinary) ───────────────────────────────────────────────────
  brandsSection: { paddingVertical: 30 },
  brandsCarouselWrap: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 20,
  },
  brandsScroll: { gap: 16, alignItems: "center", paddingHorizontal: 10 },
  brandLogoWrap: {
    width: 110,
    height: 60,
    backgroundColor: "#f9f9f9",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#eee",
    justifyContent: "center",
    alignItems: "center",
    padding: 8,
  },
  brandLogo: { width: "100%", height: "100%" },

  // ── APP PROMO ─────────────────────────────────────────────────────────────────
  appPromoSection: { flexDirection: "row", gap: 20, marginBottom: 50 },
  appPromoBannerImg: {
    flex: 1,
    height: 260,
    borderRadius: 16,
    backgroundColor: "#f0f0f0",
  },

  // ── FOOTER ────────────────────────────────────────────────────────────────────
  footerContainer: {
    backgroundColor: "#f9f9f9",
    borderTopWidth: 1,
    borderTopColor: "#eee",
    width: "100%",
  },
  footerInner: {
    flexDirection: "row",
    paddingVertical: 50,
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 30,
  },
  footerCol: { flex: 1, minWidth: 200 },
  footerLogoWrap: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 14,
  },
  footerLogoImg: {
    width: 80,
    height: 50,
    marginBottom: 4,
  },
  footerBrandText: {
    fontSize: 17,
    fontWeight: "900",
    color: RED,
    lineHeight: 19,
  },
  footerDesc: { fontSize: 12, color: "#666", marginBottom: 18, lineHeight: 18 },
  footerSubtitle: {
    fontSize: 11,
    fontWeight: "800",
    color: "#333",
    marginBottom: 10,
  },
  paymentMethodsRow: { flexDirection: "row", gap: 8 },
  payBadge: {
    borderWidth: 1,
    borderColor: "#ccc",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
    backgroundColor: "#fff",
  },
  payBadgeText: { fontSize: 10, fontWeight: "800", color: "#555" },
  footerTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: "#000",
    marginBottom: 12,
  },
  footerLink: { fontSize: 12, color: "#555", marginBottom: 8 },
  newsletterRow: { flexDirection: "row", marginTop: 5 },
  newsletterInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#ddd",
    borderTopLeftRadius: 6,
    borderBottomLeftRadius: 6,
    paddingHorizontal: 10,
    height: 38,
    fontSize: 12,
    backgroundColor: "#fff",
    outlineWidth: 0,
  },
  newsletterBtn: {
    backgroundColor: RED,
    paddingHorizontal: 18,
    borderTopRightRadius: 6,
    borderBottomRightRadius: 6,
    justifyContent: "center",
  },
  newsletterBtnText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  socialRow: { flexDirection: "row", gap: 14, marginTop: 6 },
  footerBottomBar: {
    backgroundColor: RED,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  footerCopyright: { fontSize: 12, color: "#fff", fontWeight: "600" },
});
