import * as Location from "expo-location";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";

const LocationContext = createContext(null);

export function LocationProvider({ children }) {
  const [address, setAddress] = useState("Detectando ubicación...");
  const [coords, setCoords] = useState(null);
  const [permissionStatus, setPermissionStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [deliveryAddress, setDeliveryAddress] = useState("");
  const [deliveryCoords, setDeliveryCoordsState] = useState(null);
  const manualOverride = useRef(false);

  // Wrap setDeliveryAddress so that setting a value marks manual override
  const setDeliveryAddressManual = (value) => {
    manualOverride.current = true;
    setDeliveryAddress(value);
  };

  const setDeliveryCoords = (coords) => {
    setDeliveryCoordsState(coords);
  };

  const resetDeliveryAddress = () => {
    manualOverride.current = false;
    setDeliveryAddress(address);
    setDeliveryCoordsState(null);
  };

  const requestLocation = async () => {
    setLoading(true);
    setAddress("Detectando ubicación...");
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      setPermissionStatus(status);

      if (status !== "granted") {
        setAddress("Activa tu ubicación");
        if (!manualOverride.current) setDeliveryAddress("Activa tu ubicación");
        setLoading(false);
        return;
      }

      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });

      setCoords(loc.coords);

      try {
        const [place] = await Location.reverseGeocodeAsync({
          latitude: loc.coords.latitude,
          longitude: loc.coords.longitude,
        });

        if (place) {
          const street = place.street || place.name || "";
          const city = place.city || place.subregion || place.region || "";
          const postal = place.postalCode || "";
          const parts = [street, city, postal].filter(Boolean);
          const detectedAddress = parts.join(", ") || "Ubicación detectada";
          setAddress(detectedAddress);
          if (!manualOverride.current) setDeliveryAddress(detectedAddress);
        } else {
          throw new Error("no place");
        }
      } catch {
        // reverseGeocode falla en web — usar Nominatim como fallback
        try {
          const lat = loc.coords.latitude;
          const lng = loc.coords.longitude;
          const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&accept-language=es`,
            { headers: { "User-Agent": "TPN-App/1.0", Accept: "application/json" } }
          );
          const data = await res.json();
          if (data?.display_name) {
            const a = data.address || {};
            const parts = [
              a.road || a.pedestrian || a.path,
              a.house_number,
              a.suburb || a.neighbourhood || a.quarter,
              a.city || a.town || a.village || a.municipality,
              a.state,
            ].filter(Boolean);
            const detectedAddress = parts.length ? parts.join(", ") : data.display_name;
            setAddress(detectedAddress);
            if (!manualOverride.current) setDeliveryAddress(detectedAddress);
          } else {
            throw new Error("no nominatim");
          }
        } catch {
          const detectedAddress = formatCoords(loc.coords);
          setAddress(detectedAddress);
          if (!manualOverride.current) setDeliveryAddress(detectedAddress);
        }
      }
    } catch (e) {
      setAddress("No se pudo obtener la ubicación");
      if (!manualOverride.current) setDeliveryAddress("No se pudo obtener la ubicación");
    }
    setLoading(false);
  };

  useEffect(() => {
    // En web pedimos permiso al cargar, en nativo esperamos a que el usuario interactúe
    if (Platform.OS === "web") {
      requestLocation();
    } else {
      requestLocation();
    }
  }, []);

  return (
    <LocationContext.Provider
      value={{
        address,
        coords,
        permissionStatus,
        loading,
        requestLocation,
        deliveryAddress,
        setDeliveryAddress: setDeliveryAddressManual,
        deliveryCoords,
        setDeliveryCoords,
        resetDeliveryAddress,
      }}
    >
      {children}
    </LocationContext.Provider>
  );
}

function formatCoords(_coords) {
  return "Mi ubicación actual";
}

export const useLocation = () => useContext(LocationContext);
