/**
 * Firebase — Farmacia Eben-Ezer
 *
 * PENDIENTE: Crear nuevo proyecto Firebase en https://console.firebase.google.com
 * y reemplazar los valores con las credenciales del nuevo proyecto.
 * También reemplazar google-services.json (Android) y GoogleService-Info.plist (iOS).
 */
import { initializeApp, getApps } from "firebase/app";
import { Platform } from "react-native";

const firebaseConfig = {
  apiKey:            process.env.EXPO_PUBLIC_FIREBASE_API_KEY             ?? "PENDIENTE",
  authDomain:        process.env.EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN         ?? "PENDIENTE",
  projectId:         process.env.EXPO_PUBLIC_FIREBASE_PROJECT_ID          ?? "PENDIENTE",
  storageBucket:     process.env.EXPO_PUBLIC_FIREBASE_STORAGE_BUCKET      ?? "PENDIENTE",
  messagingSenderId: process.env.EXPO_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "PENDIENTE",
  appId:             process.env.EXPO_PUBLIC_FIREBASE_APP_ID              ?? "PENDIENTE",
  measurementId:     process.env.EXPO_PUBLIC_FIREBASE_MEASUREMENT_ID      ?? undefined,
};

export const firebaseApp =
  getApps().length ? getApps()[0] : initializeApp(firebaseConfig);

export async function getWebFCMToken() {
  if (Platform.OS !== "web") return null;
  if (firebaseConfig.apiKey === "PENDIENTE") return null;
  try {
    const { getMessaging, getToken } = await import("firebase/messaging");
    const messaging = getMessaging(firebaseApp);
    const vapidKey = process.env.EXPO_PUBLIC_FIREBASE_VAPID_KEY;
    if (!vapidKey) return null;
    const token = await getToken(messaging, { vapidKey });
    return token || null;
  } catch {
    return null;
  }
}
