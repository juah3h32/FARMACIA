import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";

const RED = "#e6192e";

export default function AdminLoginScreen() {
  const { signInWithEmail, authError, clearError } = useAuth();
  const { t } = useTheme();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [deniedMsg, setDeniedMsg] = useState(null);

  const handleLogin = async () => {
    if (!email.trim() || !password) return;
    clearError();
    setDeniedMsg(null);
    setLoading(true);
    const res = await signInWithEmail(email.trim(), password);
    setLoading(false);
    if (res?.success) {
      // signInWithEmail ya guardó el user; AdminApp revisa el rol y decide qué mostrar.
      // Si no es admin, avisamos aquí (el AdminApp también lo bloqueará).
    }
  };

  return (
    <KeyboardAvoidingView
      style={[s.wrapper, { backgroundColor: t.bg }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={[s.card, { backgroundColor: t.card, borderColor: t.border }]}>
        <View style={s.iconWrap}>
          <Ionicons name="shield-checkmark" size={28} color="#fff" />
        </View>
        <Text style={[s.title, { color: t.text }]}>Panel Admin</Text>
        <Text style={[s.subtitle, { color: t.textMuted }]}>Farmacia Eben-Ezer</Text>

        <TextInput
          style={[s.input, { borderColor: t.border, color: t.text, backgroundColor: t.input }]}
          placeholder="Correo"
          placeholderTextColor={t.placeholder}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
        />
        <TextInput
          style={[s.input, { borderColor: t.border, color: t.text, backgroundColor: t.input }]}
          placeholder="Contraseña"
          placeholderTextColor={t.placeholder}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
        />

        {(authError || deniedMsg) && (
          <Text style={s.error}>{authError || deniedMsg}</Text>
        )}

        <TouchableOpacity style={s.btn} onPress={handleLogin} disabled={loading}>
          {loading
            ? <ActivityIndicator color="#fff" size="small" />
            : <Text style={s.btnText}>ENTRAR</Text>}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  wrapper: { flex: 1, justifyContent: "center", alignItems: "center", padding: 20 },
  card: {
    width: "100%", maxWidth: 380, borderRadius: 20, borderWidth: 1,
    padding: 28, alignItems: "center",
  },
  iconWrap: {
    width: 56, height: 56, borderRadius: 16, backgroundColor: RED,
    justifyContent: "center", alignItems: "center", marginBottom: 16,
  },
  title: { fontSize: 20, fontWeight: "900" },
  subtitle: { fontSize: 12, marginTop: 2, marginBottom: 24 },
  input: {
    width: "100%", borderWidth: 1.5, borderRadius: 12,
    paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, marginBottom: 12,
  },
  error: { color: RED, fontSize: 12, marginBottom: 8, textAlign: "center" },
  btn: {
    width: "100%", backgroundColor: RED, borderRadius: 12,
    paddingVertical: 14, alignItems: "center", marginTop: 4,
  },
  btnText: { color: "#fff", fontWeight: "900", fontSize: 14, letterSpacing: 0.5 },
});
