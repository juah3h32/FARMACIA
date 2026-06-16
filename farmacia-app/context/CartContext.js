import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useContext, useEffect, useState } from "react";
import { useAuth } from "./AuthContext";

const CartContext = createContext();

export function CartProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id ? String(user.id) : "guest";
  const [items, setItems] = useState([]);
  const [cartUserId, setCartUserId] = useState(null);

  // Cargar carrito del usuario al cambiar de sesión
  useEffect(() => {
    const key = `@farmacia_cart_${userId}`;
    AsyncStorage.getItem(key)
      .then((data) => {
        setItems(data ? JSON.parse(data) : []);
        setCartUserId(userId);
      })
      .catch(() => {
        setItems([]);
        setCartUserId(userId);
      });
  }, [userId]);

  // Guardar carrito cuando cambian los items (solo después de cargar)
  useEffect(() => {
    if (cartUserId !== userId) return;
    const key = `@farmacia_cart_${userId}`;
    AsyncStorage.setItem(key, JSON.stringify(items)).catch(() => {});
  }, [items, cartUserId, userId]);

  const addToCart = (product, qty = 1) => {
    if (!user) return { ok: false, authRequired: true };
    const stock = product.stock ?? null;
    const existing = items.find((i) => i.id === product.id);
    const currentQty = existing?.qty ?? 0;

    if (stock !== null && stock !== -1) {
      if (stock === 0) return { ok: false, message: "Producto agotado" };
      if (currentQty >= stock)
        return { ok: false, message: `Solo hay ${stock} en stock y ya los tienes en tu carrito` };
      if (currentQty + qty > stock) qty = stock - currentQty;
    }

    setItems((prev) => {
      const ex = prev.find((i) => i.id === product.id);
      if (ex) return prev.map((i) => i.id === product.id ? { ...i, qty: i.qty + qty } : i);
      return [...prev, { ...product, qty }];
    });
    return { ok: true, added: qty };
  };

  const removeFromCart = (productId) =>
    setItems((prev) => prev.filter((i) => i.id !== productId));

  const updateQty = (productId, qty) => {
    if (qty <= 0) { removeFromCart(productId); return; }
    const item = items.find((i) => i.id === productId);
    const stock = item?.stock ?? null;
    const capped = (stock !== null && stock !== -1) ? Math.min(qty, stock) : qty;
    setItems((prev) => prev.map((i) => i.id === productId ? { ...i, qty: capped } : i));
  };

  const clearCart = () => setItems([]);

  const count = items.reduce((sum, i) => sum + i.qty, 0);
  const subtotal = items.reduce((sum, i) => {
    const price = typeof i.price === "number"
      ? i.price
      : parseFloat(String(i.price ?? "0").replace(/[^0-9.]/g, "")) || 0;
    return sum + price * i.qty;
  }, 0);

  return (
    <CartContext.Provider value={{ items, addToCart, removeFromCart, updateQty, clearCart, count, subtotal }}>
      {children}
    </CartContext.Provider>
  );
}

export const useCart = () => useContext(CartContext);
