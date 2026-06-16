import { Ionicons } from "@expo/vector-icons";
import { createAudioPlayer, setAudioModeAsync } from "expo-audio";
// expo-haptics requiere build nativo; guard igual que expo-speech
let Haptics = null;
try { Haptics = require("expo-haptics"); } catch (_) {}
import * as Location from "expo-location";
let TaskManager = null;
try { TaskManager = require("expo-task-manager"); } catch (_) {}
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Notifications from "expo-notifications";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Dimensions,
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  Vibration,
  View,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import { useNotifications } from "../context/NotificationsContext";
import { useTheme } from "../context/ThemeContext";
import { GOOGLE_MAPS_DARK_STYLE } from "../constants/theme";
import { MapView, Marker, Polyline, Callout, PROVIDER_GOOGLE } from "../components/MapComponents";
import NotificationsPanel from "../components/NotificationsPanel";
import { API_BASE_URL } from "../services/api";

// expo-speech requiere build nativo; se carga con guard para no crashear en Expo Go
let Speech = null;
try {
  Speech = require("expo-speech");
} catch (_) {}

// ─── BACKGROUND LOCATION TASK ─────────────────────────────────────────────────
const BG_LOCATION_TASK = "tpn-delivery-location";

// Registrar la tarea a nivel de módulo (fuera de cualquier componente)
if (TaskManager && Platform.OS !== "web") {
  TaskManager.defineTask(BG_LOCATION_TASK, async ({ data, error }) => {
    if (error || !data) return;
    const { locations } = data;
    const loc = locations?.[0];
    if (!loc) return;
    try {
      const token = await AsyncStorage.getItem("delivery_bg_token");
      if (!token) return;
      const { latitude, longitude } = loc.coords;
      await updateDeliveryLocation(latitude, longitude, token);
    } catch (_) {}
  });
}

const { width: SCREEN_WIDTH } = Dimensions.get("window");

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

// Valhalla usa precisión 6 en vez de 5
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

import {
  getAvailableOrders,
  getMyDeliveryOrders,
  getDeliveryHistory,
  acceptDeliveryOrder,
  updateDeliveryStatus,
  updateDeliveryLocation,
  registerPushToken,
} from "../services/api";


const RED = "#e6192e";
const GREEN = "#22c55e";
const BLUE = RED; // Forzamos BLUE a ser RED
const ORANGE = "#f59e0b";

// ─── ESTADOS DEL PEDIDO ───────────────────────────────────────────────────────
const STATUS = {
  pending:     { label: "Disponible",    color: ORANGE, bg: "#fffbeb", icon: "time-outline", darkBg: "#3a2a0a" },
  accepted:    { label: "Aceptado",      color: RED,    bg: "#fff5f5", icon: "bicycle-outline", darkBg: "#3a1515" },
  picked_up:   { label: "Recogido",      color: RED,    bg: "#fff5f5", icon: "bag-check-outline", darkBg: "#3a1515" },
  on_the_way:  { label: "En camino",     color: RED,    bg: "#fff5f5", icon: "navigate-outline", darkBg: "#3a1515" },
  arrived:     { label: "Llegó / Afuera",color: GREEN,  bg: "#f0fdf4", icon: "home-outline", darkBg: "#153a15" },
  delivered:   { label: "Entregado",     color: GREEN,  bg: "#f0fdf4", icon: "checkmark-circle-outline", darkBg: "#153a15" },
  cancelled:   { label: "Cancelado",     color: RED,    bg: "#fff1f2", icon: "close-circle-outline", darkBg: "#3a1515" },
};

function formatTime(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return `Hoy ${formatTime(dateStr)}`;
  return d.toLocaleDateString("es-MX", { day: "numeric", month: "short" }) + " " + formatTime(dateStr);
}

// ─── TARJETA DE PEDIDO (lista) ────────────────────────────────────────────────
function OrderListCard({ order, onPress, isActive }) {
  const { t, isDark } = useTheme();
  const st = STATUS[order.status] || STATUS.pending;
  const total = parseFloat(order.total || 0).toFixed(2);
  const bgBadge = isDark ? st.darkBg : st.bg;

  return (
    <TouchableOpacity
      style={[d.listCard, { backgroundColor: t.card }, isActive && { borderColor: RED, backgroundColor: isDark ? "#2a1515" : "#fff8f8" }]}
      onPress={onPress}
      activeOpacity={0.85}
    >
      <View style={d.listCardTop}>
        <View>
          <Text style={[d.orderId, { color: t.text }]}>#{String(order.id).padStart(6, "0")}</Text>
          <Text style={[d.orderTime, { color: t.textMuted }]}>{formatDate(order.created_at)}</Text>
        </View>
        <View style={[d.badge, { backgroundColor: bgBadge }]}>
          <Ionicons name={st.icon} size={12} color={st.color} />
          <Text style={[d.badgeText, { color: st.color }]}>{st.label}</Text>
        </View>
      </View>
      {order.store_name && (
        <View style={d.listCardStore}>
          <Ionicons name="storefront-outline" size={12} color={RED} />
          <Text style={d.storeNameText}>{order.store_name}</Text>
        </View>
      )}
      <View style={d.listCardMid}>
        <Ionicons name="location-outline" size={14} color={t.textMuted} />
        <Text style={[d.addrText, { color: t.textSub }]} numberOfLines={1}>{order.address || "Sin dirección"}</Text>
      </View>
      <View style={d.listCardBottom}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Ionicons name="cube-outline" size={13} color={t.textMuted} />
          <Text style={[d.metaText, { color: t.textMuted }]}>{order.items_count ?? order.items?.length ?? 0} productos</Text>
        </View>
        <Text style={[d.totalText, { color: t.text }]}>${total}</Text>
      </View>
    </TouchableOpacity>
  );
}

// ─── MOTOR DE VOZ: instrucciones basadas en heading entre puntos ─────────────
function bearingDeg(a, b) {
  const dLng = (b.longitude - a.longitude) * Math.PI / 180;
  const lat1  = a.latitude  * Math.PI / 180;
  const lat2  = b.latitude  * Math.PI / 180;
  const y = Math.sin(dLng) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}
function turnInstruction(prev, curr, next) {
  if (!prev || !next) return null;
  const inBearing  = bearingDeg(prev, curr);
  const outBearing = bearingDeg(curr, next);
  let diff = ((outBearing - inBearing) + 360) % 360;
  if (diff > 180) diff -= 360;
  if (Math.abs(diff) < 20) return null; // recto, sin instrucción
  if (diff > 60)  return "Gira a la derecha";
  if (diff < -60) return "Gira a la izquierda";
  if (diff > 0)   return "Conserva la derecha";
  return "Conserva la izquierda";
}

function haversineMeters(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180;
  const Δφ = (lat2 - lat1) * Math.PI / 180;
  const Δλ = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(Δφ/2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ/2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ─── COMPONENTE DE MAPA PARA EL REPARTIDOR ───────────────────────────────────
function DeliveryMap({ destLat, destLng, driverLat, driverLng, storeLat, storeLng, storeName, storeAddress, storeCity, storePhone }) {
  const { t, isDark } = useTheme();
  const [routeCoords, setRouteCoords]   = useState([]);
  const [eta, setEta]                   = useState(null);
  const [km, setKm]                     = useState(null);
  const [navMode, setNavMode]           = useState("app");
  const [originLat, setOriginLat]       = useState(null);
  const [originLng, setOriginLng]       = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError]     = useState(false);
  const [trafficRatio, setTrafficRatio] = useState(1.0);
  // Voz
  const [voiceOn, setVoiceOn]           = useState(false);
  const [nextInstruction, setNextInstruction] = useState(null);
  const [showStoreCard, setShowStoreCard] = useState(false);
  const lastSpokenRef   = useRef(null);
  const routeCoordsRef  = useRef([]);
  const ttsSoundRef     = useRef(null);
  const speakRef        = useRef(null); // ref estable para evitar stale closure en effects
  const mapRef = useRef(null);
  const isWeb  = Platform.OS === "web";

  const started = originLat !== null && originLng !== null;

  // Voz: intenta Google Cloud TTS (misma voz que Google Maps), si falla usa expo-speech
  const speak = useCallback(async (text) => {
    if (!voiceOn || !text || text === lastSpokenRef.current) return;
    lastSpokenRef.current = text;

    // Detener audio anterior
    if (ttsSoundRef.current) {
      try { ttsSoundRef.current.remove(); } catch (_) {}
      ttsSoundRef.current = null;
    }
    if (Speech) { try { Speech.stop(); } catch (_) {} }

    try {
      const ttsUrl = `${API_BASE_URL}?resource=tts&text=${encodeURIComponent(text)}`;
      const player = createAudioPlayer({ uri: ttsUrl });
      ttsSoundRef.current = player;
      player.addListener("playbackStatusUpdate", (s) => {
        if (s.didJustFinish) { try { player.remove(); } catch (_) {} ttsSoundRef.current = null; }
      });
      player.play();
    } catch (_) {
      // Fallback: expo-speech (requiere build nativo)
      if (Speech) try { Speech.speak(text, { language: "es-MX", rate: 0.95, pitch: 1.0 }); } catch (_2) {}
    }
  }, [voiceOn]);

  // Mantener speakRef siempre apuntando a la versión actualizada de speak
  useEffect(() => { speakRef.current = speak; }, [speak]);

  // Limpiar TTS al desmontar el componente
  useEffect(() => {
    return () => {
      if (ttsSoundRef.current) {
        try { ttsSoundRef.current.remove(); } catch (_) {}
        ttsSoundRef.current = null;
      }
      if (Speech) { try { Speech.stop(); } catch (_) {} }
    };
  }, []);

  // Cada vez que cambia la posición del conductor, calcular instrucción siguiente
  useEffect(() => {
    if (!voiceOn || !driverLat || !driverLng) return;
    const coords = routeCoordsRef.current;
    if (coords.length < 3) return;

    // Encontrar el punto más cercano al conductor en la ruta
    let minDist = Infinity, closestIdx = 0;
    coords.forEach((c, i) => {
      const d = Math.hypot(c.latitude - driverLat, c.longitude - driverLng);
      if (d < minDist) { minDist = d; closestIdx = i; }
    });

    // Mirar ~5 puntos adelante para la instrucción
    const lookAhead = Math.min(closestIdx + 5, coords.length - 1);
    const instr = turnInstruction(
      coords[lookAhead - 1],
      coords[lookAhead],
      coords[Math.min(lookAhead + 1, coords.length - 1)]
    );

    // Distancia al punto de giro en metros
    const R = 6371000;
    const dφ = (coords[lookAhead].latitude - driverLat) * Math.PI / 180;
    const dλ = (coords[lookAhead].longitude - driverLng) * Math.PI / 180;
    const a  = Math.sin(dφ/2)**2 + Math.cos(driverLat*Math.PI/180) * Math.cos(coords[lookAhead].latitude*Math.PI/180) * Math.sin(dλ/2)**2;
    const distToTurn = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    if (instr) {
      const label = distToTurn < 50
        ? instr
        : distToTurn < 200
        ? `En ${Math.round(distToTurn)} metros, ${instr.toLowerCase()}`
        : null;
      setNextInstruction(label || instr);
      if (label) speakRef.current?.(label);
    } else {
      setNextInstruction(null);
    }
  }, [driverLat, driverLng, voiceOn]); // speak via ref — no stale closure, no double-fire

  const openExternalNav = () => {
    const latLng = `${destLat},${destLng}`;
    const url = Platform.select({
      ios:     `maps://0,0?q=Cliente TPN@${latLng}`,
      android: `google.navigation:q=${latLng}`,
    });
    if (url) Linking.openURL(url);
  };

  const fetchRoute = useCallback(async (fromLat, fromLng) => {
    if (!fromLat || !fromLng || !destLat || !destLng) return;
    setRouteLoading(true);
    setRouteError(false);
    setRouteCoords([]);

    // Multiplicador de tráfico por hora local (fallback cuando el servidor no retorna ratio)
    const localTrafficMul = () => {
      const h = new Date().getHours();
      if ((h >= 7 && h < 9) || (h >= 17 && h < 19))  return 1.40;
      if ((h >= 9 && h < 12) || (h >= 19 && h < 21)) return 1.15;
      return 1.0;
    };

    const apply = (decoded, durSec, distM, trafficSec, tRatio) => {
      const effectiveSec   = trafficSec && trafficSec > 0 ? trafficSec : Math.round(durSec * localTrafficMul());
      const effectiveRatio = tRatio && tRatio > 0 ? tRatio : localTrafficMul();
      setRouteCoords(decoded);
      routeCoordsRef.current = decoded;
      setEta(Math.ceil(effectiveSec / 60));
      setKm((distM / 1000).toFixed(1));
      setTrafficRatio(effectiveRatio);
      setRouteLoading(false);
      if (!isWeb) {
        mapRef.current?.fitToCoordinates(decoded, {
          edgePadding: { top: 80, bottom: 200, left: 50, right: 50 }, animated: true,
        });
      }
    };

    // ── Proxy PHP (Google Directions + OSRM server-side, sin restricciones Android) ─
    try {
      const base = API_BASE_URL.includes("?") ? API_BASE_URL + "&" : API_BASE_URL + "?";
      const proxyUrl = `${base}resource=route&origin_lat=${fromLat}&origin_lng=${fromLng}&dest_lat=${destLat}&dest_lng=${destLng}`;
      const raw  = await (await fetch(proxyUrl, { headers: { Accept: "application/json" } })).text();
      const json = JSON.parse(raw);
      if (json.success && json.data) {
        const d = json.data;
        const decoded = d.polyline
          ? (d.polyline6 ? decodePolyline6(d.polyline) : decodePolyline(d.polyline))
          : (d.coordinates ?? []);
        if (decoded.length > 1) {
          apply(decoded, d.duration_sec, d.distance_m, d.duration_traffic_sec, d.traffic_ratio);
          return;
        }
      }
      console.log("Route proxy failed:", json.message);
    } catch (e) { console.log("Route proxy error:", e); }

    // ── Intento 2: Valhalla (openstreetmap.de) — POST, funciona desde Android ─
    try {
      const body = JSON.stringify({
        locations: [
          { lon: fromLng, lat: fromLat },
          { lon: destLng, lat: destLat },
        ],
        costing: "auto",
        shape_match: "map_snap",
      });
      const data = await (await fetch("https://valhalla1.openstreetmap.de/route", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body,
      })).json();
      const shape = data?.trip?.legs?.[0]?.shape;
      if (shape) {
        const decoded = decodePolyline6(shape);
        if (decoded.length > 1) {
          const sumTime = data.trip.summary.time;
          const sumLen  = data.trip.summary.length * 1000;
          apply(decoded, sumTime, sumLen, null, null); // localTrafficMul applied inside apply()
          return;
        }
      }
    } catch (e) { console.log("Valhalla error:", e); }

    setRouteLoading(false);
    setRouteError(true);
  }, [destLat, destLng, isWeb]);

  const handleStart = (fromLat, fromLng, withVoice = false) => {
    setOriginLat(fromLat);
    setOriginLng(fromLng);
    setVoiceOn(withVoice);
    fetchRoute(fromLat, fromLng);
    if (withVoice) {
      setTimeout(() => speak("Calculando ruta. Navegación por voz activada."), 400);
    }
  };

  const toggleVoice = () => {
    const next = !voiceOn;
    setVoiceOn(next);
    if (next) {
      setTimeout(() => speak("Voz activada"), 200);
    } else {
      if (ttsSoundRef.current) { try { ttsSoundRef.current.remove(); } catch (_) {} ttsSoundRef.current = null; }
      if (Speech) { try { Speech.stop(); } catch (_) {} }
    }
  };

  // ── Pantalla de selección de partida (antes de comenzar) ──────────────────
  if (!started) {
    const StartOption = ({ icon, iconBg, title, sub, disabled, onGo, onGoVoice }) => (
      <View style={[d.startOptionCard, { opacity: disabled ? 0.4 : 1, borderColor: t.border }]}>
        <View style={d.startOptionTop}>
          <View style={[d.startOptionIcon, { backgroundColor: iconBg }]}>
            <Ionicons name={icon} size={22} color="#fff" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[d.startOptionTitle, { color: t.text }]}>{title}</Text>
            <Text style={[d.startOptionSub, { color: t.textMuted }]}>{sub}</Text>
          </View>
        </View>
        <View style={d.startOptionBtns}>
          <TouchableOpacity
            style={[d.startGoBtn, { backgroundColor: "#1a73e8" }]}
            onPress={onGo}
            disabled={disabled}
            activeOpacity={0.85}
          >
            <Ionicons name="navigate" size={15} color="#fff" />
            <Text style={d.startGoBtnText}>IR A RUTA</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[d.startGoBtn, { backgroundColor: "#34A853", flex: 0, paddingHorizontal: 14 }]}
            onPress={onGoVoice}
            disabled={disabled}
            activeOpacity={0.85}
          >
            <Ionicons name="volume-high" size={15} color="#fff" />
            <Text style={d.startGoBtnText}>CON VOZ</Text>
          </TouchableOpacity>
        </View>
      </View>
    );

    // Distancia del repartidor a la tienda
    const distToStoreM = (driverLat && driverLng && storeLat && storeLng)
      ? haversineMeters(driverLat, driverLng, storeLat, storeLng)
      : null;
    const nearStore = distToStoreM === null || distToStoreM <= 300;
    const storeDistLabel = distToStoreM !== null
      ? distToStoreM >= 1000
        ? `Estás a ${(distToStoreM / 1000).toFixed(1)} km de la tienda`
        : `Estás a ${Math.round(distToStoreM)} m de la tienda`
      : null;

    const onStoreGo = (withVoice) => {
      if (nearStore) {
        handleStart(storeLat, storeLng, withVoice);
        return;
      }
      Alert.alert(
        "¿No estás en la tienda?",
        `${storeDistLabel}. La ruta se calculará como si partieras de la tienda.\n\n¿Confirmas que ya recogiste el pedido ahí?`,
        [
          { text: "Cancelar", style: "cancel" },
          { text: "Sí, partir desde tienda", onPress: () => handleStart(storeLat, storeLng, withVoice) },
        ]
      );
    };

    return (
      <View style={[d.startScreen, { backgroundColor: t.bg, borderBottomColor: t.border }]}>
        <Text style={[d.startTitle, { color: t.text }]}>¿Desde dónde inicias?</Text>
        <Text style={[d.startSub, { color: t.textMuted }]}>
          "IR A RUTA" muestra el mapa · "CON VOZ" activa instrucciones habladas
        </Text>

        {storeLat && storeLng && (
          <StartOption
            icon="storefront-outline"
            iconBg={nearStore ? RED : "#f59e0b"}
            title="Desde la tienda"
            sub={
              !driverLat ? "Recojo el pedido en tienda y parto de aquí" :
              nearStore   ? "Estás en la tienda ✓" :
              storeDistLabel
            }
            disabled={false}
            onGo={() => onStoreGo(false)}
            onGoVoice={() => onStoreGo(true)}
          />
        )}

        <StartOption
          icon="navigate-outline"
          iconBg="#1e293b"
          title="Desde mi ubicación actual"
          sub={driverLat ? "Ya tengo los productos, parto desde aquí" : "Esperando señal GPS…"}
          disabled={!driverLat && !storeLat}
          onGo={() => handleStart(driverLat || storeLat, driverLng || storeLng, false)}
          onGoVoice={() => handleStart(driverLat || storeLat, driverLng || storeLng, true)}
        />
      </View>
    );
  }

  // ── Modo oculto ───────────────────────────────────────────────────────────
  if (navMode === "hidden") {
    return (
      <TouchableOpacity
        style={[d.showNavBtn, { backgroundColor: t.card, borderColor: t.border }]}
        onPress={() => setNavMode("app")}
      >
        <Ionicons name="map" size={18} color={RED} />
        <Text style={d.showNavText}>MOSTRAR MAPA DE NAVEGACIÓN</Text>
      </TouchableOpacity>
    );
  }

  // ── Mapa con ruta ─────────────────────────────────────────────────────────
  return (
    <View style={d.mapContainer}>
      {/* MAPA */}
      {MapView ? (
        <MapView
          ref={mapRef}
          style={StyleSheet.absoluteFillObject}
          provider={PROVIDER_GOOGLE}
          showsUserLocation
          followsUserLocation={navMode === "app"}
          showsMyLocationButton={false}
          showsCompass={false}
          showsTraffic
          customMapStyle={isDark ? GOOGLE_MAPS_DARK_STYLE : []}
          initialRegion={{
            latitude:       (originLat + destLat) / 2,
            longitude:      (originLng + destLng) / 2,
            latitudeDelta:  Math.abs(destLat - originLat) * 1.6 + 0.02,
            longitudeDelta: Math.abs(destLng - originLng) * 1.6 + 0.02,
          }}
          userInterfaceStyle={isDark ? "dark" : "light"}
        >
          {/* Borde blanco de la ruta (efecto Google Maps) */}
          {routeCoords.length > 1 && Polyline && (
            <Polyline coordinates={routeCoords} strokeColor="#fff" strokeWidth={12} zIndex={1} />
          )}
          {/* Ruta azul principal */}
          {routeCoords.length > 1 && Polyline && (
            <Polyline coordinates={routeCoords} strokeColor="#4285F4" strokeWidth={7} zIndex={2} />
          )}
          {/* Marcador tienda */}
          {storeLat && storeLng && (
            <Marker
              coordinate={{ latitude: storeLat, longitude: storeLng }}
              anchor={{ x: 0.5, y: 1 }}
              tracksViewChanges={false}
              onPress={() => setShowStoreCard(true)}
            >
              <View style={d.markerStore}>
                <View style={d.markerStoreCircle}>
                  <Ionicons name="storefront" size={18} color="#fff" />
                </View>
                <View style={d.markerStoreTail} />
              </View>
            </Marker>
          )}
          {/* Marcador origen */}
          <Marker coordinate={{ latitude: originLat, longitude: originLng }} anchor={{ x: 0.5, y: 0.5 }}>
            <View style={d.markerOrigin}>
              <View style={d.markerOriginDot} />
            </View>
          </Marker>
          {/* Marcador destino */}
          <Marker coordinate={{ latitude: destLat, longitude: destLng }} anchor={{ x: 0.5, y: 1 }}>
            <View style={d.markerDest}>
              <Ionicons name="location-sharp" size={40} color="#EA4335" />
            </View>
          </Marker>
        </MapView>
      ) : null}

      {/* ── Panel superior ETA + instrucción de voz ── */}
      <View style={d.gmTopBar}>
        {/* Instrucción de giro (solo cuando hay voz activa) */}
        {voiceOn && nextInstruction && (
          <View style={d.gmInstrRow}>
            <Ionicons name="arrow-forward-circle" size={22} color="#fff" />
            <Text style={d.gmInstrText}>{nextInstruction}</Text>
          </View>
        )}
        <View style={d.gmEtaRow}>
          <Text style={d.gmEtaTime}>{eta ?? "--"}</Text>
          <Text style={d.gmEtaUnit}> min</Text>
          {/* Indicador de tráfico */}
          {eta && (() => {
            const color = trafficRatio >= 1.30 ? "#EA4335" : trafficRatio >= 1.12 ? "#FBBC04" : "#34A853";
            const label = trafficRatio >= 1.30 ? "Congestionado" : trafficRatio >= 1.12 ? "Tráfico lento" : "Fluido";
            return (
              <View style={[d.gmTrafficBadge, { backgroundColor: color + "33", borderColor: color }]}>
                <View style={[d.gmTrafficDot, { backgroundColor: color }]} />
                <Text style={[d.gmTrafficLabel, { color }]}>{label}</Text>
              </View>
            );
          })()}
          <View style={d.gmSep} />
          <Text style={d.gmDist}>{km ?? "--"} km</Text>
          {/* Toggle voz */}
          <TouchableOpacity style={[d.gmVoiceBtn, voiceOn && d.gmVoiceBtnOn]} onPress={toggleVoice}>
            <Ionicons name={voiceOn ? "volume-high" : "volume-mute"} size={18} color={voiceOn ? "#fff" : "#aaa"} />
          </TouchableOpacity>
        </View>
        {routeLoading && (
          <View style={d.gmLoadingRow}>
            <ActivityIndicator size="small" color="#4285F4" style={{ marginRight: 6 }} />
            <Text style={d.gmLoadingText}>Calculando ruta…</Text>
          </View>
        )}
        {routeError && !routeLoading && (
          <View style={d.gmLoadingRow}>
            <Ionicons name="alert-circle" size={14} color="#EA4335" style={{ marginRight: 4 }} />
            <Text style={[d.gmLoadingText, { color: "#EA4335" }]}>Sin ruta — </Text>
            <TouchableOpacity onPress={() => fetchRoute(originLat, originLng)}>
              <Text style={d.gmRetryLink}>Reintentar</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* ── Barra inferior (estilo Google Maps) ── */}
      <View style={d.gmBottomBar}>
        <TouchableOpacity style={d.gmNavBtn} onPress={openExternalNav} activeOpacity={0.85}>
          <Ionicons name="navigate-circle" size={20} color="#fff" />
          <Text style={d.gmNavBtnText}>ABRIR EN GOOGLE MAPS</Text>
        </TouchableOpacity>
        <View style={d.gmSecondRow}>
          <TouchableOpacity
            style={[d.gmChip, navMode === "app" && d.gmChipActive]}
            onPress={() => setNavMode("app")}
          >
            <Ionicons name="phone-portrait-outline" size={13} color={navMode === "app" ? "#fff" : "#555"} />
            <Text style={[d.gmChipText, navMode === "app" && { color: "#fff" }]}>Seguir</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[d.gmChip, voiceOn && { backgroundColor: "#34A853" }]}
            onPress={toggleVoice}
          >
            <Ionicons name={voiceOn ? "volume-high" : "volume-mute"} size={13} color={voiceOn ? "#fff" : "#555"} />
            <Text style={[d.gmChipText, voiceOn && { color: "#fff" }]}>{voiceOn ? "Voz ON" : "Voz"}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={d.gmChip} onPress={() => setNavMode("hidden")}>
            <Ionicons name="eye-off-outline" size={13} color="#555" />
            <Text style={d.gmChipText}>Ocultar</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={d.gmChip}
            onPress={() => mapRef.current?.fitToCoordinates(
              routeCoords.length > 1 ? routeCoords
                : [{ latitude: originLat, longitude: originLng }, { latitude: destLat, longitude: destLng }],
              { edgePadding: { top: 80, bottom: 200, left: 50, right: 50 }, animated: true }
            )}
          >
            <Ionicons name="expand-outline" size={13} color="#555" />
            <Text style={d.gmChipText}>Centrar</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* ── Card info de tienda (aparece al tocar el marcador) ── */}
      {showStoreCard && storeLat && storeLng && (
        <TouchableOpacity
          style={d.storeCardOverlay}
          activeOpacity={1}
          onPress={() => setShowStoreCard(false)}
        >
          <View style={[d.storeCard, { backgroundColor: isDark ? "#1e1e1e" : "#fff" }]}>
            {/* Cabecera */}
            <View style={d.storeCardHeader}>
              <View style={d.storeCardIconWrap}>
                <Ionicons name="storefront" size={20} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[d.storeCardBrand, { color: t.text }]}>Todo Pal Negocio</Text>
                {storeName ? (
                  <Text style={d.storeCardBranch}>Sucursal {storeName}</Text>
                ) : null}
              </View>
              <TouchableOpacity onPress={() => setShowStoreCard(false)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                <Ionicons name="close-circle" size={24} color={t.textMuted} />
              </TouchableOpacity>
            </View>

            {/* Dirección */}
            {storeAddress ? (
              <View style={d.storeCardRow}>
                <View style={[d.storeCardRowIcon, { backgroundColor: isDark ? "#2a1515" : "#fff0f0" }]}>
                  <Ionicons name="location-outline" size={16} color={RED} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[d.storeCardLabel, { color: t.textMuted }]}>Dirección</Text>
                  <Text style={[d.storeCardValue, { color: t.text }]}>
                    {storeAddress}{storeCity ? `, ${storeCity}, Mich.` : ""}
                  </Text>
                </View>
              </View>
            ) : null}

            {/* Teléfono */}
            {storePhone ? (
              <View style={d.storeCardRow}>
                <View style={[d.storeCardRowIcon, { backgroundColor: isDark ? "#122a12" : "#f0fff0" }]}>
                  <Ionicons name="call-outline" size={16} color="#22c55e" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[d.storeCardLabel, { color: t.textMuted }]}>Teléfono</Text>
                  <Text style={[d.storeCardValue, { color: t.text }]}>{storePhone}</Text>
                </View>
              </View>
            ) : null}
          </View>
        </TouchableOpacity>
      )}
    </View>
  );
}

// ─── DETALLE DEL PEDIDO ───────────────────────────────────────────────────────
function OrderDetail({ order, onBack, onRefresh }) {
  const { user } = useAuth();
  const { t, isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [localOrder, setLocalOrder] = useState(order);
  const [driverLoc, setDriverLoc] = useState({ lat: null, lng: null });
  const st = STATUS[localOrder.status] || STATUS.pending;
  const watchId = useRef(null);
  const bgBadge = isDark ? st.darkBg : st.bg;

  // Watcher de posición solo para actualizar el marcador en el mapa (UI local)
  useEffect(() => {
    const startTracking = async () => {
      if (!["accepted", "picked_up", "on_the_way", "arrived"].includes(localOrder.status)) {
        if (watchId.current) { watchId.current.remove(); watchId.current = null; }
        return;
      }
      if (Platform.OS === "web") return; // web usa el polling del componente padre
      try {
        if (watchId.current) watchId.current.remove();
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") return;
        watchId.current = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, distanceInterval: 10, timeInterval: 5000 },
          (loc) => {
            const { latitude, longitude } = loc.coords;
            setDriverLoc({ lat: latitude, lng: longitude });
            // La llamada a la API la gestiona el background task del componente padre
          }
        );
      } catch (_) {}
    };

    startTracking();
    return () => { if (watchId.current) watchId.current.remove(); };
  }, [localOrder.status]);

  // Sincronizar cuando el pedido llega actualizado desde el poll
  useEffect(() => {
    setLocalOrder((prev) => ({ ...prev, ...order }));
  }, [order.status, order.delivery_user_name, order.delivery_user_id]);

  // Distancia al destino en metros (null si no hay coords aún)
  const distToDestM = (() => {
    const dLat = driverLoc.lat;
    const dLng = driverLoc.lng;
    const oLat = localOrder.dest_lat ? parseFloat(localOrder.dest_lat) : null;
    const oLng = localOrder.dest_lng ? parseFloat(localOrder.dest_lng) : null;
    if (!dLat || !dLng || !oLat || !oLng) return null;
    return haversineMeters(dLat, dLng, oLat, oLng);
  })();

  const GEOFENCE_M = 300; // metros máximos para "llegué" y "entregado"
  const nearDest = distToDestM === null || distToDestM <= GEOFENCE_M;

  const distLabel = distToDestM !== null
    ? distToDestM >= 1000
      ? `${(distToDestM / 1000).toFixed(1)} km del destino`
      : `${Math.round(distToDestM)} m del destino`
    : null;

  const doAction = async (action) => {
    setLoading(true);
    try {
      let res;
      if (action === "accept") {
        res = await acceptDeliveryOrder(localOrder.id, user?.token);
      } else {
        res = await updateDeliveryStatus(localOrder.id, action, user?.token);
      }
      const nextStatus = {
        accept: "accepted",
        picked_up: "picked_up",
        on_the_way: "on_the_way",
        arrived: "arrived",
        delivered: "delivered",
      }[action] || localOrder.status;

      setLocalOrder((o) => ({ ...o, status: nextStatus }));

      if (nextStatus === "delivered") {
        setTimeout(() => onRefresh?.(), 500);
      } else {
        onRefresh?.();
      }
    } catch {}
    setLoading(false);
  };

  const confirmDelivered = () => {
    Alert.alert(
      "¿Confirmar entrega?",
      "Esto marcará el pedido como entregado y notificará al cliente.",
      [
        { text: "Cancelar", style: "cancel" },
        { text: "Sí, entregar", style: "default", onPress: () => doAction("delivered") },
      ]
    );
  };

  // Botones de acción según estado
  const renderActions = () => {
    if (localOrder.status === "pending") {
      return (
        <TouchableOpacity style={d.acceptBtn} onPress={() => doAction("accept")} disabled={loading}>
          {loading ? <ActivityIndicator color="#fff" size="small" /> : (
            <>
              <Ionicons name="checkmark-circle" size={20} color="#fff" />
              <Text style={d.acceptBtnText}>ACEPTAR PEDIDO</Text>
            </>
          )}
        </TouchableOpacity>
      );
    }
    if (localOrder.status === "accepted") {
      return (
        <TouchableOpacity style={[d.acceptBtn, { backgroundColor: BLUE }]} onPress={() => doAction("picked_up")} disabled={loading}>
          {loading ? <ActivityIndicator color="#fff" size="small" /> : (
            <>
              <Ionicons name="bag-check-outline" size={20} color="#fff" />
              <Text style={d.acceptBtnText}>PEDIDO RECOGIDO</Text>
            </>
          )}
        </TouchableOpacity>
      );
    }
    if (localOrder.status === "picked_up") {
      return (
        <TouchableOpacity style={[d.acceptBtn, { backgroundColor: BLUE }]} onPress={() => doAction("on_the_way")} disabled={loading}>
          {loading ? <ActivityIndicator color="#fff" size="small" /> : (
            <>
              <Ionicons name="navigate-outline" size={20} color="#fff" />
              <Text style={d.acceptBtnText}>SALIR A ENTREGAR</Text>
            </>
          )}
        </TouchableOpacity>
      );
    }
    if (localOrder.status === "on_the_way") {
      return (
        <View>
          {!nearDest && distLabel && (
            <View style={d.geoWarning}>
              <Ionicons name="navigate-outline" size={14} color={ORANGE} />
              <Text style={d.geoWarningText}>Todavía estás a {distLabel}</Text>
            </View>
          )}
          <TouchableOpacity
            style={[d.acceptBtn, { backgroundColor: nearDest ? ORANGE : "#aaa" }]}
            onPress={() => nearDest ? doAction("arrived") : null}
            disabled={loading || !nearDest}
          >
            {loading ? <ActivityIndicator color="#fff" size="small" /> : (
              <>
                <Ionicons name="home-outline" size={20} color="#fff" />
                <Text style={d.acceptBtnText}>
                  {nearDest ? "LLEGUÉ / ESTOY AFUERA" : "AÚN NO HAS LLEGADO"}
                </Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      );
    }
    if (localOrder.status === "arrived") {
      return (
        <TouchableOpacity style={[d.acceptBtn, { backgroundColor: GREEN }]} onPress={confirmDelivered} disabled={loading}>
          {loading ? <ActivityIndicator color="#fff" size="small" /> : (
            <>
              <Ionicons name="checkmark-done-circle" size={20} color="#fff" />
              <Text style={d.acceptBtnText}>MARCAR COMO ENTREGADO</Text>
            </>
          )}
        </TouchableOpacity>
      );
    }
    if (localOrder.status === "delivered") {
      return (
        <View style={[d.acceptBtn, { backgroundColor: GREEN }]}>
          <Ionicons name="checkmark-circle" size={20} color="#fff" />
          <Text style={d.acceptBtnText}>ENTREGADO ✓</Text>
        </View>
      );
    }
    return null;
  };

  // Timeline de estado
  const TIMELINE = [
    { key: "pending",    label: "Pedido recibido",   icon: "document-text-outline" },
    { key: "accepted",   label: "Aceptado",           icon: "hand-right-outline" },
    { key: "picked_up",  label: "Pedido recogido",    icon: "bag-check-outline" },
    { key: "on_the_way", label: "En camino",          icon: "navigate-outline" },
    { key: "arrived",    label: "Llegó / Afuera",     icon: "home-outline" },
    { key: "delivered",  label: "Entregado",          icon: "checkmark-circle-outline" },
  ];
  const statusOrder = ["pending", "accepted", "picked_up", "on_the_way", "arrived", "delivered"];
  const currentIdx = statusOrder.indexOf(localOrder.status);

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      {/* Header */}
      <View style={[d.detailHeader, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <TouchableOpacity style={[d.backBtn, { backgroundColor: t.iconBg }]} onPress={onBack}>
          <Ionicons name="arrow-back" size={20} color={t.text} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[d.detailOrderId, { color: t.text }]}>Pedido #{String(localOrder.id).padStart(6, "0")}</Text>
          <Text style={[d.detailTime, { color: t.textMuted }]}>{formatDate(localOrder.created_at)}</Text>
        </View>
        <View style={[d.badge, { backgroundColor: bgBadge }]}>
          <Ionicons name={st.icon} size={12} color={st.color} />
          <Text style={[d.badgeText, { color: st.color }]}>{st.label}</Text>
        </View>
      </View>

      {/* Mapa para el repartidor */}
      {["accepted", "picked_up", "on_the_way", "arrived"].includes(localOrder.status) &&
       localOrder.dest_lat && localOrder.dest_lng && (
        <DeliveryMap
          destLat={parseFloat(localOrder.dest_lat)}
          destLng={parseFloat(localOrder.dest_lng)}
          driverLat={driverLoc.lat}
          driverLng={driverLoc.lng}
          storeLat={localOrder.store_lat ? parseFloat(localOrder.store_lat) : null}
          storeLng={localOrder.store_lng ? parseFloat(localOrder.store_lng) : null}
          storeName={localOrder.store_name ?? null}
          storeAddress={localOrder.store_address ?? null}
          storeCity={localOrder.store_city ?? null}
          storePhone={localOrder.store_phone ?? null}
        />
      )}

      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ padding: 16, paddingBottom: 100 }}>

        {/* Timeline */}
        <View style={[d.card, { backgroundColor: t.card }]}>
          <Text style={d.cardTitle}>ESTADO DEL PEDIDO</Text>
          {TIMELINE.map((step, i) => {
            const done = i <= currentIdx;
            const active = i === currentIdx;
            return (
              <View key={step.key} style={d.timelineRow}>
                <View style={{ alignItems: "center", width: 32 }}>
                  <View style={[d.timelineDot, { backgroundColor: t.iconBg }, done && d.timelineDotDone, active && d.timelineDotActive]}>
                    <Ionicons name={step.icon} size={14} color={done ? "#fff" : t.textMuted} />
                  </View>
                  {i < TIMELINE.length - 1 && (
                    <View style={[d.timelineLine, { backgroundColor: t.divider }, done && i < currentIdx && d.timelineLineDone]} />
                  )}
                </View>
                <Text style={[d.timelineLabel, { color: t.textMuted }, active && [d.timelineLabelActive, { color: t.text }], done && i < currentIdx && { color: GREEN }]}>
                  {step.label}
                </Text>
              </View>
            );
          })}
        </View>

        {/* Datos del cliente y dirección */}
        <View style={[d.card, { backgroundColor: t.card }]}>
          <Text style={d.cardTitle}>CLIENTE Y ENTREGA</Text>
          <View style={[d.infoRow, { borderBottomColor: t.divider }]}>
            <View style={[d.infoIcon, { backgroundColor: t.iconBgRed }]}><Ionicons name="person-outline" size={17} color={RED} /></View>
            <View style={{ flex: 1 }}>
              <Text style={d.infoLabel}>Cliente</Text>
              <Text style={[d.infoValue, { color: t.text }]}>{localOrder.customer_name || "No disponible"}</Text>
              {localOrder.customer_email && <Text style={[d.infoSub, { color: t.textMuted }]}>{localOrder.customer_email}</Text>}
            </View>
          </View>
          {localOrder.store_name && (
            <View style={[d.infoRow, { borderBottomColor: t.divider }]}>
              <View style={[d.infoIcon, { backgroundColor: t.iconBgRed }]}><Ionicons name="storefront-outline" size={17} color={RED} /></View>
              <View style={{ flex: 1 }}>
                <Text style={d.infoLabel}>Sucursal origen</Text>
                <Text style={[d.infoValue, { color: RED }]}>{localOrder.store_name}</Text>
              </View>
            </View>
          )}
          {localOrder.delivery_user_name && (
            <View style={[d.infoRow, { borderBottomColor: t.divider }]}>
              <View style={[d.infoIcon, { backgroundColor: t.iconBgRed }]}><Ionicons name="bicycle-outline" size={17} color={BLUE} /></View>
              <View style={{ flex: 1 }}>
                <Text style={d.infoLabel}>Repartidor asignado</Text>
                <Text style={[d.infoValue, { color: BLUE }]}>{localOrder.delivery_user_name}</Text>
              </View>
            </View>
          )}
          <View style={[d.infoRow, { borderBottomColor: t.divider }]}>
            <View style={[d.infoIcon, { backgroundColor: t.iconBgRed }]}><Ionicons name="location-outline" size={17} color={RED} /></View>
            <View style={{ flex: 1 }}>
              <Text style={d.infoLabel}>Dirección de entrega</Text>
              <Text style={[d.infoValue, { color: t.text }]}>{localOrder.address || "No especificada"}</Text>
            </View>
          </View>
          <View style={[d.infoRow, { borderBottomColor: t.divider }]}>
            <View style={[d.infoIcon, { backgroundColor: t.iconBgRed }]}><Ionicons name="card-outline" size={17} color={RED} /></View>
            <View style={{ flex: 1 }}>
              <Text style={d.infoLabel}>Método de pago</Text>
              <Text style={[d.infoValue, { color: t.text }]}>{localOrder.payment_method || "—"}</Text>
              <View style={[d.payBadge, { backgroundColor: localOrder.payment_status === "paid" ? (isDark ? "#153a15" : "#f0fdf4") : (isDark ? "#3a2a0a" : "#fffbeb") }]}>
                <Ionicons name={localOrder.payment_status === "paid" ? "checkmark-circle" : "time"} size={11}
                  color={localOrder.payment_status === "paid" ? GREEN : ORANGE} />
                <Text style={{ fontSize: 10, fontWeight: "700", color: localOrder.payment_status === "paid" ? GREEN : ORANGE }}>
                  {localOrder.payment_status === "paid" ? "Pagado" : "Pago al entregar"}
                </Text>
              </View>
            </View>
          </View>
        </View>

        {/* Productos */}
        {Array.isArray(localOrder.items) && localOrder.items.length > 0 && (
          <View style={[d.card, { backgroundColor: t.card }]}>
            <Text style={d.cardTitle}>PRODUCTOS ({localOrder.items.length})</Text>
            {localOrder.items.map((item, i) => (
              <View key={i} style={[d.productRow, i < localOrder.items.length - 1 && [d.productDivider, { borderBottomColor: t.divider }]]}>
                <View style={[d.productQtyBadge, { backgroundColor: t.iconBg }]}>
                  <Text style={[d.productQtyText, { color: t.textSub }]}>x{item.qty}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[d.productName, { color: t.text }]}>{item.product_name}</Text>
                  <Text style={[d.productPrice, { color: t.textMuted }]}>${parseFloat(item.price || 0).toFixed(2)} c/u</Text>
                </View>
                <Text style={[d.productTotal, { color: t.text }]}>${(parseFloat(item.price || 0) * item.qty).toFixed(2)}</Text>
              </View>
            ))}
            <View style={[d.totalRow, { borderTopColor: t.divider }]}>
              <Text style={d.totalLabel}>TOTAL</Text>
              <Text style={[d.totalValue, { color: t.text }]}>${parseFloat(localOrder.total || 0).toFixed(2)}</Text>
            </View>
          </View>
        )}

        {/* Notas */}
        {localOrder.notes ? (
          <View style={[d.card, { backgroundColor: t.card }]}>
            <Text style={d.cardTitle}>NOTAS DEL CLIENTE</Text>
            <Text style={{ fontSize: 13, color: t.textSub, lineHeight: 19 }}>{localOrder.notes}</Text>
          </View>
        ) : null}
      </ScrollView>

      {/* Acción flotante */}
      <View style={[d.actionBar, { backgroundColor: t.card, borderTopColor: t.border }]}>
        {renderActions()}
      </View>
    </View>
  );
}

// ─── BANNER DE NUEVO PEDIDO ───────────────────────────────────────────────────
function NewOrderBanner({ order, onView, onDismiss }) {
  const slideY  = useRef(new Animated.Value(-200)).current;
  const opacity = useRef(new Animated.Value(0)).current;
  const timerRef = useRef(null);

  useEffect(() => {
    // Slide-in
    Animated.parallel([
      Animated.spring(slideY,  { toValue: 0,   useNativeDriver: true, tension: 80, friction: 10 }),
      Animated.timing(opacity, { toValue: 1,   duration: 250, useNativeDriver: true }),
    ]).start();

    // Auto-dismiss 12 s
    timerRef.current = setTimeout(() => dismiss(), 12000);
    return () => clearTimeout(timerRef.current);
  }, []);

  const dismiss = () => {
    Animated.parallel([
      Animated.timing(slideY,  { toValue: -200, duration: 300, useNativeDriver: true }),
      Animated.timing(opacity, { toValue: 0,    duration: 300, useNativeDriver: true }),
    ]).start(() => onDismiss?.());
  };

  const handleView = () => {
    clearTimeout(timerRef.current);
    dismiss();
    onView?.(order);
  };

  if (!order) return null;

  return (
    <Animated.View style={[d.bannerWrap, { transform: [{ translateY: slideY }], opacity }]}>
      <View style={d.bannerInner}>
        {/* Icono pulsante */}
        <View style={d.bannerIcon}>
          <Ionicons name="bicycle" size={26} color="#fff" />
        </View>

        {/* Info */}
        <View style={{ flex: 1, marginHorizontal: 10 }}>
          <Text style={d.bannerTitle}>🛵 ¡Nuevo pedido asignado!</Text>
          <Text style={d.bannerOrderId}>#{String(order.id).padStart(6, "0")}</Text>
          <Text style={d.bannerAddr} numberOfLines={1}>
            {order.address || "Sin dirección"}
          </Text>
          <View style={d.bannerMeta}>
            <Ionicons name="cube-outline" size={12} color="rgba(255,255,255,0.8)" />
            <Text style={d.bannerMetaText}>
              {order.items_count ?? order.items?.length ?? 0} productos
            </Text>
            <Text style={d.bannerDot}>·</Text>
            <Text style={d.bannerTotal}>${parseFloat(order.total || 0).toFixed(2)}</Text>
          </View>
        </View>

        {/* Botón cerrar */}
        <TouchableOpacity onPress={dismiss} style={d.bannerClose}>
          <Ionicons name="close" size={18} color="rgba(255,255,255,0.7)" />
        </TouchableOpacity>
      </View>

      {/* Botón Ver pedido */}
      <TouchableOpacity style={d.bannerViewBtn} onPress={handleView} activeOpacity={0.85}>
        <Text style={d.bannerViewText}>VER PEDIDO</Text>
        <Ionicons name="arrow-forward" size={16} color={RED} />
      </TouchableOpacity>
    </Animated.View>
  );
}

// ─── PANTALLA PRINCIPAL DEL REPARTIDOR ───────────────────────────────────────
export default function DeliveryScreen() {
  const { user, signOut } = useAuth();
  const { t, isDark } = useTheme();
  const { addNotification, unreadCount } = useNotifications();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 1024;

  const [availableOrders, setAvailableOrders] = useState([]);
  const [myOrders, setMyOrders] = useState([]);
  const [historyOrders, setHistoryOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState(null);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [activeFilter, setActiveFilter] = useState("active"); // "active" | "available" | "done"
  const [showNotifPanel, setShowNotifPanel] = useState(false);

  const [newOrderBanner, setNewOrderBanner] = useState(null);

  const intervalRef = useRef(null);
  const myOrdersRef = useRef([]);
  const prevAvailableCountRef = useRef(-1); // -1 = primera carga, no notificar
  const prevMyOrdersCountRef = useRef(-1);
  const prevOrdersMapRef = useRef({}); // { [id]: status } para detectar cancelaciones
  const soundRef = useRef(null);
  const fetchOrdersRef = useRef(null); // ref para llamar fetchOrders desde listeners

  useEffect(() => {
    if (Platform.OS !== "web") {
      // La app muestra su propio banner rojo; fuera de la app FCM lo maneja
      Notifications.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowBanner: false,
          shouldShowList:   false,
          shouldPlaySound:  true,
          shouldSetBadge:   false,
        }),
      });

      // Canal Android (debe existir antes de enviar cualquier notificación)
      if (Platform.OS === "android") {
        Notifications.setNotificationChannelAsync("pedidos", {
          name: "Pedidos TPN",
          importance: Notifications.AndroidImportance.MAX,
          sound: "default",
          vibrationPattern: [0, 250, 150, 250],
          lightColor: "#e6192e",
          enableLights: true,
          enableVibrate: true,
          bypassDnd: true,
          lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
          showBadge: true,
        });
      }

      // Pedir permiso y registrar token FCM nativo con el servidor
      Notifications.requestPermissionsAsync().then(({ status }) => {
        if (status !== "granted") return;
        // getDevicePushTokenAsync devuelve el token FCM directo (funciona aunque la app esté cerrada)
        Notifications.getDevicePushTokenAsync().then(({ data: pushToken }) => {
          if (pushToken && user?.token) {
            registerPushToken(pushToken, user.token).catch(() => {});
          }
        }).catch(() => {});
      });

      // Sonido interno (cuando app está abierta)
      setAudioModeAsync({ playsInSilentModeIOS: true, staysActiveInBackground: false }).catch(() => {});
      try {
        soundRef.current = createAudioPlayer(require("../assets/sounds/notification.wav"));
      } catch (_) {}

      // Al tocar la notificación en bandeja → abrir pestaña correcta
      const tapSub = Notifications.addNotificationResponseReceivedListener((response) => {
        const tab = response.notification.request.content.data?.tab;
        if (tab) setActiveFilter(tab);
      });

      // Notificación en foreground → vibrar + mostrar banner inmediatamente (sin esperar el poll)
      const fgSub = Notifications.addNotificationReceivedListener((notification) => {
        const data = notification.request.content.data || {};
        if (data.type === "new_order" || data.tab === "active" || data.tab === "available") {
          Vibration.vibrate([0, 400, 200, 400]);
          // Refrescar pedidos al instante para que aparezca el banner rojo
          fetchOrdersRef.current?.();
        }
      });

      return () => { soundRef.current?.remove(); tapSub.remove(); fgSub.remove(); };
    } else {
      if ("Notification" in window) Notification.requestPermission();
    }
  }, [user?.token]);

  const showNewOrderNotification = useCallback((msg, tab) => {
    if (tab) setActiveFilter(tab);

    if (Platform.OS !== "web") {
      // Sonido interno (nativo)
      if (soundRef.current) {
        try { soundRef.current.seekTo(0); soundRef.current.play(); } catch (_) {}
      }
      // Notificación del sistema — sale en bandeja aunque app esté minimizada
      Notifications.scheduleNotificationAsync({
        content: { title: "🛵 Todo Pal Negocio", body: msg, sound: "default", data: { tab } },
        trigger: null,
      }).catch(() => {});
    } else {
      // Web: notificación del browser
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("🛵 Todo Pal Negocio", { body: msg, icon: "/favicon.png" });
      }
    }
  }, []);

  const fetchOrders = useCallback(async () => {
    if (!user?.token) return;
    try {
      const [resMine, resHist] = await Promise.all([
        getMyDeliveryOrders(user.token),
        getDeliveryHistory(user.token),
      ]);

      if (!resMine?.success && !resHist?.success) {
        setApiError("Error al conectar con el servidor");
      } else {
        setApiError(null);
      }

      if (resMine?.success) {
        const newMine = resMine.data || [];
        const prevMine = prevMyOrdersCountRef.current;
        const prevMap  = prevOrdersMapRef.current;

        // ── Detectar pedidos cancelados ──────────────────────────────────────
        if (Object.keys(prevMap).length > 0) {
          const newMap = {};
          for (const o of newMine) newMap[o.id] = o.status;
          for (const [id, prevStatus] of Object.entries(prevMap)) {
            const activeStatuses = ["pending", "accepted", "picked_up", "on_the_way", "arrived"];
            if (!activeStatuses.includes(prevStatus)) continue;
            const newStatus = newMap[id];
            if (!newStatus || newStatus === "cancelled") {
              const label = `#${String(id).padStart(6, "0")}`;
              addNotification({
                title: "❌ Pedido cancelado",
                body: `El pedido ${label} fue cancelado.`,
                type: "cancelled",
                orderId: Number(id),
              });
              showNewOrderNotification(`Pedido ${label} cancelado`, "active");
              if (Platform.OS !== "web") {
                Vibration.vibrate([0, 500, 150, 500, 150, 500]);
                if (Haptics) {
                  try { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error); } catch (_) {}
                }
              }
            }
          }
        }

        // Actualizar mapa de estados para el siguiente poll
        const updatedMap = {};
        for (const o of newMine) updatedMap[o.id] = o.status;
        prevOrdersMapRef.current = updatedMap;

        if (prevMine >= 0 && newMine.length > prevMine) {
          showNewOrderNotification("¡Te asignaron un pedido nuevo!", "active");
          const newest = newMine[0];
          if (newest) {
            setNewOrderBanner(newest);
            if (Platform.OS !== "web") Vibration.vibrate([0, 400, 200, 400]);
          }
        }
        prevMyOrdersCountRef.current = newMine.length;
        myOrdersRef.current = newMine;
        setMyOrders(newMine);
        setSelectedOrder((sel) => sel ? (newMine.find(o => o.id === sel.id) || sel) : null);
      }
      if (resHist?.success) setHistoryOrders(resHist.data || []);
    } catch (e) {
      console.error("Error fetching orders:", e);
      setApiError("Error de conexión: " + (e?.message || "intenta de nuevo"));
    }
    setLoading(false);
  }, [user?.token, showNewOrderNotification, addNotification]);

  // Mantener ref actualizada para llamarla desde listeners de notificación
  useEffect(() => { fetchOrdersRef.current = fetchOrders; }, [fetchOrders]);

  // Calcular ganancias del día (pedidos entregados hoy)
  const today = new Date().toDateString();
  const todayOrders = historyOrders.filter(o => new Date(o.updated_at).toDateString() === today);
  const dailyEarnings = todayOrders.reduce((sum, o) => sum + parseFloat(o.total || 0), 0);

  // ─── Gestión del tracking en background (nativo) ───────────────────────────
  const startBgTracking = useCallback(async (token) => {
    if (Platform.OS === "web" || !TaskManager || !Location.startLocationUpdatesAsync) return;
    try {
      const fg = await Location.requestForegroundPermissionsAsync();
      if (fg.status !== "granted") return;
      const bg = await Location.requestBackgroundPermissionsAsync();
      if (bg.status !== "granted") return;

      await AsyncStorage.setItem("delivery_bg_token", token);

      const alreadyRunning = await Location.hasStartedLocationUpdatesAsync(BG_LOCATION_TASK).catch(() => false);
      if (!alreadyRunning) {
        await Location.startLocationUpdatesAsync(BG_LOCATION_TASK, {
          accuracy: Location.Accuracy.High,
          distanceInterval: 10,
          timeInterval: 5000,
          showsBackgroundLocationIndicator: true,
          foregroundService: {
            notificationTitle: "TPN — Entrega en curso",
            notificationBody: "Tu ubicación se está compartiendo con el cliente.",
            notificationColor: "#e6192e",
          },
        });
      }
    } catch (_) {}
  }, []);

  const stopBgTracking = useCallback(async () => {
    if (Platform.OS === "web" || !TaskManager || !Location.stopLocationUpdatesAsync) return;
    try {
      await AsyncStorage.removeItem("delivery_bg_token");
      const running = await Location.hasStartedLocationUpdatesAsync(BG_LOCATION_TASK).catch(() => false);
      if (running) await Location.stopLocationUpdatesAsync(BG_LOCATION_TASK);
    } catch (_) {}
  }, []);

  // Web fallback: polling simple con geolocation API
  const webLocationIntervalRef = useRef(null);
  const startWebTracking = useCallback((token) => {
    if (Platform.OS !== "web" || !navigator.geolocation) return;
    if (webLocationIntervalRef.current) clearInterval(webLocationIntervalRef.current);
    webLocationIntervalRef.current = setInterval(() => {
      navigator.geolocation.getCurrentPosition((pos) => {
        updateDeliveryLocation(pos.coords.latitude, pos.coords.longitude, token).catch(() => {});
      });
    }, 8000);
  }, []);

  const stopWebTracking = useCallback(() => {
    if (webLocationIntervalRef.current) {
      clearInterval(webLocationIntervalRef.current);
      webLocationIntervalRef.current = null;
    }
  }, []);

  // Arrancar/detener tracking según si hay pedidos activos
  const activeStatuses = ["accepted", "picked_up", "on_the_way", "arrived"];
  useEffect(() => {
    const hasActive = myOrders.some(o => activeStatuses.includes(o.status));
    if (hasActive && user?.token) {
      if (Platform.OS === "web") startWebTracking(user.token);
      else startBgTracking(user.token);
    } else {
      if (Platform.OS === "web") stopWebTracking();
      else stopBgTracking();
    }
  }, [myOrders, user?.token]);

  useEffect(() => {
    setLoading(true);
    setActiveFilter("active");
    prevMyOrdersCountRef.current = -1;
    fetchOrders();
    intervalRef.current = setInterval(fetchOrders, 10000);
    return () => {
      clearInterval(intervalRef.current);
      stopBgTracking();
      stopWebTracking();
    };
  }, [user?.token, fetchOrders]);

  const displayList = {
    active: myOrders,
    done: historyOrders
  }[activeFilter] || [];

  const newCount = availableOrders.length;

  // ── Desktop: sidebar + detail ─────────────────────────────────────────────
  if (isDesktop) {
    return (
      <View style={{ flex: 1, backgroundColor: t.bg }}>
        {newOrderBanner && (
          <NewOrderBanner
            order={newOrderBanner}
            onView={(o) => { setSelectedOrder(o); setActiveFilter("active"); }}
            onDismiss={() => setNewOrderBanner(null)}
          />
        )}
        <View style={d.desktopBody}>
          {/* Sidebar */}
          <View style={[d.desktopSidebar, { backgroundColor: t.card, borderRightColor: t.border }]}>
            <View style={[d.sidebarHeader, { borderBottomColor: t.border }]}>
              <View style={d.driverBadge}>
                <Ionicons name="bicycle" size={18} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[d.driverName, { color: t.text }]} numberOfLines={1}>{user?.name || "Repartidor"}</Text>
                {user?.store_name ? (
                  <View style={d.storeBadge}>
                    <Ionicons name="storefront" size={10} color={RED} />
                    <Text style={d.storeBadgeText}>{user.store_name}</Text>
                  </View>
                ) : (
                  <Text style={d.driverRole}>MODO ENTREGA</Text>
                )}
              </View>
              <TouchableOpacity onPress={fetchOrders} style={[d.refreshBtn, { backgroundColor: t.iconBg }]}>
                <Ionicons name="refresh-outline" size={18} color={t.textMuted} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setShowNotifPanel(true)} style={[d.refreshBtn, { marginLeft: 4, backgroundColor: t.iconBg }]}>
                <View>
                  <Ionicons name="notifications-outline" size={18} color={t.textMuted} />
                  {unreadCount > 0 && (
                    <View style={d.notifBadge}>
                      <Text style={d.notifBadgeText}>{unreadCount > 9 ? "9+" : String(unreadCount)}</Text>
                    </View>
                  )}
                </View>
              </TouchableOpacity>
            </View>

            {/* Filtros */}
            <View style={d.filterRow}>
              <TouchableOpacity style={[d.filterBtn, { backgroundColor: t.iconBg }, activeFilter === "active" && [d.filterBtnActive, { backgroundColor: t.iconBgRed }]]} onPress={() => setActiveFilter("active")}>
                <Text style={[d.filterBtnText, { color: t.textMuted }, activeFilter === "active" && d.filterBtnTextActive]}>
                  Activos {myOrders.length > 0 ? `(${myOrders.length})` : ""}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity style={[d.filterBtn, { backgroundColor: t.iconBg }, activeFilter === "done" && [d.filterBtnActive, { backgroundColor: t.iconBgRed }]]} onPress={() => setActiveFilter("done")}>
                <Text style={[d.filterBtnText, { color: t.textMuted }, activeFilter === "done" && d.filterBtnTextActive]}>Historial</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[d.filterBtn, { backgroundColor: t.iconBg }, activeFilter === "stats" && [d.filterBtnActive, { backgroundColor: t.iconBgRed }]]} onPress={() => setActiveFilter("stats")}>
                <Text style={[d.filterBtnText, { color: t.textMuted }, activeFilter === "stats" && d.filterBtnTextActive]}>Ganancias</Text>
              </TouchableOpacity>
            </View>

            <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
              {apiError && (
                <View style={d.errorBanner}>
                  <Ionicons name="warning-outline" size={14} color="#92400e" />
                  <Text style={[d.errorBannerText, { flex: 1 }]} numberOfLines={2}>{apiError}</Text>
                  <TouchableOpacity onPress={fetchOrders} style={d.errorRetryBtn}>
                    <Text style={d.errorRetryText}>Reintentar</Text>
                  </TouchableOpacity>
                </View>
              )}
              {loading && <ActivityIndicator color={RED} style={{ marginTop: 20 }} />}
              {!loading && displayList.length === 0 && !apiError && (
                <View style={d.emptyList}>
                  <Ionicons name={
                    activeFilter === "available" ? "time-outline" : 
                    activeFilter === "active" ? "bicycle-outline" : "checkmark-circle-outline"
                  } size={40} color={t.border} />
                  <Text style={[d.emptyListText, { color: t.textMuted }]}>
                    {activeFilter === "available" ? "No hay pedidos nuevos" : 
                     activeFilter === "active" ? "No tienes pedidos asignados" : "Sin historial de entregas"}
                  </Text>
                </View>
              )}
              {displayList.map((order) => (
                <OrderListCard
                  key={order.id}
                  order={order}
                  onPress={() => setSelectedOrder(order)}
                  isActive={selectedOrder?.id === order.id}
                />
              ))}
            </ScrollView>

            <TouchableOpacity style={[d.signOutBtn, { borderTopColor: t.border }]} onPress={signOut}>
              <Ionicons name="log-out-outline" size={16} color={RED} />
              <Text style={d.signOutText}>Cerrar sesión</Text>
            </TouchableOpacity>
          </View>

          {/* Panel principal */}
          <View style={{ flex: 1 }}>
            {selectedOrder ? (
              <OrderDetail
                order={selectedOrder}
                onBack={() => setSelectedOrder(null)}
                onRefresh={fetchOrders}
              />
            ) : (
              <View style={d.desktopPlaceholder}>
                <Ionicons name="bicycle-outline" size={64} color={t.border} />
                <Text style={[d.desktopPlaceholderTitle, { color: t.text }]}>
                  {newCount > 0 ? `${newCount} pedido${newCount > 1 ? "s" : ""} disponible${newCount > 1 ? "s" : ""}` : "Sin pedidos nuevos"}
                </Text>
                <Text style={[d.desktopPlaceholderSub, { color: t.textMuted }]}>
                  {newCount > 0 ? "Selecciona un pedido para aceptarlo" : "Los nuevos pedidos aparecerán aquí automáticamente"}
                </Text>
                {loading && <ActivityIndicator color={RED} style={{ marginTop: 16 }} />}
              </View>
            )}
          </View>
        </View>
        <NotificationsPanel
          visible={showNotifPanel}
          onClose={() => setShowNotifPanel(false)}
          onOrderPress={() => setShowNotifPanel(false)}
        />
      </View>
    );
  }

  // ── Mobile layout ─────────────────────────────────────────────────────────
  if (selectedOrder) {
    return (
      <View style={[d.mobileWrapper, { backgroundColor: t.bg }]}>
        <OrderDetail order={selectedOrder} onBack={() => setSelectedOrder(null)} onRefresh={fetchOrders} />
        {newOrderBanner && (
          <NewOrderBanner
            order={newOrderBanner}
            onView={(o) => { setSelectedOrder(o); setActiveFilter("active"); }}
            onDismiss={() => setNewOrderBanner(null)}
          />
        )}
      </View>
    );
  }

  return (
    <View style={[d.mobileWrapper, { backgroundColor: t.bg }]}>

      {/* Header */}
      <View style={[d.mobileHeader, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <View style={d.driverBadge}>
          <Ionicons name="bicycle" size={18} color="#fff" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[d.driverName, { color: t.text }]}>{user?.name || "Repartidor"}</Text>
          {user?.store_name ? (
            <View style={d.storeBadge}>
              <Ionicons name="storefront" size={10} color={RED} />
              <Text style={d.storeBadgeText}>{user.store_name}</Text>
            </View>
          ) : (
            <Text style={d.driverRole}>MODO ENTREGA</Text>
          )}
        </View>
        <TouchableOpacity onPress={fetchOrders} style={[d.refreshBtn, { backgroundColor: t.iconBg }]}>
          <Ionicons name="refresh-outline" size={20} color={t.textMuted} />
        </TouchableOpacity>
        {/* Campana de notificaciones */}
        <TouchableOpacity onPress={() => setShowNotifPanel(true)} style={[d.refreshBtn, { marginLeft: 4, backgroundColor: t.iconBg }]}>
          <View>
            <Ionicons name="notifications-outline" size={20} color={t.textMuted} />
            {unreadCount > 0 && (
              <View style={d.notifBadge}>
                <Text style={d.notifBadgeText}>{unreadCount > 9 ? "9+" : String(unreadCount)}</Text>
              </View>
            )}
          </View>
        </TouchableOpacity>
        <TouchableOpacity onPress={signOut} style={[d.refreshBtn, { marginLeft: 4, backgroundColor: t.iconBgRed }]}>
          <Ionicons name="log-out-outline" size={20} color={RED} />
        </TouchableOpacity>
      </View>

      {/* Stats */}
      <View style={[d.statsRow, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <View style={d.statItem}>
          <Text style={[d.statNum, { color: t.text }]}>{myOrders.length}</Text>
          <Text style={[d.statLabel, { color: t.textMuted }]}>Activos</Text>
        </View>
        <View style={[d.statDivider, { backgroundColor: t.divider }]} />
        <View style={d.statItem}>
          <Text style={[d.statNum, { color: GREEN }]}>${Math.round(dailyEarnings)}</Text>
          <Text style={[d.statLabel, { color: t.textMuted }]}>Hoy</Text>
        </View>
        <View style={[d.statDivider, { backgroundColor: t.divider }]} />
        <View style={d.statItem}>
          <Text style={[d.statNum, { color: RED }]}>{todayOrders.length}</Text>
          <Text style={[d.statLabel, { color: t.textMuted }]}>Entregas</Text>
        </View>
      </View>

      {/* Filtros */}
      <View style={d.filterRow}>
        <TouchableOpacity style={[d.filterBtn, { backgroundColor: t.iconBg }, activeFilter === "active" && [d.filterBtnActive, { backgroundColor: t.iconBgRed }]]} onPress={() => setActiveFilter("active")}>
          <Text style={[d.filterBtnText, { color: t.textMuted }, activeFilter === "active" && d.filterBtnTextActive]}>
            ACTIVOS {myOrders.length > 0 ? `(${myOrders.length})` : ""}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity style={[d.filterBtn, { backgroundColor: t.iconBg }, activeFilter === "done" && [d.filterBtnActive, { backgroundColor: t.iconBgRed }]]} onPress={() => setActiveFilter("done")}>
          <Text style={[d.filterBtnText, { color: t.textMuted }, activeFilter === "done" && d.filterBtnTextActive]}>HISTORIAL</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[d.filterBtn, { backgroundColor: t.iconBg }, activeFilter === "stats" && [d.filterBtnActive, { backgroundColor: t.iconBgRed }]]} onPress={() => setActiveFilter("stats")}>
          <Text style={[d.filterBtnText, { color: t.textMuted }, activeFilter === "stats" && d.filterBtnTextActive]}>GANANCIAS</Text>
        </TouchableOpacity>
      </View>

      {apiError && (
        <View style={d.errorBanner}>
          <Ionicons name="warning-outline" size={16} color="#92400e" />
          <Text style={d.errorBannerText}>{apiError}</Text>
          <TouchableOpacity onPress={fetchOrders} style={d.errorRetryBtn}>
            <Text style={d.errorRetryText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      )}

      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ padding: 14 }}>
        {loading && <ActivityIndicator color={RED} style={{ marginTop: 20 }} />}
        
        {activeFilter === "stats" && !loading && (
          <View style={{ paddingBottom: 20 }}>
            {/* Tarjeta Principal de Ganancias */}
            <View style={d.premiumEarningsCard}>
              <View style={d.earningsHeader}>
                <Ionicons name="wallet" size={18} color="rgba(255,255,255,0.7)" />
                <Text style={d.earningsTitle}>GANANCIA TOTAL DE HOY</Text>
              </View>
              <Text style={d.earningsValue}>${dailyEarnings.toFixed(2)}</Text>
              
              <View style={d.earningsMetrics}>
                <View style={d.metricItem}>
                  <Text style={d.metricVal}>{todayOrders.length}</Text>
                  <Text style={d.metricLabel}>Entregas</Text>
                </View>
                <View style={d.metricDivider} />
                <View style={d.metricItem}>
                  <Text style={d.metricVal}>100%</Text>
                  <Text style={d.metricLabel}>Efectividad</Text>
                </View>
              </View>
            </View>

            {/* Detalles Adicionales */}
            <View style={[d.modernSection, { backgroundColor: t.card }]}>
              <Text style={d.modernSectionTitle}>MI ACTIVIDAD</Text>
              
              <View style={[d.modernRow, { borderBottomColor: t.divider }]}>
                <View style={[d.modernIcon, { backgroundColor: t.iconBgRed }]}>
                  <Ionicons name="storefront" size={20} color={RED} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={d.modernRowLabel}>Sucursal Asignada</Text>
                  <Text style={[d.modernRowVal, { color: t.text }]}>{user?.store_name || "General / Central"}</Text>
                </View>
                <Ionicons name="chevron-forward" size={14} color={t.border} />
              </View>

              <View style={[d.modernRow, { borderBottomColor: t.divider }]}>
                <View style={[d.modernIcon, { backgroundColor: isDark ? "#153a15" : "#f0fdf4" }]}>
                  <Ionicons name="calendar" size={20} color={GREEN} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={d.modernRowLabel}>Histórico Total</Text>
                  <Text style={[d.modernRowVal, { color: t.text }]}>{historyOrders.length} pedidos entregados</Text>
                </View>
                <Ionicons name="chevron-forward" size={14} color={t.border} />
              </View>

              <View style={[d.modernRow, { borderBottomColor: t.divider }]}>
                <View style={[d.modernIcon, { backgroundColor: isDark ? "#3a2a0a" : "#fffbeb" }]}>
                  <Ionicons name="star" size={20} color={ORANGE} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={d.modernRowLabel}>Tu Calificación</Text>
                  <Text style={[d.modernRowVal, { color: t.text }]}>
                    {user?.avg_rating ? `${user.avg_rating} (${user.total_ratings} votos)` : "Sin calificaciones aún"}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={14} color={t.border} />
              </View>
            </View>

            <TouchableOpacity style={d.refreshStatsBtn} onPress={fetchOrders}>
              <Ionicons name="refresh" size={16} color={t.textMuted} />
              <Text style={[d.refreshStatsText, { color: t.textMuted }]}>ACTUALIZAR RESUMEN</Text>
            </TouchableOpacity>
          </View>
        )}

        {!loading && activeFilter !== "stats" && displayList.length === 0 && !apiError && (
          <View style={d.emptyList}>
            <Ionicons name={
              activeFilter === "available" ? "time-outline" :
              activeFilter === "active" ? "bicycle-outline" : "checkmark-circle-outline"
            } size={48} color={t.border} />
            <Text style={[d.emptyListText, { color: t.textMuted }]}>
              {activeFilter === "available" ? "No hay pedidos nuevos por ahora" :
               activeFilter === "active" ? "No tienes pedidos asignados" : "Sin historial de pedidos"}
            </Text>
            <Text style={{ fontSize: 12, color: t.textMuted, textAlign: "center" }}>Desliza hacia abajo para actualizar</Text>
          </View>
        )}
        {displayList.map((order) => (
          <OrderListCard key={order.id} order={order} onPress={() => setSelectedOrder(order)} />
        ))}
        <View style={{ height: 40 }} />
      </ScrollView>

      {newOrderBanner && (
        <NewOrderBanner
          order={newOrderBanner}
          onView={(o) => { setSelectedOrder(o); setActiveFilter("active"); }}
          onDismiss={() => setNewOrderBanner(null)}
        />
      )}
      <NotificationsPanel
        visible={showNotifPanel}
        onClose={() => setShowNotifPanel(false)}
        onOrderPress={() => setShowNotifPanel(false)}
      />
    </View>
  );
}


// ─── DEMO DATA (mientras el endpoint no esté listo) ───────────────────────────
const DEMO_ORDERS = [
  {
    id: 100042,
    status: "pending",
    created_at: new Date().toISOString(),
    address: "Av. Insurgentes Sur 1234, Col. Del Valle, CDMX",
    customer_name: "María González",
    customer_email: "maria@correo.com",
    payment_method: "Tarjeta VISA •••• 4242",
    payment_status: "paid",
    total: 340.50,
    items_count: 3,
    items: [
      { product_name: "Aceite Vegetal 1L", qty: 2, price: 45 },
      { product_name: "Leche Entera 1L",   qty: 3, price: 22 },
      { product_name: "Pan Integral",       qty: 1, price: 38 },
    ],
    notes: "Tocar timbre 2 veces",
  },
  {
    id: 100041,
    status: "on_the_way",
    created_at: new Date(Date.now() - 1800000).toISOString(),
    address: "Calle Morelos 56, Col. Centro, CDMX",
    customer_name: "Carlos Ramírez",
    customer_email: "carlos@correo.com",
    payment_method: "Efectivo al entregar",
    payment_status: "pending",
    total: 185.00,
    items_count: 2,
    items: [
      { product_name: "Agua Purificada 20L", qty: 1, price: 120 },
      { product_name: "Detergente 1Kg",      qty: 1, price: 65 },
    ],
    notes: "",
  },
];

// ─── ESTILOS ──────────────────────────────────────────────────────────────────
const d = StyleSheet.create({
  mobileWrapper: { flex: 1, backgroundColor: "#f5f5f5", paddingTop: Platform.OS === "ios" ? 54 : 44 },
  mobileHeader: {
    backgroundColor: "#fff", paddingHorizontal: 16, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", gap: 12,
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  driverBadge: { width: 38, height: 38, borderRadius: 10, backgroundColor: RED, justifyContent: "center", alignItems: "center" },
  driverName: { fontSize: 14, fontWeight: "800", color: "#111" },
  driverRole: { fontSize: 9, fontWeight: "800", color: RED, letterSpacing: 1 },
  storeBadge: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 },
  storeBadgeText: { fontSize: 10, fontWeight: "700", color: RED },
  listCardStore: { flexDirection: "row", alignItems: "center", gap: 4, marginBottom: 4 },
  storeNameText: { fontSize: 11, fontWeight: "700", color: RED },
  refreshBtn: { width: 36, height: 36, borderRadius: 10, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  notifBadge: {
    position: "absolute", top: -5, right: -6,
    minWidth: 16, height: 16, borderRadius: 8,
    backgroundColor: RED, justifyContent: "center", alignItems: "center",
    paddingHorizontal: 3, borderWidth: 1.5, borderColor: "#fff",
  },
  notifBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff" },

  statsRow: { flexDirection: "row", backgroundColor: "#fff", paddingVertical: 14, marginBottom: 8, borderBottomWidth: 1, borderBottomColor: "#f0f0f0" },
  statItem: { flex: 1, alignItems: "center" },
  statNum: { fontSize: 22, fontWeight: "900", marginBottom: 2 },
  statLabel: { fontSize: 10, color: "#aaa", fontWeight: "600" },
  statDivider: { width: 1, backgroundColor: "#f0f0f0" },

  filterRow: { flexDirection: "row", paddingHorizontal: 14, paddingVertical: 10, gap: 8 },
  filterBtn: { flex: 1, paddingVertical: 8, borderRadius: 10, backgroundColor: "#f5f5f5", alignItems: "center", position: "relative" },
  filterBtnActive: { backgroundColor: "#fff0f0" },
  filterBtnText: { fontSize: 13, fontWeight: "700", color: "#aaa" },
  filterBtnTextActive: { color: RED },
  newDot: { position: "absolute", top: 6, right: 8, width: 8, height: 8, borderRadius: 4, backgroundColor: RED },

  listCard: {
    backgroundColor: "#fff", borderRadius: 16, padding: 14, marginBottom: 10,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 8, elevation: 2,
    borderWidth: 1.5, borderColor: "transparent",
  },
  listCardActive: { borderColor: RED, backgroundColor: "#fff8f8" },
  listCardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 },
  orderId: { fontSize: 15, fontWeight: "900", color: "#111" },
  orderTime: { fontSize: 11, color: "#aaa", marginTop: 1 },
  badge: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8 },
  badgeText: { fontSize: 11, fontWeight: "700" },
  listCardMid: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 },
  addrText: { flex: 1, fontSize: 12, color: "#666" },
  listCardBottom: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  metaText: { fontSize: 12, color: "#aaa" },
  totalText: { fontSize: 15, fontWeight: "900", color: "#111" },

  emptyList: { alignItems: "center", paddingTop: 60, gap: 12 },
  emptyListText: { fontSize: 14, fontWeight: "600", color: "#ccc", textAlign: "center" },

  signOutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderTopWidth: 1, borderTopColor: "#f0f0f0" },
  signOutText: { fontSize: 13, fontWeight: "700", color: RED },

  // Desktop
  desktopBody: { flex: 1, flexDirection: "row" },
  desktopSidebar: {
    width: 320, backgroundColor: "#fff",
    borderRightWidth: 1, borderRightColor: "#f0f0f0",
    flexDirection: "column",
  },
  sidebarHeader: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: 16, paddingVertical: 16,
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  desktopPlaceholder: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  desktopPlaceholderTitle: { fontSize: 20, fontWeight: "900", color: "#333" },
  desktopPlaceholderSub: { fontSize: 14, color: "#aaa", textAlign: "center" },

  // Detail
  detailHeader: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: 16, paddingVertical: 14, backgroundColor: "#fff",
    borderBottomWidth: 1, borderBottomColor: "#f0f0f0",
  },
  backBtn: { width: 36, height: 36, borderRadius: 10, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  detailOrderId: { fontSize: 16, fontWeight: "900", color: "#111" },
  detailTime: { fontSize: 11, color: "#aaa" },

  // Pantalla de selección de punto de inicio
  startScreen: {
    paddingHorizontal: 20,
    paddingVertical: 24,
    borderBottomWidth: 1,
    gap: 12,
  },
  startTitle: { fontSize: 18, fontWeight: "900", letterSpacing: 0.2 },
  startSub: { fontSize: 12, marginBottom: 4, lineHeight: 17 },
  startOptionCard: {
    borderRadius: 16,
    borderWidth: 1,
    padding: 14,
    gap: 12,
    backgroundColor: "rgba(0,0,0,0.03)",
  },
  startOptionTop: { flexDirection: "row", alignItems: "center", gap: 14 },
  startOptionIcon: {
    width: 44, height: 44, borderRadius: 12,
    justifyContent: "center", alignItems: "center",
  },
  startOptionTitle: { fontSize: 15, fontWeight: "800" },
  startOptionSub: { fontSize: 12, marginTop: 2 },
  startOptionBtns: { flexDirection: "row", gap: 10 },
  startGoBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 7, paddingVertical: 12, borderRadius: 12,
    elevation: 3,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.2, shadowRadius: 4,
  },
  startGoBtnText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 0.4 },

  // Overlay de estado de ruta (cargando / error)
  routeStatusOverlay: {
    position: "absolute",
    bottom: 90,
    left: 20,
    right: 20,
    backgroundColor: "rgba(255,255,255,0.95)",
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 18,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 6,
  },
  routeStatusText: { flex: 1, fontSize: 13, fontWeight: "700" },
  retryBtn: { paddingHorizontal: 12, paddingVertical: 6, backgroundColor: RED, borderRadius: 8 },
  retryBtnText: { color: "#fff", fontSize: 12, fontWeight: "800" },

  // Marcadores
  markerOrigin: {
    width: 22, height: 22, borderRadius: 11,
    backgroundColor: "#fff",
    borderWidth: 3, borderColor: "#4285F4",
    justifyContent: "center", alignItems: "center",
    elevation: 6,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.35, shadowRadius: 3,
  },
  markerOriginDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#4285F4" },
  markerDest: { alignItems: "center" },

  // Marcador tienda
  markerStore: { alignItems: "center" },
  markerStoreCircle: {
    width: 38, height: 38, borderRadius: 19,
    backgroundColor: RED,
    justifyContent: "center", alignItems: "center",
    borderWidth: 2.5, borderColor: "#fff",
    elevation: 6,
    shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.35, shadowRadius: 3,
  },
  markerStoreTail: {
    width: 0, height: 0,
    borderLeftWidth: 6, borderRightWidth: 6, borderTopWidth: 8,
    borderLeftColor: "transparent", borderRightColor: "transparent", borderTopColor: RED,
    marginTop: -1,
  },

  // Card info tienda (flotante sobre el mapa)
  storeCardOverlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: "flex-end",
    paddingBottom: 100,
    paddingHorizontal: 16,
  },
  storeCard: {
    borderRadius: 18,
    padding: 16,
    shadowColor: "#000", shadowOffset: { width: 0, height: 6 }, shadowOpacity: 0.22, shadowRadius: 12,
    elevation: 14,
  },
  storeCardHeader: {
    flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 14,
  },
  storeCardIconWrap: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: RED,
    justifyContent: "center", alignItems: "center",
  },
  storeCardBrand: {
    fontSize: 16, fontWeight: "800",
  },
  storeCardBranch: {
    fontSize: 13, fontWeight: "600", color: RED, marginTop: 1,
  },
  storeCardRow: {
    flexDirection: "row", alignItems: "center", gap: 12, marginTop: 10,
  },
  storeCardRowIcon: {
    width: 34, height: 34, borderRadius: 10,
    justifyContent: "center", alignItems: "center",
  },
  storeCardLabel: {
    fontSize: 11, fontWeight: "600", marginBottom: 2,
  },
  storeCardValue: {
    fontSize: 14, fontWeight: "500", lineHeight: 19,
  },

  // Mapa principal
  mapContainer: {
    height: 430,
    backgroundColor: "#e8eaed",
    position: "relative",
    overflow: "hidden",
  },

  // Panel superior ETA — estilo Google Maps
  gmTopBar: {
    position: "absolute",
    top: 0, left: 0, right: 0,
    backgroundColor: "rgba(26,26,26,0.92)",
    paddingTop: 14, paddingBottom: 10,
    paddingHorizontal: 20,
    elevation: 12,
    shadowColor: "#000", shadowOffset: { width: 0, height: 3 }, shadowOpacity: 0.4, shadowRadius: 6,
  },
  gmEtaRow: { flexDirection: "row", alignItems: "center" },
  gmEtaTime: { fontSize: 32, fontWeight: "900", color: "#fff", letterSpacing: -0.5 },
  gmEtaUnit: { fontSize: 16, fontWeight: "700", color: "rgba(255,255,255,0.7)", marginBottom: 1 },
  gmTrafficBadge: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderRadius: 12, borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 3,
    marginLeft: 10, marginBottom: 1,
  },
  gmTrafficDot: { width: 7, height: 7, borderRadius: 3.5 },
  gmTrafficLabel: { fontSize: 11, fontWeight: "700" },
  gmSep: { width: 1, height: 22, backgroundColor: "rgba(255,255,255,0.25)", marginHorizontal: 14, alignSelf: "center" },
  gmDist: { fontSize: 20, fontWeight: "800", color: "rgba(255,255,255,0.85)" },
  gmInstrRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "rgba(255,255,255,0.12)",
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8,
    marginBottom: 8,
  },
  gmInstrText: { flex: 1, color: "#fff", fontSize: 15, fontWeight: "800" },
  gmVoiceBtn: {
    marginLeft: "auto",
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: "rgba(255,255,255,0.15)",
    justifyContent: "center", alignItems: "center",
  },
  gmVoiceBtnOn: { backgroundColor: "#34A853" },
  gmLoadingRow: { flexDirection: "row", alignItems: "center", marginTop: 4 },
  gmLoadingText: { fontSize: 11, color: "rgba(255,255,255,0.6)", fontWeight: "600" },
  gmRetryLink: { fontSize: 11, color: "#4285F4", fontWeight: "800", textDecorationLine: "underline" },

  // Barra inferior — botón grande Google Maps + chips
  gmBottomBar: {
    position: "absolute",
    bottom: 0, left: 0, right: 0,
    backgroundColor: "#fff",
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 16,
    elevation: 16,
    shadowColor: "#000", shadowOffset: { width: 0, height: -3 }, shadowOpacity: 0.12, shadowRadius: 8,
    gap: 10,
  },
  gmNavBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#1a73e8",
    borderRadius: 14,
    paddingVertical: 14,
    gap: 10,
    elevation: 4,
    shadowColor: "#1a73e8", shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.35, shadowRadius: 8,
  },
  gmNavBtnText: { color: "#fff", fontSize: 14, fontWeight: "900", letterSpacing: 0.3 },
  gmSecondRow: { flexDirection: "row", gap: 8 },
  gmChip: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 5, paddingVertical: 9, borderRadius: 10,
    backgroundColor: "#f1f3f4",
  },
  gmChipActive: { backgroundColor: "#1a73e8" },
  gmChipText: { fontSize: 11, fontWeight: "700", color: "#555" },

  // Botón mostrar mapa (modo hidden)
  showNavBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#fff",
    paddingVertical: 14,
    marginHorizontal: 16,
    borderRadius: 15,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#eee",
    gap: 10,
  },
  showNavText: { fontSize: 12, fontWeight: "900", color: RED, letterSpacing: 0.5 },

  card: { backgroundColor: "#fff", borderRadius: 16, padding: 16, marginBottom: 12, shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.04, shadowRadius: 8, elevation: 2 },
  cardTitle: { fontSize: 10, fontWeight: "800", color: "#bbb", letterSpacing: 0.5, marginBottom: 14 },

  timelineRow: { flexDirection: "row", alignItems: "flex-start", marginBottom: 0 },
  timelineDot: { width: 32, height: 32, borderRadius: 16, backgroundColor: "#f0f0f0", justifyContent: "center", alignItems: "center", marginBottom: 0 },
  timelineDotDone: { backgroundColor: GREEN },
  timelineDotActive: { backgroundColor: RED },
  timelineLine: { width: 2, height: 24, backgroundColor: "#f0f0f0", marginLeft: 15 },
  timelineLineDone: { backgroundColor: GREEN },
  timelineLabel: { flex: 1, fontSize: 13, color: "#aaa", marginLeft: 12, paddingTop: 7, paddingBottom: 16 },
  timelineLabelActive: { color: "#111", fontWeight: "800" },

  infoRow: { flexDirection: "row", alignItems: "flex-start", gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#f9f9f9" },
  infoIcon: { width: 34, height: 34, borderRadius: 10, backgroundColor: "#fff5f5", justifyContent: "center", alignItems: "center", marginTop: 2 },
  infoLabel: { fontSize: 10, fontWeight: "700", color: "#bbb", marginBottom: 2 },
  infoValue: { fontSize: 14, fontWeight: "700", color: "#111" },
  infoSub: { fontSize: 12, color: "#aaa", marginTop: 1 },
  payBadge: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, alignSelf: "flex-start", marginTop: 4 },

  productRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10 },
  productDivider: { borderBottomWidth: 1, borderBottomColor: "#f5f5f5" },
  productQtyBadge: { width: 32, height: 32, borderRadius: 8, backgroundColor: "#f5f5f5", justifyContent: "center", alignItems: "center" },
  productQtyText: { fontSize: 12, fontWeight: "800", color: "#555" },
  productName: { fontSize: 13, fontWeight: "700", color: "#111" },
  productPrice: { fontSize: 11, color: "#aaa" },
  productTotal: { fontSize: 14, fontWeight: "800", color: "#111" },
  totalRow: { flexDirection: "row", justifyContent: "space-between", paddingTop: 12, marginTop: 4, borderTopWidth: 1, borderTopColor: "#f0f0f0" },
  totalLabel: { fontSize: 12, fontWeight: "800", color: "#aaa" },
  totalValue: { fontSize: 18, fontWeight: "900", color: "#111" },

  actionBar: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    padding: 16,
    backgroundColor: "#fff",
    borderTopWidth: 1, borderTopColor: "#f0f0f0",
    shadowColor: "#000", shadowOffset: { width: 0, height: -2 }, shadowOpacity: 0.06, shadowRadius: 8,
  },
  acceptBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    backgroundColor: GREEN, borderRadius: 16, paddingVertical: 16,
  },
  acceptBtnText: { color: "#fff", fontWeight: "900", fontSize: 16 },
  geoWarning: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#fffbeb", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8,
    marginBottom: 8, borderWidth: 1, borderColor: "#f59e0b",
  },
  geoWarningText: { color: "#92400e", fontSize: 13, fontWeight: "600", flex: 1 },

  // ─── Banner nuevo pedido ───────────────────────────────────────────────────
  bannerWrap: {
    position: "absolute", top: Platform.OS === "ios" ? 54 : 44, left: 12, right: 12,
    backgroundColor: RED, borderRadius: 20,
    shadowColor: "#000", shadowOffset: { width: 0, height: 6 }, shadowOpacity: 0.25, shadowRadius: 16,
    elevation: 12, zIndex: 9999, overflow: "hidden",
  },
  bannerInner: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 14, paddingTop: 14, paddingBottom: 10,
  },
  bannerIcon: {
    width: 46, height: 46, borderRadius: 13,
    backgroundColor: "rgba(0,0,0,0.18)", justifyContent: "center", alignItems: "center",
  },
  bannerTitle: { fontSize: 14, fontWeight: "900", color: "#fff", marginBottom: 2 },
  bannerOrderId: { fontSize: 12, fontWeight: "800", color: "rgba(255,255,255,0.85)", marginBottom: 2 },
  bannerAddr: { fontSize: 11, color: "rgba(255,255,255,0.75)", marginBottom: 4 },
  bannerMeta: { flexDirection: "row", alignItems: "center", gap: 4 },
  bannerMetaText: { fontSize: 11, color: "rgba(255,255,255,0.8)" },
  bannerDot: { fontSize: 11, color: "rgba(255,255,255,0.5)" },
  bannerTotal: { fontSize: 12, fontWeight: "800", color: "#fff" },
  bannerClose: {
    width: 30, height: 30, borderRadius: 8,
    backgroundColor: "rgba(0,0,0,0.15)", justifyContent: "center", alignItems: "center",
  },
  bannerViewBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#fff", marginHorizontal: 14, marginBottom: 14, borderRadius: 12,
    paddingVertical: 12,
  },
  bannerViewText: { fontSize: 14, fontWeight: "900", color: RED },

  // Error banner
  errorBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#fef3c7", borderLeftWidth: 4, borderLeftColor: "#f59e0b",
    marginHorizontal: 14, marginVertical: 8,
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10,
  },
  errorBannerText: { fontSize: 12, fontWeight: "600", color: "#92400e", flex: 1 },
  errorRetryBtn: { paddingHorizontal: 10, paddingVertical: 4, backgroundColor: "#f59e0b", borderRadius: 8 },
  errorRetryText: { fontSize: 11, fontWeight: "800", color: "#fff" },

  // Ganancias Modernas
  premiumEarningsCard: {
    backgroundColor: RED,
    borderRadius: 24,
    padding: 24,
    shadowColor: RED,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.25,
    shadowRadius: 15,
    elevation: 10,
    marginBottom: 20,
  },
  earningsHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12 },
  earningsTitle: { fontSize: 11, fontWeight: "900", color: "rgba(255,255,255,0.7)", letterSpacing: 1.5 },
  earningsValue: { fontSize: 42, fontWeight: "900", color: "#fff", marginBottom: 24 },
  earningsMetrics: { flexDirection: "row", alignItems: "center", backgroundColor: "rgba(255,255,255,0.15)", borderRadius: 16, padding: 14 },
  metricItem: { flex: 1, alignItems: "center" },
  metricVal: { fontSize: 18, fontWeight: "900", color: "#fff" },
  metricLabel: { fontSize: 10, fontWeight: "700", color: "rgba(255,255,255,0.8)", marginTop: 2 },
  metricDivider: { width: 1, height: 24, backgroundColor: "rgba(255,255,255,0.2)" },

  modernSection: {
    backgroundColor: "#fff",
    borderRadius: 20,
    padding: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
    marginBottom: 20,
  },
  modernSectionTitle: { fontSize: 10, fontWeight: "900", color: "#bbb", letterSpacing: 1, marginBottom: 16, marginLeft: 4 },
  modernRow: { flexDirection: "row", alignItems: "center", gap: 14, marginBottom: 20 },
  modernIcon: { width: 44, height: 44, borderRadius: 14, justifyContent: "center", alignItems: "center" },
  modernRowLabel: { fontSize: 11, fontWeight: "700", color: "#aaa" },
  modernRowVal: { fontSize: 14, fontWeight: "800", color: "#111", marginTop: 1 },
  refreshStatsBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 10 },
  refreshStatsText: { fontSize: 11, fontWeight: "800", color: "#aaa", letterSpacing: 0.5 },
});
