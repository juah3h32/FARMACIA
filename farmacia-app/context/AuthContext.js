import AsyncStorage from "@react-native-async-storage/async-storage";
import * as AuthSession from "expo-auth-session";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { createContext, useContext, useEffect, useState } from "react";
import { Platform } from "react-native";
import { loginWithEmail, loginWithGoogle, registerUser, getMyProfile } from "../services/api";

WebBrowser.maybeCompleteAuthSession();

// ─── GOOGLE CONFIG ────────────────────────────────────────────────────────────
// PENDIENTE: reemplazar con Client IDs del nuevo proyecto Firebase de Farmacia Eben-Ezer
const WEB_CLIENT_ID =
  process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? "PENDIENTE.apps.googleusercontent.com";

const GOOGLE_CONFIG = {
  webClientId:     WEB_CLIENT_ID,
  androidClientId: process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID ?? "",
  iosClientId:     process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID ?? "",
};

// ─── NATIVE GOOGLE SIGN-IN (Android / iOS) ────────────────────────────────────
// Loaded lazily so the web bundle doesn't crash (the package is native-only)
let GoogleSignin = null;
let isErrorWithCode = null;
let statusCodes = null;

if (Platform.OS !== "web") {
  try {
    const mod = require("@react-native-google-signin/google-signin");
    GoogleSignin = mod.GoogleSignin;
    isErrorWithCode = mod.isErrorWithCode;
    statusCodes = mod.statusCodes;

    GoogleSignin.configure({ webClientId: WEB_CLIENT_ID, offlineAccess: false });
  } catch (e) {
    console.warn("@react-native-google-signin not available:", e.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
const AuthContext = createContext(null);

export function AuthProvider({ children, storageKey = "@farmacia_user" }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);

  // expo-auth-session — used only on WEB
  const redirectUri = AuthSession.makeRedirectUri({
    native: `com.googleusercontent.apps.1041797301392-0nj3f2sk5t9vnsofau603asnelkbge12:/oauth2redirect/google`,
  });
  const [request, response, promptAsync] = Google.useAuthRequest(
    { ...GOOGLE_CONFIG, extraParams: { prompt: "select_account" } },
    { redirectUri }
  );

  // ── Restaurar sesión guardada y refrescar rol desde el servidor ──────────
  useEffect(() => {
    AsyncStorage.getItem(storageKey)
      .then(async (stored) => {
        if (!stored) return;
        const cached = JSON.parse(stored);
        setUser(cached); // mostrar inmediatamente con datos cacheados

        // Si hay token, refrescar perfil para obtener role actualizado
        if (cached?.token) {
          try {
            const res = await getMyProfile(cached.token);
            if (res?.success && res?.data) {
              const refreshed = { ...cached, ...res.data, token: cached.token };
              setUser(refreshed);
              await AsyncStorage.setItem(storageKey, JSON.stringify(refreshed));
            }
          } catch {
            // Si falla el refresh, continuar con datos cacheados
          }
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // ── Procesar respuesta de Google (solo WEB) ───────────────────────────────
  useEffect(() => {
    if (Platform.OS !== "web" || !response) return;

    if (response.type === "success") {
      const token = response.authentication?.accessToken;
      if (token) {
        handleGoogleToken(token);
      } else {
        setAuthError("Google no devolvió un token válido");
      }
    } else if (response.type === "error") {
      const code = response.error?.code || "";
      if (code === "access_denied") {
        setAuthError("Cancelaste el inicio de sesión con Google");
      } else {
        setAuthError(
          `Error Google: ${code || response.error?.message || "Desconocido"}`
        );
      }
    }
  }, [response]);

  const handleGoogleToken = async (accessToken) => {
    try {
      const res = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!res.ok) throw new Error("No se pudo obtener perfil de Google");
      const g = await res.json();

      let backendToken = null;
      let backendUser  = null;
      try {
        const result = await loginWithGoogle({
          googleId: g.sub,
          name: g.name,
          email: g.email,
          photo: g.picture,
        });
        backendToken = result?.data?.token ?? null;
        backendUser  = result?.data?.user  ?? null;
      } catch {
        console.warn("Backend no disponible, usando datos de Google directamente");
      }

      await saveUser({
        id: g.sub,
        name: g.name,
        email: g.email,
        photo: g.picture,
        givenName: g.given_name,
        ...(backendUser || {}),
        token: backendToken,
        loginType: "google",
      });
    } catch (e) {
      setAuthError("Error al obtener perfil de Google: " + e.message);
    }
  };

  const saveUser = async (u) => {
    setUser(u);
    setAuthError(null);
    await AsyncStorage.setItem(storageKey, JSON.stringify(u));
  };

  // ── Login con email/contraseña ────────────────────────────────────────────
  const signInWithEmail = async (email, password) => {
    setAuthError(null);
    try {
      const result = await loginWithEmail(email, password);
      if (result?.success) {
        await saveUser({ ...result.data.user, token: result.data.token, loginType: "email" });
        return { success: true };
      }
      const msg = result?.message || "Email o contraseña incorrectos";
      setAuthError(msg);
      return { success: false, message: msg };
    } catch {
      const msg = "Error de conexión. Verifica tu internet.";
      setAuthError(msg);
      return { success: false, message: msg };
    }
  };

  // ── Registro con email/contraseña ─────────────────────────────────────────
  const signUp = async (name, email, password) => {
    setAuthError(null);
    try {
      const result = await registerUser(name, email, password);
      if (result?.success) {
        await saveUser({ ...result.data.user, token: result.data.token, loginType: "email" });
        return { success: true };
      }
      const msg = result?.message || "Error al registrarse";
      setAuthError(msg);
      return { success: false, message: msg };
    } catch {
      const msg = "Error de conexión. Verifica tu internet.";
      setAuthError(msg);
      return { success: false, message: msg };
    }
  };

  // ── Google Sign-In ────────────────────────────────────────────────────────
  const signInWithGoogle = async () => {
    setAuthError(null);

    if (Platform.OS !== "web") {
      // ── ANDROID / iOS: SDK nativo (sin navegador, sin redirect) ──────────
      if (!GoogleSignin) {
        setAuthError("Google Sign-In no está disponible en este dispositivo.");
        return;
      }
      try {
        await GoogleSignin.hasPlayServices();
        // Forzar el selector de cuentas limpiando la sesión previa
        try { await GoogleSignin.signOut(); } catch {}
        const result = await GoogleSignin.signIn();
        const googleUser = result.data?.user;
        if (!googleUser) throw new Error("No se recibieron datos del usuario");

        let backendToken = null;
        let backendUser  = null;
        try {
          const backendResult = await loginWithGoogle({
            googleId: googleUser.id,
            name: googleUser.name,
            email: googleUser.email,
            photo: googleUser.photo,
          });
          backendToken = backendResult?.data?.token ?? null;
          backendUser  = backendResult?.data?.user  ?? null;
        } catch {
          console.warn("Backend no disponible, usando datos de Google directamente");
        }

        await saveUser({
          id: googleUser.id,
          name: googleUser.name,
          email: googleUser.email,
          photo: googleUser.photo,
          givenName: googleUser.givenName,
          ...(backendUser || {}),
          token: backendToken,
          loginType: "google",
        });
      } catch (error) {
        if (isErrorWithCode && isErrorWithCode(error)) {
          if (error.code === statusCodes.SIGN_IN_CANCELLED) {
            setAuthError("Cancelaste el inicio de sesión con Google");
          } else if (error.code === statusCodes.IN_PROGRESS) {
            // ya en progreso, ignorar
          } else if (error.code === statusCodes.PLAY_SERVICES_NOT_AVAILABLE) {
            setAuthError("Google Play Services no disponible en este dispositivo");
          } else {
            setAuthError("Error al iniciar sesión con Google: " + error.message);
          }
        } else {
          setAuthError("Error al iniciar sesión con Google: " + error.message);
        }
      }
    } else {
      // ── WEB: expo-auth-session ────────────────────────────────────────────
      if (!request) {
        setAuthError("Google Auth no está listo, intenta de nuevo.");
        return;
      }
      try {
        await promptAsync();
      } catch (e) {
        setAuthError("Error al abrir Google: " + e.message);
      }
    }
  };

  // ── Sign Out ──────────────────────────────────────────────────────────────
  const signOut = async () => {
    try {
      if (Platform.OS !== "web" && GoogleSignin) {
        await GoogleSignin.signOut();
      }
    } catch {}
    setUser(null);
    setAuthError(null);
    await AsyncStorage.removeItem(storageKey);
  };

  const clearError = () => setAuthError(null);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        authError,
        clearError,
        signInWithGoogle,
        signInWithEmail,
        signUp,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
