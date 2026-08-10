// Abre la página web (productos) en el navegador — usado por `npm run dev`.
// Necesario porque expo start --web pierde la TTY dentro de `concurrently`
// y no auto-abre el navegador como cuando se corre suelto.
const { exec } = require("child_process");

const url = "http://localhost:8081";
const cmd =
  process.platform === "win32" ? `start "" "${url}"` :
  process.platform === "darwin" ? `open "${url}"` :
  `xdg-open "${url}"`;

exec(cmd, (err) => {
  if (err) console.error("[open-web] No se pudo abrir el navegador:", err.message);
});
