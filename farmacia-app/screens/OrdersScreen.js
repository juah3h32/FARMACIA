import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState, useRef, useCallback } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  useWindowDimensions,
  Dimensions,
  Modal,
  TextInput,
  KeyboardAvoidingView,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useLocation } from "../context/LocationContext";
import { useNotifications } from "../context/NotificationsContext";
import { MENU_CLEARANCE } from "../components/MobileMenu";
import { GOOGLE_MAPS_DARK_STYLE } from "../constants/theme";
import { getUserOrders, getOrderTracking, cancelOrder, rateOrder, GOOGLE_MAPS_API_KEY, API_BASE_URL } from "../services/api";

import { MapView, Marker, Polyline, PROVIDER_GOOGLE } from "../components/MapComponents";
// WebView para el mapa web (iframe Mapbox)
let WebView = null;
if (Platform.OS !== "web") {
  WebView = require("react-native-webview").WebView;
}

// Decodifica polyline de Google Directions API
function decodePolyline(encoded) {
  let index = 0, lat = 0, lng = 0;
  const coords = [];
  while (index < encoded.length) {
    let b, shift = 0, result = 0;
    do { b = encoded.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
    lat += (result & 1) ? ~(result >> 1) : (result >> 1);
    shift = 0; result = 0;
    do { b = encoded.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
    lng += (result & 1) ? ~(result >> 1) : (result >> 1);
    coords.push({ latitude: lat / 1e5, longitude: lng / 1e5 });
  }
  return coords;
}
function decodePolyline6(encoded) {
  let index = 0, lat = 0, lng = 0;
  const coords = [];
  while (index < encoded.length) {
    let b, shift = 0, result = 0;
    do { b = encoded.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
    lat += (result & 1) ? ~(result >> 1) : (result >> 1);
    shift = 0; result = 0;
    do { b = encoded.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
    lng += (result & 1) ? ~(result >> 1) : (result >> 1);
    coords.push({ latitude: lat / 1e6, longitude: lng / 1e6 });
  }
  return coords;
}

const RED = "#e6192e";
const YELLOW = "#fede33";
const GREEN = "#22c55e";
const BLUE = RED; // Forzamos BLUE a ser RED

const STATUS_MAP = {
  pending:    { label: "Pendiente",   style: "preparando" },
  accepted:   { label: "Aceptado",    style: "preparando" },
  preparing:  { label: "Preparando",  style: "preparando" },
  picked_up:  { label: "Recogido",    style: "en_camino"  },
  on_the_way: { label: "En camino",   style: "en_camino"  },
  shipped:    { label: "En camino",   style: "en_camino"  },
  arrived:    { label: "Llegó",       style: "llegado"    },
  delivered:  { label: "Entregado",   style: "entregado"  },
  cancelled:  { label: "Cancelado",   style: "cancelado"  },
};

const STATUS_STYLES = {
  entregado:  { bg: "#f0fdf4", color: GREEN, icon: "checkmark-circle" },
  en_camino:  { bg: "#fff5f5", color: RED,   icon: "bicycle"          },
  llegado:    { bg: "#f0fdf4", color: GREEN, icon: "home"             },
  preparando: { bg: "#fffbeb", color: "#f59e0b", icon: "time"             },
  cancelado:  { bg: "#fff1f2", color: RED,        icon: "close-circle"    },
};

// ─── COMPONENTE DE MAPA DE RASTREO ───────────────────────────────────────────
function TrackingMap({ order, onBack }) {
  const { user } = useAuth();
  const { t, isDark } = useTheme();
  const { coords: userCoords } = useLocation();
  const { bottom: safeBottom } = useSafeAreaInsets();
  const userCoordsRef = useRef(userCoords);
  useEffect(() => { userCoordsRef.current = userCoords; }, [userCoords]);
  const [trackingData, setTrackingData] = useState(null);
  const [eta, setEta] = useState(null);
  const [km, setKm] = useState(null);
  const [traffic, setTraffic] = useState(null);
  const [routeCoords, setRouteCoords] = useState([]);
  const [routeColor, setRouteColor] = useState(BLUE);
  const [markerReady, setMarkerReady] = useState(false);
  const mapRef = useRef(null);
  const timerRef = useRef(null);
  // Cuenta regresiva en tiempo real entre polls
  const etaSecsRef = useRef(null);
  const countdownRef = useRef(null);
  // Posición y tiempo anterior del conductor para calcular velocidad real
  const prevDriverRef = useRef(null);

  // Helper: aplica ETA en segundos y arranca/resetea el countdown de 1 s
  const applyEta = useCallback((totalSecs) => {
    etaSecsRef.current = Math.max(0, totalSecs);
    setEta(Math.ceil(etaSecsRef.current / 60));
  }, []);

  // Countdown de 1 segundo — decrementa entre polls para que el número no se "congele"
  useEffect(() => {
    countdownRef.current = setInterval(() => {
      if (etaSecsRef.current !== null && etaSecsRef.current > 0) {
        etaSecsRef.current -= 1;
        setEta(Math.ceil(etaSecsRef.current / 60));
      }
    }, 1000);
    return () => clearInterval(countdownRef.current);
  }, []);

  // Espera a que Ionicons cargue antes de congelar el bitmap del marcador
  useEffect(() => {
    const t = setTimeout(() => setMarkerReady(true), 1800);
    return () => clearTimeout(t);
  }, []);

  // ── Google Directions API (nativo) ──────────────────────────────────────────
  // viaLat/viaLng: waypoint intermedio (ej. la tienda) para calcular ruta completa
  // driver → tienda → cliente en una sola llamada con ETA total
  const fetchRoute = useCallback(async (fromLat, fromLng, toLat, toLng, status, viaLat = null, viaLng = null, speedMs = null) => {
    const hasVia = !!(viaLat && viaLng);
    const prepSecs = hasVia ? 10 * 60 : 0;

    const trafficFromRatio = (ratio) =>
      ratio >= 1.30 ? "congestionado" : ratio >= 1.12 ? "lento" : "fluido";

    const colorFromTraffic = (trf, isViaOrStore) => {
      if (isViaOrStore) return "#f59e0b";
      return trf === "congestionado" ? RED : trf === "lento" ? "#f97316" : BLUE;
    };

    // Corrección de velocidad real del conductor: si tenemos la velocidad medida
    // escala el tiempo de la ruta proporcionalmente (sólo ajuste menor ±30%)
    const adjustForSpeed = (routeSecs, distM) => {
      if (!speedMs || speedMs <= 0 || !distM) return routeSecs;
      const expectedSpeedMs = distM / Math.max(routeSecs, 1);
      const actualSpeed = Math.min(Math.max(speedMs, expectedSpeedMs * 0.5), expectedSpeedMs * 1.8);
      const ratio = expectedSpeedMs / actualSpeed;
      return Math.round(routeSecs * ratio);
    };

    const applyResult = (coords, durTraffic, distM, ratio, fit = true) => {
      const adjusted = adjustForSpeed(durTraffic, distM);
      const total = adjusted + prepSecs;
      const trf = trafficFromRatio(ratio);
      setRouteCoords(coords);
      applyEta(total);
      setKm((distM / 1000).toFixed(1));
      setTraffic(trf);
      setRouteColor(colorFromTraffic(trf, hasVia || ["accepted","preparing"].includes(status)));
      if (fit) mapRef.current?.fitToCoordinates(coords, {
        edgePadding: { top: 120, bottom: 340, left: 60, right: 60 }, animated: true,
      });
    };

    const fallback = () => {
      const R = 6371000;
      const φ1 = fromLat * Math.PI / 180, φ2 = toLat * Math.PI / 180;
      const Δφ = (toLat - fromLat) * Math.PI / 180, Δλ = (toLng - fromLng) * Math.PI / 180;
      const a = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
      const distM = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      const spd = speedMs && speedMs > 1 ? speedMs : 8.3; // ~30 km/h default
      const secs = distM / spd;
      applyResult(
        [{ latitude: fromLat, longitude: fromLng }, { latitude: toLat, longitude: toLng }],
        secs, distM, 1.0
      );
    };

    // ── Intento 1: Proxy PHP (Google Directions con tráfico real o OSRM) ──────
    try {
      const base = API_BASE_URL.includes("?") ? API_BASE_URL + "&" : API_BASE_URL + "?";
      const proxyUrl = `${base}resource=route&origin_lat=${fromLat}&origin_lng=${fromLng}&dest_lat=${toLat}&dest_lng=${toLng}`;
      const pJson = JSON.parse(await (await fetch(proxyUrl, { headers: { Accept: "application/json" } })).text());
      if (pJson.success && pJson.data) {
        const pd = pJson.data;
        const coords = pd.polyline
          ? (pd.polyline6 ? decodePolyline6(pd.polyline) : decodePolyline(pd.polyline))
          : (pd.coordinates ?? []);
        if (coords.length > 1) {
          // Usar duration_traffic_sec (con tráfico real si vino de Google, o estimado si OSRM)
          const durTraffic = pd.duration_traffic_sec ?? pd.duration_sec ?? 0;
          const ratio = pd.traffic_ratio ?? 1.0;
          applyResult(coords, durTraffic, pd.distance_m ?? 0, ratio);
          return;
        }
      }
    } catch (err) { console.log("Route proxy error:", err); }

    // ── Intento 2: Google Directions directo con tráfico ─────────────────────
    if (GOOGLE_MAPS_API_KEY && GOOGLE_MAPS_API_KEY !== "TU_GOOGLE_MAPS_API_KEY") {
      try {
        const waypointParam = hasVia ? `&waypoints=${viaLat},${viaLng}` : "";
        const url = `https://maps.googleapis.com/maps/api/directions/json`
          + `?origin=${fromLat},${fromLng}&destination=${toLat},${toLng}${waypointParam}`
          + `&key=${GOOGLE_MAPS_API_KEY}&language=es&mode=driving`
          + `&departure_time=now&traffic_model=best_guess`;
        const route = (await (await fetch(url)).json()).routes?.[0];
        if (route) {
          const legs = route.legs;
          const durNormal  = legs.reduce((s, l) => s + l.duration.value, 0);
          const durTraffic = legs.reduce((s, l) => s + (l.duration_in_traffic?.value ?? l.duration.value), 0);
          const distM      = legs.reduce((s, l) => s + l.distance.value, 0);
          const ratio      = durTraffic / Math.max(durNormal, 1);
          applyResult(decodePolyline(route.overview_polyline.points), durTraffic, distM, ratio);
          return;
        }
      } catch (err) { console.log("Google Directions error:", err); }
    }

    // ── Intento 3: Valhalla POST ──────────────────────────────────────────────
    try {
      const locs = hasVia
        ? [{ lon: fromLng, lat: fromLat }, { lon: viaLng, lat: viaLat }, { lon: toLng, lat: toLat }]
        : [{ lon: fromLng, lat: fromLat }, { lon: toLng, lat: toLat }];
      const data = await (await fetch("https://valhalla1.openstreetmap.de/route", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ locations: locs, costing: "auto", costing_options: { auto: { top_speed: 120 } } }),
      })).json();
      const shape = data?.trip?.legs?.[0]?.shape;
      if (shape) {
        const allLegs = data.trip.legs ?? [];
        const totalTime = allLegs.reduce((s, l) => s + (l.summary?.time ?? 0), 0);
        const totalDist = allLegs.reduce((s, l) => s + (l.summary?.length ?? 0), 0) * 1000;
        if (decodePolyline6(shape).length > 1) {
          applyResult(decodePolyline6(shape), totalTime, totalDist, 1.0);
          return;
        }
      }
    } catch (err) { console.log("Valhalla error:", err); }

    fallback();
  }, [applyEta]);

  const fetchTracking = useCallback(async () => {
    try {
      const res = await getOrderTracking(order.id, user?.token);
      if (res?.success && res.data) {
        const data = res.data;
        setTrackingData(data);
        const status = data.status || order.status;
        const destLat = parseFloat(data.dest_lat) || userCoordsRef.current?.latitude || 19.7044;
        const destLng = parseFloat(data.dest_lng) || userCoordsRef.current?.longitude || -101.2262;
        const sLat = parseFloat(data.store_lat) || 0;
        const sLng = parseFloat(data.store_lng) || 0;
        const hasDriver = !!(data.delivery_lat && data.delivery_lng && parseFloat(data.delivery_lat) !== 0);

        // Calcular velocidad real del conductor (m/s) comparando posición anterior
        let speedMs = null;
        if (hasDriver) {
          const dLat = parseFloat(data.delivery_lat);
          const dLng = parseFloat(data.delivery_lng);
          const now = Date.now();
          if (prevDriverRef.current) {
            const { lat: pLat, lng: pLng, ts } = prevDriverRef.current;
            const dtSec = (now - ts) / 1000;
            if (dtSec > 5) {
              const R = 6371000;
              const φ1 = pLat * Math.PI / 180, φ2 = dLat * Math.PI / 180;
              const Δφ = (dLat - pLat) * Math.PI / 180, Δλ = (dLng - pLng) * Math.PI / 180;
              const a = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
              const distM = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
              speedMs = distM / dtSec; // m/s medidos
            }
          }
          prevDriverRef.current = { lat: dLat, lng: dLng, ts: now };

          if (["accepted", "preparing"].includes(status) && sLat && sLat !== 0) {
            fetchRoute(dLat, dLng, destLat, destLng, status, sLat, sLng, speedMs);
          } else {
            fetchRoute(dLat, dLng, destLat, destLng, status, null, null, speedMs);
          }
        } else if (sLat && sLng && sLat !== 0) {
          fetchRoute(sLat, sLng, destLat, destLng, status);
        } else {
          mapRef.current?.animateToRegion({
            latitude: destLat, longitude: destLng,
            latitudeDelta: 0.03, longitudeDelta: 0.03,
          }, 800);
        }
      }
    } catch {}
  }, [order.id, user?.token, fetchRoute]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    fetchTracking();
    timerRef.current = setInterval(fetchTracking, 15000);
    return () => { clearInterval(timerRef.current); timerRef.current = null; };
  }, [fetchTracking]);

  const currentStatus = trackingData?.status || order.status;
  const trafficColor = { fluido: GREEN, lento: "#f59e0b", congestionado: RED }[traffic];
  const trafficLabel = { fluido: "Tráfico fluido", lento: "Tráfico moderado", congestionado: "Tráfico intenso" }[traffic];

  const destLat  = trackingData?.dest_lat != null  ? parseFloat(trackingData.dest_lat)  : (userCoords?.latitude  ?? 19.7044);
  const destLng  = trackingData?.dest_lng != null  ? parseFloat(trackingData.dest_lng)  : (userCoords?.longitude ?? -101.2262);
  const driverLat = trackingData?.delivery_lat != null ? parseFloat(trackingData.delivery_lat) : null;
  const driverLng = trackingData?.delivery_lng != null ? parseFloat(trackingData.delivery_lng) : null;
  const storeLat  = trackingData?.store_lat != null   ? parseFloat(trackingData.store_lat)   : null;
  const storeLng  = trackingData?.store_lng != null   ? parseFloat(trackingData.store_lng)   : null;

  const isWeb = Platform.OS === "web";
  const { width: screenWidth } = useWindowDimensions();
  const isDesktopMap = screenWidth >= 1024;
  const topInset = isDesktopMap ? 0 : Platform.OS === "ios" ? 54 : 44;

  return (
    <View style={[styles.trackingContainer, { backgroundColor: t.bg }]}>

      {/* ── Mapa Google Maps (nativo) ── */}
      {MapView ? (
        <MapView
          ref={mapRef}
          style={StyleSheet.absoluteFillObject}
          provider={PROVIDER_GOOGLE}
          userInterfaceStyle={isDark ? "dark" : "light"}
          customMapStyle={isDark ? GOOGLE_MAPS_DARK_STYLE : []}
          initialRegion={{
            latitude: destLat,
            longitude: destLng,
            latitudeDelta: 0.04,
            longitudeDelta: 0.04,
          }}
          showsMyLocationButton={false}
          toolbarEnabled={false}
        >
          {/* Ruta — casing blanco + línea de color (estilo Google Maps navegación) */}
          {routeCoords.length > 1 && (
            <Polyline
              coordinates={routeCoords}
              strokeColor={isDark ? "#1f2937" : "#ffffff"}
              strokeWidth={10}
              lineCap="round"
              lineJoin="round"
              zIndex={1}
            />
          )}
          {routeCoords.length > 1 && (
            <Polyline
              coordinates={routeCoords}
              strokeColor={routeColor}
              strokeWidth={6}
              lineCap="round"
              lineJoin="round"
              zIndex={2}
            />
          )}

          {/* Marcador repartidor */}
          {driverLat && driverLng && (
            <Marker
              coordinate={{ latitude: driverLat, longitude: driverLng }}
              anchor={{ x: 0.5, y: 0.5 }}
              flat
              tracksViewChanges={!markerReady}
            >
              <View style={[styles.markerCircle, { backgroundColor: isDark ? "#fff" : "#000" }]}>
                <Ionicons name="bicycle" size={20} color={isDark ? "#000" : "#fff"} />
              </View>
            </Marker>
          )}

          {/* Marcador tienda */}
          {storeLat && storeLng && (
            <Marker
              coordinate={{ latitude: storeLat, longitude: storeLng }}
              anchor={{ x: 0.5, y: 0.5 }}
              tracksViewChanges={!markerReady}
            >
              <View style={[styles.markerCircle, { backgroundColor: RED }]}>
                <Ionicons name="storefront" size={18} color="#fff" />
              </View>
            </Marker>
          )}

          {/* Marcador destino */}
          <Marker
            coordinate={{ latitude: destLat, longitude: destLng }}
            anchor={{ x: 0.5, y: 0.5 }}
            tracksViewChanges={!markerReady}
          >
            <View style={[styles.markerCircle, { backgroundColor: isDark ? "#fff" : "#111" }]}>
              <Ionicons name="home" size={18} color={isDark ? "#000" : "#fff"} />
            </View>
          </Marker>
        </MapView>
      ) : (
        <View style={[StyleSheet.absoluteFillObject, { backgroundColor: isDark ? "#111" : "#e8e8e8", justifyContent: "center", alignItems: "center" }]}>
          <Text style={{ color: "#aaa" }}>Mapa no disponible</Text>
        </View>
      )}

      {/* ── Barra flotante superior ── */}
      <View style={[styles.trackingTopBar, { paddingTop: topInset + 6 }]}>
        <TouchableOpacity onPress={onBack} style={[styles.backBtn, { backgroundColor: t.card }]}>
          <Ionicons name="arrow-back" size={20} color={t.text} />
        </TouchableOpacity>
        <View style={[styles.trackingStatusPill, { backgroundColor: isDark ? "rgba(30,30,30,0.95)" : "rgba(255,255,255,0.96)" }]}>
          <View style={[styles.trackingStatusDot,
            { backgroundColor: currentStatus === "delivered" ? GREEN : currentStatus === "cancelled" ? RED : BLUE }
          ]} />
          <Text style={[styles.trackingStatusText, { color: t.text }]} numberOfLines={1}>
            #{String(order.id).padStart(6, "0")} · {STATUS_MAP[currentStatus]?.label || "En proceso"}
          </Text>
        </View>
        {eta ? (
          <View style={[styles.etaFloatBadge, { backgroundColor: RED }]}>
            <Text style={styles.etaFloatNum}>{eta}</Text>
            <Text style={styles.etaFloatLabel}>min</Text>
          </View>
        ) : null}
      </View>

      {/* ── Bottom sheet estilo Uber ── */}
      <View style={[styles.trackingFooter, { backgroundColor: t.card }]}>

        {/* Zona scrollable: repartidor + tienda + items */}
        <ScrollView
          style={styles.footerScroll}
          contentContainerStyle={styles.footerScrollContent}
          showsVerticalScrollIndicator={false}
          bounces={true}
        >
          {/* Fila repartidor + ETA */}
          <View style={styles.footerTop}>
            <View style={[styles.driverAvatarCircle,
              currentStatus === "accepted" && { backgroundColor: "#f59e0b" }]}>
              <Ionicons name={currentStatus === "accepted" ? "storefront" : "bicycle"} size={24} color="#fff" />
            </View>
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={[styles.driverName, { color: t.text }]}>{trackingData?.driver_name || "Repartidor TPN"}</Text>
              <View style={styles.starsRow}>
                {[1,2,3,4,5].map((i) => <Ionicons key={i} name="star" size={12} color={YELLOW} />)}
                <Text style={[styles.ratingVal, { color: t.textMuted }]}>4.8</Text>
              </View>
              <Text style={[styles.driverRole, { color: t.textMuted }]}>
                {currentStatus === "accepted" ? "En tienda recogiendo" :
                 currentStatus === "picked_up" ? "Pedido recogido" :
                 currentStatus === "on_the_way" ? "En camino a tu dirección" : "Procesando pedido"}
              </Text>
            </View>
            <View style={styles.etaBlock}>
              <Text style={styles.etaBigNum}>{eta || "—"}</Text>
              <Text style={[styles.etaBigLabel, { color: t.textMuted }]}>MIN</Text>
            </View>
          </View>

          {/* Card info de tienda */}
          {trackingData?.store_name && (
            <View style={[styles.storeCard, { backgroundColor: isDark ? "#1a1a1a" : "#fafafa", borderColor: t.divider }]}>
              {/* Cabecera */}
              <View style={styles.storeCardHeader}>
                <View style={[styles.storeCardIconWrap, { backgroundColor: RED }]}>
                  <Ionicons name="storefront" size={18} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.storeCardBrand, { color: t.text }]}>Todo Pal Negocio</Text>
                  <Text style={styles.storeCardBranch}>Sucursal {trackingData.store_name}</Text>
                </View>
              </View>

              {/* Dirección */}
              {trackingData.store_address ? (
                <View style={styles.storeCardRow}>
                  <View style={[styles.storeCardRowIcon, { backgroundColor: isDark ? "#2a1515" : "#fff0f0" }]}>
                    <Ionicons name="location-outline" size={14} color={RED} />
                  </View>
                  <Text style={[styles.storeCardValue, { color: t.text }]} numberOfLines={2}>
                    {trackingData.store_address}
                    {trackingData.store_city ? `, ${trackingData.store_city}, Mich.` : ""}
                  </Text>
                </View>
              ) : null}

              {/* Teléfono + botón llamar */}
              {trackingData.store_phone ? (
                <View style={styles.storeCardRow}>
                  <View style={[styles.storeCardRowIcon, { backgroundColor: isDark ? "#0a2a0a" : "#f0fff4" }]}>
                    <Ionicons name="call-outline" size={14} color={GREEN} />
                  </View>
                  <Text style={[styles.storeCardValue, { color: t.text, flex: 1 }]}>
                    {trackingData.store_phone}
                  </Text>
                  <TouchableOpacity
                    style={[styles.storeCallBtn, { backgroundColor: isDark ? "#0a2a0a" : "#f0fff4", borderColor: isDark ? "#1a5a1a" : "#bbf7d0" }]}
                    onPress={() => Linking.openURL(`tel:${trackingData.store_phone.replace(/\s/g, "")}`)}
                  >
                    <Ionicons name="call" size={14} color={GREEN} />
                    <Text style={[styles.storeCallBtnText, { color: GREEN }]}>Llamar</Text>
                  </TouchableOpacity>
                </View>
              ) : null}
            </View>
          )}

          {/* Items del pedido — todos sin cortar */}
          {Array.isArray(order.items) && order.items.length > 0 && (
            <View style={[styles.orderItemsSection, { borderTopColor: t.divider }]}>
              <Text style={[styles.orderItemsLabel, { color: t.textMuted }]}>TU PEDIDO</Text>
              {order.items.map((item, i) => (
                <View key={i} style={styles.orderItemTrackRow}>
                  <View style={[styles.orderItemTrackQty, { backgroundColor: t.iconBg }]}>
                    <Text style={[styles.orderItemTrackQtyText, { color: t.text }]}>{item.qty}</Text>
                  </View>
                  <Text style={[styles.orderItemTrackName, { color: t.text }]}>{item.product_name}</Text>
                  <Text style={[styles.orderItemTrackPrice, { color: t.textMuted }]}>${parseFloat(item.price || 0).toFixed(2)}</Text>
                </View>
              ))}
              <View style={[styles.orderItemsTotal, { borderTopColor: t.divider }]}>
                <Text style={[styles.orderItemsTotalLabel, { color: t.textMuted }]}>Total del pedido</Text>
                <Text style={[styles.orderItemsTotalVal, { color: t.text }]}>${parseFloat(order.total || 0).toFixed(2)}</Text>
              </View>
            </View>
          )}
        </ScrollView>

        {/* Fila fija inferior: km + tráfico + llamar */}
        <View style={[styles.footerBottom, { backgroundColor: t.card, borderTopColor: t.divider, paddingBottom: Math.max(safeBottom, Platform.OS === "ios" ? 36 : 14) }]}>
          <View style={styles.kmBlock}>
            <Ionicons name="navigate-outline" size={13} color={t.textMuted} />
            <Text style={[styles.kmText, { color: t.text }]}>{km ? `${km} km` : "Calculando..."}</Text>
          </View>
          {traffic ? (
            <View style={[styles.trafficPill, { backgroundColor: trafficColor + "22", borderColor: trafficColor }]}>
              <View style={[styles.trafficDot, { backgroundColor: trafficColor }]} />
              <Text style={[styles.trafficText, { color: trafficColor }]}>{trafficLabel}</Text>
            </View>
          ) : (
            <Text style={[styles.etaSubText, { color: t.textMuted }]}>Calculando ruta...</Text>
          )}
          <TouchableOpacity style={[styles.callBtn, { backgroundColor: isDark ? "#020" : "#f0fdf4", borderColor: isDark ? "#050" : "#bbf7d0" }]}>
            <Ionicons name="call" size={18} color={GREEN} />
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  return d.toLocaleDateString("es-MX", { day: "numeric", month: "short", year: "numeric" });
}

// Timeline de progreso del pedido (estilo Uber Eats)
const ORDER_STEPS = [
  { key: "pending",    label: "Pedido recibido",        icon: "receipt-outline"   },
  { key: "accepted",   label: "Repartidor asignado",     icon: "bicycle-outline"   },
  { key: "picked_up",  label: "Pedido recogido",         icon: "bag-check-outline" },
  { key: "on_the_way", label: "En camino",               icon: "navigate-outline"  },
  { key: "arrived",    label: "Llegó",                   icon: "home"              },
  { key: "delivered",  label: "Entregado",               icon: "checkmark-circle"  },
];
const STATUS_ORDER = ["pending","accepted","preparing","picked_up","on_the_way","shipped","arrived","delivered"];

// Timeline de progreso del pedido con ANIMACIÓN
function OrderTimeline({ status }) {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    // Animación infinita para el paso actual
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1.2, duration: 800, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1,   duration: 800, useNativeDriver: true }),
      ])
    ).start();
  }, [status]);

  if (status === "cancelled") {
    return (
      <View style={styles.timelineWrap}>
        <View style={styles.timelineCancelRow}>
          <Ionicons name="close-circle" size={18} color={RED} />
          <Text style={styles.timelineCancelText}>Pedido cancelado</Text>
        </View>
      </View>
    );
  }
  
  const currentIdx = STATUS_ORDER.indexOf(status);
  
  return (
    <View style={styles.timelineWrap}>
      {ORDER_STEPS.map((step, i) => {
        const stepIdx = STATUS_ORDER.indexOf(step.key);
        const done    = currentIdx > stepIdx;
        const active  = currentIdx === stepIdx;
        
        return (
          <View key={step.key} style={styles.timelineRow}>
            <View style={styles.timelineLineCol}>
              <View style={[
                styles.timelineDot,
                done   && { backgroundColor: RED },
                active && { backgroundColor: RED, elevation: 4 },
              ]}>
                {done ? (
                  <Ionicons name="checkmark" size={14} color="#fff" />
                ) : active ? (
                  <Animated.View style={{ transform: [{ scale: pulseAnim }] }}>
                    <Ionicons name={step.icon} size={14} color="#fff" />
                  </Animated.View>
                ) : (
                  <Ionicons name={step.icon} size={12} color="#ccc" />
                )}
              </View>
              {i < ORDER_STEPS.length - 1 && (
                <View style={[styles.timelineConnector, done && { backgroundColor: RED }]} />
              )}
            </View>
            <Text style={[
              styles.timelineLabel,
              done   && { color: "#333", fontWeight: "600" },
              active && { color: RED, fontWeight: "900", fontSize: 13 },
            ]}>
              {step.label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

// Statuses donde el repartidor aún NO recogió el pedido → cancelación permitida
const CANCELLABLE = ["pending", "accepted", "preparing"];

// ─── MODAL DE CALIFICACIÓN ────────────────────────────────────────────────────
function RatingModal({ visible, order, onClose, onRated }) {
  const { user } = useAuth();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (rating === 0) {
      Alert.alert("Atención", "Por favor selecciona una puntuación.");
      return;
    }
    setLoading(true);
    try {
      const res = await rateOrder(order.id, rating, comment, user?.token);
      if (res?.success) {
        Alert.alert("¡Gracias!", "Tu calificación ha sido enviada.");
        onRated?.();
        onClose();
      } else {
        Alert.alert("Error", res?.message || "No se pudo enviar la calificación.");
      }
    } catch {
      Alert.alert("Error", "Error de conexión al enviar calificación.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.modalCard}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>¿Cómo fue tu entrega?</Text>
            <TouchableOpacity onPress={onClose} style={styles.modalClose}>
              <Ionicons name="close" size={24} color="#aaa" />
            </TouchableOpacity>
          </View>
          
          <Text style={styles.modalOrderId}>Pedido #{String(order?.id).padStart(6, "0")}</Text>
          
          <View style={styles.starsRow}>
            {[1, 2, 3, 4, 5].map((s) => (
              <TouchableOpacity key={s} onPress={() => setRating(s)}>
                <Ionicons name={s <= rating ? "star" : "star-outline"} size={42} color={s <= rating ? "#f59e0b" : "#ddd"} />
              </TouchableOpacity>
            ))}
          </View>

          <TextInput
            style={styles.ratingInput}
            placeholder="Escribe un comentario opcional..."
            multiline
            numberOfLines={3}
            placeholderTextColor="#aaa"
            value={comment}
            onChangeText={setComment}
          />

          <TouchableOpacity style={styles.rateSubmitBtn} onPress={handleSubmit} disabled={loading}>
            {loading ? <ActivityIndicator color="#fff" size="small" /> : (
              <Text style={styles.rateSubmitText}>ENVIAR CALIFICACIÓN</Text>
            )}
          </TouchableOpacity>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

function OrderCard({ order, onTrack, onCancelled, defaultExpanded = false }) {
  const { user } = useAuth();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [cancelling, setCancelling] = useState(false);
  const [rateModalVisible, setRateModalVisible] = useState(false);

  const handleCancel = () => {
    Alert.alert(
      "Cancelar pedido",
      `¿Cancelar el pedido #${String(order.id).padStart(6, "0")}? Esta acción no se puede deshacer.`,
      [
        { text: "No, mantener", style: "cancel" },
        {
          text: "Sí, cancelar",
          style: "destructive",
          onPress: async () => {
            setCancelling(true);
            try {
              const res = await cancelOrder(order.id, user?.token);
              if (res?.success) {
                onCancelled?.();
              } else {
                Alert.alert("Error", res?.message || "No se pudo cancelar el pedido.");
              }
            } catch {
              Alert.alert("Error", "Error de conexión. Intenta de nuevo.");
            } finally {
              setCancelling(false);
            }
          },
        },
      ]
    );
  };

  // Sincronizar expansión inicial si cambia la prop
  useEffect(() => {
    if (defaultExpanded) setExpanded(true);
  }, [defaultExpanded]);

  const mapped = STATUS_MAP[order.status] || { label: order.status || "Pendiente", style: "preparando" };
  const s = STATUS_STYLES[mapped.style];
  const isActive = ["pending", "accepted", "preparing", "picked_up", "on_the_way", "shipped", "arrived"].includes(order.status);
  const canTrack  = ["accepted", "shipped", "on_the_way", "picked_up", "arrived"].includes(order.status);
  const canCancel = CANCELLABLE.includes(order.status);

  return (
    <View style={[
      styles.historyCard, 
      isActive && { borderColor: RED, borderWidth: 1.5 },
      expanded && { shadowOpacity: 0.1, elevation: 4 }
    ]}>
      <TouchableOpacity
        style={styles.historyCardMain}
        activeOpacity={0.7}
        onPress={() => setExpanded(!expanded)}
      >
        <View style={styles.historyCardLeft}>
          <View style={[styles.historyIcon, { backgroundColor: "#f8faff" }]}>
            <Ionicons name="bicycle-outline" size={18} color={BLUE} />
          </View>
          <View>
            <Text style={styles.historyId}>Pedido #{String(order.id).padStart(6, "0")}</Text>
            <Text style={styles.historyDate}>{formatDate(order.created_at)}</Text>
          </View>
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={styles.historyTotal}>${parseFloat(order.total || 0).toFixed(2)}</Text>
          <Text style={[styles.historyStatus, { color: s.color }]}>{mapped.label.toUpperCase()}</Text>
        </View>
      </TouchableOpacity>

      {expanded && (
        <View style={styles.expandedContent}>
          <View style={styles.orderDivider} />
          
          {isActive && (
            <View style={{ marginVertical: 15, paddingHorizontal: 4 }}>
              <OrderTimeline status={order.status} />
              {canTrack && (
                <TouchableOpacity style={styles.trackBtnFull} onPress={() => onTrack(order)}>
                  <Ionicons name="map-outline" size={18} color="#fff" />
                  <Text style={styles.trackBtnText}>RASTREAR EN TIEMPO REAL</Text>
                </TouchableOpacity>
              )}
            </View>
          )}

          <Text style={styles.detailLabel}>PRODUCTOS</Text>
          {Array.isArray(order.items) && order.items.map((item, i) => (
            <View key={i} style={styles.orderItem}>
              <Text style={styles.orderItemName} numberOfLines={1}>{item.product_name.toUpperCase()}</Text>
              <Text style={styles.orderItemQtyPrice}>x{item.qty}  ${parseFloat(item.price || 0).toFixed(2)}</Text>
            </View>
          ))}

          {order.address && (
            <View style={[styles.orderAddr, { marginTop: 15, paddingTop: 10, borderTopWidth: 1, borderTopColor: "#f5f5f5" }]}>
              <Ionicons name="location-outline" size={14} color="#aaa" />
              <Text style={styles.orderAddrText} numberOfLines={2}>{order.address}</Text>
            </View>
          )}

          {isActive && canCancel && (
            <TouchableOpacity style={styles.cancelBtnCompact} onPress={handleCancel} disabled={cancelling}>
              {cancelling
                ? <ActivityIndicator size="small" color={RED} />
                : <Text style={styles.cancelBtnText}>CANCELAR PEDIDO</Text>
              }
            </TouchableOpacity>
          )}

          {/* Botón calificar si está entregado y no calificado */}
          {order.status === "delivered" && !order.rating && (
            <TouchableOpacity 
              style={styles.rateBtn} 
              onPress={() => setRateModalVisible(true)}
            >
              <Ionicons name="star" size={16} color="#fff" />
              <Text style={styles.rateBtnText}>CALIFICAR REPARTIDOR</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      <RatingModal 
        visible={rateModalVisible} 
        order={order} 
        onClose={() => setRateModalVisible(false)} 
        onRated={onCancelled} 
      />
    </View>
  );
}

const FILTERS = ["Todos", "Preparando", "En camino", "Entregados", "Cancelados"];
const FILTER_STATUS = {
  "Todos": null,
  "Preparando": ["pending", "accepted", "preparing"],
  "En camino": ["shipped", "on_the_way", "picked_up"],
  "Entregados": ["delivered"],
  "Cancelados": ["cancelled"],
};

function getNotifTitle(status) {
  const titles = {
    accepted:    "🛵 Repartidor asignado",
    preparing:   "🏪 Preparando tu pedido",
    picked_up:   "📦 Pedido recogido",
    on_the_way:  "🛵 ¡En camino!",
    arrived:     "🏠 ¡Tu repartidor llegó!",
    delivered:   "✅ ¡Pedido entregado!",
    cancelled:   "❌ Pedido cancelado",
  };
  return titles[status] || "Actualización de pedido";
}

// Mensajes de toast para cada cambio de estado
const STATUS_TOAST = {
  accepted:    { icon: "bicycle",           color: BLUE,    msg: "¡Repartidor asignado a tu pedido!" },
  preparing:   { icon: "storefront",        color: "#f59e0b", msg: "Tu pedido se está preparando" },
  picked_up:   { icon: "bag-check-outline", color: BLUE,    msg: "El repartidor recogió tu pedido" },
  on_the_way:  { icon: "navigate",          color: BLUE,    msg: "¡Tu pedido va en camino!" },
  arrived:     { icon: "home",               color: GREEN,   msg: "¡Tu repartidor llegó!" },
  delivered:   { icon: "checkmark-circle",  color: GREEN,   msg: "¡Pedido entregado! 🎉" },
  cancelled:   { icon: "close-circle",      color: RED,     msg: "Tu pedido fue cancelado" },
};

export default function OrdersScreen({ onStorePress, onBack, onTrackingChange }) {
  const { width } = useWindowDimensions();
  const isDesktop = width >= 1024;
  const { user, signInWithGoogle } = useAuth();
  const { t } = useTheme();
  const { top: safeTop, bottom: safeBottom } = useSafeAreaInsets();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeFilter, setActiveFilter] = useState("Todos");
  const [trackingOrder, setTrackingOrder] = useState(null);
  const openTracking = (order) => { setTrackingOrder(order); onTrackingChange?.(true); };
  const [toast, setToast] = useState(null);
  const toastAnim = useRef(new Animated.Value(0)).current;
  const prevStatusMap = useRef({});
  const toastTimer = useRef(null);
  const { addNotification } = useNotifications();

  // Mostrar toast animado
  const showToast = useCallback((msg, icon, color) => {
    setToast({ msg, icon, color });
    Animated.spring(toastAnim, { toValue: 1, useNativeDriver: true, tension: 100 }).start();
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => {
      Animated.timing(toastAnim, { toValue: 0, duration: 300, useNativeDriver: true }).start(
        () => setToast(null)
      );
    }, 3500);
  }, [toastAnim]);

  const fetchOrders = useCallback(() => {
    if (!user?.token) return;
    setLoading(true);
    getUserOrders(user.token)
      .then((res) => {
        if (res?.success && Array.isArray(res.data)) {
          const newOrders = res.data;
          // Detectar cambios de estado para toast + historial de notificaciones
          newOrders.forEach((o) => {
            const prev = prevStatusMap.current[o.id];
            if (prev && prev !== o.status && STATUS_TOAST[o.status]) {
              const t = STATUS_TOAST[o.status];
              showToast(t.msg, t.icon, t.color);
              // Guardar en el historial de notificaciones in-app
              addNotification({
                title:   getNotifTitle(o.status),
                body:    `Pedido #${String(o.id).padStart(6, "0")} — ${t.msg}`,
                type:    o.status,
                orderId: String(o.id),
              });
            }
            prevStatusMap.current[o.id] = o.status;
          });
          setOrders(newOrders);
        }
      })
      .finally(() => setLoading(false));
  }, [user?.token, showToast, addNotification]);

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(fetchOrders, 20000);
    return () => {
      clearInterval(interval);
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, [fetchOrders]);

  if (trackingOrder) {
    return (
      <TrackingMap
        order={trackingOrder}
        onBack={() => { setTrackingOrder(null); onTrackingChange?.(false); }}
      />
    );
  }

  const inTransit = orders.filter((o) => ["accepted", "preparing", "picked_up", "on_the_way", "shipped", "arrived", "pending"].includes(o.status));
  const pastOrders = orders.filter((o) => ["delivered", "cancelled"].includes(o.status));

  // Aplicar filtro de chips solo al historial (a menos que se busque algo específico)
  const filteredPast = pastOrders.filter((o) => {
    const statuses = FILTER_STATUS[activeFilter];
    if (!statuses || activeFilter === "Todos") return true;
    return statuses.includes(o.status);
  });

  const topPad = isDesktop ? 0 : (safeTop > 0 ? safeTop : Platform.OS === "ios" ? 50 : 40);

  return (
    <View style={[styles.wrapper, { backgroundColor: t.bg, paddingTop: topPad }]}>
      <View style={[styles.header, { backgroundColor: t.header, borderBottomColor: t.border }]}>
        <Text style={[styles.headerTitle, { color: t.text }]}>MIS PEDIDOS</Text>
        {loading && (
          <View style={{ marginLeft: "auto" }}>
            <ActivityIndicator size="small" color={RED} />
          </View>
        )}
      </View>

      {/* Toast de notificación in-app */}
      {toast && (
        <Animated.View style={[
          styles.toastWrap,
          { opacity: toastAnim, transform: [{ translateY: toastAnim.interpolate({ inputRange: [0,1], outputRange: [-20, 0] }) }] }
        ]}>
          <View style={[styles.toastInner, { borderLeftColor: toast.color }]}>
            <Ionicons name={toast.icon} size={20} color={toast.color} />
            <Text style={styles.toastMsg}>{toast.msg}</Text>
          </View>
        </Animated.View>
      )}

      {!user ? (
        <View style={styles.emptyWrap}>
          <View style={styles.emptyIcon}>
            <Ionicons name="receipt-outline" size={48} color="#e6192e" />
          </View>
          <Text style={styles.emptyTitle}>Ve el historial de tus pedidos</Text>
          <Text style={styles.emptySubtitle}>
            Inicia sesión para consultar tus pedidos, rastrear entregas y más
          </Text>
          <TouchableOpacity style={styles.googleLoginBtn} onPress={signInWithGoogle} activeOpacity={0.88}>
            <Ionicons name="logo-google" size={18} color="#EA4335" />
            <Text style={styles.googleLoginText}>Continuar con Google</Text>
          </TouchableOpacity>
        </View>
      ) : loading && orders.length === 0 ? (
        <View style={styles.emptyWrap}>
          <ActivityIndicator size="large" color={RED} />
          <Text style={[styles.emptySubtitle, { marginTop: 16 }]}>Cargando pedidos...</Text>
        </View>
      ) : orders.length === 0 ? (
        <View style={styles.emptyWrap}>
          <View style={styles.emptyIcon}>
            <Ionicons name="receipt-outline" size={64} color="#ddd" />
          </View>
          <Text style={styles.emptyTitle}>Sin pedidos aún</Text>
          <Text style={styles.emptySubtitle}>
            Tus pedidos aparecerán aquí una vez que realices tu primera compra
          </Text>
          <TouchableOpacity style={styles.shopBtn} onPress={onStorePress}>
            <Text style={styles.shopBtnText}>IR A LA TIENDA</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={styles.scrollContent}
        >
          {/* FILTROS ARRIBA DE TODO */}
          <View style={{ marginBottom: 20 }}>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ gap: 8 }}
            >
              {FILTERS.map((f) => (
                <TouchableOpacity
                  key={f}
                  style={[styles.statusChip, activeFilter === f && styles.statusChipActive]}
                  onPress={() => setActiveFilter(f)}
                >
                  <Text style={[styles.statusChipText, activeFilter === f && styles.statusChipTextActive]}>
                    {f}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>

          {/* SECCIÓN 1: PEDIDOS EN CURSO */}
          <View style={{ marginBottom: 25 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
              <Text style={styles.sectionLabel}>EN CURSO ({inTransit.length})</Text>
              {inTransit.length > 0 && <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: RED }} />}
            </View>
            
            {inTransit.length === 0 ? (
              <View style={styles.emptyHistory}>
                <Text style={{ color: "#bbb", fontSize: 13 }}>No tienes pedidos activos</Text>
              </View>
            ) : (
              inTransit.map((order, i) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  onTrack={openTracking}
                  onCancelled={fetchOrders}
                  defaultExpanded={i === 0}
                />
              ))
            )}
          </View>

          {/* SECCIÓN 2: HISTORIAL / FINALIZADOS */}
          <View>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <Text style={styles.sectionLabel}>HISTORIAL / FINALIZADOS</Text>
              <Text style={{ fontSize: 10, color: RED, fontWeight: "800" }}>{activeFilter.toUpperCase()}</Text>
            </View>

            {filteredPast.length === 0 ? (
              <View style={styles.emptyHistory}>
                <Text style={{ color: "#bbb", fontSize: 13 }}>No hay pedidos para mostrar</Text>
              </View>
            ) : (
              filteredPast.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  onTrack={openTracking}
                  onCancelled={fetchOrders}
                />
              ))
            )}
          </View>

          <View style={{ height: safeBottom + MENU_CLEARANCE }} />
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
    backgroundColor: "#f5f5f5",
  },
  header: {
    backgroundColor: "#fff",
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
    flexDirection: "row",
    alignItems: "center",
    height: 72, 
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
  headerTitle: {
    fontSize: 18,
    fontWeight: "900",
    color: "#111",
    marginLeft: 0,
  },


  emptyWrap: { flex: 1, justifyContent: "center", alignItems: "center", padding: 40 },
  emptyIcon: {
    width: 100, height: 100, borderRadius: 50,
    backgroundColor: "#fff5f5", borderWidth: 2, borderColor: "#ffd0d4",
    justifyContent: "center", alignItems: "center", marginBottom: 22,
  },
  emptyTitle: { fontSize: 19, fontWeight: "900", color: "#222", marginBottom: 8, textAlign: "center" },
  emptySubtitle: { fontSize: 14, color: "#999", textAlign: "center", lineHeight: 20, marginBottom: 28 },
  shopBtn: { backgroundColor: YELLOW, paddingHorizontal: 32, paddingVertical: 14, borderRadius: 14 },
  shopBtnText: { fontSize: 14, fontWeight: "900", color: "#000" },
  googleLoginBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    width: "100%", paddingVertical: 15, borderRadius: 14,
    backgroundColor: "#fff", borderWidth: 1.5, borderColor: "#e0e0e0",
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07, shadowRadius: 6, elevation: 3,
  },
  googleLoginText: { fontSize: 15, fontWeight: "800", color: "#222" },

  scrollContent: { padding: 16 },
  statusChips: { gap: 8, paddingBottom: 16 },
  statusChip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20,
    backgroundColor: "#fff", borderWidth: 1, borderColor: "#eee",
  },
  statusChipActive: { backgroundColor: RED, borderColor: RED },
  statusChipText: { fontSize: 12, fontWeight: "700", color: "#666" },
  statusChipTextActive: { color: "#fff" },

  // Estilos TPN Roja
  activeLabel: { fontSize: 10, fontWeight: "900", color: RED, letterSpacing: 1, marginBottom: 4 },
  trackPill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: RED, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 20,
  },
  trackPillText: { fontSize: 11, fontWeight: "900", color: "#fff" },
  activeDetailBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, marginTop: 8, borderTopWidth: 1, borderTopColor: "#f5f5f5",
  },
  activeDetailText: { fontSize: 12, fontWeight: "700", color: "#aaa" },

  historyHeader: { marginBottom: 12 },
  historyCard: {
    backgroundColor: "#fff", borderRadius: 16, padding: 14, marginBottom: 10,
    borderWidth: 1, borderColor: "#f0f0f0",
  },
  historyCardMain: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  historyCardLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  historyIcon: { width: 36, height: 36, borderRadius: 10, justifyContent: "center", alignItems: "center" },
  historyId: { fontSize: 14, fontWeight: "800", color: "#111" },
  historyDate: { fontSize: 11, color: "#aaa", marginTop: 1 },
  historyTotal: { fontSize: 14, fontWeight: "900", color: "#111", textAlign: "right" },
  historyStatus: { fontSize: 10, fontWeight: "800", textAlign: "right", marginTop: 2, textTransform: "uppercase" },
  historyDetail: { marginTop: 4 },
  emptyHistory: { paddingVertical: 30, alignItems: "center" },

  // Nuevos estilos compactos
  expandedContent: { paddingBottom: 10 },
  detailLabel: { fontSize: 10, fontWeight: "900", color: "#ccc", letterSpacing: 1, marginBottom: 8, marginTop: 10 },
  trackBtnFull: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: RED, borderRadius: 12, paddingVertical: 14, marginTop: 15,
  },
  cancelBtnCompact: {
    alignItems: "center", paddingVertical: 10, marginTop: 10,
    borderWidth: 1, borderColor: "#ffd0d4", borderRadius: 12,
  },
  rateBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#f59e0b", borderRadius: 12, paddingVertical: 14, marginTop: 15,
  },
  rateBtnText: { color: "#fff", fontWeight: "900", fontSize: 13, letterSpacing: 0.5 },

  // Modal Rating
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: "#fff", borderRadius: 24, padding: 24 },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  modalTitle: { fontSize: 18, fontWeight: "900", color: "#111" },
  modalOrderId: { fontSize: 12, color: "#aaa", marginBottom: 20 },
  starsRow: { flexDirection: "row", justifyContent: "center", gap: 8, marginBottom: 24 },
  ratingInput: { backgroundColor: "#f5f5f5", borderRadius: 12, padding: 16, height: 80, fontSize: 14, color: "#111", textAlignVertical: "top", marginBottom: 20 },
  rateSubmitBtn: { backgroundColor: RED, borderRadius: 14, paddingVertical: 16, alignItems: "center" },
  rateSubmitText: { color: "#fff", fontWeight: "900", fontSize: 14, letterSpacing: 1 },

  activeOrderBanner: {
    backgroundColor: "#fff5f5", borderRadius: 16, padding: 16,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 20, borderWidth: 1, borderColor: "#ffd0d4",
  },
  activeOrderLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  activeOrderIcon: {
    width: 42, height: 42, borderRadius: 12,
    backgroundColor: "#ffd0d4", justifyContent: "center", alignItems: "center",
  },
  activeOrderLabel: { fontSize: 13, fontWeight: "800", color: RED },
  activeOrderId: { fontSize: 12, color: "#6b7280", marginTop: 2 },
  trackLivePill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: RED, paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: 20,
  },
  trackLiveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: "#fff", opacity: 0.85 },
  trackLiveText: { fontSize: 11, fontWeight: "900", color: "#fff", letterSpacing: 0.5 },

  sectionLabel: { fontSize: 11, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 12 },

  // Toast notificación in-app
  toastWrap: {
    position: "absolute", top: 70, left: 16, right: 16, zIndex: 999,
  },
  toastInner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "#fff", borderRadius: 14, padding: 14,
    borderLeftWidth: 4,
    shadowColor: "#000", shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12, shadowRadius: 12, elevation: 8,
  },
  toastMsg: { flex: 1, fontSize: 13, fontWeight: "700", color: "#111" },

  // Timeline de progreso del pedido
  timelineWrap: { paddingTop: 10, paddingBottom: 4, paddingHorizontal: 2 },
  timelineRow: { flexDirection: "row", alignItems: "flex-start", minHeight: 36 },
  timelineLineCol: { alignItems: "center", width: 28 },
  timelineDot: {
    width: 24, height: 24, borderRadius: 12,
    backgroundColor: "#e8e8e8", justifyContent: "center", alignItems: "center",
  },
  timelineDotDone: { backgroundColor: RED },
  timelineDotActive: { backgroundColor: RED, shadowColor: RED, shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.5, shadowRadius: 4, elevation: 3 },
  timelineConnector: { width: 2, flex: 1, minHeight: 12, backgroundColor: "#e8e8e8", marginVertical: 2 },
  timelineConnectorDone: { backgroundColor: RED },
  timelineLabel: { flex: 1, fontSize: 12, color: "#bbb", fontWeight: "500", paddingLeft: 10, paddingTop: 4 },
  timelineLabelDone: { color: "#555", fontWeight: "600" },
  timelineLabelActive: { color: RED, fontWeight: "800" },
  timelineCancelRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  timelineCancelText: { fontSize: 12, color: RED, fontWeight: "700" },

  orderCard: {
    backgroundColor: "#fff", borderRadius: 16, padding: 16, marginBottom: 12,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05, shadowRadius: 8, elevation: 2,
  },
  orderCardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  orderId: { fontSize: 14, fontWeight: "800", color: "#111" },
  orderDate: { fontSize: 12, color: "#aaa", marginTop: 2 },
  statusBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 20,
  },
  statusText: { fontSize: 11, fontWeight: "700" },
  orderDivider: { height: 1, backgroundColor: "#f5f5f5", marginVertical: 12 },
  orderCardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  orderMeta: { flexDirection: "row", alignItems: "center", gap: 6 },
  orderMetaText: { fontSize: 13, color: "#888" },
  orderMetaRight: { flexDirection: "row", alignItems: "center", gap: 6 },
  orderTotal: { fontSize: 15, fontWeight: "900", color: "#111" },

  itemsList: { marginTop: 12, borderTopWidth: 1, borderTopColor: "#f5f5f5", paddingTop: 12 },
  orderItem: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 4,
  },
  orderItemName: { fontSize: 12, color: "#555", flex: 1, marginRight: 8 },
  orderItemQtyPrice: { fontSize: 12, color: "#888", fontWeight: "600" },
  orderAddr: { flexDirection: "row", gap: 4, marginTop: 8, alignItems: "flex-start" },
  orderAddrText: { fontSize: 11, color: "#aaa", flex: 1 },

  cancelBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: 12, paddingVertical: 10, borderRadius: 12,
    borderWidth: 1.5, borderColor: "#fca5a5", backgroundColor: "#fff5f5",
  },
  cancelBtnText: { fontSize: 13, fontWeight: "700", color: RED },

  trackBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: BLUE, borderRadius: 12, paddingVertical: 12, marginTop: 16,
  },
  trackBtnText: { color: "#fff", fontWeight: "800", fontSize: 13 },

  trackingContainer: { flex: 1, backgroundColor: "#000" },

  // Barra flotante superior
  trackingTopBar: {
    position: "absolute", top: 0, left: 0, right: 0,
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingBottom: 12,
  },
  backBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: "#fff",
    justifyContent: "center", alignItems: "center",
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.18, shadowRadius: 6, elevation: 5,
  },
  trackingStatusPill: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(255,255,255,0.96)",
    paddingHorizontal: 14, paddingVertical: 9, borderRadius: 22,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.12, shadowRadius: 6, elevation: 4,
  },
  trackingStatusDot: { width: 9, height: 9, borderRadius: 5 },
  trackingStatusText: { fontSize: 13, fontWeight: "700", color: "#111", flex: 1 },
  etaFloatBadge: {
    backgroundColor: RED, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 18,
    alignItems: "center", minWidth: 52,
    shadowColor: RED, shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.35, shadowRadius: 6, elevation: 4,
  },
  etaFloatNum: { fontSize: 16, fontWeight: "900", color: "#fff" },
  etaFloatLabel: { fontSize: 8, fontWeight: "700", color: "rgba(255,255,255,0.8)", letterSpacing: 0.5 },

  // Marcadores del mapa estandarizados
  markerCircle: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: "center",
    alignItems: "center",
    borderWidth: 2,
    borderColor: "#fff",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 3,
    elevation: 4,
  },

  trackingFooter: {
    position: "absolute",
    bottom: 0, left: 0, right: 0,
    // Máximo 58% de pantalla; el ScrollView interno permite ver el resto
    maxHeight: Dimensions.get("window").height * 0.58,
    backgroundColor: "#fff",
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    shadowColor: "#000", shadowOffset: { width: 0, height: -8 }, shadowOpacity: 0.12, shadowRadius: 20,
    elevation: 20,
    overflow: "hidden",
  },
  footerScroll: {
    flexShrink: 1,
  },
  footerScrollContent: {
    paddingBottom: 6,
  },
  // Fila superior: avatar + datos + ETA
  footerTop: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 18, paddingTop: 18, paddingBottom: 12,
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  driverAvatarCircle: {
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: BLUE, justifyContent: "center", alignItems: "center",
    shadowColor: BLUE, shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.30, shadowRadius: 8,
    elevation: 4,
  },
  driverName: { fontSize: 15, fontWeight: "900", color: "#111" },
  starsRow: { flexDirection: "row", alignItems: "center", gap: 2, marginTop: 3, marginBottom: 3 },
  ratingVal: { fontSize: 12, fontWeight: "700", color: "#555", marginLeft: 4 },
  driverRole: { fontSize: 11, color: "#888", fontWeight: "600" },
  etaBlock: { alignItems: "center", minWidth: 60 },
  etaBigNum: { fontSize: 34, fontWeight: "900", color: RED, lineHeight: 38 },
  etaBigLabel: { fontSize: 10, fontWeight: "800", color: "#aaa", letterSpacing: 0.5 },
  // Fila inferior fija: km + tráfico + llamar
  footerBottom: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 14,
    gap: 10,
    borderTopWidth: 1, borderTopColor: "#f0f0f0",
    backgroundColor: "#fff",
  },
  storeInfoRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 18, paddingTop: 10, paddingBottom: 4,
    borderBottomWidth: 1, borderBottomColor: "#f5f5f5",
  },
  storeInfoIcon: {
    width: 26, height: 26, borderRadius: 8,
    backgroundColor: "#fff0f1", justifyContent: "center", alignItems: "center",
  },
  storeInfoText: { fontSize: 12, color: "#888", fontWeight: "500" },
  storeInfoName: { fontWeight: "800", color: "#333" },
  // Card de tienda en tracking
  storeCard: {
    marginHorizontal: 14, marginTop: 10, marginBottom: 4,
    borderRadius: 14, borderWidth: 1,
    padding: 14,
  },
  storeCardHeader: {
    flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10,
  },
  storeCardIconWrap: {
    width: 38, height: 38, borderRadius: 19,
    justifyContent: "center", alignItems: "center",
  },
  storeCardBrand: { fontSize: 15, fontWeight: "800" },
  storeCardBranch: { fontSize: 12, fontWeight: "600", color: RED, marginTop: 1 },
  storeCardRow: {
    flexDirection: "row", alignItems: "center", gap: 10, marginTop: 8,
  },
  storeCardRowIcon: {
    width: 30, height: 30, borderRadius: 8,
    justifyContent: "center", alignItems: "center", flexShrink: 0,
  },
  storeCardValue: { fontSize: 13, fontWeight: "500", lineHeight: 18, flex: 1 },
  storeCallBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 8, borderWidth: 1, flexShrink: 0,
  },
  storeCallBtnText: { fontSize: 12, fontWeight: "700" },
  kmBlock: { flexDirection: "row", alignItems: "center", gap: 4, flex: 1 },
  kmText: { fontSize: 12, fontWeight: "700", color: "#666" },
  etaSubText: { fontSize: 11, color: "#aaa", flex: 1 },
  trafficPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 9, paddingVertical: 4,
    borderRadius: 10, borderWidth: 1,
  },
  trafficDot: { width: 6, height: 6, borderRadius: 3 },
  trafficText: { fontSize: 10, fontWeight: "700" },
  callBtn: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "#f0fdf4", justifyContent: "center", alignItems: "center",
    borderWidth: 1.5, borderColor: "#bbf7d0",
  },

  // Items del pedido en el mapa
  orderItemsSection: {
    paddingHorizontal: 18, paddingVertical: 12,
    borderTopWidth: 1, borderTopColor: "#f0f0f0",
  },
  orderItemsLabel: {
    fontSize: 10, fontWeight: "900", color: "#bbb", letterSpacing: 0.8,
    marginBottom: 10,
  },
  orderItemTrackRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 5,
  },
  orderItemTrackQty: {
    width: 24, height: 24, borderRadius: 6,
    backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center",
  },
  orderItemTrackQtyText: { fontSize: 12, fontWeight: "900", color: "#333" },
  orderItemTrackName: { fontSize: 13, color: "#333", fontWeight: "600", flex: 1, flexWrap: "wrap" },
  orderItemTrackPrice: { fontSize: 13, fontWeight: "700", color: "#888" },
  orderItemsMore: { fontSize: 12, color: "#aaa", marginTop: 4, fontWeight: "600" },
  orderItemsTotal: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    marginTop: 10, paddingTop: 10,
    borderTopWidth: 1, borderTopColor: "#f5f5f5",
  },
  orderItemsTotalLabel: { fontSize: 13, fontWeight: "700", color: "#666" },
  orderItemsTotalVal: { fontSize: 15, fontWeight: "900", color: "#111" },
});
