import { Ionicons } from "@expo/vector-icons";
import {
  Image,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCart } from "../context/CartContext";
import { useTheme } from "../context/ThemeContext";
import { MENU_CLEARANCE } from "../components/MobileMenu";

const RED    = "#e6192e";
const YELLOW = "#fede33";

function CartItem({ item, t }) {
  const { updateQty, removeFromCart } = useCart();
  const isUnlimited = item.stock === -1;
  const atMax = !isUnlimited && item.stock !== null && item.qty >= item.stock;

  return (
    <View style={styles.cartItem}>
      <View style={[styles.cartItemImgWrap, { backgroundColor: "#fff" }]}>
        <Image source={{ uri: item.img }} style={styles.cartItemImg} resizeMode="contain" />
      </View>
      <View style={styles.cartItemInfo}>
        <Text style={[styles.cartItemCat, { color: t.textMuted }]}>{item.cat}</Text>
        <Text style={[styles.cartItemName, { color: t.text }]}>{item.name}</Text>
        <Text style={styles.cartItemPrice}>{item.price}</Text>
      </View>
      <View style={styles.cartItemRight}>
        <TouchableOpacity onPress={() => removeFromCart(item.id)} style={styles.deleteBtn}>
          <Ionicons name="trash-outline" size={16} color={t.textMuted} />
        </TouchableOpacity>
        <View style={[styles.qtyControl, { backgroundColor: t.iconBg }]}>
          <TouchableOpacity
            style={[styles.qtyBtn, { backgroundColor: t.border }]}
            onPress={() => updateQty(item.id, item.qty - 1)}
          >
            <Text style={[styles.qtyBtnText, { color: t.text }]}>-</Text>
          </TouchableOpacity>
          <Text style={[styles.qtyText, { color: t.text }]}>{item.qty}</Text>
          <TouchableOpacity
            style={[styles.qtyBtn, { backgroundColor: atMax ? "#888" : RED }]}
            onPress={() => updateQty(item.id, item.qty + 1)}
            disabled={atMax}
          >
            <Text style={[styles.qtyBtnText, { color: "#fff" }]}>+</Text>
          </TouchableOpacity>
        </View>
        {!isUnlimited && item.stock !== null && item.stock <= 5 && item.stock > 0 && (
          <Text style={{ fontSize: 10, color: "#e65100", textAlign: "center", marginTop: 2 }}>
            Stock: {item.stock}
          </Text>
        )}
      </View>
    </View>
  );
}

export default function CartScreen({ onBack, onCheckout }) {
  const { items, subtotal, clearCart, count } = useCart();
  const { t } = useTheme();
  const { top: safeTop, bottom: safeBottom } = useSafeAreaInsets();

  const shipping = subtotal > 500 ? 0 : 49;
  const total = subtotal + shipping;

  const topPad = safeTop > 0 ? safeTop : Platform.OS === "ios" ? 50 : 40;
  // Menu sits at (safeBottom + 8) with height 62 → top of menu = safeBottom + 70
  // Place bar just above that with an 8px gap
  const bottomBarBottom = safeBottom + 78;
  const scrollSpacer = bottomBarBottom + 120; // enough room so content clears the bar

  return (
    <View style={[styles.wrapper, { backgroundColor: t.bg, paddingTop: topPad }]}>
      <View style={[styles.header, { backgroundColor: t.header, borderBottomColor: t.border }]}>
        <TouchableOpacity onPress={onBack} style={[styles.backBtn, { backgroundColor: t.iconBg }]}>
          <Ionicons name="arrow-back" size={22} color={t.text} />
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: t.text }]}>MI CARRITO</Text>
        <Text style={[styles.headerCount, { color: t.textMuted }]}>{count} {count === 1 ? "it" : "its"}</Text>
      </View>

      {items.length === 0 ? (
        <View style={[styles.emptyWrap, { backgroundColor: t.card }]}>
          <View style={[styles.emptyIconWrap, { backgroundColor: t.iconBg }]}>
            <Ionicons name="cart-outline" size={72} color={t.textMuted} />
          </View>
          <Text style={[styles.emptyTitle, { color: t.text }]}>Tu carrito está vacío</Text>
          <Text style={[styles.emptySubtitle, { color: t.textMuted }]}>
            Agrega productos desde la tienda para verlos aquí
          </Text>
          <TouchableOpacity style={styles.shopBtn} onPress={onBack}>
            <Text style={styles.shopBtnText}>IR A LA TIENDA</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={[styles.itemsCard, { backgroundColor: t.card }]}>
            {items.map((item, i) => (
              <View key={item.id}>
                <CartItem item={item} t={t} />
                {i < items.length - 1 && <View style={[styles.divider, { backgroundColor: t.divider }]} />}
              </View>
            ))}
          </View>

          <TouchableOpacity onPress={clearCart} style={styles.clearBtn}>
            <Ionicons name="trash-outline" size={14} color={t.textMuted} />
            <Text style={[styles.clearBtnText, { color: t.textMuted }]}>Vaciar carrito</Text>
          </TouchableOpacity>

          <View style={[styles.summaryCard, { backgroundColor: t.card }]}>
            <Text style={[styles.summaryTitle, { color: t.textSub }]}>RESUMEN DE PEDIDO</Text>
            <View style={styles.summaryRow}>
              <Text style={[styles.summaryLabel, { color: t.textSub }]}>Subtotal</Text>
              <Text style={[styles.summaryValue, { color: t.textSub }]}>${subtotal.toFixed(2)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={[styles.summaryLabel, { color: t.textSub }]}>Envío</Text>
              <Text style={[styles.summaryValue, shipping === 0 && styles.freeShipping, { color: shipping === 0 ? "#22c55e" : t.textSub }]}>
                {shipping === 0 ? "GRATIS" : `$${shipping.toFixed(2)}`}
              </Text>
            </View>
            {shipping > 0 && (
              <View style={styles.freeShippingBanner}>
                <Ionicons name="information-circle-outline" size={14} color={RED} />
                <Text style={styles.freeShippingText}>
                  Agrega ${(500 - subtotal).toFixed(2)} más para envío gratis
                </Text>
              </View>
            )}
            <View style={[styles.divider, { backgroundColor: t.divider }]} />
            <View style={[styles.summaryRow, { marginTop: 8 }]}>
              <Text style={[styles.totalLabel, { color: t.text }]}>TOTAL</Text>
              <Text style={styles.totalValue}>${total.toFixed(2)}</Text>
            </View>
          </View>

          <View style={[styles.couponRow, { backgroundColor: t.card }]}>
            <Ionicons name="pricetag-outline" size={18} color={RED} />
            <Text style={[styles.couponText, { color: t.textSub }]}>¿Tienes un cupón de descuento?</Text>
            <Ionicons name="chevron-forward" size={16} color={t.textMuted} />
          </View>

          <View style={{ height: scrollSpacer }} />
        </ScrollView>
      )}

      {items.length > 0 && (
        <View style={[styles.bottomBar, { backgroundColor: t.header, borderTopColor: t.border, bottom: bottomBarBottom }]}>
          <View style={styles.totalRow}>
            <Text style={[styles.bottomTotalLabel, { color: t.textSub }]}>Total</Text>
            <Text style={[styles.bottomTotalValue, { color: t.text }]}>${total.toFixed(2)}</Text>
          </View>
          <TouchableOpacity style={styles.checkoutBtn} onPress={onCheckout}>
            <Text style={styles.checkoutBtnText}>PROCEDER AL PAGO</Text>
            <Ionicons name="arrow-forward" size={18} color="#000" />
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { flex: 1 },
  header: {
    paddingHorizontal: 16, borderBottomWidth: 1,
    flexDirection: "row", alignItems: "center", height: 72,
  },
  headerTitle: { fontSize: 18, fontWeight: "900" },
  headerCount: { fontSize: 13, fontWeight: "600", marginLeft: "auto" },
  backBtn: {
    width: 44, height: 44, borderRadius: 22,
    justifyContent: "center", alignItems: "center", marginRight: 16,
  },
  scroll: { flex: 1 },
  scrollContent: { padding: 16 },
  emptyWrap: { flex: 1, justifyContent: "center", alignItems: "center", padding: 40 },
  emptyIconWrap: {
    width: 100, height: 100, borderRadius: 50,
    justifyContent: "center", alignItems: "center", marginBottom: 20,
  },
  emptyTitle: { fontSize: 20, fontWeight: "900", marginBottom: 8 },
  emptySubtitle: { fontSize: 14, textAlign: "center", lineHeight: 20, marginBottom: 24 },
  shopBtn: { backgroundColor: RED, paddingHorizontal: 30, paddingVertical: 14, borderRadius: 12 },
  shopBtnText: { color: "#fff", fontSize: 14, fontWeight: "900", letterSpacing: 1 },
  itemsCard: {
    borderRadius: 16, padding: 16, marginBottom: 12,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2,
  },
  cartItem: { flexDirection: "row", alignItems: "center", paddingVertical: 8 },
  cartItemImgWrap: {
    width: 70, height: 70, borderRadius: 12,
    justifyContent: "center", alignItems: "center", marginRight: 12, padding: 4,
  },
  cartItemImg: { width: "100%", height: "100%" },
  cartItemInfo: { flex: 1 },
  cartItemCat: { fontSize: 9, fontWeight: "700", marginBottom: 2 },
  cartItemName: { fontSize: 13, fontWeight: "800", marginBottom: 4 },
  cartItemPrice: { fontSize: 13, fontWeight: "900", color: RED },
  cartItemRight: { alignItems: "flex-end", gap: 8 },
  deleteBtn: { padding: 4 },
  qtyControl: { flexDirection: "row", alignItems: "center", borderRadius: 10, overflow: "hidden" },
  qtyBtn: { width: 28, height: 28, justifyContent: "center", alignItems: "center" },
  qtyBtnText: { fontSize: 16, fontWeight: "700" },
  qtyText: { fontSize: 13, fontWeight: "800", paddingHorizontal: 10 },
  divider: { height: 1, marginVertical: 8 },
  clearBtn: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", gap: 6, marginBottom: 16, paddingRight: 4 },
  clearBtnText: { fontSize: 12 },
  summaryCard: {
    borderRadius: 16, padding: 20, marginBottom: 12,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2,
  },
  summaryTitle: { fontSize: 12, fontWeight: "900", marginBottom: 16, letterSpacing: 0.5 },
  summaryRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: 10 },
  summaryLabel: { fontSize: 14 },
  summaryValue: { fontSize: 14, fontWeight: "700" },
  freeShipping: { fontWeight: "800" },
  freeShippingBanner: {
    flexDirection: "row", alignItems: "center", backgroundColor: "#fff5f5",
    borderRadius: 8, padding: 10, gap: 6, marginBottom: 8,
  },
  freeShippingText: { fontSize: 12, color: RED, flex: 1 },
  totalLabel: { fontSize: 16, fontWeight: "900" },
  totalValue: { fontSize: 18, fontWeight: "900", color: RED },
  couponRow: {
    flexDirection: "row", alignItems: "center", borderRadius: 16, padding: 16, gap: 10,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2,
  },
  couponText: { flex: 1, fontSize: 14, fontWeight: "600" },
  bottomBar: {
    position: "absolute", left: 0, right: 0,
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 16,
    borderTopWidth: 1,
    shadowColor: "#000", shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.06, shadowRadius: 12, elevation: 12,
  },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  bottomTotalLabel: { fontSize: 14 },
  bottomTotalValue: { fontSize: 20, fontWeight: "900" },
  checkoutBtn: {
    backgroundColor: YELLOW, borderRadius: 14, paddingVertical: 16,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  checkoutBtnText: { fontSize: 15, fontWeight: "900", color: "#000" },
});
