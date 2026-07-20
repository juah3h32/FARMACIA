import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";
import AdminLoginScreen from "./screens/AdminLoginScreen";
import AdminScreen from "./screens/AdminScreen";

const RED = "#e6192e";

function AdminGate() {
  const { user, loading, signOut } = useAuth();
  const { t } = useTheme();

  if (loading) return null;

  if (!user?.token) return <AdminLoginScreen />;

  if (user.role !== "admin" && user.role !== "admin_web") {
    return (
      <View style={[s.denied, { backgroundColor: t.bg }]}>
        <Ionicons name="lock-closed-outline" size={40} color={RED} />
        <Text style={[s.deniedText, { color: t.text }]}>
          Esta cuenta no tiene permisos de administrador.
        </Text>
        <TouchableOpacity style={s.btn} onPress={signOut}>
          <Text style={s.btnText}>CERRAR SESIÓN</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return <AdminScreen />;
}

export default function AdminApp() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AuthProvider storageKey="@farmacia_admin_session">
          <AdminGate />
        </AuthProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

const s = StyleSheet.create({
  denied: { flex: 1, justifyContent: "center", alignItems: "center", gap: 14, padding: 24 },
  deniedText: { fontSize: 14, fontWeight: "700", textAlign: "center" },
  btn: { backgroundColor: RED, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 24, marginTop: 8 },
  btnText: { color: "#fff", fontWeight: "900", fontSize: 13 },
});
