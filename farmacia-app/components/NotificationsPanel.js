import { Ionicons } from "@expo/vector-icons";
import { useEffect } from "react";
import {
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useNotifications } from "../context/NotificationsContext";

const RED   = "#e6192e";
const BLUE  = RED; // Forzamos BLUE a ser RED
const GREEN = "#22c55e";

const TYPE_META = {
  accepted:   { icon: "bicycle",            color: RED,       bg: "#fff5f5" },
  preparing:  { icon: "storefront-outline", color: "#f59e0b", bg: "#fffbeb" },
  picked_up:  { icon: "bag-check-outline",  color: RED,       bg: "#fff5f5" },
  on_the_way: { icon: "navigate",           color: RED,       bg: "#fff5f5" },
  arrived:    { icon: "home",               color: GREEN,     bg: "#f0fdf4" },
  delivered:  { icon: "checkmark-circle",   color: GREEN,     bg: "#f0fdf4" },
  cancelled:  { icon: "close-circle",       color: RED,       bg: "#fff1f2" },
  nearby:     { icon: "location",           color: RED,       bg: "#fff1f2" },
  new_order:  { icon: "bicycle",            color: RED,       bg: "#fff1f2" },
  info:       { icon: "notifications",      color: "#6b7280", bg: "#f9fafb" },
};

function timeAgo(isoStr) {
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60)    return "ahora";
  if (diff < 3600)  return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return `hace ${Math.floor(diff / 86400)} d`;
}

// ─── CONTENIDO COMPARTIDO ────────────────────────────────────────────────────
function PanelContent({ onClose, onOrderPress }) {
  const { notifications, markAllRead, clearAll } = useNotifications();

  return (
    <>
      {/* Header */}
      <View style={s.header}>
        <View style={s.headerLeft}>
          <Ionicons name="notifications" size={20} color={RED} />
          <Text style={s.headerTitle}>NOTIFICACIONES</Text>
        </View>
        <View style={s.headerActions}>
          {notifications.length > 0 && (
            <TouchableOpacity onPress={clearAll} style={s.clearBtn}>
              <Text style={s.clearBtnText}>Borrar todo</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity onPress={onClose} style={s.closeBtn}>
            <Ionicons name="close" size={22} color="#444" />
          </TouchableOpacity>
        </View>
      </View>

      {/* Lista */}
      {notifications.length === 0 ? (
        <View style={s.empty}>
          <View style={s.emptyIcon}>
            <Ionicons name="notifications-off-outline" size={40} color="#ccc" />
          </View>
          <Text style={s.emptyTitle}>Sin notificaciones</Text>
          <Text style={s.emptySub}>
            Aquí verás el estado de tus pedidos en tiempo real
          </Text>
        </View>
      ) : (
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={s.list}
        >
          {notifications.map((n) => {
            const meta = TYPE_META[n.type] || TYPE_META.info;
            return (
              <TouchableOpacity
                key={n.id}
                style={[s.item, !n.read && s.itemUnread]}
                activeOpacity={0.75}
                onPress={() => {
                  onClose();
                  if (n.orderId) onOrderPress?.();
                }}
              >
                <View style={[s.iconWrap, { backgroundColor: meta.bg }]}>
                  <Ionicons name={meta.icon} size={20} color={meta.color} />
                </View>
                <View style={s.itemText}>
                  <View style={s.itemTopRow}>
                    <Text style={s.itemTitle} numberOfLines={1}>{n.title}</Text>
                    <Text style={s.itemTime}>{timeAgo(n.timestamp)}</Text>
                  </View>
                  <Text style={s.itemBody} numberOfLines={2}>{n.body}</Text>
                </View>
                {!n.read && <View style={s.unreadDot} />}
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      )}
    </>
  );
}

// ─── COMPONENTE PRINCIPAL ────────────────────────────────────────────────────
export default function NotificationsPanel({ visible, onClose, onOrderPress }) {
  const { markAllRead } = useNotifications();
  const { bottom } = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const isDesktop = Platform.OS === "web" && width >= 1024;

  useEffect(() => {
    if (visible) markAllRead();
  }, [visible, markAllRead]);

  // ── DESKTOP: drawer lateral derecho ──────────────────────────────────────
  if (isDesktop) {
    if (!visible) return null;

    const backdropStyle = {
      position: "fixed",
      top: 0, left: 0, right: 0, bottom: 0,
      zIndex: 1000,
      flexDirection: "row",
      justifyContent: "flex-end",
    };

    return (
      <View style={backdropStyle}>
        <TouchableOpacity
          style={d.overlay}
          activeOpacity={1}
          onPress={onClose}
        />
        <View style={d.panel}>
          <PanelContent onClose={onClose} onOrderPress={onOrderPress} />
        </View>
      </View>
    );
  }

  // ── MÓVIL: bottom sheet ───────────────────────────────────────────────────
  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <View style={s.backdrop}>
        <TouchableOpacity style={s.overlay} activeOpacity={1} onPress={onClose} />
        <View style={[s.panel, { paddingBottom: bottom + 16 }]}>
          <View style={s.handle} />
          <PanelContent onClose={onClose} onOrderPress={onOrderPress} />
        </View>
      </View>
    </Modal>
  );
}

// ─── ESTILOS DESKTOP ─────────────────────────────────────────────────────────
const d = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  panel: {
    width: 380,
    height: "100%",
    backgroundColor: "#fff",
    ...Platform.select({
      ios: {
        shadowColor: "#000",
        shadowOffset: { width: -4, height: 0 },
        shadowOpacity: 0.18,
        shadowRadius: 20,
      },
      android: {
        elevation: 20,
      },
      web: {
        boxShadow: "-4px 0 20px rgba(0,0,0,0.18)",
      },
    }),
    flexDirection: "column",
  },
});

// ─── ESTILOS COMPARTIDOS (header + items) ────────────────────────────────────
const s = StyleSheet.create({
  // Móvil backdrop
  backdrop: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  overlay: { ...StyleSheet.absoluteFillObject },

  // Móvil panel
  panel: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: "85%",
    ...Platform.select({
      ios: {
        shadowColor: "#000",
        shadowOffset: { width: 0, height: -6 },
        shadowOpacity: 0.12,
        shadowRadius: 20,
      },
      android: {
        elevation: 20,
      },
      web: {
        boxShadow: "0 -6px 20px rgba(0,0,0,0.12)",
      },
    }),
  },
  handle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: "#e0e0e0",
    alignSelf: "center", marginTop: 10, marginBottom: 4,
  },

  // Header
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 20, paddingVertical: 16,
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 8 },
  headerTitle: { fontSize: 15, fontWeight: "900", color: "#111", letterSpacing: 0.5 },
  headerActions: { flexDirection: "row", alignItems: "center", gap: 12 },
  clearBtn: { paddingVertical: 4, paddingHorizontal: 8 },
  clearBtnText: { fontSize: 12, fontWeight: "700", color: "#aaa" },
  closeBtn: { padding: 2 },

  // Empty
  empty: {
    alignItems: "center", justifyContent: "center",
    paddingVertical: 60, paddingHorizontal: 40, gap: 12,
  },
  emptyIcon: {
    width: 80, height: 80, borderRadius: 40,
    backgroundColor: "#fafafa", borderWidth: 2, borderColor: "#f0f0f0",
    justifyContent: "center", alignItems: "center", marginBottom: 6,
  },
  emptyTitle: { fontSize: 17, fontWeight: "800", color: "#333" },
  emptySub: { fontSize: 13, color: "#aaa", textAlign: "center", lineHeight: 20 },

  // Lista
  list: { padding: 12 },
  item: {
    flexDirection: "row", alignItems: "flex-start", gap: 12,
    backgroundColor: "#fff", borderRadius: 14, padding: 14,
    marginBottom: 8,
    borderWidth: 1, borderColor: "#f0f0f0",
  },
  itemUnread: {
    backgroundColor: "#f8faff", borderColor: "#dbeafe",
  },
  iconWrap: {
    width: 44, height: 44, borderRadius: 14,
    justifyContent: "center", alignItems: "center", flexShrink: 0,
  },
  itemText: { flex: 1 },
  itemTopRow: {
    flexDirection: "row", justifyContent: "space-between",
    alignItems: "center", marginBottom: 3,
  },
  itemTitle: { fontSize: 13, fontWeight: "800", color: "#111", flex: 1, marginRight: 8 },
  itemTime: { fontSize: 11, color: "#aaa", fontWeight: "500", flexShrink: 0 },
  itemBody: { fontSize: 12, color: "#666", lineHeight: 17 },
  unreadDot: {
    width: 8, height: 8, borderRadius: 4,
    backgroundColor: BLUE, alignSelf: "center", flexShrink: 0,
  },
});
