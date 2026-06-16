import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useContext, useEffect, useState } from "react";
import { useAuth } from "./AuthContext";

const WishlistContext = createContext();

export function WishlistProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id ? String(user.id) : "guest";
  const [wishlist, setWishlist] = useState([]);
  const [loadedUserId, setLoadedUserId] = useState(null);

  useEffect(() => {
    const key = `@farmacia_wishlist_${userId}`;
    AsyncStorage.getItem(key)
      .then((data) => {
        setWishlist(data ? JSON.parse(data) : []);
        setLoadedUserId(userId);
      })
      .catch(() => {
        setWishlist([]);
        setLoadedUserId(userId);
      });
  }, [userId]);

  useEffect(() => {
    if (loadedUserId !== userId) return;
    const key = `@farmacia_wishlist_${userId}`;
    AsyncStorage.setItem(key, JSON.stringify(wishlist)).catch(() => {});
  }, [wishlist, loadedUserId, userId]);

  const toggleWishlist = (product) => {
    setWishlist((prev) => {
      const exists = prev.find((p) => p.id === product.id);
      return exists ? prev.filter((p) => p.id !== product.id) : [...prev, product];
    });
  };

  const isWishlisted = (productId) => wishlist.some((p) => p.id === productId);

  return (
    <WishlistContext.Provider value={{ wishlist, toggleWishlist, isWishlisted }}>
      {children}
    </WishlistContext.Provider>
  );
}

export const useWishlist = () => useContext(WishlistContext);
