import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  FlatList,
  Image,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useCart } from "../context/CartContext";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import LoginPromptSheet from "./LoginPromptSheet";
import { getProduct } from "../services/api";

const RED = "#e6192e";
const { width: SCREEN_W } = Dimensions.get("window");
const IMG_H = 280;

export default function ProductDetailModal({ visible, product, onClose }) {
  const { t, isDark } = useTheme();
  const { addToCart, items } = useCart();
  const { user } = useAuth();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeImg, setActiveImg] = useState(0);
  const [qty, setQty] = useState(1);
  const [added, setAdded] = useState(false);
  const [stockMsg, setStockMsg] = useState("");
  const [showLogin, setShowLogin] = useState(false);
  const flatRef = useRef(null);
  const lastTapRef = useRef(0);

  const handleDoubleTap = () => {
    const now = Date.now();
    if (now - lastTapRef.current < 350) {
      onClose();
      lastTapRef.current = 0;
    } else {
      lastTapRef.current = now;
    }
  };

  useEffect(() => {
    if (!visible || !product) return;
    setDetail(null);
    setActiveImg(0);
    setQty(1);
    setAdded(false);
    setStockMsg("");
    setLoading(true);
    getProduct(product.id)
      .then((res) => {
        if (res?.success && res.data) setDetail(res.data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [visible, product?.id]);

  // Stock real viene del detalle (BD). Mientras carga usamos el del listado.
  const stock = detail?.stock ?? product?.stock ?? null;
  const stockTracked = stock !== null;
  const isUnlimited  = stock === -1;
  const inCartQty = items.find((i) => i.id === product?.id)?.qty ?? 0;
  const available = isUnlimited ? Infinity : (stockTracked ? Math.max(0, stock - inCartQty) : Infinity);
  const isAgotado = !isUnlimited && stockTracked && stock === 0;
  const atMax     = !isUnlimited && stockTracked && inCartQty >= stock;

  const changeQty = (delta) => {
    setStockMsg("");
    const next = qty + delta;
    if (next < 1) return;
    if (!isUnlimited && stockTracked && next > available) {
      setStockMsg(
        available === 0
          ? "Ya tienes todo el stock disponible en tu carrito"
          : `Solo puedes agregar ${available} más`
      );
      return;
    }
    setQty(next);
  };

  const handleAdd = () => {
    const result = addToCart({ ...product, stock }, qty);
    if (result.authRequired) { setShowLogin(true); return; }
    if (!result.ok) {
      setStockMsg(result.message);
      return;
    }
    if (stockTracked && result.added < qty) {
      setStockMsg(`Solo se agregaron ${result.added} (stock máximo alcanzado)`);
    }
    setAdded(true);
    setTimeout(() => { setAdded(false); setStockMsg(""); }, 1800);
  };

  if (!product) return null;

  const images = detail?.extra_images?.length
    ? [detail.image_url || product.img, ...detail.extra_images]
    : [detail?.image_url || product.img];

  const isDesktop = Platform.OS === "web" && SCREEN_W > 768;
  const cardW = isDesktop ? Math.min(520, SCREEN_W * 0.5) : SCREEN_W;

  return (
    <>
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      statusBarTranslucent
      onRequestClose={onClose}
    >
      {/* Backdrop — doble toque para cerrar */}
      <TouchableOpacity
        style={[styles.backdrop, { backgroundColor: t.overlay }]}
        activeOpacity={1}
        onPress={handleDoubleTap}
      />

      {/* Card — doble toque en cualquier parte para cerrar */}
      <Pressable
        style={[styles.card, isDesktop && styles.cardDesktop, { width: cardW, backgroundColor: t.card }]}
        onPress={handleDoubleTap}
      >
        {/* Cerrar */}
        <TouchableOpacity style={[styles.closeBtn, { backgroundColor: isDark ? "rgba(255,255,255,0.15)" : "rgba(255,255,255,0.9)" }]} onPress={onClose}>
          <Ionicons name="close" size={20} color={t.text} />
        </TouchableOpacity>

        {/* Hint doble toque */}
        <TouchableOpacity style={styles.doubleTapHint} onPress={handleDoubleTap} activeOpacity={0.6}>
          <View style={[styles.dragHandle, { backgroundColor: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.12)" }]} />
          <Text style={[styles.doubleTapText, { color: t.textMuted }]}>
            <Ionicons name="finger-print-outline" size={11} /> Toca 2 veces el fondo para cerrar
          </Text>
        </TouchableOpacity>

        <ScrollView
          showsVerticalScrollIndicator={false}
          bounces={false}
          contentContainerStyle={{ paddingBottom: 24 }}
        >
          {/* Galería de imágenes */}
          <View style={[styles.gallery, { backgroundColor: "#fff" }]}>
            <FlatList
              ref={flatRef}
              data={images}
              horizontal
              pagingEnabled
              showsHorizontalScrollIndicator={false}
              keyExtractor={(_, i) => String(i)}
              onMomentumScrollEnd={(e) => {
                const idx = Math.round(e.nativeEvent.contentOffset.x / cardW);
                setActiveImg(idx);
              }}
              renderItem={({ item }) => (
                <Image
                  source={{ uri: item }}
                  style={[styles.img, { width: cardW }]}
                  resizeMode="contain"
                />
              )}
            />
            {/* Indicadores */}
            {images.length > 1 && (
              <View style={styles.dots}>
                {images.map((_, i) => (
                  <View
                    key={i}
                    style={[styles.dot, { backgroundColor: t.border }, i === activeImg && styles.dotActive]}
                  />
                ))}
              </View>
            )}
            {/* Badge promo */}
            {product.promo && (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{product.promo}</Text>
              </View>
            )}
          </View>

          {/* Info */}
          <View style={styles.info}>
            <Text style={[styles.cat, { color: t.textMuted }]}>{product.cat}</Text>
            <Text style={[styles.name, { color: t.text }]}>{product.name}</Text>
            <Text style={styles.price}>
              {detail?.price_display || product.price}
            </Text>

            {/* Descripción */}
            {loading ? (
              <ActivityIndicator size="small" color={RED} style={{ marginTop: 16 }} />
            ) : detail?.description ? (
              <View style={[styles.descBox, { backgroundColor: t.cardAlt }]}>
                <Text style={[styles.descTitle, { color: t.textMuted }]}>Descripción</Text>
                <Text style={[styles.desc, { color: t.textSub }]}>{detail.description}</Text>
              </View>
            ) : null}

            {/* Stock badge */}
            {!loading && stockTracked && (
              <View style={styles.stockRow}>
                <Ionicons
                  name={isAgotado ? "close-circle" : atMax ? "alert-circle" : "checkmark-circle"}
                  size={16}
                  color={isAgotado ? "#f44336" : atMax ? "#ff9800" : "#4caf50"}
                />
                <Text style={[
                  styles.stockText,
                  { color: isAgotado ? "#f44336" : atMax ? "#ff9800" : "#4caf50" },
                ]}>
                  {isAgotado
                    ? "Agotado"
                    : atMax
                    ? `Máximo en carrito (${stock})`
                    : stock <= 5
                    ? `¡Solo quedan ${stock}!`
                    : "En stock"}
                </Text>
              </View>
            )}

            {/* Mensaje de error de stock */}
            {stockMsg !== "" && (
              <View style={[styles.stockErrBox, { backgroundColor: isDark ? "#3a2a0a" : "#fff3e0" }]}>
                <Ionicons name="warning-outline" size={14} color="#e65100" />
                <Text style={[styles.stockErrText, { color: isDark ? "#ff9800" : "#e65100" }]}>{stockMsg}</Text>
              </View>
            )}

            {/* Cantidad + agregar */}
            <View style={styles.footer}>
              <View style={[styles.qtyRow, { backgroundColor: t.iconBg }]}>
                <TouchableOpacity
                  style={[styles.qtyBtn, { backgroundColor: t.iconBg }]}
                  onPress={() => changeQty(-1)}
                >
                  <Text style={[styles.qtyBtnText, { color: t.text }]}>-</Text>
                </TouchableOpacity>
                <Text style={[styles.qtyVal, { color: t.text }]}>{qty}</Text>
                <TouchableOpacity
                  style={[
                    styles.qtyBtn,
                    { backgroundColor: atMax || qty >= available ? t.border : RED },
                  ]}
                  onPress={() => changeQty(1)}
                  disabled={atMax || qty >= available}
                >
                  <Text style={[styles.qtyBtnText, { color: "#fff" }]}>+</Text>
                </TouchableOpacity>
              </View>

              <TouchableOpacity
                style={[
                  styles.addBtn,
                  added && styles.addBtnOk,
                  (isAgotado || atMax) && styles.addBtnDisabled,
                ]}
                onPress={handleAdd}
                disabled={isAgotado || atMax}
                activeOpacity={0.85}
              >
                <Ionicons
                  name={added ? "checkmark" : isAgotado ? "close-circle-outline" : "cart-outline"}
                  size={18}
                  color="#fff"
                />
                <Text style={styles.addBtnText}>
                  {added
                    ? "¡Agregado!"
                    : isAgotado
                    ? "Agotado"
                    : atMax
                    ? "Ya tienes todo el stock"
                    : "Agregar al carrito"}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </Pressable>
    </Modal>
    <LoginPromptSheet visible={showLogin} onClose={() => setShowLogin(false)} />
    </>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.55)",
  },
  card: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: "#fff",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: "90%",
    overflow: "hidden",
  },
  cardDesktop: {
    top: "50%",
    left: "50%",
    bottom: "auto",
    right: "auto",
    transform: [{ translateX: "-50%" }, { translateY: "-50%" }],
    borderRadius: 16,
    maxHeight: "85%",
  },
  closeBtn: {
    position: "absolute",
    top: 12,
    right: 12,
    zIndex: 10,
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: "rgba(255,255,255,0.9)",
    justifyContent: "center",
    alignItems: "center",
    shadowColor: "#000",
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 4,
  },
  gallery: {
    width: "100%",
    height: IMG_H,
    backgroundColor: "#fff",
  },
  img: {
    height: IMG_H,
    backgroundColor: "#fff",
  },
  dots: {
    position: "absolute",
    bottom: 10,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "center",
    gap: 6,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#ccc",
  },
  dotActive: {
    backgroundColor: RED,
    width: 18,
  },
  badge: {
    position: "absolute",
    top: 14,
    left: 14,
    backgroundColor: RED,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
  },
  badgeText: { color: "#fff", fontWeight: "700", fontSize: 12 },

  info: { padding: 20 },
  cat: { fontSize: 11, color: "#aaa", fontWeight: "600", letterSpacing: 1, marginBottom: 4 },
  name: { fontSize: 22, fontWeight: "900", color: "#111", marginBottom: 6 },
  price: { fontSize: 20, fontWeight: "700", color: RED, marginBottom: 12 },

  descBox: {
    backgroundColor: "#f9f9f9",
    borderRadius: 10,
    padding: 14,
    marginTop: 4,
    marginBottom: 12,
  },
  descTitle: { fontSize: 12, fontWeight: "700", color: "#888", marginBottom: 6, letterSpacing: 0.5 },
  desc: { fontSize: 14, color: "#444", lineHeight: 22 },

  stockRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 20,
  },
  stockText: { fontSize: 13, fontWeight: "600" },

  footer: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: 4,
  },
  qtyRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f5f5f5",
    borderRadius: 10,
    overflow: "hidden",
  },
  qtyBtn: {
    width: 38,
    height: 42,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#f0f0f0",
  },
  qtyBtnText: { fontSize: 18, fontWeight: "700", color: "#333" },
  qtyVal: { paddingHorizontal: 14, fontSize: 16, fontWeight: "700", color: "#111" },

  addBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: RED,
    paddingVertical: 13,
    borderRadius: 12,
  },
  addBtnOk: { backgroundColor: "#4caf50" },
  addBtnDisabled: { backgroundColor: "#bbb" },
  addBtnText: { color: "#fff", fontWeight: "700", fontSize: 15 },
  stockErrBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#fff3e0",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginBottom: 10,
  },
  stockErrText: { color: "#e65100", fontSize: 13, fontWeight: "600", flex: 1 },

  doubleTapHint: {
    alignItems: "center",
    paddingTop: 10,
    paddingBottom: 6,
  },
  dragHandle: {
    width: 38,
    height: 4,
    borderRadius: 2,
    marginBottom: 6,
  },
  doubleTapText: {
    fontSize: 11,
    color: "#aaa",
    letterSpacing: 0.2,
  },
});
