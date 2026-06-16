import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useAuth } from "../context/AuthContext";

const RED = "#e6192e";

export default function LoginPromptSheet({ visible, onClose }) {
  const { signInWithGoogle } = useAuth();

  const handleSignIn = () => {
    onClose();
    signInWithGoogle();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      statusBarTranslucent
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.handle} />

        <View style={styles.iconCircle}>
          <Ionicons name="cart-outline" size={36} color={RED} />
        </View>

        <Text style={styles.title}>¡Inicia sesión para continuar!</Text>
        <Text style={styles.subtitle}>
          Crea una cuenta gratis o inicia sesión para agregar productos y hacer tus pedidos.
        </Text>

        <TouchableOpacity style={styles.googleBtn} onPress={handleSignIn} activeOpacity={0.88}>
          <Ionicons name="logo-google" size={18} color="#EA4335" />
          <Text style={styles.googleBtnText}>Continuar con Google</Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.cancelBtn} onPress={onClose} activeOpacity={0.7}>
          <Text style={styles.cancelText}>Ahora no</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.52)",
  },
  sheet: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    paddingHorizontal: 28,
    paddingBottom: 44,
    paddingTop: 14,
    alignItems: "center",
  },
  handle: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#e0e0e0",
    marginBottom: 28,
  },
  iconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: "#fff5f5",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 18,
    borderWidth: 2,
    borderColor: "#ffd0d4",
  },
  title: {
    fontSize: 21,
    fontWeight: "900",
    color: "#111",
    textAlign: "center",
    marginBottom: 10,
  },
  subtitle: {
    fontSize: 14,
    color: "#888",
    textAlign: "center",
    lineHeight: 21,
    marginBottom: 30,
    paddingHorizontal: 8,
  },
  googleBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    width: "100%",
    paddingVertical: 15,
    borderRadius: 14,
    backgroundColor: "#fff",
    borderWidth: 1.5,
    borderColor: "#e0e0e0",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07,
    shadowRadius: 6,
    elevation: 3,
    marginBottom: 14,
  },
  googleBtnText: {
    fontSize: 15,
    fontWeight: "800",
    color: "#222",
  },
  cancelBtn: {
    paddingVertical: 10,
    paddingHorizontal: 20,
  },
  cancelText: {
    fontSize: 14,
    color: "#aaa",
    fontWeight: "600",
  },
});
