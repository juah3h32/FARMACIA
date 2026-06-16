import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useAuth } from "./AuthContext";

const STORAGE_PREFIX = "@farmacia_notifications_v1_";
const MAX_NOTIFS     = 50;

const NotificationsContext = createContext({});

export function NotificationsProvider({ children }) {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState([]);

  const userId = user?.id || "guest";
  const STORAGE_KEY = STORAGE_PREFIX + userId;

  // Cargar desde AsyncStorage cuando cambia el usuario
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((v) => { 
        if (v) setNotifications(JSON.parse(v));
        else setNotifications([]); 
      })
      .catch(() => setNotifications([]));
  }, [userId, STORAGE_KEY]);

  const persist = useCallback((list) => {
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(list)).catch(() => {});
  }, [STORAGE_KEY]);

  const addNotification = useCallback(({ title, body, type = "info", orderId = null }) => {
    setNotifications((prev) => {
      const notif = {
        id:        Date.now().toString() + Math.random().toString(36).slice(2),
        title,
        body,
        type,      // accepted | preparing | picked_up | on_the_way | arrived | delivered | cancelled | nearby | info
        orderId,
        read:      false,
        timestamp: new Date().toISOString(),
      };
      const updated = [notif, ...prev].slice(0, MAX_NOTIFS);
      persist(updated);
      return updated;
    });
  }, [persist]);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => {
      const updated = prev.map((n) => ({ ...n, read: true }));
      persist(updated);
      return updated;
    });
  }, [persist]);

  const clearAll = useCallback(() => {
    setNotifications([]);
    AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
  }, [STORAGE_KEY]);

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <NotificationsContext.Provider value={{
      notifications,
      addNotification,
      markAllRead,
      clearAll,
      unreadCount,
    }}>
      {children}
    </NotificationsContext.Provider>
  );
}

export function useNotifications() {
  return useContext(NotificationsContext);
}
