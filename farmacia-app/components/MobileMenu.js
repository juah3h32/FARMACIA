import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef } from "react";
import {
  Animated,
  Dimensions,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTheme } from "../context/ThemeContext";

// Clearance screens must add as paddingBottom to not be covered by the menu:
// BAR_HEIGHT(62) + bottom gap(8) + breathing room(14) = 84
export const MENU_CLEARANCE = 84;

const { width } = Dimensions.get("window");
const TAB_COUNT = 5;
const BAR_PADDING = 16;
const BAR_WIDTH = width - BAR_PADDING * 2;
const BAR_HEIGHT = 62;
const PILL_H = 44;
const PILL_W = 52;

const RED = "#e6192e";
const YELLOW = "#fede33";

const TABS = [
  { icon: "home",      label: "Inicio"   },
  { icon: "storefront",label: "Tienda"   },
  { icon: "cart",      label: "Carrito"  },
  { icon: "receipt",   label: "Pedidos"  },
  { icon: "person",    label: "Perfil"   },
];

// Tab index mapping: 0=Home, 1=Store, 2=Cart(4), 3=Orders(2), 4=Profile(3)
const TAB_INDEX_MAP = [0, 1, 4, 2, 3];
const APP_INDEX_MAP = { 0: 0, 1: 1, 4: 2, 2: 3, 3: 4 };

export default function MobileMenu({ active, setActive, isDesktop, cartCount = 0, onCartPress }) {
  const { t } = useTheme();
  const { bottom: safeBottom } = useSafeAreaInsets();
  if (isDesktop) return null;

  // Convert app tab index (0-4) to menu index (0-4)
  const menuActive = active === -1 ? 2 : (APP_INDEX_MAP[active] ?? 0);

  const slideAnim = useRef(new Animated.Value(menuActive)).current;
  const scaleAnims = useRef(TABS.map(() => new Animated.Value(1))).current;

  useEffect(() => {
    Animated.spring(slideAnim, {
      toValue: menuActive,
      useNativeDriver: false,
      friction: 9,
      tension: 55,
    }).start();
  }, [menuActive]);

  const handlePress = (menuIdx) => {
    const appIdx = TAB_INDEX_MAP[menuIdx];

    Animated.sequence([
      Animated.timing(scaleAnims[menuIdx], {
        toValue: 0.78,
        duration: 70,
        useNativeDriver: true,
      }),
      Animated.spring(scaleAnims[menuIdx], {
        toValue: 1,
        useNativeDriver: true,
        friction: 4,
      }),
    ]).start();

    if (appIdx === 4 && onCartPress) {
      onCartPress();
    }
    setActive(appIdx);
  };

  const tabWidth = BAR_WIDTH / TAB_COUNT;
  const pillOffsetX = (tabWidth - PILL_W) / 2;

  const pillLeft = slideAnim.interpolate({
    inputRange: [0, 1, 2, 3, 4],
    outputRange: TABS.map((_, i) => pillOffsetX + tabWidth * i),
  });

  return (
    <View style={[styles.wrapper, { bottom: safeBottom + 8 }]} pointerEvents="box-none">
      <View style={[styles.bar, { backgroundColor: t.tabBar }]}>
        {/* Pill animado */}
        <Animated.View style={[styles.pill, { left: pillLeft }]} />

        {TABS.map((tab, i) => {
          const isActive = menuActive === i;
          const isCart = i === 2;
          const showBadge = isCart && cartCount > 0;

          return (
            <Pressable
              key={i}
              style={styles.tab}
              onPress={() => handlePress(i)}
              android_ripple={{ color: "rgba(0,0,0,0.05)", borderless: true, radius: 28 }}
            >
              <Animated.View
                style={[styles.tabInner, { transform: [{ scale: scaleAnims[i] }] }]}
              >
                <View style={{ position: "relative" }}>
                  <Ionicons
                    name={isActive ? tab.icon : `${tab.icon}-outline`}
                    size={isCart ? 24 : 21}
                    color={isActive ? "#1a1a1a" : t.textMuted}
                  />
                  {showBadge && (
                    <View style={[styles.badge, { borderColor: t.tabBar }]}>
                      <Text style={styles.badgeText}>
                        {cartCount > 9 ? "9+" : cartCount}
                      </Text>
                    </View>
                  )}
                </View>
                <Text style={[styles.tabLabel, { color: t.textMuted }, isActive && styles.tabLabelActive]}>
                  {tab.label}
                </Text>
              </Animated.View>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    position: "absolute",
    left: 0,
    right: 0,
    alignItems: "center",
    pointerEvents: "box-none",
  },
  bar: {
    flexDirection: "row",
    backgroundColor: "#ffffff",
    width: BAR_WIDTH,
    height: BAR_HEIGHT,
    borderRadius: 28,
    alignItems: "center",
    ...Platform.select({
      ios: {
        shadowColor: "#000",
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.10,
        shadowRadius: 20,
      },
      android: { elevation: 12 },
      web: {
        boxShadow: "0 8px 32px rgba(0,0,0,0.10)",
      },
    }),
  },
  pill: {
    position: "absolute",
    width: PILL_W,
    height: PILL_H,
    borderRadius: 20,
    backgroundColor: YELLOW,
  },
  tab: {
    flex: 1,
    height: "100%",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1,
  },
  tabInner: {
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  tabLabel: {
    fontSize: 9,
    fontWeight: "600",
    color: "#b0b0b0",
    letterSpacing: 0.1,
  },
  tabLabelActive: {
    color: "#1a1a1a",
    fontWeight: "800",
  },
  badge: {
    position: "absolute",
    top: -5,
    right: -7,
    backgroundColor: RED,
    minWidth: 15,
    height: 15,
    borderRadius: 8,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 3,
    borderWidth: 1.5,
    borderColor: "#fff",
  },
  badgeText: {
    color: "#fff",
    fontSize: 8,
    fontWeight: "900",
  },
});
