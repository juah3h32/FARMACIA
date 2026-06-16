import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

const ThemeContext = createContext();

const DARK_KEY  = "@farmacia_dark_mode";
const NOTIF_KEY = "@farmacia_notifications_enabled";

export const LIGHT = {
  bg:           "#f5f5f5",
  card:         "#ffffff",
  cardAlt:      "#fafafa",
  text:         "#111111",
  textSub:      "#555555",
  textMuted:    "#999999",
  border:       "#f0f0f0",
  borderStrong: "#e5e7eb",
  input:        "#f8f8f8",
  inputBorder:  "#f0f0f0",
  header:       "#ffffff",
  iconBg:       "#f5f5f5",
  iconBgRed:    "#fff5f5",
  divider:      "#f5f5f5",
  placeholder:  "#cccccc",
  tabBar:       "#ffffff",
  overlay:      "rgba(0,0,0,0.45)",
};

export const DARK = {
  bg:           "#0f0f0f",
  card:         "#1c1c1e",
  cardAlt:      "#252527",
  text:         "#f2f2f2",
  textSub:      "#ababab",
  textMuted:    "#6d6d6d",
  border:       "#2c2c2e",
  borderStrong: "#3a3a3c",
  input:        "#2c2c2e",
  inputBorder:  "#3a3a3c",
  header:       "#1c1c1e",
  iconBg:       "#2c2c2e",
  iconBgRed:    "#3a1515",
  divider:      "#2c2c2e",
  placeholder:  "#555555",
  tabBar:       "#1c1c1e",
  overlay:      "rgba(0,0,0,0.65)",
};

export function ThemeProvider({ children }) {
  const [isDark, setIsDark] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);

  useEffect(() => {
    AsyncStorage.multiGet([DARK_KEY, NOTIF_KEY])
      .then(([[, dark], [, notif]]) => {
        if (dark  !== null) setIsDark(dark === "true");
        if (notif !== null) setNotificationsEnabled(notif !== "false");
      })
      .catch(() => {});
  }, []);

  const toggleDark = useCallback(async () => {
    const next = !isDark;
    setIsDark(next);
    await AsyncStorage.setItem(DARK_KEY, String(next)).catch(() => {});
  }, [isDark]);

  const toggleNotifications = useCallback(async (registerFn) => {
    const next = !notificationsEnabled;
    setNotificationsEnabled(next);
    await AsyncStorage.setItem(NOTIF_KEY, String(next)).catch(() => {});
    if (next && registerFn) {
      try { await registerFn(); } catch {}
    }
  }, [notificationsEnabled]);

  const t = isDark ? DARK : LIGHT;

  return (
    <ThemeContext.Provider value={{ isDark, t, toggleDark, notificationsEnabled, toggleNotifications }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
