import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import ProductDetailModal from "../components/ProductDetailModal";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useWishlist } from "../context/WishlistContext";
import { MOBILE_HEADER_FIXED } from "./HomeScreen";
import { forgotPassword } from "../services/api";
import { useLocation } from "../context/LocationContext";
import { registerForPushNotifications } from "../services/notifications";

const RED = "#e6192e";
const YELLOW = "#fede33";

// ─── AUTH VIEW (login / registro) ────────────────────────────────────────────
function AuthView() {
  const { signInWithGoogle, signInWithEmail, signUp, authError, clearError } = useAuth();
  const [view, setView] = useState("login");
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const error = localError || authError;

  const clearAll = () => { setLocalError(null); clearError(); setSuccessMsg(null); };
  const switchView = (v) => { clearAll(); setPassword(""); setConfirmPassword(""); setView(v); };

  const handleLogin = async () => {
    clearAll();
    if (!email.trim() || !password) { setLocalError("Completa todos los campos"); return; }
    setLoading(true);
    const result = await signInWithEmail(email.trim().toLowerCase(), password);
    setLoading(false);
    if (!result.success) setLocalError(result.message);
  };

  const handleRegister = async () => {
    clearAll();
    if (!name.trim() || !email.trim() || !password) { setLocalError("Completa todos los campos"); return; }
    if (password !== confirmPassword) { setLocalError("Las contraseñas no coinciden"); return; }
    if (password.length < 6) { setLocalError("La contraseña debe tener al menos 6 caracteres"); return; }
    setLoading(true);
    const result = await signUp(name.trim(), email.trim().toLowerCase(), password);
    setLoading(false);
    if (!result.success) setLocalError(result.message);
  };

  const handleForgot = async () => {
    clearAll();
    if (!email.trim()) { setLocalError("Ingresa tu email"); return; }
    setLoading(true);
    try {
      await forgotPassword(email.trim().toLowerCase());
      setView("forgot_sent");
    } catch {
      setLocalError("Error de conexión. Intenta más tarde.");
    }
    setLoading(false);
  };

  if (view === "forgot_sent") {
    return (
      <View style={styles.authCard}>
        <View style={styles.successIcon}>
          <Ionicons name="mail-outline" size={44} color={RED} />
        </View>
        <Text style={styles.authTitle}>¡Revisa tu correo!</Text>
        <Text style={styles.authSubtitle}>
          Si el email <Text style={{ fontWeight: "800" }}>{email}</Text> está registrado,
          recibirás un enlace para restablecer tu contraseña.
        </Text>
        <TouchableOpacity style={styles.loginBtn} onPress={() => switchView("login")}>
          <Text style={styles.loginBtnText}>VOLVER AL INICIO DE SESIÓN</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.authCard}>
        {(view === "login" || view === "register") && (
          <View style={styles.authTabs}>
            <TouchableOpacity style={[styles.authTab, view === "login" && styles.authTabActive]} onPress={() => switchView("login")}>
              <Text style={[styles.authTabText, view === "login" && styles.authTabTextActive]}>Iniciar sesión</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.authTab, view === "register" && styles.authTabActive]} onPress={() => switchView("register")}>
              <Text style={[styles.authTabText, view === "register" && styles.authTabTextActive]}>Registrarse</Text>
            </TouchableOpacity>
          </View>
        )}
        {view === "forgot" && (
          <View style={styles.forgotHeader}>
            <TouchableOpacity onPress={() => switchView("login")} style={styles.backBtn}>
              <Ionicons name="arrow-back" size={20} color="#555" />
            </TouchableOpacity>
            <Text style={styles.authTitle}>Recuperar contraseña</Text>
          </View>
        )}
        {error && (
          <View style={styles.errorBanner}>
            <Ionicons name="alert-circle" size={16} color="#dc2626" />
            <Text style={styles.errorText}>{error}</Text>
            <TouchableOpacity onPress={clearAll}><Ionicons name="close" size={16} color="#dc2626" /></TouchableOpacity>
          </View>
        )}
        {view === "register" && (
          <View style={styles.inputWrap}>
            <Ionicons name="person-outline" size={18} color="#bbb" style={styles.inputIcon} />
            <TextInput style={styles.input} placeholder="Nombre completo" placeholderTextColor="#bbb" value={name} onChangeText={setName} autoCapitalize="words" returnKeyType="next" />
          </View>
        )}
        <View style={styles.inputWrap}>
          <Ionicons name="mail-outline" size={18} color="#bbb" style={styles.inputIcon} />
          <TextInput style={styles.input} placeholder="Correo electrónico" placeholderTextColor="#bbb" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" autoCorrect={false} returnKeyType={view === "forgot" ? "done" : "next"} />
        </View>
        {view !== "forgot" && (
          <View style={styles.inputWrap}>
            <Ionicons name="lock-closed-outline" size={18} color="#bbb" style={styles.inputIcon} />
            <TextInput style={[styles.input, { flex: 1 }]} placeholder="Contraseña" placeholderTextColor="#bbb" value={password} onChangeText={setPassword} secureTextEntry={!showPass} returnKeyType={view === "register" ? "next" : "done"} onSubmitEditing={view === "login" ? handleLogin : undefined} />
            <TouchableOpacity onPress={() => setShowPass(!showPass)} style={{ paddingRight: 14 }}>
              <Ionicons name={showPass ? "eye-off-outline" : "eye-outline"} size={18} color="#bbb" />
            </TouchableOpacity>
          </View>
        )}
        {view === "register" && (
          <View style={styles.inputWrap}>
            <Ionicons name="lock-closed-outline" size={18} color="#bbb" style={styles.inputIcon} />
            <TextInput style={[styles.input, { flex: 1 }]} placeholder="Confirmar contraseña" placeholderTextColor="#bbb" value={confirmPassword} onChangeText={setConfirmPassword} secureTextEntry={!showPass} returnKeyType="done" onSubmitEditing={handleRegister} />
          </View>
        )}
        {view === "login" && (
          <TouchableOpacity style={styles.forgotLink} onPress={() => switchView("forgot")}>
            <Text style={styles.forgotLinkText}>¿Olvidaste tu contraseña?</Text>
          </TouchableOpacity>
        )}
        <TouchableOpacity style={[styles.loginBtn, loading && { opacity: 0.7 }]} onPress={view === "login" ? handleLogin : view === "register" ? handleRegister : handleForgot} disabled={loading} activeOpacity={0.85}>
          {loading ? <ActivityIndicator color="#fff" size="small" /> : (
            <Text style={styles.loginBtnText}>
              {view === "login" ? "INICIAR SESIÓN" : view === "register" ? "CREAR CUENTA" : "ENVIAR ENLACE"}
            </Text>
          )}
        </TouchableOpacity>
        {view !== "forgot" && (
          <>
            <View style={styles.dividerRow}>
              <View style={styles.dividerLine} /><Text style={styles.dividerText}>o</Text><View style={styles.dividerLine} />
            </View>
            <TouchableOpacity style={styles.googleBtn} onPress={signInWithGoogle} activeOpacity={0.85}>
              <View style={styles.googleIconWrap}><Ionicons name="logo-google" size={18} color="#4285F4" /></View>
              <Text style={styles.googleBtnText}>Continuar con Google</Text>
            </TouchableOpacity>
          </>
        )}
        {view === "forgot" && <Text style={styles.forgotHint}>Recibirás un correo con un enlace válido por 1 hora.</Text>}
      </View>
    </KeyboardAvoidingView>
  );
}

// ─── SUB-HEADER (botón atrás + título) ────────────────────────────────────────
function SubHeader({ title, onBack, isDesktop }) {
  if (isDesktop) {
    return (
      <View style={sub.desktopHeader}>
        <Text style={sub.title}>{title}</Text>
      </View>
    );
  }
  return (
    <View style={sub.header}>
      <TouchableOpacity style={sub.backBtn} onPress={onBack}>
        <Ionicons name="arrow-back" size={22} color="#333" />
      </TouchableOpacity>
      <Text style={sub.title}>{title}</Text>
    </View>
  );
}

// ─── MIS DATOS ────────────────────────────────────────────────────────────────
export function MisDatos({ user, onBack, isDesktop }) {
  const [displayName, setDisplayName] = useState(user?.name || "");
  const [phone, setPhone] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!user?.id) return;
    AsyncStorage.getItem(`@tpn_phone_${user.id}`).then((v) => v && setPhone(v)).catch(() => {});
  }, [user?.id]);

  const handleSave = async () => {
    if (user?.id) {
      await AsyncStorage.setItem(`@tpn_phone_${user.id}`, phone).catch(() => {});
    }
    setSaved(true);
    setTimeout(() => { setSaved(false); if (!isDesktop) onBack(); }, 800);
  };

  return (
    <View style={isDesktop ? { flex: 1, backgroundColor: "#fff" } : styles.wrapper}>
      <SubHeader title="MIS DATOS" onBack={onBack} isDesktop={isDesktop} />
      <ScrollView contentContainerStyle={{ padding: 24 }}>
        {/* Avatar */}
        <View style={sub.avatarRow}>
          {user?.photo || user?.photo_url ? (
            <Image source={{ uri: user.photo || user.photo_url }} style={sub.avatar} />
          ) : (
            <View style={[sub.avatar, { backgroundColor: RED, justifyContent: "center", alignItems: "center" }]}>
              <Text style={{ color: "#fff", fontSize: 26, fontWeight: "900" }}>
                {(user?.name || "U")[0].toUpperCase()}
              </Text>
            </View>
          )}
        </View>

        <View style={sub.card}>
          <Text style={sub.fieldLabel}>NOMBRE</Text>
          <View style={sub.inputRow}>
            <Ionicons name="person-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
            <TextInput
              style={sub.input}
              value={displayName}
              onChangeText={setDisplayName}
              placeholder="Tu nombre"
              placeholderTextColor="#ccc"
              autoCapitalize="words"
            />
          </View>

          <Text style={[sub.fieldLabel, { marginTop: 12 }]}>CORREO ELECTRÓNICO</Text>
          <View style={[sub.inputRow, { backgroundColor: "#f9f9f9" }]}>
            <Ionicons name="mail-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
            <TextInput style={sub.input} value={user?.email || ""} editable={false} placeholderTextColor="#ccc" />
            <Ionicons name="lock-closed-outline" size={14} color="#ccc" style={{ marginRight: 14 }} />
          </View>
          <Text style={sub.hint}>El email no puede cambiarse</Text>

          <Text style={[sub.fieldLabel, { marginTop: 12 }]}>TELÉFONO</Text>
          <View style={sub.inputRow}>
            <Ionicons name="call-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
            <TextInput
              style={sub.input}
              value={phone}
              onChangeText={setPhone}
              placeholder="Tu número de teléfono"
              placeholderTextColor="#ccc"
              keyboardType="phone-pad"
            />
          </View>
        </View>

        <TouchableOpacity style={[sub.saveBtn, saved && { backgroundColor: "#22c55e" }]} onPress={handleSave} activeOpacity={0.85}>
          <Ionicons name={saved ? "checkmark" : "save-outline"} size={18} color="#fff" />
          <Text style={sub.saveBtnText}>{saved ? "¡Guardado!" : "GUARDAR CAMBIOS"}</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

// ─── MIS DIRECCIONES ──────────────────────────────────────────────────────────
export function MisDirecciones({ userId, onBack, isDesktop }) {
  const { address: gpsAddress, deliveryAddress, setDeliveryAddress } = useLocation();
  const [addresses, setAddresses] = useState([]);
  const [newAddr, setNewAddr] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const ADDR_KEY = `@tpn_addresses_${userId || "guest"}`;

  useEffect(() => {
    AsyncStorage.getItem(ADDR_KEY).then((d) => d && setAddresses(JSON.parse(d))).catch(() => {});
  }, [ADDR_KEY]);

  const save = async (list) => {
    setAddresses(list);
    await AsyncStorage.setItem(ADDR_KEY, JSON.stringify(list)).catch(() => {});
  };

  const addAddress = async () => {
    if (!newAddr.trim()) return;
    const entry = { id: Date.now(), label: newLabel.trim() || "Casa", address: newAddr.trim(), isDefault: addresses.length === 0 };
    await save([...addresses, entry]);
    setNewAddr(""); setNewLabel(""); setAdding(false);
  };

  const deleteAddress = (id) => save(addresses.filter((a) => a.id !== id));

  const setDefault = (id) => save(addresses.map((a) => ({ ...a, isDefault: a.id === id })));

  return (
    <View style={isDesktop ? { flex: 1, backgroundColor: "#fff" } : styles.wrapper}>
      <SubHeader title="MIS DIRECCIONES" onBack={onBack} isDesktop={isDesktop} />
      <ScrollView contentContainerStyle={{ padding: 24 }}>

        {/* Dirección activa que usa el mapa */}
        <View style={sub.activeAddrCard}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <Ionicons name="navigate-circle" size={18} color={RED} />
            <Text style={sub.activeAddrTitle}>DIRECCIÓN ACTIVA DEL MAPA</Text>
          </View>
          <Text style={sub.activeAddrText} numberOfLines={2}>
            {deliveryAddress || gpsAddress || "No detectada"}
          </Text>
          <Text style={sub.activeAddrHint}>
            Esta es la dirección que usa la app para tus pedidos y el mapa de rastreo.
            Selecciona una guardada para cambiarla.
          </Text>
        </View>

        {addresses.length === 0 && !adding && (
          <View style={sub.emptyBox}>
            <Ionicons name="location-outline" size={44} color="#ddd" />
            <Text style={sub.emptyText}>No tienes direcciones guardadas</Text>
          </View>
        )}

        {addresses.map((addr) => (
          <View key={addr.id} style={sub.addrCard}>
            <View style={[sub.addrIcon, addr.isDefault && { backgroundColor: "#fff5f5" }]}>
              <Ionicons name={addr.isDefault ? "location-sharp" : "location-outline"} size={20} color={addr.isDefault ? RED : "#aaa"} />
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={sub.addrLabel}>{addr.label}</Text>
                {addr.isDefault && (
                  <View style={sub.defaultBadge}><Text style={sub.defaultBadgeText}>Predeterminada</Text></View>
                )}
              </View>
              <Text style={sub.addrText}>{addr.address}</Text>
            </View>
            <View style={{ gap: 6 }}>
              {!addr.isDefault && (
                <TouchableOpacity onPress={() => { setDefault(addr.id); setDeliveryAddress(addr.address); }}>
                  <Ionicons name="star-outline" size={18} color="#aaa" />
                </TouchableOpacity>
              )}
              <TouchableOpacity onPress={() => deleteAddress(addr.id)}>
                <Ionicons name="trash-outline" size={18} color="#f87171" />
              </TouchableOpacity>
            </View>
          </View>
        ))}

        {adding ? (
          <View style={sub.card}>
            <Text style={sub.fieldLabel}>ETIQUETA (ej: Casa, Trabajo)</Text>
            <View style={sub.inputRow}>
              <Ionicons name="pricetag-outline" size={16} color="#bbb" style={{ marginLeft: 14 }} />
              <TextInput style={sub.input} value={newLabel} onChangeText={setNewLabel} placeholder="Casa" placeholderTextColor="#ccc" />
            </View>
            <Text style={[sub.fieldLabel, { marginTop: 10 }]}>DIRECCIÓN COMPLETA</Text>
            <View style={sub.inputRow}>
              <Ionicons name="location-outline" size={16} color="#bbb" style={{ marginLeft: 14 }} />
              <TextInput style={sub.input} value={newAddr} onChangeText={setNewAddr} placeholder="Calle, número, colonia..." placeholderTextColor="#ccc" multiline />
            </View>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity style={[sub.saveBtn, { flex: 1, backgroundColor: "#f0f0f0" }]} onPress={() => { setAdding(false); setNewAddr(""); setNewLabel(""); }}>
                <Text style={[sub.saveBtnText, { color: "#555" }]}>CANCELAR</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[sub.saveBtn, { flex: 1 }]} onPress={addAddress}>
                <Ionicons name="add" size={18} color="#fff" />
                <Text style={sub.saveBtnText}>AGREGAR</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <TouchableOpacity style={sub.addBtn} onPress={() => setAdding(true)}>
            <Ionicons name="add-circle-outline" size={20} color={RED} />
            <Text style={sub.addBtnText}>Agregar nueva dirección</Text>
          </TouchableOpacity>
        )}
      </ScrollView>
    </View>
  );
}

// ─── MÉTODOS DE PAGO ─────────────────────────────────────────────────────────
export function MetodosPago({ userId, onBack, isDesktop }) {
  const [cards, setCards] = useState([]);
  const [adding, setAdding] = useState(false);
  const [cardNum, setCardNum] = useState("");
  const [cardName, setCardName] = useState("");
  const [cardExpiry, setCardExpiry] = useState("");
  const CARDS_KEY = `@tpn_cards_${userId || "guest"}`;

  useEffect(() => {
    AsyncStorage.getItem(CARDS_KEY).then((d) => d && setCards(JSON.parse(d))).catch(() => {});
  }, [CARDS_KEY]);

  const save = async (list) => {
    setCards(list);
    await AsyncStorage.setItem(CARDS_KEY, JSON.stringify(list)).catch(() => {});
  };

  const brandIcon = (num) => {
    const n = num.replace(/\s/g, "");
    if (n.startsWith("4")) return { name: "VISA", color: "#1a1f71" };
    if (n.startsWith("5") || n.startsWith("2")) return { name: "MC", color: "#eb001b" };
    if (n.startsWith("3")) return { name: "AMEX", color: "#007bc1" };
    return { name: "CARD", color: "#888" };
  };

  const addCard = async () => {
    const digits = cardNum.replace(/\s/g, "");
    if (digits.length < 4) return;
    const brand = brandIcon(digits);
    const entry = { id: Date.now(), last4: digits.slice(-4), name: cardName.trim() || "Mi tarjeta", brand: brand.name, brandColor: brand.color, expiry: cardExpiry };
    await save([...cards, entry]);
    setCardNum(""); setCardName(""); setCardExpiry(""); setAdding(false);
  };

  const formatCardInput = (text) => {
    const digits = text.replace(/\D/g, "").slice(0, 16);
    return digits.replace(/(.{4})/g, "$1 ").trim();
  };

  const formatExpiry = (text) => {
    const digits = text.replace(/\D/g, "").slice(0, 4);
    if (digits.length > 2) return digits.slice(0, 2) + "/" + digits.slice(2);
    return digits;
  };

  return (
    <View style={isDesktop ? { flex: 1, backgroundColor: "#fff" } : styles.wrapper}>
      <SubHeader title="MÉTODOS DE PAGO" onBack={onBack} isDesktop={isDesktop} />
      <ScrollView contentContainerStyle={{ padding: 24 }}>
        {cards.length === 0 && !adding && (
          <View style={sub.emptyBox}>
            <Ionicons name="card-outline" size={44} color="#ddd" />
            <Text style={sub.emptyText}>No tienes tarjetas guardadas</Text>
          </View>
        )}

        {cards.map((card) => (
          <View key={card.id} style={sub.cardItem}>
            <View style={[sub.brandBadge, { backgroundColor: card.brandColor }]}>
              <Text style={sub.brandText}>{card.brand}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={sub.cardName}>{card.name}</Text>
              <Text style={sub.cardNum}>•••• •••• •••• {card.last4}   {card.expiry}</Text>
            </View>
            <TouchableOpacity onPress={() => save(cards.filter((c) => c.id !== card.id))}>
              <Ionicons name="trash-outline" size={18} color="#f87171" />
            </TouchableOpacity>
          </View>
        ))}

        {adding ? (
          <View style={sub.card}>
            <Text style={sub.fieldLabel}>NÚMERO DE TARJETA</Text>
            <View style={sub.inputRow}>
              <Ionicons name="card-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
              <TextInput style={sub.input} value={cardNum} onChangeText={(t) => setCardNum(formatCardInput(t))} placeholder="0000 0000 0000 0000" placeholderTextColor="#ccc" keyboardType="numeric" maxLength={19} />
            </View>
            <Text style={[sub.fieldLabel, { marginTop: 10 }]}>NOMBRE EN LA TARJETA</Text>
            <View style={sub.inputRow}>
              <Ionicons name="person-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
              <TextInput style={sub.input} value={cardName} onChangeText={setCardName} placeholder="Como aparece en la tarjeta" placeholderTextColor="#ccc" autoCapitalize="characters" />
            </View>
            <Text style={[sub.fieldLabel, { marginTop: 10 }]}>VENCIMIENTO</Text>
            <View style={sub.inputRow}>
              <Ionicons name="calendar-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
              <TextInput style={sub.input} value={cardExpiry} onChangeText={(t) => setCardExpiry(formatExpiry(t))} placeholder="MM/AA" placeholderTextColor="#ccc" keyboardType="numeric" maxLength={5} />
            </View>
            <View style={sub.hint2}><Ionicons name="lock-closed-outline" size={13} color="#aaa" /><Text style={sub.hintText}>Tus datos se guardan de forma segura en este dispositivo</Text></View>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity style={[sub.saveBtn, { flex: 1, backgroundColor: "#f0f0f0" }]} onPress={() => setAdding(false)}>
                <Text style={[sub.saveBtnText, { color: "#555" }]}>CANCELAR</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[sub.saveBtn, { flex: 1 }]} onPress={addCard}>
                <Ionicons name="add" size={18} color="#fff" />
                <Text style={sub.saveBtnText}>AGREGAR</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <TouchableOpacity style={sub.addBtn} onPress={() => setAdding(true)}>
            <Ionicons name="add-circle-outline" size={20} color={RED} />
            <Text style={sub.addBtnText}>Agregar tarjeta</Text>
          </TouchableOpacity>
        )}
      </ScrollView>
    </View>
  );
}

// ─── LISTA DE DESEOS ──────────────────────────────────────────────────────────
export function ListaDeseos({ onBack, isDesktop }) {
  const { wishlist, toggleWishlist } = useWishlist();
  const [selectedProduct, setSelectedProduct] = useState(null);

  return (
    <View style={isDesktop ? { flex: 1, backgroundColor: "#fff" } : styles.wrapper}>
      <SubHeader title="LISTA DE DESEOS" onBack={onBack} isDesktop={isDesktop} />
      {wishlist.length === 0 ? (
        <View style={sub.emptyBox}>
          <Ionicons name="heart-outline" size={48} color="#ddd" />
          <Text style={sub.emptyText}>Tu lista de deseos está vacía</Text>
          <Text style={{ fontSize: 12, color: "#bbb", textAlign: "center", marginTop: 4 }}>
            Presiona el corazón en cualquier producto para guardarlo aquí
          </Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 24 }}>
          <Text style={sub.listCount}>{wishlist.length} {wishlist.length === 1 ? "producto" : "productos"}</Text>
          {wishlist.map((item) => (
            <TouchableOpacity key={item.id} style={sub.wishItem} onPress={() => setSelectedProduct(item)} activeOpacity={0.85}>
              <Image source={{ uri: item.img }} style={sub.wishImg} resizeMode="contain" />
              <View style={{ flex: 1 }}>
                <Text style={sub.wishCat}>{item.cat}</Text>
                <Text style={sub.wishName} numberOfLines={2}>{item.name}</Text>
                <Text style={sub.wishPrice}>{item.price}</Text>
              </View>
              <TouchableOpacity
                style={sub.wishHeart}
                onPress={(e) => { e.stopPropagation?.(); toggleWishlist(item); }}
              >
                <Ionicons name="heart" size={20} color={RED} />
              </TouchableOpacity>
            </TouchableOpacity>
          ))}
          <View style={{ height: 80 }} />
        </ScrollView>
      )}
      <ProductDetailModal visible={!!selectedProduct} product={selectedProduct} onClose={() => setSelectedProduct(null)} />
    </View>
  );
}

// ─── PANTALLA PRINCIPAL ───────────────────────────────────────────────────────
export default function ProfileScreen({ onAuthSuccess, onOrdersPress, initialSubScreen = null, onReturn = null }) {
  const { user, signOut } = useAuth();
  const { wishlist } = useWishlist();
  const { isDark, t, toggleDark, notificationsEnabled, toggleNotifications } = useTheme();
  const { width } = useWindowDimensions();
  const { bottom: safeBottom } = useSafeAreaInsets();
  const isDesktop = width >= 1024;
  const isLoggedIn = !!user;
  const wasLoggedIn = useRef(isLoggedIn);
  const [currentScreen, setCurrentScreen] = useState(initialSubScreen);
  const [ordersCount, setOrdersCount] = useState(0);
  const [savedAmount, setSavedAmount] = useState(0);

  // Sincronizar sub-pantalla externa
  useEffect(() => {
    if (initialSubScreen) setCurrentScreen(initialSubScreen);
  }, [initialSubScreen]);

  // Cargar estadísticas del usuario (Pedidos y Ahorro estimado)
  useEffect(() => {
    if (user?.token) {
      const { getUserOrders } = require("../services/api");
      getUserOrders(user.token).then((res) => {
        if (res?.success && Array.isArray(res.data)) {
          setOrdersCount(res.data.length);
          // Simulación de ahorro: 5% del total de pedidos entregados
          const totalSpent = res.data
            .filter(o => o.status === "delivered")
            .reduce((sum, o) => sum + parseFloat(o.total || 0), 0);
          setSavedAmount(totalSpent * 0.05); 
        }
      }).catch(() => {});
    }
  }, [user?.token, isLoggedIn]);

  useEffect(() => {
    if (isLoggedIn && !wasLoggedIn.current) {
      onAuthSuccess?.();
    }
    wasLoggedIn.current = isLoggedIn;
  }, [isLoggedIn]);

  const handleBack = () => {
    if (initialSubScreen && onReturn) {
      onReturn();
    } else {
      setCurrentScreen(null);
    }
  };

  // Mobile: sub-screens as full-page replacements
  if (!isDesktop) {
    if (currentScreen === "datos") return <MisDatos user={user} onBack={handleBack} />;
    if (currentScreen === "direcciones") return <MisDirecciones userId={user?.id} onBack={handleBack} />;
    if (currentScreen === "pagos") return <MetodosPago userId={user?.id} onBack={handleBack} />;
    if (currentScreen === "deseos") return <ListaDeseos onBack={handleBack} />;
  }


  const MENU_SECTIONS = [
    {
      title: "MI CUENTA",
      items: [
        { key: "datos",      icon: "person-circle-outline", label: "Mis datos",         onPress: () => setCurrentScreen("datos") },
        { key: "direcciones",icon: "location-outline",      label: "Mis direcciones",   onPress: () => setCurrentScreen("direcciones") },
        { key: "pagos",      icon: "card-outline",          label: "Métodos de pago",   onPress: () => setCurrentScreen("pagos") },
      ],
    },
    {
      title: "PEDIDOS",
      items: [
        { key: null, icon: "receipt-outline", label: "Historial de pedidos", onPress: () => onOrdersPress?.() },
        { key: "deseos", icon: "heart-outline", label: "Lista de deseos", onPress: () => setCurrentScreen("deseos"), badge: wishlist.length > 0 ? String(wishlist.length) : null },
      ],
    },
    {
      title: "PREFERENCIAS",
      items: [
        { key: null, icon: "notifications-outline", label: "Notificaciones", toggle: true, toggleValue: notificationsEnabled, onToggle: () => toggleNotifications(registerForPushNotifications) },
        { key: null, icon: "moon-outline",          label: "Modo oscuro",     toggle: true, toggleValue: isDark,                 onToggle: toggleDark },
      ],
    },
    {
      title: "SOPORTE",
      items: [
        { key: null, icon: "chatbubble-ellipses-outline", label: "Chat de soporte" },
        { key: null, icon: "help-circle-outline",         label: "Preguntas frecuentes" },
        { key: null, icon: "document-text-outline",       label: "Términos y condiciones" },
        { key: null, icon: "shield-checkmark-outline",    label: "Aviso de privacidad" },
      ],
    },
  ];

  // ─── DESKTOP LAYOUT ──────────────────────────────────────────────────────────
  if (isDesktop) {
    const renderDesktopContent = () => {
      if (currentScreen === "datos")       return <MisDatos user={user} onBack={() => setCurrentScreen(null)} isDesktop />;
      if (currentScreen === "direcciones") return <MisDirecciones userId={user?.id} onBack={() => setCurrentScreen(null)} isDesktop />;
      if (currentScreen === "pagos")       return <MetodosPago userId={user?.id} onBack={() => setCurrentScreen(null)} isDesktop />;
      if (currentScreen === "deseos")      return <ListaDeseos onBack={() => setCurrentScreen(null)} isDesktop />;
      return (
        <View style={deskProf.placeholder}>
          <Ionicons name="person-circle-outline" size={56} color="#e0e0e0" />
          <Text style={deskProf.placeholderText}>Selecciona una opción del menú</Text>
        </View>
      );
    };

    return (
      <View style={{ flex: 1, backgroundColor: t.bg }}>
        <View style={deskProf.body}>
          {/* ── Sidebar izquierdo ─────────────────────────────────────── */}
          <View style={[deskProf.sidebar, { backgroundColor: t.card }]}>
            <ScrollView showsVerticalScrollIndicator={false}>
              {isLoggedIn ? (
                <>
                  {/* Perfil */}
                  <View style={deskProf.profileHead}>
                    <View style={styles.avatarWrap}>
                      {user.photo || user.photo_url ? (
                        <Image source={{ uri: user.photo || user.photo_url }} style={deskProf.avatar} />
                      ) : (
                        <View style={[deskProf.avatar, { backgroundColor: RED, justifyContent: "center", alignItems: "center" }]}>
                          <Text style={{ color: "#fff", fontSize: 22, fontWeight: "900" }}>{(user.name || "U")[0].toUpperCase()}</Text>
                        </View>
                      )}
                      {user.loginType === "google" && (
                        <View style={styles.googleBadge}><Ionicons name="logo-google" size={9} color="#fff" /></View>
                      )}
                    </View>
                    <Text style={deskProf.profileName} numberOfLines={1}>{(user.name || "Usuario").toUpperCase()}</Text>
                    <Text style={deskProf.profileEmail} numberOfLines={1}>{user.email}</Text>
                  </View>

                  {/* Stats */}
                  <View style={deskProf.statsRow}>
                    <TouchableOpacity style={deskProf.statItem} onPress={() => onOrdersPress?.()}>
                      <Text style={[deskProf.statNum, { color: t.text }]}>{ordersCount}</Text>
                      <Text style={[deskProf.statLabel, { color: t.textMuted }]}>Pedidos</Text>
                    </TouchableOpacity>
                    <View style={[styles.statDivider, { backgroundColor: t.divider }]} />
                    <TouchableOpacity style={deskProf.statItem} onPress={() => setCurrentScreen("deseos")}>
                      <Text style={[deskProf.statNum, { color: t.text }]}>{wishlist.length}</Text>
                      <Text style={[deskProf.statLabel, { color: t.textMuted }]}>Favoritos</Text>
                    </TouchableOpacity>
                  </View>
                  {/* Menú */}
                  <View style={{ paddingHorizontal: 12, paddingTop: 8 }}>
                    {MENU_SECTIONS.map((section, si) => (
                      <View key={si} style={{ marginBottom: 16 }}>
                        <Text style={deskProf.sectionTitle}>{section.title}</Text>
                        {section.items.map((item, ii) => {
                          const isActive = item.key && currentScreen === item.key;
                          return (
                            <TouchableOpacity
                              key={ii}
                              style={[deskProf.menuItem, isActive && deskProf.menuItemActive]}
                              onPress={item.toggle ? item.onToggle : item.onPress}
                              disabled={!item.onPress && !item.toggle}
                              activeOpacity={item.toggle ? 1 : 0.7}
                            >
                              <View style={[deskProf.menuIcon, isActive && deskProf.menuIconActive]}>
                                <Ionicons name={item.icon} size={18} color={isActive ? RED : "#888"} />
                              </View>
                              <Text style={[deskProf.menuLabel, isActive && deskProf.menuLabelActive]}>{item.label}</Text>
                              {item.badge && (
                                <View style={styles.menuBadge}><Text style={styles.menuBadgeText}>{item.badge}</Text></View>
                              )}
                              {item.toggle ? (
                                <Switch
                                  value={item.toggleValue}
                                  onValueChange={item.onToggle}
                                  trackColor={{ false: "#e5e7eb", true: "#fca5a5" }}
                                  thumbColor={item.toggleValue ? RED : "#f3f4f6"}
                                  ios_backgroundColor="#e5e7eb"
                                />
                              ) : !item.badge && (
                                <Ionicons name="chevron-forward" size={14} color={isActive ? RED : "#ddd"} />
                              )}
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    ))}

                    <TouchableOpacity style={deskProf.logoutBtn} onPress={signOut}>
                      <Ionicons name="log-out-outline" size={16} color={RED} />
                      <Text style={deskProf.logoutText}>Cerrar sesión</Text>
                    </TouchableOpacity>
                    <Text style={[styles.versionText, { marginBottom: 16 }]}>TPN v1.0.0</Text>
                  </View>
                </>
              ) : (
                <View style={{ padding: 20 }}>
                  <AuthView />
                </View>
              )}
            </ScrollView>
          </View>

          {/* ── Panel derecho ─────────────────────────────────────────── */}
          <View style={[deskProf.main, { backgroundColor: t.card }]}>
            {isLoggedIn ? renderDesktopContent() : (
              <View style={deskProf.placeholder}>
                <Ionicons name="lock-closed-outline" size={48} color="#e0e0e0" />
                <Text style={deskProf.placeholderText}>Inicia sesión para ver tu perfil</Text>
              </View>
            )}
          </View>
        </View>
      </View>
    );
  }

  // ─── MOBILE LAYOUT ───────────────────────────────────────────────────────────
  return (
    <View style={[styles.wrapper, { backgroundColor: t.bg }]}>
      <View style={[styles.header, { backgroundColor: t.header, borderBottomColor: t.border }]}>
        <Text style={[styles.headerTitle, { color: t.text }]}>MI PERFIL</Text>
      </View>

      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={[styles.scrollContent, { paddingBottom: safeBottom + 84 }]}>
        {isLoggedIn ? (
          <>
            {/* Tarjeta de usuario */}
            <View style={[styles.profileCard, { backgroundColor: t.card }]}>
              <View style={styles.avatarWrap}>
                {user.photo || user.photo_url ? (
                  <Image source={{ uri: user.photo || user.photo_url }} style={styles.avatarImg} />
                ) : (
                  <View style={styles.avatar}>
                    <Text style={styles.avatarText}>{(user.name || "U")[0].toUpperCase()}</Text>
                  </View>
                )}
                {user.loginType === "google" && (
                  <View style={styles.googleBadge}>
                    <Ionicons name="logo-google" size={9} color="#fff" />
                  </View>
                )}
              </View>
              <View style={styles.profileInfo}>
                <Text style={[styles.profileName, { color: t.text }]}>{(user.name || "USUARIO").toUpperCase()}</Text>
                <Text style={[styles.profileEmail, { color: t.textMuted }]}>{user.email}</Text>
              </View>
              <TouchableOpacity style={styles.editBtn} onPress={() => setCurrentScreen("datos")}>
                <Ionicons name="create-outline" size={18} color={RED} />
              </TouchableOpacity>
            </View>

            {/* Estadísticas */}
            <View style={[styles.statsRow, { backgroundColor: t.card }]}>
              <TouchableOpacity style={styles.statItem} onPress={() => onOrdersPress?.()}>
                <Text style={[styles.statNum, { color: t.text }]}>{ordersCount}</Text>
                <Text style={[styles.statLabel, { color: t.textMuted }]}>Pedidos</Text>
              </TouchableOpacity>
              <View style={[styles.statDivider, { backgroundColor: t.divider }]} />
              <TouchableOpacity style={styles.statItem} onPress={() => setCurrentScreen("deseos")}>
                <Text style={[styles.statNum, { color: t.text }]}>{wishlist.length}</Text>
                <Text style={[styles.statLabel, { color: t.textMuted }]}>Favoritos</Text>
              </TouchableOpacity>
              <View style={[styles.statDivider, { backgroundColor: t.divider }]} />
              <View style={styles.statItem}>
                <Text style={[styles.statNum, { color: t.text }]}>${Math.round(savedAmount)}</Text>
                <Text style={[styles.statLabel, { color: t.textMuted }]}>Ahorrado</Text>
              </View>
            </View>

            {/* Menú de secciones */}
            {MENU_SECTIONS.map((section, si) => (
              <View key={si} style={styles.menuSection}>
                <Text style={[styles.menuSectionTitle, { color: t.textMuted }]}>{section.title}</Text>
                <View style={[styles.menuCard, { backgroundColor: t.card }]}>
                  {section.items.map((item, ii) => (
                    <View key={ii}>
                      <TouchableOpacity
                        style={[styles.menuItem, { borderBottomColor: t.divider }]}
                        activeOpacity={item.toggle ? 1 : 0.7}
                        onPress={item.toggle ? item.onToggle : item.onPress}
                        disabled={!item.onPress && !item.toggle}
                      >
                        <View style={styles.menuItemLeft}>
                          <View style={[styles.menuIconWrap, { backgroundColor: t.iconBgRed }]}>
                            <Ionicons name={item.icon} size={20} color={RED} />
                          </View>
                          <Text style={[styles.menuItemLabel, { color: t.text }]}>{item.label}</Text>
                          {item.badge && (
                            <View style={styles.menuBadge}>
                              <Text style={styles.menuBadgeText}>{item.badge}</Text>
                            </View>
                          )}
                        </View>
                        {item.toggle ? (
                          <Switch
                            value={item.toggleValue}
                            onValueChange={item.onToggle}
                            trackColor={{ false: "#e5e7eb", true: "#fca5a5" }}
                            thumbColor={item.toggleValue ? RED : "#f3f4f6"}
                            ios_backgroundColor="#e5e7eb"
                          />
                        ) : (
                          <Ionicons name="chevron-forward" size={16} color="#ddd" />
                        )}
                      </TouchableOpacity>
                      {ii < section.items.length - 1 && <View style={styles.menuDivider} />}
                    </View>
                  ))}
                </View>
              </View>
            ))}

            <TouchableOpacity style={styles.logoutBtn} onPress={signOut}>
              <Ionicons name="log-out-outline" size={18} color={RED} />
              <Text style={styles.logoutText}>Cerrar sesión</Text>
            </TouchableOpacity>
            <Text style={styles.versionText}>Todo Pal Negocio v1.0.0</Text>
          </>
        ) : (
          <AuthView />
        )}
        <View style={{ height: 120 }} />
      </ScrollView>
    </View>
  );
}

// ─── ESTILOS PRINCIPALES ──────────────────────────────────────────────────────
const styles = StyleSheet.create({
  wrapper: { 
    flex: 1, 
    backgroundColor: "#f5f5f5",
    paddingTop: Platform.OS === "ios" ? 54 : 44,
  },
  header: {
    backgroundColor: "#fff", 
    paddingHorizontal: 16, 
    height: 72,
    borderBottomWidth: 1, 
    borderBottomColor: "#f0f0f0",
    flexDirection: "row", 
    alignItems: "center",
  },
  headerTitle: { fontSize: 18, fontWeight: "900", color: "#111" },
  scrollContent: { padding: 16 },

  // Auth
  authCard: {
    backgroundColor: "#fff", borderRadius: 20, padding: 24, marginBottom: 16,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.06, shadowRadius: 12, elevation: 3,
  },
  authTabs: { flexDirection: "row", backgroundColor: "#f5f5f5", borderRadius: 12, padding: 4, marginBottom: 20 },
  authTab: { flex: 1, paddingVertical: 9, borderRadius: 10, alignItems: "center" },
  authTabActive: { backgroundColor: "#fff", shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.08, shadowRadius: 4, elevation: 2 },
  authTabText: { fontSize: 13, fontWeight: "700", color: "#999" },
  authTabTextActive: { color: "#111" },
  forgotHeader: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 20 },
  backBtn: { width: 36, height: 36, borderRadius: 10, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  authTitle: { fontSize: 18, fontWeight: "900", color: "#111" },
  authSubtitle: { fontSize: 14, color: "#888", lineHeight: 21, marginBottom: 20, textAlign: "center" },
  successIcon: { width: 80, height: 80, borderRadius: 40, backgroundColor: "#fff5f5", justifyContent: "center", alignItems: "center", alignSelf: "center", marginBottom: 16 },
  inputWrap: { flexDirection: "row", alignItems: "center", backgroundColor: "#f8f8f8", borderRadius: 12, marginBottom: 12, borderWidth: 1, borderColor: "#f0f0f0", height: 50 },
  inputIcon: { paddingHorizontal: 14 },
  input: { flex: 1, fontSize: 14, color: "#111", paddingRight: 12 },
  forgotLink: { alignSelf: "flex-end", marginBottom: 16 },
  forgotLinkText: { fontSize: 12, color: RED, fontWeight: "700" },
  forgotHint: { fontSize: 12, color: "#999", textAlign: "center", marginTop: 12 },
  errorBanner: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fef2f2", borderRadius: 10, padding: 12, marginBottom: 12, borderWidth: 1, borderColor: "#fecaca" },
  errorText: { flex: 1, fontSize: 12, color: "#dc2626", fontWeight: "600" },
  loginBtn: { backgroundColor: RED, paddingVertical: 14, borderRadius: 14, alignItems: "center", marginBottom: 12 },
  loginBtnText: { fontSize: 14, fontWeight: "900", color: "#fff" },
  dividerRow: { flexDirection: "row", alignItems: "center", gap: 12, marginVertical: 4, marginBottom: 12 },
  dividerLine: { flex: 1, height: 1, backgroundColor: "#f0f0f0" },
  dividerText: { fontSize: 12, color: "#ccc", fontWeight: "700" },
  googleBtn: { flexDirection: "row", alignItems: "center", backgroundColor: "#fff", borderWidth: 1.5, borderColor: "#e5e7eb", borderRadius: 14, paddingVertical: 12, paddingHorizontal: 16, gap: 12 },
  googleIconWrap: { width: 30, height: 30, borderRadius: 15, backgroundColor: "#f0f6ff", justifyContent: "center", alignItems: "center" },
  googleBtnText: { fontSize: 14, fontWeight: "700", color: "#333", flex: 1, textAlign: "center" },

  // Profile card
  profileCard: { backgroundColor: "#fff", borderRadius: 20, padding: 20, flexDirection: "row", alignItems: "center", gap: 16, marginBottom: 16, shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2 },
  avatarWrap: { position: "relative" },
  avatar: { width: 64, height: 64, borderRadius: 32, backgroundColor: RED, justifyContent: "center", alignItems: "center" },
  avatarImg: { width: 64, height: 64, borderRadius: 32 },
  avatarText: { fontSize: 22, fontWeight: "900", color: "#fff" },
  googleBadge: { position: "absolute", bottom: 0, right: 0, width: 20, height: 20, borderRadius: 10, backgroundColor: "#4285F4", justifyContent: "center", alignItems: "center", borderWidth: 2, borderColor: "#fff" },
  profileInfo: { flex: 1 },
  profileName: { fontSize: 16, fontWeight: "900", color: "#111", marginBottom: 2 },
  profileEmail: { fontSize: 12, color: "#888" },
  editBtn: { width: 36, height: 36, borderRadius: 10, backgroundColor: "#fff5f5", justifyContent: "center", alignItems: "center" },

  // Stats
  statsRow: { backgroundColor: "#fff", borderRadius: 16, flexDirection: "row", alignItems: "center", padding: 20, marginBottom: 16, shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2 },
  statItem: { flex: 1, alignItems: "center" },
  statNum: { fontSize: 22, fontWeight: "900", color: "#111", marginBottom: 2 },
  statLabel: { fontSize: 11, color: "#999", fontWeight: "600" },
  statDivider: { width: 1, height: 36, backgroundColor: "#f0f0f0" },

  // Menu
  menuSection: { marginBottom: 20 },
  menuSectionTitle: { fontSize: 11, fontWeight: "800", color: "#bbb", marginBottom: 8, letterSpacing: 0.5 },
  menuCard: { backgroundColor: "#fff", borderRadius: 16, overflow: "hidden", shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2 },
  menuItem: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 16, paddingVertical: 14 },
  menuItemLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  menuIconWrap: { width: 36, height: 36, borderRadius: 10, backgroundColor: "#fff5f5", justifyContent: "center", alignItems: "center" },
  menuItemLabel: { fontSize: 14, fontWeight: "600", color: "#222" },
  menuBadge: { backgroundColor: RED, borderRadius: 10, minWidth: 20, height: 20, justifyContent: "center", alignItems: "center", paddingHorizontal: 5 },
  menuBadgeText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  menuDivider: { height: 1, backgroundColor: "#f8f8f8", marginLeft: 64 },
  toggleOff: { width: 42, height: 24, borderRadius: 12, backgroundColor: "#e5e7eb", justifyContent: "center", paddingHorizontal: 3 },
  toggleThumb: { width: 18, height: 18, borderRadius: 9, backgroundColor: "#fff", shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.15, shadowRadius: 2, elevation: 2 },

  logoutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 16, marginBottom: 8 },
  logoutText: { fontSize: 14, fontWeight: "700", color: RED },
  versionText: { fontSize: 11, color: "#ccc", textAlign: "center" },
});

// ─── ESTILOS SUB-PANTALLAS ────────────────────────────────────────────────────
const sub = StyleSheet.create({
  header: { 
    backgroundColor: "#fff", 
    paddingHorizontal: 16, 
    height: 72, 
    flexDirection: "row", 
    alignItems: "center", 
    borderBottomWidth: 1, 
    borderBottomColor: "#f0f0f0" 
  },
  backBtn: { 
    width: 44, 
    height: 44, 
    borderRadius: 22, 
    backgroundColor: "#f5f5f5", 
    justifyContent: "center", 
    alignItems: "center",
    marginRight: 16,
  },
  title: { fontSize: 18, fontWeight: "900", color: "#111" },

  avatarRow: { alignItems: "center", marginBottom: 16 },
  avatar: { width: 80, height: 80, borderRadius: 40 },

  card: { backgroundColor: "#fff", borderRadius: 16, padding: 16, marginBottom: 16, shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2 },
  fieldLabel: { fontSize: 10, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 6 },
  inputRow: { flexDirection: "row", alignItems: "center", backgroundColor: "#f8f8f8", borderRadius: 12, borderWidth: 1, borderColor: "#f0f0f0", height: 50 },
  input: { flex: 1, fontSize: 14, color: "#111", paddingHorizontal: 12 },
  hint: { fontSize: 11, color: "#bbb", marginTop: 4 },
  hint2: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  hintText: { fontSize: 11, color: "#aaa", flex: 1 },

  saveBtn: { backgroundColor: RED, borderRadius: 14, paddingVertical: 14, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  saveBtnText: { color: "#fff", fontWeight: "900", fontSize: 14 },

  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, backgroundColor: "#fff", borderRadius: 14, borderWidth: 1.5, borderColor: "#f0f0f0", borderStyle: "dashed" },
  addBtnText: { color: RED, fontWeight: "700", fontSize: 14 },

  emptyBox: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: 60, gap: 12 },
  emptyText: { fontSize: 14, color: "#bbb", fontWeight: "600", textAlign: "center" },

  activeAddrCard: { backgroundColor: "#fff5f5", borderRadius: 14, padding: 14, marginBottom: 16, borderWidth: 1, borderColor: "#fecaca" },
  activeAddrTitle: { fontSize: 10, fontWeight: "800", color: RED, letterSpacing: 0.5 },
  activeAddrText: { fontSize: 13, fontWeight: "700", color: "#111", marginBottom: 4 },
  activeAddrHint: { fontSize: 11, color: "#888" },
  addrCard: { backgroundColor: "#fff", borderRadius: 14, padding: 14, marginBottom: 10, flexDirection: "row", alignItems: "center", gap: 12, shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.04, shadowRadius: 4, elevation: 1 },
  addrIcon: { width: 40, height: 40, borderRadius: 10, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  addrLabel: { fontSize: 13, fontWeight: "800", color: "#111" },
  addrText: { fontSize: 12, color: "#888", marginTop: 2 },
  defaultBadge: { backgroundColor: "#fff5f5", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8 },
  defaultBadgeText: { fontSize: 10, fontWeight: "700", color: RED },

  cardItem: { backgroundColor: "#fff", borderRadius: 14, padding: 14, marginBottom: 10, flexDirection: "row", alignItems: "center", gap: 12, shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.04, shadowRadius: 4, elevation: 1 },
  brandBadge: { width: 44, height: 28, borderRadius: 6, justifyContent: "center", alignItems: "center" },
  brandText: { color: "#fff", fontSize: 10, fontWeight: "900" },
  cardName: { fontSize: 13, fontWeight: "700", color: "#111" },
  cardNum: { fontSize: 12, color: "#aaa", marginTop: 2 },

  wishItem: { backgroundColor: "#fff", borderRadius: 14, padding: 12, marginBottom: 10, flexDirection: "row", alignItems: "center", gap: 12, shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.04, shadowRadius: 4, elevation: 1 },
  wishImg: { width: 64, height: 64, borderRadius: 10, backgroundColor: "#f9f9f9" },
  wishCat: { fontSize: 10, color: "#aaa", fontWeight: "600", marginBottom: 2 },
  wishName: { fontSize: 13, fontWeight: "700", color: "#111", marginBottom: 4 },
  wishPrice: { fontSize: 14, fontWeight: "900", color: RED },
  wishHeart: { padding: 8 },
  listCount: { fontSize: 11, fontWeight: "700", color: "#bbb", marginBottom: 12 },

  desktopHeader: { paddingHorizontal: 24, paddingVertical: 20, borderBottomWidth: 1, borderBottomColor: "#f0f0f0", backgroundColor: "#fff" },
});

// ─── ESTILOS DESKTOP PERFIL ──────────────────────────────────────────────────
const deskProf = StyleSheet.create({
  body: {
    flex: 1,
    flexDirection: "row",
    maxWidth: 1200,
    alignSelf: "center",
    width: "100%",
    paddingHorizontal: 16,
    paddingTop: 24,
    paddingBottom: 24,
    gap: 24,
  },
  sidebar: {
    width: 280,
    backgroundColor: "#fff",
    borderRadius: 20,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 3,
  },
  main: {
    flex: 1,
    backgroundColor: "#fff",
    borderRadius: 20,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 3,
  },
  profileHead: {
    alignItems: "center",
    paddingVertical: 24,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: "#f5f5f5",
  },
  avatar: { width: 72, height: 72, borderRadius: 36, marginBottom: 10 },
  profileName: { fontSize: 14, fontWeight: "900", color: "#111", textAlign: "center", marginBottom: 2 },
  profileEmail: { fontSize: 12, color: "#aaa", textAlign: "center" },
  statsRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: "#f5f5f5",
  },
  statItem: { flex: 1, alignItems: "center" },
  statNum: { fontSize: 18, fontWeight: "900", color: "#111", marginBottom: 2 },
  statLabel: { fontSize: 10, color: "#aaa", fontWeight: "600" },
  sectionTitle: { fontSize: 10, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 6, marginTop: 4 },
  menuItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 9,
    paddingHorizontal: 10,
    borderRadius: 10,
    marginBottom: 2,
  },
  menuItemActive: { backgroundColor: "#fff5f5" },
  menuIcon: { width: 32, height: 32, borderRadius: 8, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  menuIconActive: { backgroundColor: "#fff0f0" },
  menuLabel: { flex: 1, fontSize: 13, color: "#555", fontWeight: "600" },
  menuLabelActive: { color: RED, fontWeight: "800" },
  logoutBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 12, paddingHorizontal: 10, marginTop: 4 },
  logoutText: { fontSize: 13, fontWeight: "700", color: RED },
  placeholder: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
  placeholderText: { fontSize: 14, color: "#ccc", fontWeight: "600" },
});
