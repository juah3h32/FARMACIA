// import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { getWebFCMToken } from "./firebase";

// Configura cómo se muestran las notificaciones cuando la app está abierta (clientes)
export async function setupForegroundHandler() {
  if (Platform.OS === "web") return;
  const Notifications = await import("expo-notifications");
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList:   true,
      shouldPlaySound:  true,
      shouldSetBadge:   false,
    }),
  });
}

// Pide permisos y devuelve el token FCM (Android/iOS) o token web FCM
export async function registerForPushNotifications() {
  if (Platform.OS === "web") {
    if (typeof window !== "undefined" && !("Notification" in window)) return null;
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return null;
    return await getWebFCMToken();
  }

  const Notifications = await import("expo-notifications");

  const { status: existing } = await Notifications.getPermissionsAsync();
  let finalStatus = existing;
  if (existing !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") return null;

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("pedidos", {
      name: "Pedidos TPN",
      importance: Notifications.AndroidImportance.MAX,
      sound: "default",
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#e6192e",
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    });
  }

  try {
    const { data: token } = await Notifications.getDevicePushTokenAsync();
    return token ?? null;
  } catch {
    return null;
  }
}
