importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyCJsxFBcOuU8vqav8YJIEWTuh4MX_EMX3s",
  authDomain: "todopalnegocio.firebaseapp.com",
  projectId: "todopalnegocio",
  storageBucket: "todopalnegocio.firebasestorage.app",
  messagingSenderId: "1041797301392",
  appId: "1:1041797301392:web:001a384dd25c8cae7b8415",
});

const messaging = firebase.messaging();

// Notificaciones cuando la app web está en background/cerrada
messaging.onBackgroundMessage((payload) => {
  const { title, body, icon } = payload.notification || {};
  self.registration.showNotification(title || "Todo Pal Negocio", {
    body: body || "",
    icon: icon || "/favicon.png",
    badge: "/favicon.png",
    data: payload.data || {},
  });
});
