import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
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
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { useTheme } from "../context/ThemeContext";
import { useLocation } from "../context/LocationContext";
import LocationPickerModal, { COVERAGE_KM, EXTENDED_KM, TPN_STORES } from "../components/LocationPickerModal";
import { createOrder, getStores, GOOGLE_MAPS_API_KEY } from "../services/api";

const RED    = "#e6192e";
const GREEN  = "#22c55e";
const ORANGE = "#f59e0b";

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

async function fetchDrivingETA(fromLat, fromLng, toLat, toLng) {
  try {
    if (!GOOGLE_MAPS_API_KEY || GOOGLE_MAPS_API_KEY === "TU_GOOGLE_MAPS_API_KEY") return null;
    const url = `https://maps.googleapis.com/maps/api/directions/json?origin=${fromLat},${fromLng}&destination=${toLat},${toLng}&key=${GOOGLE_MAPS_API_KEY}&departure_time=now`;
    const res  = await fetch(url);
    const data = await res.json();
    const leg = data?.routes?.[0]?.legs?.[0];
    const secs = leg?.duration_in_traffic?.value || leg?.duration?.value;
    if (!secs) return null;
    const min = Math.ceil((secs / 60 + 10) / 5) * 5;
    return min;
  } catch {
    return null;
  }
}

function formatMinutes(min) {
  if (!min) return null;
  return min >= 60
    ? `~${Math.floor(min / 60)}h ${min % 60 > 0 ? `${min % 60} min` : ""} en auto`.trim()
    : `~${min} min en auto`;
}

// ─── PASOS DEL CHECKOUT ───────────────────────────────────────────────────────
const STEPS = ["Dirección", "Pago", "Confirmar"];

// ─── STEP INDICATOR ───────────────────────────────────────────────────────────
function StepBar({ step, width, isDesktop }) {
  const isSmall = !isDesktop && width < 360;

  return (
    <View style={s.stepBarContainer}>
      <View style={s.stepBar}>
        {STEPS.map((label, i) => (
          <React.Fragment key={i}>
            <View style={s.stepPoint}>
              <View style={[s.stepCircle, i < step && s.stepDone, i === step && s.stepActive]}>
                {i < step ? (
                  <Ionicons name="checkmark" size={13} color="#fff" />
                ) : (
                  <Text style={[s.stepNum, i === step && { color: "#fff" }]}>{i + 1}</Text>
                )}
              </View>
              {!isSmall && (
                <Text style={[s.stepLabel, i === step && s.stepLabelActive]} numberOfLines={1}>
                  {label}
                </Text>
              )}
            </View>
            {i < STEPS.length - 1 && (
              <View style={[s.stepLine, i < step && s.stepLineDone]} />
            )}
          </React.Fragment>
        ))}
      </View>
    </View>
  );
}

// ─── PANTALLA PRINCIPAL ───────────────────────────────────────────────────────
export default function CheckoutScreen({ onBack, onSuccess }) {
  const { user } = useAuth();
  const { t } = useTheme();
  const { items, subtotal, clearCart } = useCart();
  const { address, coords, deliveryAddress, deliveryCoords } = useLocation();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 1024;
  
  const shipping = subtotal > 500 ? 0 : 49;
  const total = subtotal + shipping;

  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [orderDone, setOrderDone] = useState(null);

  // ── Dirección ──────────────────────────────────────────────────────────────
  const [addresses, setAddresses] = useState([]);
  const [selectedAddr, setSelectedAddr] = useState(null);
  const [manualAddr, setManualAddr] = useState("");
  const [destCoords, setDestCoords] = useState(null);
  const [pickerVisible, setPickerVisible] = useState(false);
  const [etaMinutes, setEtaMinutes] = useState(null);
  const [etaLoading, setEtaLoading] = useState(false);

  useEffect(() => {
    if (!user?.id) return;
    AsyncStorage.getItem(`@tpn_addresses_${user.id}`)
      .then((d) => {
        if (d) {
          const list = JSON.parse(d);
          setAddresses(list);
          const def = list.find((a) => a.isDefault) || list[0];
          if (def) setSelectedAddr(def.id);
        }
      })
      .catch(() => {});
  }, [user?.id]);

  // Calcular ETA real con Mapbox cuando el usuario elige coordenadas
  useEffect(() => {
    const dLat = destCoords?.lat || deliveryCoords?.lat || coords?.latitude || null;
    const dLng = destCoords?.lng || deliveryCoords?.lng || coords?.longitude || null;
    if (!dLat || !dLng || selectedAddr) { setEtaMinutes(null); return; }
    let minD = Infinity, nearest = null;
    TPN_STORES.forEach((s) => {
      const d = haversineKm(dLat, dLng, s.lat, s.lng);
      if (d < minD) { minD = d; nearest = s; }
    });
    if (!nearest || minD > EXTENDED_KM) { setEtaMinutes(null); return; }
    setEtaLoading(true);
    fetchDrivingETA(nearest.lat, nearest.lng, dLat, dLng).then((min) => {
      setEtaMinutes(min);
      setEtaLoading(false);
    });
  }, [destCoords, deliveryCoords, coords, selectedAddr]);

  useEffect(() => {
    // Si la app tiene una ubicación detectada, la ponemos en manualAddr como backup/opción
    if (deliveryAddress && deliveryAddress !== "Detectando ubicación..." && !manualAddr) {
      setManualAddr(deliveryAddress);
    }
  }, [deliveryAddress, manualAddr]);

  // ── Método de pago ─────────────────────────────────────────────────────────
  const [cards, setCards] = useState([]);
  const [selectedCard, setSelectedCard] = useState(null);
  const [payMethod, setPayMethod] = useState("card"); // "card" | "cash" | "transfer"

  useEffect(() => {
    if (!user?.id) return;
    AsyncStorage.getItem(`@tpn_cards_${user.id}`)
      .then((d) => {
        if (d) {
          const list = JSON.parse(d);
          setCards(list);
          if (list.length > 0) setSelectedCard(list[0].id);
        }
      })
      .catch(() => {});
  }, [user?.id]);

  // ── Crear pedido ───────────────────────────────────────────────────────────
  const [orderError, setOrderError] = useState(null);

  const handleConfirm = async () => {
    setLoading(true);
    setOrderError(null);
    const addr = addresses.find((a) => a.id === selectedAddr);
    const deliveryAddress = addr ? addr.address : manualAddr.trim();
    const card = cards.find((c) => c.id === selectedCard);

    const dLat = addr?.lat || destCoords?.lat || deliveryCoords?.lat || coords?.latitude || null;
    const dLng = addr?.lng || destCoords?.lng || deliveryCoords?.lng || coords?.longitude || null;

    let storeId = null;
    if (dLat && dLng) {
      try {
        const resStores = await getStores();
        if (resStores?.success && Array.isArray(resStores.data)) {
          let minD = Infinity;
          resStores.data.forEach(s => {
            if (!s.lat || !s.lng) return;
            const R = 6371;
            const dφ = (s.lat - dLat) * Math.PI / 180;
            const dλ = (s.lng - dLng) * Math.PI / 180;
            const a = Math.sin(dφ / 2) ** 2 +
              Math.cos(dLat * Math.PI / 180) * Math.cos(s.lat * Math.PI / 180) * Math.sin(dλ / 2) ** 2;
            const dist = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
            if (dist < minD) { minD = dist; storeId = s.id; }
          });
        }
      } catch {}
    }

    const orderData = {
      items: items.map((item) => ({
        product_id: item.id,
        product_name: item.name,
        qty: item.qty,
        price: typeof item.price === "number"
          ? item.price
          : parseFloat(String(item.price).replace(/[^0-9.]/g, "")) || 0,
      })),
      subtotal,
      shipping,
      total,
      address: deliveryAddress,
      dest_lat: dLat,
      dest_lng: dLng,
      store_id: storeId,
      payment_method: payMethod === "card"
        ? `Tarjeta •••• ${card?.last4 || "xxxx"}`
        : payMethod === "cash" ? "Efectivo al entregar" : "Transferencia",
      payment_status: payMethod === "card" ? "paid" : "pending",
      customer_name: user?.name,
      customer_email: user?.email,
      notes: "",
    };

    try {
      const res = await createOrder(orderData, user?.token);
      const orderId = res?.data?.order_id || res?.data?.id || res?.order_id || res?.id;
      if (res?.success && orderId) {
        setOrderDone({ id: orderId, total, address: deliveryAddress, payMethod: orderData.payment_method });
        clearCart();
      } else {
        setOrderError(res?.message || "No se pudo crear el pedido. Intenta de nuevo.");
      }
    } catch (e) {
      setOrderError("Error de conexión: " + (e?.message || "revisa tu internet e intenta de nuevo."));
    }
    setLoading(false);
  };

  // ── Vista: Pedido confirmado ───────────────────────────────────────────────
  if (orderDone) {
    const successContent = (
      <View style={isDesktop ? s.desktopPanel : s.wrapper}>
        <ScrollView contentContainerStyle={s.successWrap} showsVerticalScrollIndicator={false}>
          <View style={s.successIcon}>
            <Ionicons name="checkmark-circle" size={72} color={GREEN} />
          </View>
          <Text style={s.successTitle}>¡Pedido realizado!</Text>
          <Text style={s.successSub}>
            Tu pedido #{String(orderDone.id).padStart(6, "0")} fue enviado al equipo de entrega.
          </Text>

          <View style={s.successCard}>
            <Row icon="receipt-outline" label="Pedido" value={`#${String(orderDone.id).padStart(6, "0")}`} />
            <Row icon="cash-outline"    label="Total"   value={`$${orderDone.total.toFixed(2)}`} bold />
            <Row icon="card-outline"    label="Pago"    value={orderDone.payMethod} />
            <Row icon="location-outline" label="Entregar en" value={orderDone.address} />
          </View>

          <View style={s.trackingInfo}>
            <Ionicons name="bicycle-outline" size={22} color={RED} />
            <Text style={s.trackingText}>
              Podrás ver el estado de tu pedido en tiempo real desde{" "}
              <Text style={{ fontWeight: "800" }}>Mis Pedidos</Text>.
            </Text>
          </View>

          <TouchableOpacity style={s.doneBtn} onPress={onSuccess}>
            <Text style={s.doneBtnText}>VER MIS PEDIDOS</Text>
            <Ionicons name="arrow-forward" size={18} color="#000" />
          </TouchableOpacity>
          <TouchableOpacity style={s.homeBtn} onPress={onBack}>
            <Text style={s.homeBtnText}>Seguir comprando</Text>
          </TouchableOpacity>
        </ScrollView>
      </View>
    );

    if (isDesktop) {
      return (
        <View style={[s.desktopWrapper, Platform.OS === "web" && { position: "fixed" }]}>
          <TouchableOpacity style={s.overlay} activeOpacity={1} onPress={onBack} />
          {successContent}
        </View>
      );
    }
    return successContent;
  }

  // ── Cobertura: calcular distancia a la sucursal más cercana ──────────────
  const getCoverageInfo = () => {
    const lat = destCoords?.lat || deliveryCoords?.lat || coords?.latitude || null;
    const lng = destCoords?.lng || deliveryCoords?.lng || coords?.longitude || null;
    if (!lat || !lng || selectedAddr) return null; // dirección guardada ya fue validada al elegirla
    let minD = Infinity, nearest = null;
    TPN_STORES.forEach((s) => {
      const d = haversineKm(lat, lng, s.lat, s.lng);
      if (d < minD) { minD = d; nearest = s; }
    });
    return nearest ? { dist: minD, store: nearest } : null;
  };

  // ── Paso 0: Dirección ──────────────────────────────────────────────────────
  const renderStep0 = () => {
    const coverage = getCoverageInfo();
    const outOfRange = coverage && coverage.dist > EXTENDED_KM;
    const isExtended = coverage && coverage.dist > COVERAGE_KM && coverage.dist <= EXTENDED_KM;
    const formatKm = (d) => d < 1 ? `${Math.round(d * 1000)} m` : `${d.toFixed(1)} km`;

    return (
    <View>
      <Text style={s.sectionTitle}>¿A dónde enviamos tu pedido?</Text>

      {addresses.map((addr) => (
        <TouchableOpacity
          key={addr.id}
          style={[s.addrCard, selectedAddr === addr.id && s.addrCardActive]}
          onPress={() => setSelectedAddr(addr.id)}
          activeOpacity={0.8}
        >
          <View style={[s.radio, selectedAddr === addr.id && s.radioActive]}>
            {selectedAddr === addr.id && <View style={s.radioDot} />}
          </View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={s.addrLabel}>{addr.label}</Text>
              {addr.isDefault && <View style={s.defaultBadge}><Text style={s.defaultBadgeText}>Principal</Text></View>}
            </View>
            <Text style={s.addrText}>{addr.address}</Text>
          </View>
          <Ionicons name="location-outline" size={20} color={selectedAddr === addr.id ? RED : "#ccc"} />
        </TouchableOpacity>
      ))}

      <TouchableOpacity
        style={[s.addrCard, !selectedAddr && s.addrCardActive]}
        onPress={() => setSelectedAddr(null)}
        activeOpacity={0.8}
      >
        <View style={[s.radio, !selectedAddr && s.radioActive]}>
          {!selectedAddr && <View style={s.radioDot} />}
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.addrLabel}>Ubicación actual o elegir nueva</Text>
          <Text style={s.addrText} numberOfLines={2}>
            {manualAddr || "Toca para elegir en el mapa..."}
          </Text>
        </View>
        <TouchableOpacity
          onPress={() => {
            setSelectedAddr(null);
            setPickerVisible(true);
          }}
          style={s.changeBtn}
        >
          <Ionicons name="map-outline" size={18} color={RED} />
          <Text style={s.changeBtnText}>Elegir</Text>
        </TouchableOpacity>
      </TouchableOpacity>

      {!selectedAddr && (
        <View style={s.card}>
          <Text style={s.fieldLabel}>DETALLES DE DIRECCIÓN / REFERENCIAS</Text>
          <View style={s.inputRow}>
            <Ionicons name="location-outline" size={18} color="#bbb" style={{ marginLeft: 14 }} />
            <TextInput
              style={s.input}
              value={manualAddr}
              onChangeText={setManualAddr}
              placeholder="Calle, número, colonia, referencias..."
              placeholderTextColor="#ccc"
              multiline
            />
          </View>
          <Text style={s.hint}>
            Puedes tocar "Elegir" arriba para usar el buscador con mapa y autocompletado.
          </Text>
        </View>
      )}

      {/* Banner de cobertura */}
      {outOfRange && (
        <View style={s.coverageBanner}>
          <Ionicons name="alert-circle" size={20} color={RED} />
          <View style={{ flex: 1 }}>
            <Text style={s.coverageBannerTitle}>Fuera de cobertura</Text>
            <Text style={s.coverageBannerText}>
              Estás a {formatKm(coverage.dist)} de {coverage.store.name} en línea recta —
              demasiado lejos para entrega en auto por el momento.
              ¡Esperamos tener una sucursal cerca de ti muy pronto! 🏪
            </Text>
          </View>
        </View>
      )}
      {isExtended && (
        <View style={[s.coverageBanner, s.coverageBannerOrange]}>
          <Ionicons name="car-outline" size={20} color={ORANGE} />
          <View style={{ flex: 1 }}>
            <Text style={[s.coverageBannerTitle, { color: ORANGE }]}>
              Zona extendida
              {etaLoading ? " · calculando..." : etaMinutes ? ` · ${formatMinutes(etaMinutes)}` : ""}
            </Text>
            <Text style={s.coverageBannerText}>
              Tu domicilio está a {formatKm(coverage.dist)} de {coverage.store.name}.
              Podemos llegar en auto pero el tiempo de entrega es mayor al habitual.
            </Text>
          </View>
        </View>
      )}
      {!outOfRange && !isExtended && coverage && (
        <View style={[s.coverageBanner, s.coverageBannerGreen]}>
          <Ionicons name="car-outline" size={20} color="#16a34a" />
          <View style={{ flex: 1 }}>
            <Text style={[s.coverageBannerTitle, { color: "#16a34a" }]}>
              {etaLoading ? "Calculando tiempo en auto..." : etaMinutes ? formatMinutes(etaMinutes) : "Con cobertura"}
            </Text>
            <Text style={s.coverageBannerText}>
              Tiempo estimado de entrega en auto con tráfico desde {coverage.store.name}.
            </Text>
          </View>
        </View>
      )}

      <TouchableOpacity
        style={[s.nextBtn, ((!selectedAddr && !manualAddr.trim()) || outOfRange) && s.nextBtnDisabled]}
        onPress={() => setStep(1)}
        disabled={(!selectedAddr && !manualAddr.trim()) || outOfRange}
      >
        <Text style={s.nextBtnText}>{outOfRange ? "Sin cobertura en esta zona" : "Continuar"}</Text>
        {!outOfRange && <Ionicons name="arrow-forward" size={18} color="#fff" />}
      </TouchableOpacity>
    </View>
  );
  };

  // ── Paso 1: Método de pago ─────────────────────────────────────────────────
  const PAY_OPTIONS = [
    { key: "card",     icon: "card-outline",        label: "Tarjeta guardada" },
    { key: "cash",     icon: "cash-outline",         label: "Efectivo al entregar" },
    { key: "transfer", icon: "swap-horizontal-outline", label: "Transferencia / SPEI" },
  ];

  const renderStep1 = () => (
    <View>
      <Text style={s.sectionTitle}>¿Cómo quieres pagar?</Text>

      {PAY_OPTIONS.map((opt) => (
        <TouchableOpacity
          key={opt.key}
          style={[s.addrCard, payMethod === opt.key && s.addrCardActive]}
          onPress={() => setPayMethod(opt.key)}
          activeOpacity={0.8}
        >
          <View style={[s.radio, payMethod === opt.key && s.radioActive]}>
            {payMethod === opt.key && <View style={s.radioDot} />}
          </View>
          <Ionicons name={opt.icon} size={22} color={payMethod === opt.key ? RED : "#aaa"} />
          <Text style={[s.addrLabel, { flex: 1, marginLeft: 8 }]}>{opt.label}</Text>
        </TouchableOpacity>
      ))}

      {payMethod === "card" && (
        <View style={{ marginTop: 4 }}>
          {cards.length === 0 ? (
            <View style={s.noCardNote}>
              <Ionicons name="information-circle-outline" size={16} color={RED} />
              <Text style={s.noCardNoteText}>
                No tienes tarjetas guardadas. Agrega una en Perfil → Métodos de pago o elige otro método.
              </Text>
            </View>
          ) : (
            cards.map((card) => (
              <TouchableOpacity
                key={card.id}
                style={[s.cardItem, selectedCard === card.id && s.cardItemActive]}
                onPress={() => setSelectedCard(card.id)}
                activeOpacity={0.8}
              >
                <View style={[s.radio, selectedCard === card.id && s.radioActive]}>
                  {selectedCard === card.id && <View style={s.radioDot} />}
                </View>
                <View style={[s.brandBadge, { backgroundColor: card.brandColor }]}>
                  <Text style={s.brandText}>{card.brand}</Text>
                </View>
                <Text style={[s.addrLabel, { flex: 1 }]}>{card.name}  •••• {card.last4}</Text>
                <Text style={s.cardExpiry}>{card.expiry}</Text>
              </TouchableOpacity>
            ))
          )}
        </View>
      )}

      {payMethod === "transfer" && (
        <View style={s.transferNote}>
          <Text style={s.transferTitle}>Datos para transferencia</Text>
          <Text style={s.transferLine}>Banco: BBVA</Text>
          <Text style={s.transferLine}>CLABE: 012 180 01234567890 1</Text>
          <Text style={s.transferLine}>Beneficiario: Todo Pal Negocio SA de CV</Text>
          <Text style={s.transferHint}>Tu pedido se procesará al confirmar el pago.</Text>
        </View>
      )}

      <View style={{ flexDirection: "row", gap: 10, marginTop: 20 }}>
        <TouchableOpacity style={s.backStepBtn} onPress={() => setStep(0)}>
          <Ionicons name="arrow-back" size={16} color="#555" />
          <Text style={s.backStepBtnText}>Atrás</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[s.nextBtn, { flex: 1 }, (payMethod === "card" && cards.length === 0) && s.nextBtnDisabled]}
          onPress={() => setStep(2)}
          disabled={payMethod === "card" && cards.length === 0}
        >
          <Text style={s.nextBtnText}>Revisar pedido</Text>
          <Ionicons name="arrow-forward" size={18} color="#fff" />
        </TouchableOpacity>
      </View>
    </View>
  );

  // ── Paso 2: Confirmar ──────────────────────────────────────────────────────
  const renderStep2 = () => {
    const addr = addresses.find((a) => a.id === selectedAddr);
    const addrText = addr ? `${addr.label}: ${addr.address}` : manualAddr;
    const card = cards.find((c) => c.id === selectedCard);
    const payText = payMethod === "card"
      ? `Tarjeta ${card?.brand} •••• ${card?.last4}`
      : payMethod === "cash" ? "Efectivo al entregar" : "Transferencia / SPEI";

    return (
      <View>
        <Text style={s.sectionTitle}>Revisa tu pedido</Text>

        {/* Items */}
        <View style={s.card}>
          <Text style={s.cardTitle}>PRODUCTOS ({items.length})</Text>
          {items.map((item) => (
            <View key={item.id} style={s.confirmItem}>
              <Image source={{ uri: item.img }} style={s.confirmImg} resizeMode="contain" />
              <View style={{ flex: 1 }}>
                <Text style={s.confirmName} numberOfLines={1}>{item.name}</Text>
                <Text style={s.confirmQty}>x{item.qty}  {item.price}</Text>
              </View>
            </View>
          ))}
        </View>

        {/* Resumen */}
        <View style={s.card}>
          <Text style={s.cardTitle}>RESUMEN</Text>
          <Row icon="location-outline"      label="Entrega"    value={addrText} />
          <Row icon="card-outline"          label="Pago"       value={payText} />
          <View style={s.summaryDivider} />
          <Row icon="receipt-outline"       label="Subtotal"   value={`$${subtotal.toFixed(2)}`} />
          <Row icon="bicycle-outline"       label="Envío"      value={shipping === 0 ? "GRATIS" : `$${shipping.toFixed(2)}`} />
          <View style={s.summaryDivider} />
          <Row icon="cash-outline"          label="TOTAL"      value={`$${total.toFixed(2)}`} bold big />
        </View>

        {payMethod !== "cash" && (
          <View style={s.payNowNote}>
            <Ionicons name="shield-checkmark-outline" size={16} color={GREEN} />
            <Text style={s.payNowText}>
              Al confirmar, tu pedido quedará {payMethod === "card" ? "pagado" : "registrado"} y se enviará al repartidor disponible.
            </Text>
          </View>
        )}

        {orderError && (
          <View style={s.orderErrorBanner}>
            <Ionicons name="alert-circle" size={18} color="#991b1b" />
            <Text style={s.orderErrorText}>{orderError}</Text>
          </View>
        )}

        <View style={{ flexDirection: "row", gap: 10, marginTop: 8 }}>
          <TouchableOpacity style={s.backStepBtn} onPress={() => setStep(1)}>
            <Ionicons name="arrow-back" size={16} color="#555" />
            <Text style={s.backStepBtnText}>Atrás</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[s.nextBtn, { flex: 1, backgroundColor: loading ? "#ccc" : GREEN }]}
            onPress={handleConfirm}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <>
                <Ionicons name={payMethod === "cash" ? "bicycle" : "lock-closed"} size={18} color="#fff" />
                <Text style={s.nextBtnText}>
                  {payMethod === "cash" ? "Confirmar pedido" : "Pagar y confirmar"}
                </Text>
              </>
            )}
          </TouchableOpacity>
        </View>
        <View style={{ height: 40 }} />
      </View>
    );
  };

  // ── Renderizado Principal ──────────────────────────────────────────────────
  const checkoutContent = (
    <View style={[isDesktop ? s.desktopPanel : s.panel, { backgroundColor: t.bg }]}>
      {/* Header */}
      <View style={[s.header, { backgroundColor: t.header, borderBottomColor: t.border }]}>
        <TouchableOpacity onPress={onBack} style={[s.backBtn, { backgroundColor: t.iconBg }]}>
          <Ionicons name="close" size={24} color={t.text} />
        </TouchableOpacity>
        <Text style={[s.headerTitle, { color: t.text }]}>FINALIZAR PEDIDO</Text>
        <View style={{ width: 40 }} />
      </View>

      <StepBar step={step} width={width} isDesktop={isDesktop} />

      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      >
        {step === 0 && renderStep0()}
        {step === 1 && renderStep1()}
        {step === 2 && renderStep2()}
      </ScrollView>

      {/* LocationPickerModal solo en móvil — en desktop se maneja inline */}
      {!isDesktop && (
        <LocationPickerModal
          visible={pickerVisible}
          onClose={() => setPickerVisible(false)}
          onConfirm={(addr, coords) => {
            setManualAddr(addr);
            setDestCoords(coords);
            setSelectedAddr(null);
          }}
          currentCoords={coords}
        />
      )}
    </View>
  );

  if (isDesktop) {
    // En desktop: si el picker está activo, sustituye el checkout por el mapa dentro del mismo panel
    if (pickerVisible) {
      return (
        <View style={[s.desktopWrapper, Platform.OS === "web" && { position: "fixed" }]}>
          <TouchableOpacity style={s.overlay} activeOpacity={1} onPress={() => setPickerVisible(false)} />
          <View style={s.desktopPanel}>
            <LocationPickerModal
              visible={true}
              inline={true}
              onClose={() => setPickerVisible(false)}
              onConfirm={(addr, coords) => {
                setManualAddr(addr);
                setDestCoords(coords);
                setSelectedAddr(null);
              }}
              currentCoords={coords}
            />
          </View>
        </View>
      );
    }

    return (
      <View style={[s.desktopWrapper, Platform.OS === "web" && { position: "fixed" }]}>
        <TouchableOpacity style={s.overlay} activeOpacity={1} onPress={onBack} />
        {checkoutContent}
      </View>
    );
  }

  return <View style={[s.wrapper, { backgroundColor: t.bg }]}>{checkoutContent}</View>;
}

// ─── HELPER ───────────────────────────────────────────────────────────────────
function Row({ icon, label, value, bold, big }) {
  return (
    <View style={s.row}>
      <Ionicons name={icon} size={15} color="#aaa" style={{ marginTop: 1 }} />
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={[s.rowValue, bold && { fontWeight: "900", color: "#111" }, big && { fontSize: 16 }]} numberOfLines={2}>
        {value}
      </Text>
    </View>
  );
}

// ─── ESTILOS ──────────────────────────────────────────────────────────────────
const s = StyleSheet.create({
  wrapper: { 
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "#f5f5f5", 
    paddingTop: Platform.OS === "ios" ? 54 : 44,
    zIndex: 9999
  },
  
  // Desktop Drawer
  desktopWrapper: { 
    position: Platform.OS === "web" ? "fixed" : "absolute", 
    top: 0, left: 0, right: 0, bottom: 0, 
    flexDirection: "row", justifyContent: "flex-end", 
    zIndex: 99999,
    backgroundColor: "transparent"
  },
  overlay: { 
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(0,0,0,0.5)" 
  },
  panel: { flex: 1, backgroundColor: "#f5f5f5" },
  desktopPanel: { 
    width: 500, maxWidth: "100%", height: "100%",
    backgroundColor: "#fff",
    shadowColor: "#000", shadowOffset: { width: -4, height: 0 }, 
    shadowOpacity: 0.15, shadowRadius: 20, elevation: 20,
    zIndex: 100000
  },


  header: {
    backgroundColor: "#fff", paddingHorizontal: 16, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  backBtn: { width: 40, height: 40, borderRadius: 10, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  headerTitle: { fontSize: 16, fontWeight: "900", color: "#111", flex: 1, textAlign: "center" },

  stepBarContainer: { 
    backgroundColor: "#fff", 
    borderBottomWidth: 1, 
    borderBottomColor: "#f0f0f0", 
    paddingTop: 16,
    paddingBottom: 30,
    alignItems: "center"
  },
  stepBar: { 
    flexDirection: "row", 
    alignItems: "center", 
    justifyContent: "center",
    width: "80%",
    maxWidth: 320,
    alignSelf: "center"
  },
  stepPoint: { alignItems: "center", justifyContent: "center", width: 24 },
  stepCircle: { width: 24, height: 24, borderRadius: 12, backgroundColor: "#f0f0f0", justifyContent: "center", alignItems: "center", zIndex: 2 },
  stepActive: { backgroundColor: RED },
  stepDone: { backgroundColor: GREEN },
  stepNum: { fontSize: 11, fontWeight: "800", color: "#aaa" },
  stepNumActive: { color: "#fff" },
  stepLabel: { position: "absolute", top: 28, width: 80, fontSize: 9, fontWeight: "700", color: "#aaa", textAlign: "center" },
  stepLabelActive: { color: RED },
  stepLine: { flex: 1, height: 2, backgroundColor: "#f0f0f0", zIndex: 1 },
  stepLineDone: { backgroundColor: GREEN },


  sectionTitle: { fontSize: 16, fontWeight: "900", color: "#111", marginBottom: 14 },

  addrCard: { backgroundColor: "#fff", borderRadius: 14, padding: 14, marginBottom: 10, flexDirection: "row", alignItems: "center", gap: 12, borderWidth: 1.5, borderColor: "#f0f0f0" },
  addrCardActive: { borderColor: RED, backgroundColor: "#fff5f5" },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: "#ddd", justifyContent: "center", alignItems: "center" },
  radioActive: { borderColor: RED },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: RED },
  addrLabel: { fontSize: 14, fontWeight: "700", color: "#111" },
  addrText: { fontSize: 12, color: "#888", marginTop: 2 },
  defaultBadge: { backgroundColor: "#fff0f0", paddingHorizontal: 7, paddingVertical: 2, borderRadius: 6 },
  defaultBadgeText: { fontSize: 10, fontWeight: "700", color: RED },

  changeBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "#fff5f5", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: "#ffcccc" },
  changeBtnText: { fontSize: 11, fontWeight: "800", color: RED },

  card: { backgroundColor: "#fff", borderRadius: 16, padding: 16, marginBottom: 14, shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 8, elevation: 2 },
  cardTitle: { fontSize: 10, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 12 },
  fieldLabel: { fontSize: 10, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 6 },
  inputRow: { flexDirection: "row", alignItems: "center", backgroundColor: "#f8f8f8", borderRadius: 12, borderWidth: 1, borderColor: "#f0f0f0", minHeight: 50 },
  input: { flex: 1, fontSize: 14, color: "#111", paddingHorizontal: 12, paddingVertical: 10 },
  hint: { fontSize: 11, color: "#bbb", marginTop: 8, lineHeight: 16 },

  cardItem: { backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 8, flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1.5, borderColor: "#f0f0f0" },
  cardItemActive: { borderColor: RED, backgroundColor: "#fff5f5" },
  brandBadge: { width: 40, height: 26, borderRadius: 5, justifyContent: "center", alignItems: "center" },
  brandText: { color: "#fff", fontSize: 10, fontWeight: "900" },
  cardExpiry: { fontSize: 11, color: "#aaa" },

  noCardNote: { flexDirection: "row", alignItems: "flex-start", gap: 8, backgroundColor: "#fff5f5", borderRadius: 10, padding: 12, borderWidth: 1, borderColor: "#fecaca" },
  noCardNoteText: { flex: 1, fontSize: 12, color: "#e6192e", lineHeight: 17 },

  transferNote: { backgroundColor: "#f8fafc", borderRadius: 12, padding: 16, borderWidth: 1, borderColor: "#e2e8f0", marginTop: 4 },
  transferTitle: { fontSize: 13, fontWeight: "800", color: "#111", marginBottom: 8 },
  transferLine: { fontSize: 13, color: "#555", marginBottom: 4, fontFamily: Platform.OS === "ios" ? "Courier" : "monospace" },
  transferHint: { fontSize: 11, color: "#aaa", marginTop: 8 },

  coverageBanner: {
    flexDirection: "row", alignItems: "flex-start", gap: 10,
    backgroundColor: "#fff1f2", borderRadius: 14, padding: 14,
    borderWidth: 1, borderColor: "#fecdd3", marginBottom: 12,
  },
  coverageBannerOrange: { backgroundColor: "#fffbeb", borderColor: "#fde68a" },
  coverageBannerGreen:  { backgroundColor: "#f0fdf4", borderColor: "#bbf7d0" },
  coverageBannerTitle: { fontSize: 13, fontWeight: "800", color: RED, marginBottom: 3 },
  coverageBannerText: { fontSize: 12, color: "#555", lineHeight: 17 },

  nextBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: RED, borderRadius: 14, paddingVertical: 15, marginTop: 8 },
  nextBtnDisabled: { backgroundColor: "#ccc" },
  nextBtnText: { color: "#fff", fontWeight: "900", fontSize: 15 },
  backStepBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 15, backgroundColor: "#f5f5f5", borderRadius: 14 },
  backStepBtnText: { fontSize: 14, fontWeight: "700", color: "#555" },

  // Confirm step
  confirmItem: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: "#f5f5f5" },
  confirmImg: { width: 44, height: 44, borderRadius: 8, backgroundColor: "#f9f9f9" },
  confirmName: { fontSize: 13, fontWeight: "700", color: "#111", marginBottom: 2 },
  confirmQty: { fontSize: 12, color: "#888" },
  row: { flexDirection: "row", alignItems: "flex-start", gap: 8, paddingVertical: 7 },
  rowLabel: { fontSize: 13, color: "#888", width: 68 },
  rowValue: { flex: 1, fontSize: 13, color: "#333", fontWeight: "600", textAlign: "right" },
  summaryDivider: { height: 1, backgroundColor: "#f5f5f5", marginVertical: 4 },
  payNowNote: { flexDirection: "row", alignItems: "flex-start", gap: 8, backgroundColor: "#f0fdf4", borderRadius: 10, padding: 12, borderWidth: 1, borderColor: "#bbf7d0", marginBottom: 8 },
  payNowText: { flex: 1, fontSize: 12, color: "#15803d", lineHeight: 17 },

  // Success
  successWrap: { flexGrow: 1, alignItems: "center", padding: 24, paddingTop: 40 },
  successIcon: { marginBottom: 20 },
  successTitle: { fontSize: 26, fontWeight: "900", color: "#111", marginBottom: 8 },
  successSub: { fontSize: 14, color: "#888", textAlign: "center", lineHeight: 21, marginBottom: 24 },
  successCard: { backgroundColor: "#fff", borderRadius: 20, padding: 20, width: "100%", marginBottom: 20, shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 12, elevation: 3 },
  trackingInfo: { flexDirection: "row", alignItems: "flex-start", gap: 10, backgroundColor: "#fff5f5", borderRadius: 14, padding: 14, width: "100%", marginBottom: 24 },
  trackingText: { flex: 1, fontSize: 13, color: "#555", lineHeight: 19 },
  doneBtn: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: RED, borderRadius: 14, paddingVertical: 15, paddingHorizontal: 28, marginBottom: 12 },
  doneBtnText: { color: "#fff", fontWeight: "900", fontSize: 15 },
  homeBtn: { paddingVertical: 12 },
  homeBtnText: { fontSize: 14, color: "#888", fontWeight: "600" },

  orderErrorBanner: {
    flexDirection: "row", alignItems: "flex-start", gap: 10,
    backgroundColor: "#fef2f2", borderRadius: 12, padding: 14,
    borderWidth: 1, borderColor: "#fecaca", marginBottom: 10,
  },
  orderErrorText: { flex: 1, fontSize: 13, color: "#991b1b", lineHeight: 19, fontWeight: "600" },
});
