import { Ionicons } from "@expo/vector-icons";
import React, { useRef, useState, useEffect, useCallback } from "react";
import { getStores, GOOGLE_MAPS_API_KEY } from "../services/api";
import { useTheme } from "../context/ThemeContext";
import { GOOGLE_MAPS_DARK_STYLE } from "../constants/theme";
import { MapView, Marker, PROVIDER_GOOGLE } from "./MapComponents";
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  KeyboardAvoidingView,
} from "react-native";

const RED    = "#e6192e";
const ORANGE = "#f59e0b";
const GREEN  = "#22c55e";

// Zonas de cobertura (km en línea recta desde la sucursal más cercana)
export const COVERAGE_KM  = 10;  // cobertura normal
export const EXTENDED_KM  = 15;  // zona extendida (llega pero más tiempo)

// Consultar tiempo real en auto con tráfico vía Google Directions API
async function fetchDrivingETA(fromLat, fromLng, toLat, toLng) {
  try {
    if (!GOOGLE_MAPS_API_KEY || GOOGLE_MAPS_API_KEY === "TU_GOOGLE_MAPS_API_KEY") return null;
    const url = `https://maps.googleapis.com/maps/api/directions/json?origin=${fromLat},${fromLng}&destination=${toLat},${toLng}&key=${GOOGLE_MAPS_API_KEY}&departure_time=now`;
    const res  = await fetch(url);
    const data = await res.json();
    const leg = data?.routes?.[0]?.legs?.[0];
    const secs = leg?.duration_in_traffic?.value || leg?.duration?.value;
    if (!secs) return null;
    const min = Math.ceil((secs / 60 + 10) / 5) * 5; // +10 min preparación, redondear a 5
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

export const TPN_STORES = [
  { name: "20 de Noviembre", city: "Morelia", address: "Calle 20 de Noviembre #825", lat: 19.7061, lng: -101.1950 },
  { name: "Calle Zamora",    city: "Morelia", address: "Calle Zamora #395",           lat: 19.7074, lng: -101.1970 },
  { name: "TPN Zacapu",     city: "Zacapu",  address: "Calle Lic. Eduardo Ruiz #178",lat: 19.8248, lng: -101.7907 },
  { name: "TPN Uruapan",    city: "Uruapan", address: "Calle Sarabia #30",            lat: 19.4157, lng: -102.0573 },
  { name: "TPN Maravatío",  city: "Maravatío",address: "Calle Álvaro Obregón #206",  lat: 19.9092, lng: -100.4381 },
];

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function findNearestStore(lat, lng, storeList) {
  const list = storeList?.length ? storeList : TPN_STORES;
  return list.reduce((best, s) => {
    const d = haversineKm(lat, lng, s.lat, s.lng);
    return d < best.dist ? { ...s, dist: d } : best;
  }, { ...list[0], dist: haversineKm(lat, lng, list[0].lat, list[0].lng) });
}

// ─── BÚSQUEDA CON NOMINATIM ───────────────────────────────────────────────────
const MX_VIEWBOX = "-103.8,18.9,-99.8,20.5";

async function searchNominatim(query) {
  const needsContext = !/michoacán|michoacan|morelia|uruapan|zacapu|maravat/i.test(query);
  const q = needsContext ? `${query}, Michoacán, México` : query;
  const params = new URLSearchParams({
    q,
    format: "json",
    limit: "6",
    "accept-language": "es",
    countrycodes: "mx",
    viewbox: MX_VIEWBOX,
    bounded: "1",
    addressdetails: "1",
  });
  const res = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, { headers: { "User-Agent": "TPN-App/1.0" } });
  return res.json();
}

async function reverseNominatim(lat, lng) {
  const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&accept-language=es&zoom=18&addressdetails=1`;
  const res = await fetch(url, { headers: { "User-Agent": "TPN-App/1.0" } });
  return res.json();
}

export default function LocationPickerModal({
  visible,
  onClose,
  onConfirm,
  currentCoords,
  businessCoords,
  popup = false,
  inline = false,
}) {
  const { t, isDark } = useTheme();
  const mapRef = useRef(null);
  const searchTimer = useRef(null);
  const openedAt = useRef(0);

  const defaultLat = currentCoords?.latitude ?? currentCoords?.lat ?? 19.7044;
  const defaultLng = currentCoords?.longitude ?? currentCoords?.lng ?? -101.2262;

  const [searchText, setSearchText] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [selectedAddress, setSelectedAddress] = useState("");
  const [selectedCoords, setSelectedCoords] = useState({ lat: defaultLat, lng: defaultLng });
  const [reverseLoading, setReverseLoading] = useState(false);
  const [nearestStore, setNearestStore] = useState(null);
  const [mapReady, setMapReady] = useState(false);
  const [stores, setStores] = useState(TPN_STORES);
  const [etaMinutes, setEtaMinutes] = useState(null);
  const [etaLoading, setEtaLoading] = useState(false);

  useEffect(() => {
    getStores().then((res) => {
      if (res?.success && Array.isArray(res.data)) {
        setStores(res.data.map(s => ({ ...s, lat: parseFloat(s.lat), lng: parseFloat(s.lng) })));
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (visible) {
      openedAt.current = Date.now();
      const lat = currentCoords?.latitude ?? currentCoords?.lat ?? defaultLat;
      const lng = currentCoords?.longitude ?? currentCoords?.lng ?? defaultLng;
      setSelectedCoords({ lat, lng });
      doReverse(lat, lng);
    }
  }, [visible]);

  const doReverse = async (lat, lng) => {
    setReverseLoading(true);
    setEtaMinutes(null);
    try {
      const data = await reverseNominatim(lat, lng);
      if (data?.display_name) {
        const a = data.address || {};
        const street = [a.road || a.pedestrian, a.house_number].filter(Boolean).join(" ");
        const short = [street, a.suburb || a.neighbourhood, a.city || a.town].filter(Boolean).join(", ");
        setSelectedAddress(short || data.display_name);
      }
    } catch {}
    const store = findNearestStore(lat, lng, stores);
    setNearestStore(store);
    setReverseLoading(false);
    if (store && store.dist <= EXTENDED_KM) {
      setEtaLoading(true);
      const min = await fetchDrivingETA(store.lat, store.lng, lat, lng);
      setEtaMinutes(min);
      setEtaLoading(false);
    }
  };

  const handleSearchChange = (text) => {
    setSearchText(text);
    clearTimeout(searchTimer.current);
    if (text.length < 3) { setResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await searchNominatim(text);
        setResults(data || []);
      } catch {}
      setSearching(false);
    }, 400);
  };

  const selectResult = (item) => {
    const lat = parseFloat(item.lat);
    const lng = parseFloat(item.lon);
    const coords = { lat, lng };
    setSelectedCoords(coords);
    setSelectedAddress(item.display_name.split(",").slice(0,3).join(","));
    setSearchText("");
    setResults([]);
    panMap(lat, lng);
    doReverse(lat, lng);
  };

  const panMap = (lat, lng) => {
    mapRef.current?.animateToRegion({
      latitude: lat,
      longitude: lng,
      latitudeDelta: 0.005,
      longitudeDelta: 0.005,
    }, 1000);
  };

  const onMapPress = (e) => {
    const coords = e.nativeEvent.coordinate;
    if (coords) {
      const { latitude: lat, longitude: lng } = coords;
      setSelectedCoords({ lat, lng });
      doReverse(lat, lng);
    }
  };

  const confirm = () => {
    if (!selectedAddress) return;
    onConfirm(selectedAddress, selectedCoords);
    onClose();
  };

  const distance = nearestStore?.dist ?? null;
  const outOfRange  = distance !== null && distance > EXTENDED_KM;
  const isExtended  = distance !== null && distance > COVERAGE_KM && distance <= EXTENDED_KM;
  const canConfirm  = !!selectedAddress && !outOfRange;

  const mapSection = () => {
    if (!MapView) {
      return (
        <View style={[styles.mapWrap, { backgroundColor: isDark ? "#1c1c1e" : "#e8e8e8", justifyContent: "center", alignItems: "center" }]}>
          <Ionicons name="map-outline" size={48} color="#aaa" />
          <Text style={{ color: "#aaa", marginTop: 8, fontSize: 13 }}>Mapa no disponible en web</Text>
        </View>
      );
    }
    return (
      <View style={[styles.mapWrap, { backgroundColor: isDark ? "#1c1c1e" : "#e8e8e8" }]}>
        <MapView
          ref={mapRef}
          provider={PROVIDER_GOOGLE}
          style={styles.map}
          customMapStyle={isDark ? GOOGLE_MAPS_DARK_STYLE : []}
          initialRegion={{
            latitude: selectedCoords.lat,
            longitude: selectedCoords.lng,
            latitudeDelta: 0.01,
            longitudeDelta: 0.01,
          }}
          onPress={onMapPress}
          showsUserLocation
          userInterfaceStyle={isDark ? "dark" : "light"}
          onMapReady={() => setMapReady(true)}
        >
          <Marker coordinate={{ latitude: selectedCoords.lat, longitude: selectedCoords.lng }} draggable onDragEnd={(e) => onMapPress(e)}>
             <View style={[styles.markerCircle, { backgroundColor: RED }]}>
                <Ionicons name="location" size={24} color="#fff" />
             </View>
          </Marker>
        </MapView>
        {!mapReady && <View style={[styles.mapLoading, { backgroundColor: t.bg }]}><ActivityIndicator size="large" color={RED} /></View>}
        <View style={styles.mapHintWrap} pointerEvents="none">
          <View style={[styles.mapHintPill, { backgroundColor: isDark ? "rgba(30,30,30,0.9)" : "rgba(255,255,255,0.9)" }]}>
            <Text style={[styles.mapHintText, { color: t.textSub }]}>Toca el mapa o arrastra el pin</Text>
          </View>
        </View>
      </View>
    );
  };

  const content = (
    <KeyboardAvoidingView style={[styles.container, { backgroundColor: t.bg }]} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={[styles.header, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <TouchableOpacity onPress={onClose} style={[styles.closeBtn, { backgroundColor: t.iconBg }]}>
          <Ionicons name="close" size={24} color={t.text} />
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: t.text }]}>¿Dónde te entregamos?</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={[styles.searchWrap, { backgroundColor: t.iconBg }]}>
        <Ionicons name="search" size={18} color={RED} style={{ marginLeft: 14 }} />
        <TextInput
          value={searchText}
          onChangeText={handleSearchChange}
          placeholder="Busca tu calle, colonia o ciudad..."
          placeholderTextColor={t.placeholder}
          style={[styles.searchInput, { color: t.text }]}
          returnKeyType="search"
        />
        {searching && <ActivityIndicator size="small" color={RED} style={{ marginRight: 12 }} />}
      </View>

      {results.length > 0 && (
        <View style={[styles.resultsList, { backgroundColor: t.card }]}>
          <FlatList
            data={results}
            keyExtractor={(_, i) => String(i)}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.resultItem} onPress={() => selectResult(item)}>
                <Text style={[styles.resultText, { color: t.text }]} numberOfLines={2}>{item.display_name}</Text>
              </TouchableOpacity>
            )}
            ItemSeparatorComponent={() => <View style={[styles.resultSep, { backgroundColor: t.divider }]} />}
          />
        </View>
      )}

      {mapSection()}

      <View style={[styles.bottomPanel, { backgroundColor: t.card, borderTopColor: t.border }]}>
        <View style={styles.selectedRow}>
          <View style={styles.pinIconWrap}><Ionicons name="location-sharp" size={22} color={outOfRange ? t.border : RED} /></View>
          <View style={{ flex: 1 }}>
            <Text style={[styles.selectedLabel, { color: t.textMuted }]}>Dirección de entrega</Text>
            <Text style={[styles.selectedAddress, { color: t.text }]} numberOfLines={2}>{selectedAddress || "Cargando..."}</Text>
            {nearestStore && (
              <View style={styles.etaRow}>
                <View style={[styles.etaBadge, { backgroundColor: isExtended ? (isDark ? "#3a2a0a" : "#fffbeb") : (isDark ? "#153a15" : "#f0fdf4"), borderColor: (isExtended ? ORANGE : GREEN) + "44" }]}>
                  <Ionicons name="car-outline" size={13} color={isExtended ? ORANGE : GREEN} />
                  {etaLoading ? <ActivityIndicator size={10} color={isExtended ? ORANGE : GREEN} /> : <Text style={[styles.etaText, { color: isExtended ? ORANGE : GREEN }]}>{formatMinutes(etaMinutes) || "..."}</Text>}
                </View>
                <Text style={[styles.distanceText, { color: t.textMuted }]}>{nearestStore.dist.toFixed(1)} km · {nearestStore.name}</Text>
              </View>
            )}
            {outOfRange && (
              <View style={[styles.coverageCard, { backgroundColor: t.iconBgRed }]}>
                <Text style={styles.coverageTitle}>Fuera de cobertura</Text>
              </View>
            )}
          </View>
        </View>

        <TouchableOpacity
          style={[styles.confirmBtn, !canConfirm && styles.confirmBtnDisabled, !canConfirm && { backgroundColor: isDark ? "#3a3a3c" : "#ddd", shadowOpacity: 0, elevation: 0 }]}
          onPress={confirm}
          disabled={!canConfirm}
        >
          <Text style={styles.confirmText}>{outOfRange ? "SIN COBERTURA" : "CONFIRMAR DIRECCIÓN"}</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );

  if (inline) {
    return content;
  }

  return (
    <Modal visible={visible} animationType="slide" statusBarTranslucent onRequestClose={onClose}>
      {content}
    </Modal>
  );
}

// ─── ESTILOS ──────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#fff",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingTop: Platform.OS === "ios" ? 54 : 44,
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
    backgroundColor: "#fff",
  },
  closeBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "#f5f5f5",
    justifyContent: "center",
    alignItems: "center",
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: "900",
    color: "#111",
  },

  // ── Popup PC ──────────────────────────────────────────────────────────────
  popupBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  popupCard: {
    width: 460,
    maxWidth: "95%",
    borderRadius: 18,
    backgroundColor: "#fff",
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.22,
    shadowRadius: 28,
    elevation: 24,
  },
  popupHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
  },
  popupCloseBtn: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: "#f5f5f5",
    justifyContent: "center",
    alignItems: "center",
  },

  // Búsqueda
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    margin: 14,
    backgroundColor: "#f5f5f5",
    borderRadius: 14,
    height: 48,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  searchInput: {
    flex: 1,
    paddingHorizontal: 12,
    fontSize: 14,
    color: "#222",
  },

  // Resultados
  resultsList: {
    marginHorizontal: 14,
    marginBottom: 8,
    backgroundColor: "#fff",
    borderRadius: 14,
    maxHeight: 240,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 12,
    elevation: 8,
    overflow: "hidden",
  },
  resultItem: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingHorizontal: 16,
    paddingVertical: 13,
  },
  resultText: {
    flex: 1,
    fontSize: 13,
    color: "#333",
    lineHeight: 18,
  },
  resultSep: {
    height: 1,
    backgroundColor: "#f5f5f5",
    marginLeft: 42,
  },

  // Mapa
  mapWrap: {
    flex: 1,
    position: "relative",
    overflow: "hidden",
    ...(Platform.OS === "web" ? { minHeight: 260 } : {}),
  },
  map: {
    flex: 1,
  },
  mapLoading: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "#f8f8f8",
    justifyContent: "center",
    alignItems: "center",
    gap: 12,
  },
  mapLoadingText: { fontSize: 13, color: "#aaa", marginTop: 8 },
  mapHintWrap: {
    position: "absolute",
    top: 12,
    alignSelf: "center",
    width: "100%",
    alignItems: "center",
  },
  mapHintPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(255,255,255,0.92)",
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 20,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 6,
    elevation: 4,
  },
  mapHintText: { fontSize: 12, color: "#555", fontWeight: "600" },
  markerCircle: { width: 40, height: 40, borderRadius: 20, justifyContent: "center", alignItems: "center", borderWidth: 2, borderColor: "#fff" },

  // Panel inferior
  bottomPanel: {
    backgroundColor: "#fff",
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: Platform.OS === "ios" ? 34 : 20,
    borderTopWidth: 1,
    borderTopColor: "#f0f0f0",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.06,
    shadowRadius: 12,
    elevation: 12,
    gap: 12,
  },
  selectedRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
  },
  pinIconWrap: {
    marginTop: 2,
  },
  selectedLabel: {
    fontSize: 11,
    fontWeight: "700",
    color: "#aaa",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 3,
  },
  selectedAddress: {
    fontSize: 14,
    fontWeight: "700",
    color: "#111",
    lineHeight: 20,
  },
  distanceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    marginTop: 5,
    flexWrap: "wrap",
  },
  distanceText: {
    fontSize: 12,
    color: "#888",
    fontWeight: "600",
    flexShrink: 1,
  },
  etaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 6,
    flexWrap: "wrap",
  },
  etaBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
  },
  etaText: {
    fontSize: 12,
    fontWeight: "800",
  },
  coverageCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    marginTop: 8,
    backgroundColor: "#fff1f2",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#fecdd3",
  },
  coverageTitle: {
    fontSize: 13,
    fontWeight: "800",
    color: RED,
    marginBottom: 3,
  },
  coverageSub: {
    fontSize: 12,
    color: "#555",
    lineHeight: 17,
  },
  gpsBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: "#eee",
    alignSelf: "flex-start",
  },
  gpsBtnText: {
    fontSize: 13,
    fontWeight: "700",
    color: RED,
  },
  confirmBtn: {
    backgroundColor: RED,
    borderRadius: 16,
    paddingVertical: 16,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    shadowColor: RED,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 6,
  },
  confirmBtnDisabled: {
    backgroundColor: "#ddd",
    shadowOpacity: 0,
    elevation: 0,
  },
  confirmText: {
    color: "#fff",
    fontWeight: "900",
    fontSize: 15,
    letterSpacing: 0.8,
  },
});
